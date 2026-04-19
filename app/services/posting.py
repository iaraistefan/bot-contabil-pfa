"""
Serviciu de posting: transformă un Document validat în tranzacții contabile.

Reguli pentru PFA Ridesharing Romania (2026):

VENIT:
  → 1x INCOME / ride_revenue (sau tip_revenue dacă cash > brut*0.9)
  → payment_method: APP dacă cash=0, CASH dacă cash>0, mixt dacă ambele

CHELTUIALA:
  → 1x EXPENSE / categorie dedusă din platforma+detalii
  → deductibility_pct:
      - combustibil (fuel): 50%
      - altele (maintenance, registration, other): 100%
  → vat_treatment: STANDARD dacă TVA>0, NA altfel

FACTURA_COMISION (Bolt/Uber):
  → 1x EXPENSE / platform_commission
  → vat_treatment: REVERSE_CHARGE (servicii intracomunitare, taxare inversă)
  → deductibility_pct: 100%
  → TVA: calculat separat la pasul 12 prin tax_rules
    (pentru acum nu creăm VAT_OUT/IN — e placeholder la pasul 12)

NOTE: Funcțiile sunt PURE în sensul că nu fac commit — sesiunea e la apelant.
"""

import logging
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import Transaction
from app.repositories import transactions as tx_repo
from app.repositories import audit as audit_repo

logger = logging.getLogger(__name__)


# --- Constante categorii ---
CAT_RIDE_REVENUE = "ride_revenue"
CAT_TIP_REVENUE = "tip_revenue"
CAT_PLATFORM_COMMISSION = "platform_commission"
CAT_FUEL = "fuel"
CAT_MAINTENANCE = "maintenance"
CAT_REGISTRATION = "registration"
CAT_OTHER_EXPENSE = "other_expense"

# Cuvinte cheie pentru a detecta categoria cheltuielii din detalii + platforma
_FUEL_KEYWORDS = {
    "motorina", "benzina", "combustibil", "carburant", "gpl",
    "euro diesel", "euro premium", "omv", "petrom", "rompetrol",
    "mol", "lukoil", "socar",
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


def _parse_occurred_on(data_doc: Optional[str]):
    """Parsare DD.MM.YYYY → date. None dacă eșuează."""
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
    Derivă tranzacțiile contabile dintr-un document și le inserează în DB.
    Întoarce lista de tx_id-uri create. Commit la apelant.

    Nu aruncă excepții — logăm și întoarcem [] în caz de eroare.
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
                platforma=platforma, comision=comision, tva=tva,
                occurred_on=occurred_on, period_year=period_year, period_month=period_month,
            )

        else:
            logger.warning(f"Unknown tip '{tip}' for document_id={document_id} — no transactions created")

        # Audit pentru fiecare tranzacție creată
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


# --- Funcții private per tip ---

def _post_venit(
    session, *, user_id, document_id, platforma, brut, net, cash,
    occurred_on, period_year, period_month,
) -> List[int]:
    """VENIT → 1 tranzacție INCOME."""
    # Dacă cash ≈ brut → plată cash. Dacă cash=0 → plată app. Altfel → mixt (APP pentru simplitate).
    if cash >= brut * 0.99:
        pay_method = "CASH"
    elif cash == 0:
        pay_method = "APP"
    else:
        pay_method = "APP"  # venit mixt — simplificăm

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
    """CHELTUIALA → 1 tranzacție EXPENSE cu deductibilitate corectă."""
    is_fuel = _detect_fuel(platforma, detalii)
    is_reg = _detect_registration(platforma, detalii)

    if is_fuel:
        category = CAT_FUEL
        deductibility_pct = 50
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
        payment_method="CARD",  # presupunem card; în pasul 11 detectăm din context
        counterparty=platforma or "N/A",
        vat_treatment=vat_treatment,
        occurred_on=occurred_on,
        period_year=period_year,
        period_month=period_month,
    )
    return [tx.id]


def _post_factura_comision(
    session, *, user_id, document_id, platforma, comision, tva,
    occurred_on, period_year, period_month,
) -> List[int]:
    """
    FACTURA_COMISION → 1 tranzacție EXPENSE (reverse charge).
    TVA_OUT + TVA_IN vine la pasul 12 prin tax_rules.
    """
    tx = tx_repo.create(
        session,
        user_id=user_id,
        document_id=document_id,
        tx_type="EXPENSE",
        category=CAT_PLATFORM_COMMISSION,
        amount_brut=comision,
        amount_vat=0.0,    # TVA e 0 pe factură (reverse charge — l-ai plătit tu la ANAF)
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
    return [tx.id]
