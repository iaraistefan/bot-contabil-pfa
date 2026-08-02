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


def bolt_reconcile_nudge(session, user_id: int, clasificate: List,
                         detailed: bool = True) -> Optional[str]:
    """Nudge dacă există luni cu Bolt în extras dar fără venit sincronizat.

    Întoarce textul de adăugat la preview, sau None dacă totul e sincronizat
    (tăcere — nu deranjăm). Formulare NEUTRĂ (verificare, nu acuzație de eroare).

    `detailed` (Felia 4b): False → teaser (câte luni, fără enumerare și fără comanda
    de sync — sincronizarea e din START). Default True = comportamentul dinainte,
    bit-identic. Detectarea în sine NU se schimbă, doar cât arătăm din ea.
    """
    months = sorted(bolt_months_in_statement(clasificate))
    lipsa = [(y, m) for (y, m) in months if not has_bolt_income(session, user_id, y, m)]
    if not lipsa:
        return None

    if not detailed:
        from app.services.gating import teaser_prezenta
        return teaser_prezenta(len(lipsa))

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


def safe_reconcile_nudge(session, user_id: int, clasificate: List,
                         detailed: bool = True) -> Optional[str]:
    """Wrapper DEFENSIV peste `bolt_reconcile_nudge`.

    Reconcilierea e BONUS, nu valoarea principală (preview-ul). O eroare la
    interogarea de prezență (DB lent/eroare) NU trebuie să strice preview-ul →
    o prindem și întoarcem None (preview normal).
    """
    try:
        return bolt_reconcile_nudge(session, user_id, clasificate, detailed=detailed)
    except Exception as e:
        logger.error(f"bolt_reconcile_nudge failed (preview neafectat): {e}")
        return None


def append_nudge(preview_text: str, session, user_id: int, clasificate: List,
                 detailed: bool = True) -> str:
    """Întoarce preview-ul cu nudge-ul reconcilierii adăugat ca secțiune separată.

    Aditiv: dacă nu e nimic de raportat (tot sincronizat) SAU reconcilierea crapă
    → preview-ul rămâne NESCHIMBAT (bit-identic). `detailed` = felia 4b (vezi
    `bolt_reconcile_nudge`); default True păstrează comportamentul dinainte.
    """
    nudge = safe_reconcile_nudge(session, user_id, clasificate, detailed=detailed)
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


def bolt_amount_confirm_line(brut_api, brut_declarat, detailed: bool = True):
    """
    Linia de reconciliere pt confirmarea `/bolt` (felia 4b). NEUTRĂ (verificare,
    nu acuzație), ca prezența. ✅ pe OK (întărire de încredere), ⚠️ pe discrepanță
    cu cifrele + cauze normale, None pe INDISPONIBIL (tăcere — nu inventăm).

    `detailed=False` (FREE, felia 4b): pe DISCREPANȚĂ arată DOAR mărimea diferenței
    (teaser — cauzele și pașii sunt în PRO). Confirmarea ✅ rămâne pentru toată lumea:
    e liniștire, nu „armă secretă". `bolt_amount_reconcile` rămâne NEATINSĂ.
    """
    api, dec, dif, status = bolt_amount_reconcile(brut_api, brut_declarat)
    if status == "INDISPONIBIL":
        return None
    if status == "OK":
        return f"🔎 Reconciliere: API-ul Bolt confirmă {api:.2f} lei ✅"
    if not detailed:
        from app.services.gating import teaser_reconciliere
        return teaser_reconciliere(dif)
    return (
        f"⚠️ *Verificare sumă Bolt*: ai declarat {dec:.2f} lei, dar API-ul Bolt "
        f"arată {api:.2f} lei (diferență {dif:+.2f}).\n"
        "_Cauze normale: un sync mai vechi (rulează /bolt din nou) sau venituri "
        "Bolt adăugate manual peste sincronizare._"
    )


# ══════════════════════════════════════════════════════════════
# Axa BANCARĂ CUMULATIVĂ (felia 4c) — Bolt încasat-în-bancă vs net bancabil.
#
# A TREIA axă, ORTOGONALĂ de prezență (has_bolt_income) și de pas 1 (brut↔declarat).
# NU atinge nicio funcție de mai sus.
#
# De ce CUMULATIV (YTD), nu lunar: payout-ul Bolt e săptămânal, nu respectă luna
# calendaristică — un verdict lunar ar minți cu precizie falsă (payout de la cumpăna
# lunii cade în luna „greșită"). Cumulativ pe an, timingul se spală.
#
# De ce NET vs NET (nu brut): banca arată ce DEPUNE Bolt = NET (după comision).
# Capcana #1: Bolt depune DOAR partea card/app; cursele cash le încasezi în mână →
# net bancabil EXCLUDE cash (bolt_sync.net_bancabil_an). Fără excludere, un șofer cu
# cash ar primi discrepanță falsă sistematică.
#
# Diferențe legitime (sub toleranță, NU erori): timing (spălat cumulativ), reziduuri
# 2%/TVA/ajustări, rotunjiri. Prag LARG (cumulativ acumulează reziduuri).
# ══════════════════════════════════════════════════════════════

BANK_RECON_TOL_ABS = 50.0    # lei (cumulativ pe an → prag absolut mai mare)
BANK_RECON_TOL_PCT = 0.02    # 2% (reziduuri 2%/TVA/ajustări se adună pe an)


def bank_bolt_net_in_year(clasificate, an):
    """
    Σ încasărilor VENIT_BOLT (net, din bancă) cu data în anul `an`. Oglinda lui
    bolt_months_in_statement, dar SUMEAZĂ suma (nu doar citește datele). Pură.
    """
    from app.integrations.imports.classify import VENIT_BOLT
    total = 0.0
    for r in clasificate:
        if r.bucket == VENIT_BOLT and r.txn.data and r.txn.data.year == an:
            total += r.txn.suma
    return round(total, 2)


def bolt_bank_reconcile_cumulative(bank_net, net_bancabil):
    """
    Reconciliere BANCARĂ cumulativă: încasat-în-bancă (net) vs net bancabil Bolt.

    Args:
        bank_net: Σ VENIT_BOLT bancar pe an (net, doar card — cash nu intră în cont).
        net_bancabil: net_bancabil_an din Bolt (None → cache indisponibil).

    Returns:
        (bank_net, net_bancabil, diferenta, status), diferenta = bank − bancabil,
        status ∈ {OK, DISCREPANTA, INDISPONIBIL}. Prag LARG max(50 lei, 2%).
    """
    bank = round(bank_net or 0.0, 2)
    if net_bancabil is None:
        return (bank, None, None, "INDISPONIBIL")
    bancabil = round(net_bancabil, 2)
    dif = round(bank - bancabil, 2)
    prag = max(BANK_RECON_TOL_ABS, BANK_RECON_TOL_PCT * abs(bancabil))
    status = "OK" if abs(dif) <= prag else "DISCREPANTA"
    return (bank, bancabil, dif, status)


def bank_reconcile_nudge(session, user_id: int, clasificate, an,
                         detailed: bool = True):
    """
    Nudge NEUTRU pt axa bancară cumulativă, de adăugat la preview-ul extrasului.

    Compară Σ VENIT_BOLT bancar/an (net) vs net bancabil Bolt/an (non-cash). ✅ pe
    OK (întărire), ⚠️ pe discrepanță cu cifre + cauze, None pe INDISPONIBIL/fără Bolt
    în extras (tăcere — nu inventăm). Nu atinge prezența/pas 1.

    `detailed=False` (FREE, felia 4b): pe discrepanță doar mărimea diferenței (teaser).
    `bolt_bank_reconcile_cumulative` rămâne NEATINSĂ — ramifică doar afișajul.
    """
    bank_net = bank_bolt_net_in_year(clasificate, an)
    if bank_net <= 0:
        return None  # niciun VENIT_BOLT în extras pe anul ăsta → tăcere
    from app.integrations.bolt_sync import net_bancabil_an
    bancabil = net_bancabil_an(user_id, an)
    bank, bancabil, dif, status = bolt_bank_reconcile_cumulative(bank_net, bancabil)
    if status == "INDISPONIBIL":
        return None
    if status == "OK":
        return (
            f"───────────────\n"
            f"🔎 *Reconciliere bancară {an}*: ai încasat {bank:.2f} lei de la Bolt · "
            f"Bolt confirmă ≈{bancabil:.2f} lei net (card) ✅\n"
            "_Cashul nu intră în bancă (îl încasezi în mână), deci nu se compară aici._"
        )
    if not detailed:
        from app.services.gating import teaser_reconciliere
        return f"───────────────\n{teaser_reconciliere(dif)}"
    return (
        f"───────────────\n"
        f"⚠️ *Reconciliere bancară {an}*: ai încasat {bank:.2f} lei de la Bolt în cont, "
        f"dar Bolt confirmă ≈{bancabil:.2f} lei net card (diferență {dif:+.2f}).\n"
        "_Cauze normale: sync incomplet (rulează /bolt pe lunile lipsă), payout-uri la "
        "cumpăna anului sau ajustări. Cashul nu intră aici. Dacă diferența e mare, "
        "verifică dacă toate lunile-s sincronizate._"
    )


def safe_bank_reconcile_nudge(session, user_id: int, clasificate, an,
                              detailed: bool = True):
    """Wrapper DEFENSIV (ca safe_reconcile_nudge): eroare → None, preview neatins."""
    try:
        return bank_reconcile_nudge(session, user_id, clasificate, an, detailed=detailed)
    except Exception as e:
        logger.error(f"bank_reconcile_nudge failed (preview neafectat): {e}")
        return None


def append_bank_nudge(preview_text: str, session, user_id: int, clasificate, an,
                      detailed: bool = True) -> str:
    """Aditiv: preview + nudge bancar cumulativ (sau NESCHIMBAT dacă None/eroare)."""
    nudge = safe_bank_reconcile_nudge(session, user_id, clasificate, an, detailed=detailed)
    if nudge:
        return f"{preview_text}\n\n{nudge}"
    return preview_text
