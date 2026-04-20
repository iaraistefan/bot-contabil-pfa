"""
Export CSV pentru tranzacțiile unui PFA.

Generează două fișiere în memorie (nu pe disk):
1. transactions_<luna>_<an>.csv  — toate tranzacțiile cu detalii complete
2. rezumat_<luna>_<an>.csv       — totalurile fiscale ale perioadei

Ambele sunt returnate ca bytes, gata de trimis prin Telegram.
Nu atinge DB direct — primește datele ca argumente.
"""

import csv
import io
from datetime import date
from typing import Any, Dict, List, Optional


# Header-ul CSV pentru tranzacții
TX_HEADERS = [
    "ID",
    "Data",
    "Tip",
    "Categorie",
    "Brut (RON)",
    "TVA (RON)",
    "Net (RON)",
    "Deductibil %",
    "Suma Deductibila (RON)",
    "Moneda",
    "Metoda Plata",
    "Partener",
    "Tratament TVA",
    "An",
    "Luna",
]

# Header-ul CSV pentru rezumat
REZUMAT_HEADERS = ["Indicator", "Valoare (RON)"]


def _deductible_amount(amount_brut: float, deductibility_pct: int) -> float:
    """Suma efectiv deductibilă."""
    return round(amount_brut * deductibility_pct / 100, 2)


def generate_transactions_csv(
    transactions: List[Any],
    year: int,
    month: int,
) -> bytes:
    """
    Generează CSV cu toate tranzacțiile unei perioade.

    Args:
        transactions: Lista de obiecte Transaction din SQLAlchemy.
        year: Anul perioadei.
        month: Luna perioadei.

    Returns:
        bytes — conținutul CSV, encodat UTF-8 cu BOM (pentru Excel românesc).
    """
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)

    # Header
    writer.writerow(TX_HEADERS)

    # Rânduri
    for tx in transactions:
        occurred = tx.occurred_on.strftime("%d.%m.%Y") if tx.occurred_on else ""
        deductible = _deductible_amount(tx.amount_brut, tx.deductibility_pct)

        writer.writerow([
            tx.id,
            occurred,
            tx.tx_type,
            tx.category,
            f"{tx.amount_brut:.2f}",
            f"{tx.amount_vat:.2f}",
            f"{tx.amount_net:.2f}",
            tx.deductibility_pct,
            f"{deductible:.2f}",
            tx.currency,
            tx.payment_method or "",
            tx.counterparty or "",
            tx.vat_treatment or "",
            tx.period_year or year,
            tx.period_month or month,
        ])

    # UTF-8 cu BOM — Excel românesc îl citește corect fără probleme de encoding
    return b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")


def generate_rezumat_csv(
    totals: Dict[str, Any],
) -> bytes:
    """
    Generează CSV cu rezumatul fiscal al perioadei.

    Args:
        totals: Dict returnat de tax_engine.compute_period().

    Returns:
        bytes — conținutul CSV, encodat UTF-8 cu BOM.
    """
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)

    month_name = totals.get("month_name", str(totals.get("month", "")))
    year = totals.get("year", "")

    # Header cu titlul perioadei
    writer.writerow([f"RAPORT FISCAL {month_name.upper()} {year}", ""])
    writer.writerow([])
    writer.writerow(REZUMAT_HEADERS)

    rows = [
        ("--- VENITURI ---", ""),
        ("Venituri curse", f"{totals.get('income_rides', 0):.2f}"),
        ("Venituri bacșișuri", f"{totals.get('income_tips', 0):.2f}"),
        ("TOTAL VENITURI", f"{totals.get('income_total', 0):.2f}"),
        ("", ""),
        ("--- CHELTUIELI ---", ""),
        ("Combustibil (brut)", f"{totals.get('expense_fuel_brut', 0):.2f}"),
        ("Combustibil (deductibil 50%)", f"{totals.get('expense_fuel_deductible', 0):.2f}"),
        ("Comisioane platformă", f"{totals.get('expense_commission', 0):.2f}"),
        ("Autorizații / Înregistrare", f"{totals.get('expense_registration', 0):.2f}"),
        ("Alte cheltuieli", f"{totals.get('expense_other', 0):.2f}"),
        ("TOTAL CHELTUIELI BRUT", f"{totals.get('expense_total_brut', 0):.2f}"),
        ("TOTAL CHELTUIELI DEDUCTIBILE", f"{totals.get('expense_deductible_total', 0):.2f}"),
        ("", ""),
        ("--- TVA (TAXARE INVERSĂ D301) ---", ""),
        ("Bază impozabilă comisioane", f"{totals.get('expense_commission', 0):.2f}"),
        ("TVA colectat (VAT_OUT)", f"{totals.get('vat_out_total', 0):.2f}"),
        ("TVA deductibil (VAT_IN)", f"{totals.get('vat_in_total', 0):.2f}"),
        ("NET TVA de plătit", f"{totals.get('vat_net', 0):.2f}"),
        ("", ""),
        ("--- REZULTAT ---", ""),
        ("PROFIT ESTIMAT", f"{totals.get('profit_estimated', 0):.2f}"),
        ("", ""),
        ("Număr tranzacții", str(totals.get("tx_count", 0))),
        ("ATENȚIE", "Estimat - verificați cu contabilul"),
    ]

    for row in rows:
        writer.writerow(row)

    return b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")


def filename_transactions(year: int, month: int) -> str:
    return f"tranzactii_{year}_{month:02d}.csv"


def filename_rezumat(year: int, month: int) -> str:
    return f"rezumat_fiscal_{year}_{month:02d}.csv"
