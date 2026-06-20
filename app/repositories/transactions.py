"""
Repository pentru Transaction.
"""

from datetime import date
from typing import Any, Dict, List, Optional

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
    import_fingerprint: Optional[str] = None,
) -> Transaction:
    """Inserează o tranzacție nouă. Commit la apelant.

    `import_fingerprint`: amprenta liniei de extras pentru anti-dublură (felia 3);
    None pentru tranzacțiile non-import (foto/Bolt/manual) → comportament neschimbat.
    """
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
        import_fingerprint=import_fingerprint,
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


def cash_income_for_year(session: Session, user_id: int, year: int) -> float:
    """
    Total încasări în NUMERAR pe an (lei) — semnal pentru casa de marcat (PAS 3).
    Σ amount_brut pe INCOME cu payment_method=CASH (filtru locked=False, ca restul
    motorului fiscal). Sursa: tranzacții cash (manual + curse cash postate din Bolt).
    """
    from sqlalchemy import func
    total = (
        session.query(func.coalesce(func.sum(Transaction.amount_brut), 0.0))
        .filter(
            Transaction.user_id == user_id,
            Transaction.period_year == year,
            Transaction.tx_type == "INCOME",
            Transaction.payment_method == "CASH",
            Transaction.locked == False,  # noqa: E712
        )
        .scalar()
    )
    return round(float(total or 0.0), 2)


def delete_for_document(
    session: Session,
    document_id: int,
) -> int:
    """
    Șterge fizic tranzacțiile unui document (dacă nu sunt locked).
    Returnează numărul de tranzacții șterse.
    Folosit la /delete — documentul e în 'rejected', tranzacțiile dispar.
    Nu ștergem tranzacțiile locked (perioadă fiscală închisă).
    """
    txs = (
        session.query(Transaction)
        .filter(
            Transaction.document_id == document_id,
            Transaction.locked == False,
        )
        .all()
    )
    count = len(txs)
    for tx in txs:
        session.delete(tx)
    return count


def to_dict(tx: Transaction) -> Dict[str, Any]:
    """Serializare pentru audit."""
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
