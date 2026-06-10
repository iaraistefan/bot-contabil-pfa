"""
Repository pentru ObligationPayment (felia 5b).

Stochează faptul plății unei obligații fiscale detectate din extras. Obligația
rămâne efemeră (calculată on-the-fly); aici doar marcăm „plătit". Anti-dublură pe
(user_id, import_fingerprint) prin check-then-insert (ca `exists_fingerprint`
felia 3) + UNIQUE index ca backstop la nivel DB. Commit la apelant.

5b NU calculează fingerprint-ul — îl PRIMEȘTE (5c îl calculează cu
`dedup.compute_fingerprints`). Fără consumator în 5b (fundație).
"""
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.models import ObligationPayment


def create_payment(
    session: Session,
    *,
    user_id: int,
    obligation_code: str,
    perioada_an: int,
    perioada_luna: int,
    suma_platita: float,
    data_platii: date,
    import_fingerprint: str,
    source_file_id: Optional[int] = None,
    sursa: str = "bank_import",
) -> ObligationPayment:
    """Înregistrează o plată de obligație. IDEMPOTENT pe (user, fingerprint):
    dacă există deja → întoarce rândul existent (skip), NU creează duplicat.
    Commit la apelant.
    """
    existing = (
        session.query(ObligationPayment)
        .filter(
            ObligationPayment.user_id == user_id,
            ObligationPayment.import_fingerprint == import_fingerprint,
        )
        .first()
    )
    if existing is not None:
        return existing

    pay = ObligationPayment(
        user_id=user_id,
        obligation_code=obligation_code,
        perioada_an=perioada_an,
        perioada_luna=perioada_luna,
        suma_platita=suma_platita,
        data_platii=data_platii,
        sursa=sursa,
        import_fingerprint=import_fingerprint,
        source_file_id=source_file_id,
    )
    session.add(pay)
    session.flush()
    return pay


def has_payment(
    session: Session,
    user_id: int,
    obligation_code: str,
    perioada_an: int,
    perioada_luna: int,
) -> bool:
    """True dacă obligația (user, cod, an, lună) are măcar o plată înregistrată
    (= achitată). Folosit la afișarea „achitat" în 5c.
    """
    return (
        session.query(ObligationPayment)
        .filter(
            ObligationPayment.user_id == user_id,
            ObligationPayment.obligation_code == obligation_code,
            ObligationPayment.perioada_an == perioada_an,
            ObligationPayment.perioada_luna == perioada_luna,
        )
        .first()
        is not None
    )
