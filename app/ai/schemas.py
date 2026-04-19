"""
Pydantic schemas pentru validarea output-ului AI.

Principii:
- Toleranți la input (strip whitespace, virgulă ca zecimală, cifre ca string).
- Stricți la output (valori curate, cu tipuri garantate).
- Un item invalid nu aruncă excepție — întoarce o listă de erori.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, ValidationError


# Valorile acceptate pentru `tip`. Trebuie să corespundă cu DocType din app/enums.py.
ALLOWED_TIP = {"VENIT", "CHELTUIALA", "FACTURA_COMISION"}


class ExtractionItem(BaseModel):
    """Un document extras de AI — un rând de contabilitate."""

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
        if v not in ALLOWED_TIP:
            raise ValueError(
                f"tip '{v}' not in {sorted(ALLOWED_TIP)}"
            )
        return v

    @field_validator("brut", "comision", "tva", "net", "cash", mode="before")
    @classmethod
    def _coerce_number(cls, v):
        """Acceptă None→0, string cu virgulă, string cu spații."""
        if v is None or v == "":
            return 0.0
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            cleaned = v.strip().replace(",", ".").replace(" ", "")
            try:
                return float(cleaned)
            except ValueError:
                raise ValueError(f"cannot parse number from '{v}'")
        raise ValueError(f"expected number, got {type(v).__name__}")

    @field_validator("data", mode="before")
    @classmethod
    def _normalize_date(cls, v):
        """
        Acceptă DD.MM.YYYY, DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD.
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
        # Nu aruncăm eroare — data poate lipsi legitim (bot-ul pune azi ca fallback).
        return None

    @field_validator("platforma", "detalii", mode="before")
    @classmethod
    def _strip_strings(cls, v):
        if v is None:
            return v
        return str(v).strip()


class ValidationReport(BaseModel):
    """Rezultatul validării unui batch de item-uri."""

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
    Validează o listă de item-uri brute (dict-uri) primite de la AI.
    Un item invalid NU oprește validarea celorlalte.
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
            # Extragem mesajele din Pydantic într-o formă concisă.
            issues = "; ".join(
                f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
                for err in e.errors()
            )
            report.errors.append(f"item #{idx + 1}: {issues}")

    return report
