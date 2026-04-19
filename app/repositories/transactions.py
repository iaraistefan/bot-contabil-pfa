"""
Repository pentru Transaction.
"""

from typing import Any, Dict, List, Optional
from datetime import date

from sqlalchemy.orm import Session

from app.models import Transaction


def create(
    session: Session,
    *,
    user_id: int,
    document_id: int,
    tx_type: str,
    category: str,
    amount_brut: float,
    amount_vat: float = 0.0,
    amount_net: float = 0.0,
    currency: str = "RON",
    deductibility_pct: int = 100,
    payment_method: Optional[str] = None,
    counterparty: Optional[str] = None,
    vat_treatment: str = "NA",
    occurred_on: Optional[date] = None,
    period_year: Optional[int] = None,
    period_month: Optional[int] = None,
) -> Transaction:
    """Inserează o tranzacție nouă. Commit la apelant."""
    tx = Transaction(
        user_id=user_id,
        document_id=document_id,
        tx_type=tx_type,
        category=category,
        amount_brut=amount_brut,
        amount_vat=amount_vat,
        amount_net=amount_net,
        currency=currency,
        deductibility_pct=deductibility_pct,
        payment_method=payment_method,
        counterparty=counterparty,
        vat_treatment=vat_treatment,
        occurred_on=occurred_on,
        period_year=period_year,
        period_month=period_month,
    )
    session.add(tx)
    session.flush()
    return tx


def list_for_period(
    session: Session,
    user_id: int,
    year: int,
    month: Optional[int] = None,
) -> List[Transaction]:
    """Toate tranzacțiile pentru un an (și opțional lună)."""
    q = (
        session.query(Transaction)
        .filter(Transaction.user_id == user_id)
        .filter(Transaction.period_year == year)
        .filter(Transaction.locked == False)
    )
    if month is not None:
        q = q.filter(Transaction.period_month == month)
    return q.order_by(Transaction.occurred_on).all()


def to_dict(tx: Transaction) -> Dict[str, Any]:
    """Serializare pentru audit. Apelat înainte de session.close()."""
    return {
        "id": tx.id,
        "tx_type": tx.tx_type,
        "category": tx.category,
        "amount_brut": tx.amount_brut,
        "amount_vat": tx.amount_vat,
        "amount_net": tx.amount_net,
        "currency": tx.currency,
        "deductibility_pct": tx.deductibility_pct,
        "counterparty": tx.counterparty,
        "vat_treatment": tx.vat_treatment,
        "period_year": tx.period_year,
        "period_month": tx.period_month,
    }
