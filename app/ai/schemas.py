"""
Pydantic schemas pentru validarea output-ului AI.

Principii:
- Toleranti la input (strip whitespace, virgula ca zecimala, cifre ca string).
- Stricti la output (valori curate, cu tipuri garantate).
- Un item invalid nu arunca exceptie — intoarce o lista de erori.

FIX EXTRACTOR (audit):
- _validate_tip mapeaza variante (engleza, plural, sinonime) -> nu mai
  respinge documente bune doar pentru ca AI-ul a scris "EXPENSE" in loc de
  "CHELTUIALA".
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, ValidationError


# Valorile acceptate pentru `tip`. Trebuie sa corespunda cu DocType din app/enums.py.
ALLOWED_TIP = {"VENIT", "CHELTUIALA", "FACTURA_COMISION"}

# Variante frecvente pe care AI-ul le-ar putea returna -> mapate la valoarea corecta.
# Previne respingerea unui document bun din cauza unei etichete usor diferite.
TIP_ALIASES = {
    # Cheltuiala
    "EXPENSE": "CHELTUIALA",
    "EXPENSES": "CHELTUIALA",
    "CHELTUIELI": "CHELTUIALA",
    "BON": "CHELTUIALA",
    "BON_FISCAL": "CHELTUIALA",
    "COST": "CHELTUIALA",
    # Venit
    "INCOME": "VENIT",
    "VENITURI": "VENIT",
    "INCASARE": "VENIT",
    "REVENUE": "VENIT",
    "EARNINGS": "VENIT",
    # Factura comision
    "INVOICE": "FACTURA_COMISION",
    "FACTURA": "FACTURA_COMISION",
    "COMMISSION": "FACTURA_COMISION",
    "COMISION": "FACTURA_COMISION",
    "FACTURA_INTRACOMUNITARA": "FACTURA_COMISION",
}


class ExtractionItem(BaseModel):
    """Un document extras de AI — un rand de contabilitate."""

    data: Optional[str] = Field(default=None, description="DD.MM.YYYY")
    platforma: Optional[str] = Field(default=None, max_length=100)
    tip: str
    brut: float = 0.0
    comision: float = 0.0
    tva: float = 0.0
    net: float = 0.0
    cash: float = 0.0
    detalii: Optional[str] = Field(default="", max_length=500)

    # --- Validatori ---
    @field_validator("tip", mode="before")
    @classmethod
    def _validate_tip(cls, v):
        if v is None:
            raise ValueError("tip is required")
        v = str(v).strip().upper()
        # Acceptat direct
        if v in ALLOWED_TIP:
            return v
        # Incercam maparea variantelor (engleza, plural, sinonime)
        if v in TIP_ALIASES:
            return TIP_ALIASES[v]
        # Ultima sansa: cautam un cuvant-cheie continut
        for alias, canonical in TIP_ALIASES.items():
            if alias in v:
                return canonical
        raise ValueError(
            f"tip '{v}' not in {sorted(ALLOWED_TIP)}"
        )

    @field_validator("brut", "comision", "tva", "net", "cash", mode="before")
    @classmethod
    def _coerce_number(cls, v):
        """
        Accepta None->0, int/float direct, sau string in diverse formate:
          '300 lei'   -> 300.0   (elimina simbol moneda)
          '245.50'    -> 245.5   (punct zecimal, format standard)
          '250,50'    -> 250.5   (virgula zecimala, format RO)
          '1.250,50'  -> 1250.5  (format RO: punct=mii, virgula=zecimala)
        """
        if v is None or v == "":
            return 0.0
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            cleaned = v.strip()
            # Eliminam simboluri de moneda frecvente
            for sym in ("lei", "LEI", "Lei", "ron", "RON", "Ron", "€", "$"):
                cleaned = cleaned.replace(sym, "")
            cleaned = cleaned.replace(" ", "")
            # Normalizare separatori zecimali / de mii
            if "." in cleaned and "," in cleaned:
                # Format RO: 1.250,50 -> punctul e separator de mii
                cleaned = cleaned.replace(".", "").replace(",", ".")
            elif "," in cleaned:
                # Doar virgula = zecimala RO: 250,50 -> 250.50
                cleaned = cleaned.replace(",", ".")
            # else: doar punct (245.50) sau nicio -> deja valid
            try:
                return float(cleaned)
            except ValueError:
                raise ValueError(f"cannot parse number from '{v}'")
        raise ValueError(f"expected number, got {type(v).__name__}")

    @field_validator("data", mode="before")
    @classmethod
    def _normalize_date(cls, v):
        """
        Accepta DD.MM.YYYY, DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD.
        Output garantat: DD.MM.YYYY sau None.
        """
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        s = str(v).strip()
        for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y.%m.%d"):
            try:
                dt = datetime.strptime(s, fmt)
                return dt.strftime("%d.%m.%Y")
            except ValueError:
                continue
        # Nu aruncam eroare — data poate lipsi legitim (bot-ul pune azi ca fallback).
        return None

    @field_validator("platforma", "detalii", mode="before")
    @classmethod
    def _strip_strings(cls, v):
        if v is None:
            return v
        return str(v).strip()


class ValidationReport(BaseModel):
    """Rezultatul validarii unui batch de item-uri."""

    valid_items: List[ExtractionItem] = []
    errors: List[str] = []  # mesaje human-readable, per item invalid

    @property
    def has_valid(self) -> bool:
        return len(self.valid_items) > 0

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0


def validate_items(raw_items: list) -> ValidationReport:
    """
    Valideaza o lista de item-uri brute (dict-uri) primite de la AI.
    Un item invalid NU opreste validarea celorlalte.
    """
    report = ValidationReport()
    if not isinstance(raw_items, list):
        report.errors.append(f"expected list, got {type(raw_items).__name__}")
        return report

    for idx, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            report.errors.append(f"item #{idx + 1}: not an object")
            continue
        try:
            item = ExtractionItem(**raw)
            report.valid_items.append(item)
        except ValidationError as e:
            # Extragem mesajele din Pydantic intr-o forma concisa.
            issues = "; ".join(
                f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
                for err in e.errors()
            )
            report.errors.append(f"item #{idx + 1}: {issues}")

    return report
