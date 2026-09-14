"""
Central registry of string constants used across the bot.

Rules:
- Each enum value equals the string used in the DB / AI JSON / Sheets.
  (We're NOT changing any wire format — just giving the strings names.)
- Importing an enum gives you autocomplete + typo-proof code.
- String comparisons still work: DocType.VENIT == "VENIT" is True.
"""

from enum import Enum


class DocType(str, Enum):
    """Values the AI returns in the `tip` field."""
    VENIT = "VENIT"
    CHELTUIALA = "CHELTUIALA"
    FACTURA_COMISION = "FACTURA_COMISION"


class Platform(str, Enum):
    """Known platforms. Free-text still accepted; this is just for convenience."""
    BOLT = "Bolt"
    UBER = "Uber"
    PETROM = "Petrom"
    OMV = "OMV"
    LUKOIL = "Lukoil"
    ROMPETROL = "Rompetrol"
    MOL = "MOL"
    SOCAR = "Socar"


class PaymentMethod(str, Enum):
    """How the money moved. Reserved for future use (step 10+)."""
    CASH = "CASH"
    CARD = "CARD"
    BANK = "BANK"
    APP = "APP"
    UNKNOWN = "UNKNOWN"


class DocStatus(str, Enum):
    """
    Vocabularul rezervat pentru starea unui document.

    ⚠️ NU e lista valorilor care EXISTĂ. Enum-ul a fost scris în avans, „pentru
    pasul 9", iar pasul ăla n-a venit: din cele șase, codul scrie DOUĂ. Vezi
    `DOC_STATUSES_SCRISE` mai jos — aia e realitatea, asta e intenția.
    Diferența contează: `Document.status == DocStatus.CONFIRMED` ar fi o comparație
    veșnic falsă, care nu dă nicio eroare și pare corectă la citire.
    """
    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    POSTED = "posted"
    EXPORTED = "exported"
    REJECTED = "rejected"


# ── SURSA UNICĂ a valorilor pe care codul CHIAR le scrie în `documents.status` ──
#
# Măsurat, nu presupus: în producție (13.09.2026) există exact aceste două valori.
# Scriitorii, tot ce sunt:
#   • "posted"   — `bot_contabil.persist_document` (implicit și `documents_repo.create`)
#   • "rejected" — `bot_contabil.py`, la /delete, prin `documents_repo.set_status`
#
# ⚠️ `Document.status` N-ARE enum la nivel de coloană și nicio constrângere în DB
# (`models.py`: `Column(String(20), nullable=False, default="posted")`). Deci nimic
# nu oprește o a treia valoare să apară — și nimic n-ar semnala-o. De aceea orice
# filtru pe status trebuie să fie ALLOWLIST („care valori mă interesează"), niciodată
# denylist („toate în afară de X"): un denylist e o afirmație despre valorile care NU
# există, iar afirmația asta n-are cine s-o apere.
#
# Gardianul: tests/test_status_allowlist.py — derivă valorile DE AICI.
# Când se adaugă o a treia valoare, se adaugă AICI ÎNTÂI, și abia apoi se scrie.
DOC_STATUSES_SCRISE = frozenset({
    DocStatus.POSTED.value,      # "posted"   — document înregistrat, intră în cifre
    DocStatus.REJECTED.value,    # "rejected" — șters de user; rămâne pentru audit
})
