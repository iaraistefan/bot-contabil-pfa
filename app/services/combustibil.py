"""
Pas A+ - Integrare bonuri combustibil cu foaia de parcurs.

Calculeaza cat combustibil mai poate incarca user-ul, pe baza km
business documentati prin foaia de parcurs.

LOGICA:
  plafon_litri = km_business x norma_consum / 100
  pret_mediu   = total_lei_bonuri_cu_litri / total_litri  (din bonuri reale)
  plafon_lei   = plafon_litri x pret_mediu
  mai_poti     = plafon_lei - total_bonuri_lei

Pretul se calculeaza automat din bonurile care contin litri in descriere
(campul detalii al documentului). Daca niciun bon nu are litri inregistrati
-> fallback la pretul de referinta.

NOTA: Pentru activitatea de ridesharing, combustibilul aferent km business
documentati prin foaia de parcurs este integral deductibil (exceptat de la
plafonul de 50%). Acest modul arata cat mai poate incarca user-ul astfel
incat totul sa fie acoperit de foaia de parcurs.

CHANGELOG:
  - v1 (Pas A+): Versiune initiala
"""

import logging
import re

from db import get_session
from app.repositories import trip_logs as trip_repo
from app.repositories import vehicule as vehicule_repo

logger = logging.getLogger(__name__)

# Pret de referinta motorina (RON/L) - folosit DOAR daca niciun bon nu are litri
PRET_MOTORINA_FALLBACK = 7.5

# Categoria sub care se salveaza bonurile de combustibil (din ridesharing.py)
FUEL_CATEGORY = "fuel"

LUNI_LONG = {
    1: "Ianuarie", 2: "Februarie", 3: "Martie", 4: "Aprilie",
    5: "Mai", 6: "Iunie", 7: "Iulie", 8: "August",
    9: "Septembrie", 10: "Octombrie", 11: "Noiembrie", 12: "Decembrie",
}

# Regex pentru extragerea litrilor dintr-un text.
# Prinde: "40L", "40 l", "40 litri", "40.5 litru", "40,5l", "38 LITRI"
# NU prinde: "300 lei" (l urmat de alta litera -> lookahead esueaza)
_LITERS_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:litri|litru|litre|[lL])(?![a-zA-Z])",
    re.IGNORECASE,
)


def extract_liters(text: str):
    """
    Extrage numarul de litri dintr-un text. Returneaza float sau None.

    Exemple:
      "Combustibil OMV 40 litri"  -> 40.0
      "motorina 38.5L"            -> 38.5
      "Combustibil Lukoil"        -> None  (fara litri)
      "300 lei"                   -> None  ("lei" nu e "litri")
    """
    if not text:
        return None
    m = _LITERS_RE.search(text)
    if not m:
        return None
    try:
        val = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    # Sanity: un plin rezonabil 1-200 L
    if 1.0 <= val <= 200.0:
        return val
    return None


def _fmt_lei(value) -> str:
    """Formateaza o suma in lei."""
    return f"{value:,.0f}".replace(",", ".")


def _fmt_litri(value) -> str:
    """Formateaza litri (1 zecimala daca e nevoie)."""
    if abs(value - round(value)) < 0.05:
        return str(int(round(value)))
    return f"{value:.1f}"


# ============================================================
#       CALCUL SUMAR COMBUSTIBIL
# ============================================================

def get_fuel_summary(user_id: int, year: int, month: int) -> dict:
    """
    Calculeaza sumarul combustibil pentru o luna.

    Returns dict cu:
      km_business      - km in interes business (din foaia de parcurs)
      norma_consum     - L/100km a masinii
      plafon_litri     - litri deductibili (km x norma / 100)
      plafon_lei       - valoarea in lei a plafonului
      total_bonuri_lei - cat a incarcat pe bonuri de combustibil
      total_litri      - litri inregistrati pe bonuri (cele cu litri)
      pret_mediu       - RON/L (din bonuri sau fallback)
      pret_din_bonuri  - True daca pretul e calculat din bonuri reale
      mai_poti_lei     - cat mai poate incarca (poate fi negativ = depasit)
      nr_bonuri        - numar bonuri de combustibil
      nr_bonuri_cu_litri - cate au litri inregistrati
    """
    session = get_session()
    try:
        from app.models import Transaction, Document

        # Bonurile de combustibil ale lunii (cu documentul asociat)
        fuel_rows = (
            session.query(Transaction, Document)
            .join(Document, Transaction.document_id == Document.id)
            .filter(
                Transaction.user_id == user_id,
                Transaction.tx_type == "EXPENSE",
                Transaction.category == FUEL_CATEGORY,
                Transaction.period_year == year,
                Transaction.period_month == month,
            )
            .all()
        )

        # Km business din foaia de parcurs (ture inchise)
        trips = trip_repo.list_closed_for_month(session, user_id, year, month)
        km_business = sum((t.km or 0.0) for t in trips)

        # Norma de consum a masinii
        vehicul = vehicule_repo.get_default(session, user_id)
        norma = vehicul.norma_consum if vehicul else PRET_MOTORINA_FALLBACK
        if not norma or norma <= 0:
            norma = 7.5
    finally:
        session.close()

    # Agregare bonuri
    total_bonuri_lei = 0.0
    total_litri = 0.0
    lei_cu_litri = 0.0
    nr_bonuri = 0
    nr_bonuri_cu_litri = 0

    for tx, doc in fuel_rows:
        suma = tx.amount_brut or 0.0
        total_bonuri_lei += suma
        nr_bonuri += 1
        # Cautam litrii in descrierea documentului
        litri = extract_liters(doc.detalii if doc else None)
        if litri:
            total_litri += litri
            lei_cu_litri += suma
            nr_bonuri_cu_litri += 1

    # Pret mediu: din bonuri reale daca avem litri, altfel fallback
    if total_litri > 0:
        pret_mediu = lei_cu_litri / total_litri
        pret_din_bonuri = True
    else:
        pret_mediu = PRET_MOTORINA_FALLBACK
        pret_din_bonuri = False

    # Plafon deductibil
    plafon_litri = km_business * norma / 100.0
    plafon_lei = plafon_litri * pret_mediu
    mai_poti_lei = plafon_lei - total_bonuri_lei

    return {
        "year": year,
        "month": month,
        "km_business": km_business,
        "norma_consum": norma,
        "plafon_litri": plafon_litri,
        "plafon_lei": plafon_lei,
        "total_bonuri_lei": total_bonuri_lei,
        "total_litri": total_litri,
        "pret_mediu": pret_mediu,
        "pret_din_bonuri": pret_din_bonuri,
        "mai_poti_lei": mai_poti_lei,
        "nr_bonuri": nr_bonuri,
        "nr_bonuri_cu_litri": nr_bonuri_cu_litri,
    }


# ============================================================
#       FORMATARE PENTRU TELEGRAM
# ============================================================

def format_fuel_section(summary: dict) -> str:
    """
    Formateaza sumarul combustibil pentru afisare in Telegram.
    Returneaza string Markdown (sau "" daca nu e nimic de aratat).
    """
    km = summary["km_business"]
    nr_bonuri = summary["nr_bonuri"]

    # Daca nu exista nici km, nici bonuri -> nu afisam nimic
    if km <= 0 and nr_bonuri == 0:
        return ""

    luna = LUNI_LONG.get(summary["month"], "")
    an = summary["year"]
    norma = summary["norma_consum"]

    lines = [
        f"⛽ *Combustibil — {luna} {an}*",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    # Caz: nu are km business inca
    if km <= 0:
        lines.append("")
        lines.append(
            f"🧾 Bonuri încărcate: *{_fmt_lei(summary['total_bonuri_lei'])} lei*"
        )
        lines.append("")
        lines.append(
            "⚠️ _Nu ai km business înregistrați. Folosește foaia de "
            "parcurs (`parcurs start/stop`) ca să poți justifica "
            "deductibilitatea combustibilului._"
        )
        return "\n".join(lines)

    plafon_litri = summary["plafon_litri"]
    plafon_lei = summary["plafon_lei"]
    total_bonuri = summary["total_bonuri_lei"]
    mai_poti = summary["mai_poti_lei"]

    lines.append("")
    lines.append(f"🛣️ Km business (foaie): *{_fmt_litri(km)} km*")
    lines.append(
        f"📊 Plafon deductibil: *{_fmt_litri(plafon_litri)} L* "
        f"(~{_fmt_lei(plafon_lei)} lei)"
    )
    lines.append(f"🧾 Bonuri încărcate: *{_fmt_lei(total_bonuri)} lei*")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    # Verdictul
    if mai_poti >= 1:
        lines.append(f"✅ *Mai poți încărca: ~{_fmt_lei(mai_poti)} lei*")
    elif mai_poti <= -1:
        lines.append(
            f"⚠️ *Ai depășit plafonul cu ~{_fmt_lei(abs(mai_poti))} lei*\n"
            f"_Acea parte nu e acoperită de foaia de parcurs._"
        )
    else:
        lines.append("🎯 *Ești exact la plafon.*")

    # Nota despre pret
    pret = summary["pret_mediu"]
    if summary["pret_din_bonuri"]:
        lines.append(
            f"\n_Preț mediu motorină: {pret:.2f} lei/L "
            f"(calculat din {summary['nr_bonuri_cu_litri']} bonuri cu litri)._"
        )
    else:
        lines.append(
            f"\n_Preț estimat: {pret:.2f} lei/L. Scrie litrii pe bonuri "
            f"(ex: `... 300 lei 40 litri`) pentru un calcul exact._"
        )

    return "\n".join(lines)
