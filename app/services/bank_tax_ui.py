"""
UI confirmare plăți de taxe achitate (felia 5c-c) — LOGICĂ PURĂ + sync.

Userul vede plățile de taxe REALE din extras (după compensare, felia 5a) și
confirmă marcarea lor ca achitate în obligații (felia 5b/5c-a). Mirror al
`bank_import_ui` (felia 3 PAS 4a/4b): aici partea PURĂ + `finalize_tax_recording`
sync; glue-ul async (handlere callback `banktax|*`) vine în 5c-c-2.

Plățile reale = `compensate` — respinsele deja excluse. Confirmare PE GRUP
(confirmă-tot), fără excludere per-item (plățile-s deja filtrate de compensare).
"""
import logging
from typing import List, Set

from app.integrations.imports.dedup import compute_fingerprints
from app.integrations.imports.tax_payments import compensate, real_payment_indices

logger = logging.getLogger(__name__)

_LUNI_NUME = {
    1: "Ianuarie", 2: "Februarie", 3: "Martie", 4: "Aprilie",
    5: "Mai", 6: "Iunie", 7: "Iulie", 8: "August",
    9: "Septembrie", 10: "Octombrie", 11: "Noiembrie", 12: "Decembrie",
}


def _ron(x: float) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ============================================================
#                    STATE / HELPERS (pure)
# ============================================================

def real_tax_payments(clasificate: List) -> List:
    """Plățile de taxe REALE (după compensarea respinselor) — de propus userului."""
    return compensate(clasificate)


def has_real_tax(clasificate: List) -> bool:
    """True dacă există plăți de taxe reale → butonul „Marchează taxele" apare."""
    return bool(compensate(clasificate))


def real_tax_fingerprints(clasificate: List) -> Set[str]:
    """Amprentele plăților reale (confirmă-tot = tot setul). FINGERPRINT (stabil),
    NU index — peste tot extrasul (`compute_fingerprints` aliniat pe index, intern).
    """
    fps = compute_fingerprints([r.txn for r in clasificate])
    return {fps[i] for i in real_payment_indices(clasificate)}


# ============================================================
#                    TEXT BUILDERS (pure)
# ============================================================

def format_tax_propose(real_payments: List) -> str:
    """Ecranul de propunere: plățile reale (tip · perioadă — sumă)."""
    lines = [
        "✅ *Plăți de taxe găsite în extras*",
        "_Acestea apar achitate (au trecut, nu au fost respinse):_",
        "",
    ]
    for r in real_payments:
        o = r.oblig
        luna = _LUNI_NUME.get(o.luna, str(o.luna))
        lines.append(f"  • {o.declaratie} · {luna} {o.an} — *{_ron(r.txn.suma)} lei*")
    lines.append("")
    lines.append("Le marchez ca *achitate* în obligații?")
    return "\n".join(lines)


def format_tax_result(outcome: dict) -> str:
    """Rezultatul: succes / re-import / eroare (tot-sau-nimic transparent)."""
    if not outcome.get("ok"):
        return (
            "⚠️ A apărut o eroare. *Nimic nu a fost marcat* în obligații.\n"
            "Reîncearcă — extrasul e încă valid."
        )
    res = outcome.get("result", {})
    recorded = res.get("recorded", 0)
    if recorded == 1:
        lines = ["✅ *Gata.*", "Am marcat *1 obligație* ca achitată din extras."]
    else:
        lines = ["✅ *Gata.*",
                 f"Am marcat *{recorded} obligații* ca achitate din extras."]
    if res.get("skipped_dup"):
        lines.append(
            f"♻️ {res['skipped_dup']} erau deja marcate (ai mai încărcat extrasul)."
        )
    return "\n".join(lines)


# ============================================================
#       COMMIT TOT-SAU-NIMIC (sync, testabil — money-critical)
# ============================================================

def finalize_tax_recording(
    session, *, user_id, source_file_id, clasificate, confirmed_fingerprints
) -> dict:
    """Înregistrează plățile confirmate + commit TOT-SAU-NIMIC.

    `record_tax_payments` (5c-a) NU comite; aici un singur commit la final / rollback
    pe orice excepție = zero înregistrare parțială. Mirror `finalize_bank_post`.
    Întoarce {ok, result|error}.
    """
    from app.integrations.imports.tax_recording import record_tax_payments
    try:
        res = record_tax_payments(
            session, user_id=user_id, source_file_id=source_file_id,
            clasificate=clasificate, confirmed_fingerprints=confirmed_fingerprints,
        )
        session.commit()
        return {"ok": True, "result": res}
    except Exception as e:
        session.rollback()
        logger.error(f"finalize_tax_recording user={user_id}: {e}")
        return {"ok": False, "error": str(e)}
