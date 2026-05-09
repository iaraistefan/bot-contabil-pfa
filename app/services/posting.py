"""
Serviciu de posting: transformă un Document validat în tranzacții contabile.

ACTIVITY-AWARE (din Pas 7.3):
- Categoria + deductibilitatea NU mai sunt hardcoded
- Detectarea se face din keyword-urile activității user-ului (ex: ridesharing,
  it_freelance, generic)
- Deductibilitatea vine din BaseActivity.get_deductibility_pct(code)

PRINCIPIU FISCAL CORECT (PFA Ridesharing 2026):

VENIT (din raport Bolt/Uber):
  → 1x INCOME pentru BRUT cash (dacă cash > 0)
  → 1x INCOME pentru BRUT card (dacă card > 0)
  → 1x EXPENSE platform_commission (dacă comision > 0; deductibil 100%)

CHELTUIALA:
  → 1x EXPENSE pe categoria detectată din activitate, cu pct deductibilitate
    automat din BaseActivity.

FACTURA_COMISION (Bolt/Uber intracomunitare):
  → 1x VAT_OUT reverse charge
  → 1x VAT_IN  reverse charge

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
from app.models import User

logger = logging.getLogger(__name__)


# --- Categorii standard care nu depind de activitate ---
CAT_PLATFORM_COMMISSION = "platform_commission"
CAT_REVERSE_CHARGE_VAT = "reverse_charge_vat"
CAT_OTHER_EXPENSE = "other_expense"

# Categorii fallback pentru INCOME când activitatea nu definește una
INCOME_FALLBACK_CODE = "ride_revenue"  # pentru ridesharing
INCOME_GENERIC_FALLBACK = "service_revenue"


# ============================================================
#                    HELPER-I ACTIVITY-AWARE
# ============================================================

def _get_user_activity(session: Session, user_id: int) -> Type[BaseActivity]:
    """Returnează clasa de activitate a user-ului (Generic dacă lipsește)."""
    user = session.query(User).filter(User.id == user_id).first()
    if not user or not user.activity_code:
        return get_activity(None)
    return get_activity(user.activity_code)


def _detect_expense_category(
    activity: Type[BaseActivity],
    platforma: Optional[str],
    detalii: Optional[str],
) -> Optional[str]:
    """
    Detectează codul de categorie din keyword-urile activității user-ului.
    Returnează codul (ex: 'fuel', 'cloud_services') sau None dacă nu match.
    Prima categorie care match-uie un keyword câștigă.
    """
    text = f"{platforma or ''} {detalii or ''}".lower().strip()
    if not text:
        return None

    for cat in activity.expense_categories:
        if not cat.keywords:
            continue
        if any(kw.lower() in text for kw in cat.keywords):
            logger.debug(
                f"Matched category '{cat.code}' "
                f"(activity={activity.code}) for text='{text[:60]}...'"
            )
            return cat.code
    return None


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
) -> List[int]:
    """
    Derivă tranzacțiile contabile dintr-un document.
    Întoarce lista de tx_id-uri create. Commit la apelant.
    """
    occurred_on = _parse_occurred_on(data_doc)
    period_year = occurred_on.year if occurred_on else None
    period_month = occurred_on.month if occurred_on else None
    tx_ids: List[int] = []

    # ⭐ NOU: încărcăm activitatea user-ului o singură dată
    activity = _get_user_activity(session, user_id)
    logger.info(
        f"post_document: doc_id={document_id} user_id={user_id} "
        f"activity={activity.code} tip={tip}"
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
                document_id=document_id, platforma=platforma,
                detalii=detalii, brut=brut, tva=tva,
                occurred_on=occurred_on,
                period_year=period_year, period_month=period_month,
            )

        elif tip == "FACTURA_COMISION":
            tx_ids += _post_factura_comision(
                session, user_id=user_id, document_id=document_id,
                platforma=platforma, comision=comision,
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
#                       VENIT
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
        # Folosim pct din activitate dacă există categoria, altfel 100%
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
#                     CHELTUIALA  ⭐ ACTIVITY-AWARE
# ============================================================

def _post_cheltuiala(
    session, *, user_id, activity, document_id, platforma, detalii, brut, tva,
    occurred_on, period_year, period_month,
) -> List[int]:
    """
    CHELTUIALA → 1x EXPENSE.
    Categoria + deductibilitatea vin AUTOMAT din activitatea user-ului.
    """
    # ⭐ DETECT din keyword-urile activității
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
    )

    logger.info(
        f"CHELTUIALA doc_id={document_id}: category={category_code} "
        f"brut={brut} pct={deductibility_pct}% "
        f"(activity={activity.code})"
    )

    return [tx.id]


# ============================================================
#                  FACTURA_COMISION (neschimbat)
# ============================================================

def _post_factura_comision(
    session, *, user_id, document_id, platforma, comision,
    occurred_on, period_year, period_month,
) -> List[int]:
    """FACTURA_COMISION → 2 tranzacții TVA reverse charge."""
    vat_amount = tax_rules.apply_reverse_charge(comision)

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
        vat_treatment="REVERSE_CHARGE",
        occurred_on=occurred_on,
        period_year=period_year,
        period_month=period_month,
    )

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
        vat_treatment="REVERSE_CHARGE",
        occurred_on=occurred_on,
        period_year=period_year,
        period_month=period_month,
    )

    logger.info(
        f"FACTURA_COMISION doc_id={document_id}: "
        f"factura={comision} RON, VAT_reverse={vat_amount} RON"
    )

    return [tx_vat_out.id, tx_vat_in.id]
