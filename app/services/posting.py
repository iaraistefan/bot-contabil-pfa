"""
Serviciu de posting: transformă un Document validat în tranzacții contabile.

Reguli pentru PFA Ridesharing Romania (2026):

VENIT:
  → 1x INCOME / ride_revenue
  → payment_method: APP sau CASH sau mixt

CHELTUIALA:
  → 1x EXPENSE / categorie dedusă din platforma+detalii
  → deductibility_pct calculat prin tax_rules

FACTURA_COMISION (Bolt/Uber intracomunitare):
  → 1x EXPENSE / platform_commission (reverse charge)
  → 1x VAT_OUT / reverse_charge_vat (TVA de plătit la ANAF → D301)
  → 1x VAT_IN  / reverse_charge_vat (TVA deductibil dacă ești plătitor)

NOTE: Funcțiile nu fac commit — sesiunea e la apelant.
"""

import logging
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.repositories import transactions as tx_repo
from app.repositories import audit as audit_repo
from app.domain import tax_rules

logger = logging.getLogger(__name__)


# --- Constante categorii ---
CAT_RIDE_REVENUE = "ride_revenue"
CAT_PLATFORM_COMMISSION = "platform_commission"
CAT_FUEL = "fuel"
CAT_MAINTENANCE = "maintenance"
CAT_REGISTRATION = "registration"
CAT_OTHER_EXPENSE = "other_expense"
CAT_REVERSE_CHARGE_VAT = "reverse_charge_vat"

_FUEL_KEYWORDS = {
    "motorina", "benzina", "combustibil", "carburant", "gpl",
    "euro diesel", "euro premium", "omv", "petrom", "rompetrol",
    "mol", "lukoil", "socar", "lukoil", "diesel",
}
_REGISTRATION_KEYWORDS = {
    "autorizat", "inregistrar", "ecuson", "autorizatie", "rutier",
    "registrul", "anaf", "fisc", "impozit", "taxa", "cra", "inmatriculare",
}


def _detect_fuel(platforma: Optional[str], detalii: Optional[str]) -> bool:
    text = f"{platforma or ''} {detalii or ''}".lower()
    return any(kw in text for kw in _FUEL_KEYWORDS)


def _detect_registration(platforma: Optional[str], detalii: Optional[str]) -> bool:
    text = f"{platforma or ''} {detalii or ''}".lower()
    return any(kw in text for kw in _REGISTRATION_KEYWORDS)


def _parse_occurred_on(data_doc: Optional[str]) -> Optional[date]:
    if not data_doc:
        return None
    try:
        return datetime.strptime(data_doc, "%d.%m.%Y").date()
    except ValueError:
        return None


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
    tx_ids = []

    try:
        if tip == "VENIT":
            tx_ids += _post_venit(
                session, user_id=user_id, document_id=document_id,
                platforma=platforma, brut=brut, net=net, cash=cash,
                occurred_on=occurred_on, period_year=period_year, period_month=period_month,
            )

        elif tip == "CHELTUIALA":
            tx_ids += _post_cheltuiala(
                session, user_id=user_id, document_id=document_id,
                platforma=platforma, detalii=detalii, brut=brut, tva=tva,
                occurred_on=occurred_on, period_year=period_year, period_month=period_month,
            )

        elif tip == "FACTURA_COMISION":
            tx_ids += _post_factura_comision(
                session, user_id=user_id, document_id=document_id,
                platforma=platforma, comision=comision,
                occurred_on=occurred_on, period_year=period_year, period_month=period_month,
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
                note=f"auto-posted from document_id={document_id}",
            )

    except Exception as e:
        logger.error(f"Error in post_document for doc_id={document_id}: {e}")
        return []

    return tx_ids


def _post_venit(
    session, *, user_id, document_id, platforma, brut, net, cash,
    occurred_on, period_year, period_month,
) -> List[int]:
    """VENIT → 1x INCOME."""
    if cash >= brut * 0.99:
        pay_method = "CASH"
    elif cash == 0:
        pay_method = "APP"
    else:
        pay_method = "APP"

    tx = tx_repo.create(
        session,
        user_id=user_id,
        document_id=document_id,
        tx_type="INCOME",
        category=CAT_RIDE_REVENUE,
        amount_brut=brut,
        amount_vat=0.0,
        amount_net=net if net > 0 else brut,
        currency="RON",
        deductibility_pct=100,
        payment_method=pay_method,
        counterparty=platforma or "APP",
        vat_treatment="NA",
        occurred_on=occurred_on,
        period_year=period_year,
        period_month=period_month,
    )
    return [tx.id]


def _post_cheltuiala(
    session, *, user_id, document_id, platforma, detalii, brut, tva,
    occurred_on, period_year, period_month,
) -> List[int]:
    """CHELTUIALA → 1x EXPENSE cu deductibilitate calculată prin tax_rules."""
    is_fuel = _detect_fuel(platforma, detalii)
    is_reg = _detect_registration(platforma, detalii)

    if is_fuel:
        category = CAT_FUEL
        # Folosim tax_rules pentru deductibilitate — nu mai e hardcodat
        deductible_amount = tax_rules.fuel_deductible_share(brut)
        deductibility_pct = tax_rules.FUEL_DEDUCTIBLE_PCT
    elif is_reg:
        category = CAT_REGISTRATION
        deductibility_pct = 100
    else:
        category = CAT_OTHER_EXPENSE
        deductibility_pct = 100

    vat_treatment = "STANDARD" if tva > 0 else "NA"

    tx = tx_repo.create(
        session,
        user_id=user_id,
        document_id=document_id,
        tx_type="EXPENSE",
        category=category,
        amount_brut=brut,
        amount_vat=tva,
        amount_net=brut - tva,
        currency="RON",
        deductibility_pct=deductibility_pct,
        payment_method="CARD",
        counterparty=platforma or "N/A",
        vat_treatment=vat_treatment,
        occurred_on=occurred_on,
        period_year=period_year,
        period_month=period_month,
    )
    return [tx.id]


def _post_factura_comision(
    session, *, user_id, document_id, platforma, comision,
    occurred_on, period_year, period_month,
) -> List[int]:
    """
    FACTURA_COMISION → 3 tranzacții:
    1. EXPENSE comision (baza impozabilă)
    2. VAT_OUT reverse charge (TVA de plătit la ANAF — D301)
    3. VAT_IN reverse charge (TVA deductibil — D301, net=0 pentru neplătitori)
    """
    # 1. Comisionul propriu-zis
    tx_expense = tx_repo.create(
        session,
        user_id=user_id,
        document_id=document_id,
        tx_type="EXPENSE",
        category=CAT_PLATFORM_COMMISSION,
        amount_brut=comision,
        amount_vat=0.0,
        amount_net=comision,
        currency="RON",
        deductibility_pct=100,
        payment_method="APP",
        counterparty=platforma or "Platform",
        vat_treatment="REVERSE_CHARGE",
        occurred_on=occurred_on,
        period_year=period_year,
        period_month=period_month,
    )

    # 2. TVA colectat prin taxare inversă (îl datorezi la ANAF)
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
        payment_method="APP",
        counterparty=platforma or "Platform",
        vat_treatment="REVERSE_CHARGE",
        occurred_on=occurred_on,
        period_year=period_year,
        period_month=period_month,
    )

    # 3. TVA deductibil (îl recuperezi — net 0 pentru PFA neplătitor de TVA)
    # La pasul 13 vom condiționa asta de user.regim_tva.
    # Momentan: creăm tranzacția pentru orice user (worst case: intrare cu 0 impact).
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
        payment_method="APP",
        counterparty=platforma or "Platform",
        vat_treatment="REVERSE_CHARGE",
        occurred_on=occurred_on,
        period_year=period_year,
        period_month=period_month,
    )

    logger.info(
        f"FACTURA_COMISION doc_id={document_id}: "
        f"comision={comision} RON, VAT_reverse={vat_amount} RON "
        f"→ tx_ids={[tx_expense.id, tx_vat_out.id, tx_vat_in.id]}"
    )

    return [tx_expense.id, tx_vat_out.id, tx_vat_in.id]
