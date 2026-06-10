"""
Înregistrarea plăților de obligații confirmate de user (felia 5c-a).

Serviciu PUR (fără Telegram): primește FINGERPRINT-urile confirmate de user și
înregistrează plățile reale corespunzătoare (`create_payment`). NU decide ce e
confirmat (UI 5c-c decide), NU comite (caller-ul comite). Mirror al
`post_bank_expenses` (felia 3 PAS 3): primește decizii, scrie, refuză structural.

🛡️ GARDA COMPENSARE (defense-in-depth PESTE confirmarea userului): chiar dacă
`confirmed_fingerprints` conține o plată RESPINSĂ (compensată cu o returnare),
serviciul o REFUZĂ — înregistrează doar `confirmed ∩ plăți REALE`. Pe bani userul
poate greși; garda ține structural (ca `_POSTABILE` din felia 3).

🔑 Cheie = FINGERPRINT (valoare stabilă), NU index/poziție/id() — rezistent la
re-parse/re-ordonare între momentul în care UI arată plățile și înregistrare.
"""
import logging
from typing import Iterable

from app.integrations.imports.dedup import compute_fingerprints
from app.integrations.imports.tax_payments import real_payment_indices
from app.repositories import obligation_payments as oblig_pay_repo

logger = logging.getLogger(__name__)


def record_tax_payments(
    session,
    *,
    user_id: int,
    source_file_id,
    clasificate,
    confirmed_fingerprints: Iterable[str],
) -> dict:
    """Înregistrează plățile de obligații confirmate. Nu comite (caller-ul comite).

    Întoarce sumar: {recorded, skipped_dup, skipped_blocked, details}.
    - recorded        — plăți noi înregistrate;
    - skipped_dup     — re-import (fingerprint deja în DB);
    - skipped_blocked — fingerprint-uri confirmate care NU-s plăți reale
                        (respinse/compensate sau ne-taxe) → refuzate de gardă.
    """
    confirmed = set(confirmed_fingerprints)
    fps = compute_fingerprints([r.txn for r in clasificate])   # aliniat pe index
    real_idx = real_payment_indices(clasificate)
    fps_reale = {fps[i] for i in real_idx}

    recorded = 0
    skipped_dup = 0
    details = []
    for i in real_idx:
        fp = fps[i]
        if fp not in confirmed:
            continue                          # userul nu a confirmat această plată reală
        if oblig_pay_repo.payment_exists(session, user_id, fp):
            skipped_dup += 1                  # re-import: deja înregistrată
            continue
        r = clasificate[i]
        o = r.oblig
        oblig_pay_repo.create_payment(
            session,
            user_id=user_id,
            obligation_code=o.declaratie,     # "D301"/"D100" deja scurt din hint
            perioada_an=o.an,
            perioada_luna=o.luna,
            suma_platita=r.txn.suma,
            data_platii=r.txn.data,
            import_fingerprint=fp,
            source_file_id=source_file_id,
        )
        recorded += 1
        details.append(
            {"cod": o.declaratie, "an": o.an, "luna": o.luna, "suma": r.txn.suma}
        )

    # confirmate dar NU plăți reale (respinse/compensate sau ne-taxe) → blocate structural
    skipped_blocked = len(confirmed - fps_reale)

    return {
        "recorded": recorded,
        "skipped_dup": skipped_dup,
        "skipped_blocked": skipped_blocked,
        "details": details,
    }
