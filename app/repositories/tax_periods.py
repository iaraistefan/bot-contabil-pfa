"""
Repository pentru TaxPeriod.
"""

import json
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import TaxPeriod


def get_or_create(
    session: Session,
    *,
    user_id: int,
    year: int,
    month: int,
) -> TaxPeriod:
    """Returnează perioada existentă sau o crează cu status 'open'."""
    tp = (
        session.query(TaxPeriod)
        .filter(
            TaxPeriod.user_id == user_id,
            TaxPeriod.year == year,
            TaxPeriod.month == month,
        )
        .one_or_none()
    )
    if tp is not None:
        return tp

    tp = TaxPeriod(
        user_id=user_id,
        year=year,
        month=month,
        status="open",
    )
    session.add(tp)
    session.flush()
    return tp


def save_totals(
    session: Session,
    tp: TaxPeriod,
    totals: dict,
) -> None:
    """Salvează snapshot-ul de totaluri și marchează ca 'computed'."""
    tp.totals_json = totals
    tp.status = "computed"
    tp.computed_at = datetime.utcnow()
