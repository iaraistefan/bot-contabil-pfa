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
    """Document lifecycle state. Reserved for future use (step 9)."""
    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    POSTED = "posted"
    EXPORTED = "exported"
    REJECTED = "rejected"
