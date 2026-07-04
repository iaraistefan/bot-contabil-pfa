"""
Certificat de rezidență fiscală Bolt — SURSĂ UNICĂ (web + Telegram + reminder).

REALITATE (confirmată cu suportul Bolt): certificatul „Romania.pdf" e AL FIRMEI Bolt
Operations OÜ — ACELAȘI pentru toți șoferii Bolt din RO (NU personalizat per user). Se
găsește în Portalul de Parteneri Bolt (ascuns) sau se cere suportului Bolt în chat
(răspund rapid, îl trimit ca PDF). Cu el → impozit nerezident 2% la D100; fără → 16%.

ONESTITATE: Contai NU pretinde că „generează certificatul TĂU" — oferă DOCUMENTUL COMUN
Bolt + ghidul de obținere + reminder anual. Nota „verifică anul" peste tot.

Fișierul (asset pus de owner) e servit static din `app/http/static/` la numele DINAMIC
pe an `certificat_bolt_romania_{an}.pdf` → la an nou, codul caută automat fișierul nou.
"""

import os
from datetime import date

# app/services/certificat.py → app/http/static/
_STATIC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "http", "static"
)


def current_year() -> int:
    return date.today().year


def filename(an: int) -> str:
    """Numele fișierului PDF pentru anul dat — DINAMIC (clar la reînnoire ce an e)."""
    return f"certificat_bolt_romania_{an}.pdf"


def file_path(an: int) -> str:
    return os.path.join(_STATIC_DIR, filename(an))


def url(an: int) -> str:
    """URL-ul static (servit de Flask din static_folder, fără rută dedicată)."""
    return f"/static/{filename(an)}"


def exists(an: int) -> bool:
    """True dacă owner-ul a pus deja PDF-ul anului în app/http/static/."""
    return os.path.isfile(file_path(an))


# ── Text (sursă unică pentru ambele surfețe) ──

INTRO = (
    "Certificatul de rezidență fiscală Bolt e documentul prin care Bolt Operations OÜ "
    "(Estonia) dovedește că e rezident fiscal acolo. Cu el aplici Convenția RO-Estonia "
    "(Art.12) → impozit nerezident *2%* la D100; fără el → *16%*. E documentul COMUN al "
    "firmei Bolt (același fișier Romania.pdf pentru toți șoferii) — NU unul personal."
)

GHID_OBTINERE = (
    "📍 *Cum îl obții:*\n"
    "• Oficial: din *Portalul de Parteneri Bolt* (e ascuns/greu de găsit).\n"
    "• Mai rapid: *cere-l suportului Bolt în chat* → ți-l trimit ca PDF în câteva minute.\n\n"
    "⚠️ _Verifică ANUL pe document înainte de depunere — îți trebuie cel valabil pentru "
    "anul curent._"
)


def mesaj_reminder(an: int, regim_bolt: str) -> str | None:
    """
    Mesajul reminderului anual de certificat, în funcție de regimul Bolt:
      - BOLT_CU_CRF (2%)  → REÎNNOIRE (păstrezi 2%);
      - BOLT_FARA_CRF (16%) → OPTIMIZARE (16% → 2%, economisești 14%);
      - altceva (None / Uber / negsetat) → None (fără reminder de certificat Bolt).
    """
    if regim_bolt == "BOLT_CU_CRF":
        return (
            f"🔄 *Certificat Bolt {an}*\n\n"
            f"Reînnoiește certificatul de rezidență fiscală Bolt pentru *{an}* ca să "
            f"rămâi pe *2%* la D100. Îl iei din Portalul de Parteneri Bolt sau ceri-l "
            f"suportului Bolt în chat (ți-l trimit rapid).\n\n"
            f"Apoi îl ai la îndemână în Coniar: /certificat."
        )
    if regim_bolt == "BOLT_FARA_CRF":
        return (
            f"💡 *Economisești 14% la impozit*\n\n"
            f"Ești pe *16%* la D100 (fără certificat Bolt). Știai că poți obține "
            f"certificatul de rezidență Bolt și treci la *2%*? Cere-l suportului Bolt "
            f"în chat (ți-l trimite rapid ca PDF), apoi schimbă regimul în "
            f"Setări → Bolt → *am certificatul*.\n\n"
            f"Vezi /certificat pentru ghid."
        )
    return None
