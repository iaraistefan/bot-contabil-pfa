"""
Serviciu de posting: transformă un Document validat în tranzacții contabile.

ACTIVITY-AWARE (din Pas 7.3):
- Categoria + deductibilitatea NU mai sunt hardcoded
- Detectarea folosește scoring semantic (BaseActivity.detect_expense_category)
- Deductibilitatea vine din BaseActivity.get_deductibility_pct(code)

VAT-ENGINE-AWARE (Pas 8.4b):
- Cheltuielile primesc tratament TVA inteligent prin vat_engine.analyze()
- FACTURA_COMISION → detectare automată RO/UE/non-UE (nu mai e hardcodat reverse charge)
- vat_id detectat se salvează în Document pentru audit
- Logică SOFT: dacă vat_engine returnează confidence < 65, folosim logica veche

PRINCIPIU FISCAL CORECT (PFA Ridesharing 2026):

VENIT (din raport Bolt/Uber):
  → 1x INCOME pentru BRUT cash (dacă cash > 0)
  → 1x INCOME pentru BRUT card (dacă card > 0)
  → 1x EXPENSE platform_commission (dacă comision > 0; deductibil 100%)

CHELTUIALA:
  → 1x EXPENSE pe categoria detectată cu scoring semantic, cu pct deductibilitate
    automat din BaseActivity. vat_treatment determinat de vat_engine.

FACTURA_COMISION (Bolt/Uber/AWS/Etsy intracomunitare/import):
  → 1x VAT_OUT cu treatment determinat de vat_engine (REVERSE_CHARGE / IMPORT_NON_EU)
  → 1x VAT_IN  oglindă

NOTE: Funcțiile nu fac commit — sesiunea e la apelant.
"""

import logging
from datetime import date, datetime
from typing import List, Optional, Type

from sqlalchemy.orm import Session

from app.repositories import transactions as tx_repo
from app.repositories import audit as audit_repo
from app.domain import tax_rules
from app.activities.registry import get_activity
from app.activities.base import BaseActivity
from app.models import User, Document

# === NEW (Pas 8.4b) — VAT Engine ===
from app.domain.vat_engine import (
    analyze as vat_analyze,
    VATDecision,
    VATTreatment,
    CountryGroup,
)

logger = logging.getLogger(__name__)


# --- Categorii standard care nu depind de activitate ---
CAT_PLATFORM_COMMISSION = "platform_commission"
CAT_REVERSE_CHARGE_VAT = "reverse_charge_vat"
CAT_OTHER_EXPENSE = "other_expense"

# Categorii fallback pentru INCOME când activitatea nu definește una
INCOME_FALLBACK_CODE = "ride_revenue"  # pentru ridesharing
INCOME_GENERIC_FALLBACK = "service_revenue"

# Confidence threshold pentru a accepta decizia vat_engine
VAT_ENGINE_MIN_CONFIDENCE = 65


# ============================================================
#                    HELPER-I ACTIVITY-AWARE
# ============================================================

def _get_user_activity(session: Session, user_id: int) -> Type[BaseActivity]:
    """Returnează clasa de activitate a user-ului (Generic dacă lipsește)."""
    user = session.query(User).filter(User.id == user_id).first()
    if not user or not user.activity_code:
        return get_activity(None)
    return get_activity(user.activity_code)


def _is_user_vat_payer(session: Session, user_id: int) -> bool:
    """True dacă user-ul e plătitor TVA (din profil)."""
    user = session.query(User).filter(User.id == user_id).first()
    if not user:
        return False
    return user.regim_tva in ("PLATITOR_21", "SPECIAL_INTRACOM")


def _detect_expense_category(
    activity: Type[BaseActivity],
    platforma: Optional[str],
    detalii: Optional[str],
) -> Optional[str]:
    """
    Detectează codul de categorie folosind algoritmul semantic cu scor.

    Folosește BaseActivity.detect_expense_category() care:
    - Calculează scor pe keyword-uri (cele compuse câștigă peste cele simple)
    - Câștigă categoria cu cel mai mare scor cumulat

    Exemplu: "Lukoil ulei motor 52.99"
    - fuel (lukoil=11) → 11
    - car_service (ulei=4 + ulei motor=15 = 19) → CÂȘTIGĂ ✅
    """
    cat, score = activity.detect_expense_category(platforma, detalii)
    if cat is None:
        return None
    logger.info(
        f"Detected category '{cat.code}' (score={score}, "
        f"activity={activity.code}) for text='{platforma} {detalii}'"
    )
    return cat.code


def _pick_income_category(activity: Type[BaseActivity]) -> str:
    """
    Alege codul categoriei principale de venit pentru activitate.
    Logică:
      1. Dacă activitatea are 'ride_revenue' (ridesharing) → folosește
      2. Altfel → primul income_category definit
      3. Fallback ultimă → 'service_revenue'
    """
    if not activity.income_categories:
        return INCOME_GENERIC_FALLBACK

    for cat in activity.income_categories:
        if cat.code == INCOME_FALLBACK_CODE:
            return cat.code

    return activity.income_categories[0].code


# ============================================================
#              NEW (Pas 8.4b) — VAT ENGINE HELPERS
# ============================================================

def _analyze_vat_safely(
    *,
    platforma: Optional[str],
    detalii: Optional[str],
    user_is_vat_payer: bool,
    transaction_type: str,
) -> Optional[VATDecision]:
    """
    Wrapper safe peste vat_engine.analyze().
    Returnează None dacă analizat-ul aruncă (orice).
    """
    try:
        decision = vat_analyze(
            platforma=platforma,
            detalii=detalii,
            user_is_vat_payer=user_is_vat_payer,
            transaction_type=transaction_type,
        )
        logger.info(
            f"VAT engine: '{platforma}' → {decision.treatment.value} "
            f"({decision.country_code}, conf={decision.confidence}, "
            f"brand={decision.detected_brand})"
        )
        return decision
    except Exception as e:
        logger.warning(f"VAT engine failed for '{platforma}': {e}")
        return None


def _save_document_vat_id(
    session: Session,
    document_id: int,
    vat_id: Optional[str],
) -> None:
    """Salvează vat_id detectat în Document (best-effort)."""
    if not vat_id:
        return
    try:
        doc = session.query(Document).filter(Document.id == document_id).first()
        if doc and not doc.vat_id:
            doc.vat_id = vat_id
            session.flush()
            logger.info(f"Saved vat_id={vat_id} for document_id={document_id}")
    except Exception as e:
        logger.warning(f"Could not save vat_id for doc {document_id}: {e}")


# ============================================================
#                       UTILS
# ============================================================

def _parse_occurred_on(data_doc: Optional[str]) -> Optional[date]:
    if not data_doc:
        return None
    try:
        return datetime.strptime(data_doc, "%d.%m.%Y").date()
    except ValueError:
        return None


# ============================================================
#                     PUNCT DE INTRARE
# ============================================================

def post_document(
    session: Session,
    *,
    user_id: int,
    document_id: int,
    tip: str,
    platforma: Optional[str],
    detalii: Optional[str],
    brut: float,
    comision: float,
    tva: float,
    net: float,
    cash: float,
    banca: float,
    data_doc: Optional[str],
    category_override: Optional[str] = None,
    import_fingerprint: Optional[str] = None,
) -> List[int]:
    """
    Derivă tranzacțiile contabile dintr-un document.
    Întoarce lista de tx_id-uri create. Commit la apelant.

    Parametri opționali (felia 3 — import extras bancar; aditivi, default None
    => comportament IDENTIC cu înainte pentru foto/Bolt):
      - category_override: dacă e dat, ramura CHELTUIALA folosește ACEASTĂ categorie
        și SARE peste detect_expense_category (clasificarea e deja decisă determinist
        în felia 2). Pe date bancare e MEREU non-None => re-clasificarea pe text brut
        (cu zgomotul „0.00RON") nu mai poate produce fals-pozitive pe SCRIERE.
      - import_fingerprint: amprenta liniei de extras, stocată pe tranzacția EXPENSE
        (anti-dublură). Se aplică pe ramura CHELTUIALA (singura folosită de import).
    """
    occurred_on = _parse_occurred_on(data_doc)
    period_year = occurred_on.year if occurred_on else None
    period_month = occurred_on.month if occurred_on else None
    tx_ids: List[int] = []

    # Încărcăm activitatea + statusul TVA al user-ului o singură dată
    activity = _get_user_activity(session, user_id)
    user_is_vat_payer = _is_user_vat_payer(session, user_id)
    logger.info(
        f"post_document: doc_id={document_id} user_id={user_id} "
        f"activity={activity.code} tip={tip} vat_payer={user_is_vat_payer}"
    )

    try:
        if tip == "VENIT":
            tx_ids += _post_venit(
                session, user_id=user_id, activity=activity,
                document_id=document_id, platforma=platforma,
                brut=brut, net=net, cash=cash, comision=comision,
                occurred_on=occurred_on,
                period_year=period_year, period_month=period_month,
            )

        elif tip == "CHELTUIALA":
            tx_ids += _post_cheltuiala(
                session, user_id=user_id, activity=activity,
                user_is_vat_payer=user_is_vat_payer,
                document_id=document_id, platforma=platforma,
                detalii=detalii, brut=brut, tva=tva,
                occurred_on=occurred_on,
                period_year=period_year, period_month=period_month,
                category_override=category_override,
                import_fingerprint=import_fingerprint,
            )

        elif tip == "FACTURA_COMISION":
            tx_ids += _post_factura_comision(
                session, user_id=user_id,
                user_is_vat_payer=user_is_vat_payer,
                document_id=document_id,
                platforma=platforma, detalii=detalii,
                comision=comision,
                occurred_on=occurred_on,
                period_year=period_year, period_month=period_month,
            )

        else:
            logger.warning(f"Unknown tip '{tip}' for document_id={document_id}")

        for tx_id in tx_ids:
            audit_repo.write(
                session,
                entity_type="transaction",
                entity_id=tx_id,
                action="create",
                user_id=user_id,
                source="system",
                note=f"auto-posted from document_id={document_id} "
                     f"activity={activity.code}",
            )

    except Exception as e:
        logger.error(f"Error in post_document for doc_id={document_id}: {e}")
        return []

    return tx_ids


# ============================================================
#                       VENIT (NESCHIMBAT)
# ============================================================

def _post_venit(
    session, *, user_id, activity, document_id, platforma, brut, net, cash,
    comision, occurred_on, period_year, period_month,
) -> List[int]:
    """VENIT din raport Bolt → INCOME cash + INCOME card + EXPENSE comision."""
    tx_ids = []
    income_code = _pick_income_category(activity)
    card_amount = round(brut - cash, 2) if brut > cash else 0.0

    # ── 1. Tranzacție CASH ──
    if cash > 0:
        tx_cash = tx_repo.create(
            session,
            user_id=user_id,
            document_id=document_id,
            tx_type="INCOME",
            category=income_code,
            amount_brut=cash,
            amount_vat=0.0,
            amount_net=cash,
            currency="RON",
            deductibility_pct=100,
            payment_method="CASH",
            counterparty=platforma or "APP",
            vat_treatment="NA",
            occurred_on=occurred_on,
            period_year=period_year,
            period_month=period_month,
        )
        tx_ids.append(tx_cash.id)

    # ── 2. Tranzacție CARD ──
    if card_amount > 0:
        tx_card = tx_repo.create(
            session,
            user_id=user_id,
            document_id=document_id,
            tx_type="INCOME",
            category=income_code,
            amount_brut=card_amount,
            amount_vat=0.0,
            amount_net=card_amount,
            currency="RON",
            deductibility_pct=100,
            payment_method="CARD",
            counterparty=platforma or "APP",
            vat_treatment="NA",
            occurred_on=occurred_on,
            period_year=period_year,
            period_month=period_month,
        )
        tx_ids.append(tx_card.id)

    # Fallback: nimic alocat dar avem brut → o singură tranzacție
    if not tx_ids and brut > 0:
        tx_default = tx_repo.create(
            session,
            user_id=user_id,
            document_id=document_id,
            tx_type="INCOME",
            category=income_code,
            amount_brut=brut,
            amount_vat=0.0,
            amount_net=net if net > 0 else brut,
            currency="RON",
            deductibility_pct=100,
            payment_method="CARD",
            counterparty=platforma or "APP",
            vat_treatment="NA",
            occurred_on=occurred_on,
            period_year=period_year,
            period_month=period_month,
        )
        tx_ids.append(tx_default.id)

    # ── 3. EXPENSE comisionul Bolt din raport (deductibil 100%) ──
    if comision > 0:
        comm_pct = activity.get_deductibility_pct(CAT_PLATFORM_COMMISSION) or 100
        tx_comm = tx_repo.create(
            session,
            user_id=user_id,
            document_id=document_id,
            tx_type="EXPENSE",
            category=CAT_PLATFORM_COMMISSION,
            amount_brut=comision,
            amount_vat=0.0,
            amount_net=comision,
            currency="RON",
            deductibility_pct=comm_pct,
            payment_method="CARD",
            counterparty=platforma or "Platform",
            vat_treatment="AUTO_FROM_REPORT",
            occurred_on=occurred_on,
            period_year=period_year,
            period_month=period_month,
        )
        tx_ids.append(tx_comm.id)
        logger.info(
            f"VENIT doc_id={document_id}: brut={brut} (cash={cash}, "
            f"card={card_amount}), comision auto={comision} "
            f"(pct={comm_pct}%)"
        )

    return tx_ids


# ============================================================
#       CHELTUIALA  ⭐ ACTIVITY-AWARE + SEMANTIC + VAT-ENGINE
# ============================================================

def _post_cheltuiala(
    session, *, user_id, activity, user_is_vat_payer,
    document_id, platforma, detalii, brut, tva,
    occurred_on, period_year, period_month,
    category_override=None, import_fingerprint=None,
) -> List[int]:
    """
    CHELTUIALA → 1x EXPENSE.
    Categoria + deductibilitatea vin din scoring-ul semantic, SAU din
    `category_override` (felia 3 — clasificare deja decisă determinist; sare
    peste re-clasificare => fals-pozitivul pe text brut e imposibil pe scriere).
    vat_treatment vine din vat_engine (cu fallback la logica veche).
    `import_fingerprint` se stochează pe tranzacție (anti-dublură import).
    """
    if category_override is not None:
        # ⭐ FELIA 3 — onorăm clasificarea deterministă; NU re-clasificăm pe text.
        category_code = category_override
        deductibility_pct = activity.get_deductibility_pct(category_code)
        logger.info(
            f"CHELTUIALA override: category={category_code} "
            f"pct={deductibility_pct}% (skip detect_expense_category)"
        )
    else:
        # ⭐ DETECT cu scoring semantic (comportament istoric — foto)
        category_code = _detect_expense_category(activity, platforma, detalii)

        if category_code is None:
            # Fallback: categorie "alte cheltuieli", deductibil 100%
            category_code = CAT_OTHER_EXPENSE
            deductibility_pct = 100
            logger.info(
                f"No category match for activity={activity.code} "
                f"text='{platforma} {detalii}' → fallback to {CAT_OTHER_EXPENSE}"
            )
        else:
            # ⭐ DEDUCTIBILITY DINAMICĂ din activitate
            deductibility_pct = activity.get_deductibility_pct(category_code)

    # ════════════════════════════════════════════════════════
    # === NEW (Pas 8.4b) — VAT Engine pentru tratament TVA ===
    # ════════════════════════════════════════════════════════
    vat_decision = _analyze_vat_safely(
        platforma=platforma,
        detalii=detalii,
        user_is_vat_payer=user_is_vat_payer,
        transaction_type="EXPENSE",
    )

    # Decizia finală: vat_engine dacă confidence ≥ 65, altfel logica veche
    if vat_decision and vat_decision.confidence >= VAT_ENGINE_MIN_CONFIDENCE:
        vat_treatment = vat_decision.treatment.value
        # Salvăm vat_id detectat (dacă există)
        _save_document_vat_id(session, document_id, vat_decision.detected_vat_id)
        logger.info(
            f"VAT decision (confidence={vat_decision.confidence}): "
            f"{vat_treatment} for '{platforma}'"
        )
    else:
        # Fallback la logica veche
        vat_treatment = "STANDARD" if tva > 0 else "NA"

    tx = tx_repo.create(
        session,
        user_id=user_id,
        document_id=document_id,
        tx_type="EXPENSE",
        category=category_code,
        amount_brut=brut,
        amount_vat=tva,
        amount_net=brut - tva,
        currency="RON",
        deductibility_pct=deductibility_pct,
        payment_method="CARD",
        counterparty=platforma or detalii or "N/A",
        vat_treatment=vat_treatment,
        occurred_on=occurred_on,
        period_year=period_year,
        period_month=period_month,
        import_fingerprint=import_fingerprint,
    )

    logger.info(
        f"CHELTUIALA doc_id={document_id}: category={category_code} "
        f"brut={brut} pct={deductibility_pct}% "
        f"vat_treatment={vat_treatment} (activity={activity.code})"
    )

    return [tx.id]


# ============================================================
#       FACTURA_COMISION  ⭐ VAT-ENGINE-AWARE (Pas 8.4b)
# ============================================================

def _post_factura_comision(
    session, *, user_id, user_is_vat_payer, document_id,
    platforma, detalii, comision,
    occurred_on, period_year, period_month,
) -> List[int]:
    """
    FACTURA_COMISION → 2 tranzacții TVA (VAT_OUT + VAT_IN).

    Tratament determinat de vat_engine:
    - UE (Bolt EE / Uber NL / Etsy IE) → REVERSE_CHARGE (D301 + D390)
    - Non-UE (AWS US / OpenAI US) → IMPORT_NON_EU (doar D301, fără D390)
    - RO (rar pentru facturi comision) → STANDARD_21
    - Necunoscut → fallback REVERSE_CHARGE (compatibilitate cu logica veche)
    """
    # ════════════════════════════════════════════════════════
    # === Analiză VAT (înainte de orice calcul) ===
    # ════════════════════════════════════════════════════════
    vat_decision = _analyze_vat_safely(
        platforma=platforma,
        detalii=detalii,
        user_is_vat_payer=user_is_vat_payer,
        transaction_type="FACTURA_COMISION",
    )

    # Determinăm tratamentul final
    if vat_decision and vat_decision.confidence >= VAT_ENGINE_MIN_CONFIDENCE:
        vat_treatment = vat_decision.treatment.value
        country_group = vat_decision.country_group
        _save_document_vat_id(session, document_id, vat_decision.detected_vat_id)
    else:
        # Fallback la comportamentul vechi (REVERSE_CHARGE pentru orice intracom)
        vat_treatment = "REVERSE_CHARGE"
        country_group = CountryGroup.EU
        logger.info(
            f"FACTURA_COMISION: vat_engine confidence too low or failed, "
            f"fallback to REVERSE_CHARGE"
        )

    # Calcul TVA — cota pe data facturii (19%/21%, sursă unică: tax_rules.cota_tva).
    # Dacă data lipsește, apply_reverse_charge cade pe cota standard curentă.
    vat_amount = tax_rules.apply_reverse_charge(comision, data=occurred_on)

    # ── 1. VAT_OUT (TVA colectat — datorat) ──
    tx_vat_out = tx_repo.create(
        session,
        user_id=user_id,
        document_id=document_id,
        tx_type="VAT_OUT",
        category=CAT_REVERSE_CHARGE_VAT,
        amount_brut=vat_amount,
        amount_vat=vat_amount,
        amount_net=0.0,
        currency="RON",
        deductibility_pct=0,
        payment_method="CARD",
        counterparty=platforma or "Platform",
        vat_treatment=vat_treatment,
        occurred_on=occurred_on,
        period_year=period_year,
        period_month=period_month,
    )

    # ── 2. VAT_IN (TVA deductibil — oglindă) ──
    tx_vat_in = tx_repo.create(
        session,
        user_id=user_id,
        document_id=document_id,
        tx_type="VAT_IN",
        category=CAT_REVERSE_CHARGE_VAT,
        amount_brut=vat_amount,
        amount_vat=vat_amount,
        amount_net=0.0,
        currency="RON",
        deductibility_pct=100,
        payment_method="CARD",
        counterparty=platforma or "Platform",
        vat_treatment=vat_treatment,
        occurred_on=occurred_on,
        period_year=period_year,
        period_month=period_month,
    )

    logger.info(
        f"FACTURA_COMISION doc_id={document_id}: "
        f"factura={comision} RON, VAT={vat_amount} RON, "
        f"treatment={vat_treatment}, country={country_group.value}"
    )

    return [tx_vat_out.id, tx_vat_in.id]
