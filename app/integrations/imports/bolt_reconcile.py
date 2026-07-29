"""
Reconciliere de PREZENȚĂ a venitului Bolt (felia 4).

Extrasul confirmă că au intrat încasări Bolt. Dacă o lună are încasări Bolt în
extras DAR nu există venit Bolt sincronizat pentru ea → nudge soft: rulează /bolt.

NU e reconciliere pe SUMĂ: depunerile bancare sunt NETE, iar sync-ul postează pe
tariful BRUT; în plus payout-ul Bolt e săptămânal (≠ lună calendaristică), deci
potrivirea de sume ar produce false-alarme dese chiar când totul e corect. Aici
verificăm DOAR prezența (factual), nu corectitudinea sumelor.
"""
import logging
from typing import List, Optional, Set, Tuple

from app.integrations.imports.classify import VENIT_BOLT
# Sursă unică: filtrul de prezență Bolt + numele lunilor vin din bolt_sync.
from app.integrations.bolt_sync import has_bolt_income, LUNI_LONG

logger = logging.getLogger(__name__)


def bolt_months_in_statement(clasificate: List) -> Set[Tuple[int, int]]:
    """Lunile (an, lună) cu măcar o încasare VENIT_BOLT în extras (pur)."""
    out: Set[Tuple[int, int]] = set()
    for r in clasificate:
        if r.bucket == VENIT_BOLT and r.txn.data:
            out.add((r.txn.data.year, r.txn.data.month))
    return out


def bolt_reconcile_nudge(session, user_id: int, clasificate: List) -> Optional[str]:
    """Nudge dacă există luni cu Bolt în extras dar fără venit sincronizat.

    Întoarce textul de adăugat la preview, sau None dacă totul e sincronizat
    (tăcere — nu deranjăm). Formulare NEUTRĂ (verificare, nu acuzație de eroare).
    """
    months = sorted(bolt_months_in_statement(clasificate))
    lipsa = [(y, m) for (y, m) in months if not has_bolt_income(session, user_id, y, m)]
    if not lipsa:
        return None

    lines = [
        "───────────────",
        "ℹ️ *Verificare venit Bolt*",
        "Văd încasări Bolt în extras pentru luni care nu apar încă sincronizate:",
    ]
    for (y, m) in lipsa:
        lines.append(
            f"• {LUNI_LONG[m]} {y} — rulează `/bolt {y} {m}` ca să sincronizezi cursele"
        )
    lines.append(
        "_Venitul Bolt corect vine din sincronizarea API, nu din extras "
        "(depunerile bancare sunt nete, nu brute)._"
    )
    return "\n".join(lines)


def safe_reconcile_nudge(session, user_id: int, clasificate: List) -> Optional[str]:
    """Wrapper DEFENSIV peste `bolt_reconcile_nudge`.

    Reconcilierea e BONUS, nu valoarea principală (preview-ul). O eroare la
    interogarea de prezență (DB lent/eroare) NU trebuie să strice preview-ul →
    o prindem și întoarcem None (preview normal).
    """
    try:
        return bolt_reconcile_nudge(session, user_id, clasificate)
    except Exception as e:
        logger.error(f"bolt_reconcile_nudge failed (preview neafectat): {e}")
        return None


def append_nudge(preview_text: str, session, user_id: int, clasificate: List) -> str:
    """Întoarce preview-ul cu nudge-ul reconcilierii adăugat ca secțiune separată.

    Aditiv: dacă nu e nimic de raportat (tot sincronizat) SAU reconcilierea crapă
    → preview-ul rămâne NESCHIMBAT (bit-identic).
    """
    nudge = safe_reconcile_nudge(session, user_id, clasificate)
    if nudge:
        return f"{preview_text}\n\n{nudge}"
    return preview_text


# ══════════════════════════════════════════════════════════════
# Reconciliere pe SUMĂ (felia 4b) — axa CURATĂ: Bolt API brut vs declarat.
#
# Ortogonal de reconcilierea de PREZENȚĂ de mai sus (has_bolt_income): aceea
# acoperă luni NEsincronizate; asta acoperă luni SINCRONIZATE dar cu sumă
# divergentă. Ambele surse sunt BRUTE, lunare, tip-exclusive (post_month scrie
# exact summary["brut"]) → comparabile direct, fără false-alarme. Diferențele
# legitime pe axa asta: comenzi întârziate (re-sync) / rotunjire (sub prag).
# (Payout net / timing săptămânal / 2% / TVA = axa BANCARĂ, NU aici.)
# ══════════════════════════════════════════════════════════════

# Prag „diferență semnificativă": max(absolut, relativ). Absolutul domină la sume
# mici (rotunjiri), relativul la sume mari. Tunable.
RECON_TOL_ABS = 5.0     # lei
RECON_TOL_PCT = 0.01    # 1%


def bolt_amount_reconcile(brut_api, brut_declarat):
    """
    Compară venitul Bolt BRUT: API (adevărul Bolt) vs declarat (Registru).

    Args:
        brut_api: brut din get_month_summary (None → cache/API indisponibil).
        brut_declarat: brut din income_by_platform["bolt"] (Registru).

    Returns:
        (brut_api, brut_declarat, diferenta, status), unde
        diferenta = declarat − api (semnat), status ∈ {OK, DISCREPANTA, INDISPONIBIL}.
        Sub toleranță → OK; peste → DISCREPANTA; fără sursă API → INDISPONIBIL.
    """
    dec = round(brut_declarat or 0.0, 2)
    if brut_api is None:
        return (None, dec, None, "INDISPONIBIL")
    api = round(brut_api, 2)
    dif = round(dec - api, 2)
    prag = max(RECON_TOL_ABS, RECON_TOL_PCT * abs(api))
    status = "OK" if abs(dif) <= prag else "DISCREPANTA"
    return (api, dec, dif, status)


def declared_bolt_brut(session, user_id: int, year: int, month: int):
    """
    Venitul Bolt BRUT declarat în Registru pentru lună — din income_by_platform
    (sursă unică, invariant Σ==income_total). None dacă nu se poate calcula.
    """
    from app.services import tax_engine  # lazy — evită orice ciclu de import
    t = tax_engine.compute_period(session, user_id=user_id, year=year, month=month)
    for p in t.get("income_by_platform", []):
        if p.get("brand") == "bolt":
            return float(p["amount_brut"])
    return 0.0  # nicio felie Bolt → 0 declarat


def bolt_amount_confirm_line(brut_api, brut_declarat):
    """
    Linia de reconciliere pt confirmarea `/bolt` (felia 4b). NEUTRĂ (verificare,
    nu acuzație), ca prezența. ✅ pe OK (întărire de încredere), ⚠️ pe discrepanță
    cu cifrele + cauze normale, None pe INDISPONIBIL (tăcere — nu inventăm).
    """
    api, dec, dif, status = bolt_amount_reconcile(brut_api, brut_declarat)
    if status == "INDISPONIBIL":
        return None
    if status == "OK":
        return f"🔎 Reconciliere: API-ul Bolt confirmă {api:.2f} lei ✅"
    return (
        f"⚠️ *Verificare sumă Bolt*: ai declarat {dec:.2f} lei, dar API-ul Bolt "
        f"arată {api:.2f} lei (diferență {dif:+.2f}).\n"
        "_Cauze normale: un sync mai vechi (rulează /bolt din nou) sau venituri "
        "Bolt adăugate manual peste sincronizare._"
    )
