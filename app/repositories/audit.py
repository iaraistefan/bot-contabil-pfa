"""
Helper pentru scrierea în audit_logs.

Toate funcțiile sunt non-throwing: un fail de audit NU trebuie să spargă
operația principală. Logăm eroarea și continuăm.
"""

import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import AuditLog

logger = logging.getLogger(__name__)


def write(
    session: Session,
    *,
    entity_type: str,
    entity_id: int,
    action: str,
    user_id: Optional[int] = None,
    source: str = "system",
    before: Optional[dict] = None,
    after: Optional[dict] = None,
    note: Optional[str] = None,
) -> None:
    """
    Inserează o intrare în audit_logs.
    NU face commit — asta rămâne la apelant (în aceeași tranzacție cu op principală).
    NU aruncă excepții — logăm și continuăm.
    """
    try:
        entry = AuditLog(
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            source=source,
            before_json=before,
            after_json=after,
            note=(note[:500] if note else None),
        )
        session.add(entry)
    except Exception as e:
        # Nu vrem să picăm operația principală dintr-un fail de audit
        logger.error(f"Audit write failed: {e}")
