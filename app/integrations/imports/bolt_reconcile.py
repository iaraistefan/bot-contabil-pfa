"""
Reconciliere de PREZENȚĂ a venitului Bolt (felia 4).

Extrasul confirmă că au intrat încasări Bolt. Dacă o lună are încasări Bolt în
extras DAR nu există venit Bolt sincronizat pentru ea → nudge soft: rulează /bolt.

NU e reconciliere pe SUMĂ: depunerile bancare sunt NETE, iar sync-ul postează pe
tariful BRUT; în plus payout-ul Bolt e săptămânal (≠ lună calendaristică), deci
potrivirea de sume ar produce false-alarme dese chiar când totul e corect. Aici
verificăm DOAR prezența (factual), nu corectitudinea sumelor.
"""
from typing import List, Optional, Set, Tuple

from app.integrations.imports.classify import VENIT_BOLT
# Sursă unică: filtrul de prezență Bolt + numele lunilor vin din bolt_sync.
from app.integrations.bolt_sync import has_bolt_income, LUNI_LONG


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
