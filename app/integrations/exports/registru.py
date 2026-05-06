"""
Generator Registru de Încasări și Plăți pentru PFA.

Format conform Ordinului MFP 170/2015 (PFA sistem real).
Generat ca XLSX formatat, gata de tipărit și depus la bancă/ANAF.

Structură:
- Coloana A: Nr. crt.
- Coloana B: Data
- Coloana C: Explicații (descrierea operațiunii)
- Coloana D: Încasări numerar
- Coloana E: Încasări bancă
- Coloana F: Total încasări
- Coloana G: Plăți numerar
- Coloana H: Plăți bancă
- Coloana I: Total plăți
- Coloana J: Sold (running balance)
"""

import io
import logging
from datetime import date, datetime
from typing import List, Optional

logger = logging.getLogger(__name__)


def _parse_date(date_str: Optional[str]) -> Optional[date]:
    """Parsează data din format DD.MM.YYYY sau ISO."""
    if not date_str:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(date_str), fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def generate_registru_xlsx(
    transactions,
    year: int,
    pfa_name: str = "IARAI STEFAN PERSOANA FIZICA AUTORIZATA",
    pfa_cui: str = "53067338",
) -> bytes:
    """
    Generează Registrul de Încasări și Plăți ca fișier XLSX.

    Args:
        transactions: lista de Transaction ORM objects
        year: anul pentru care se generează registrul
        pfa_name: numele PFA-ului
        pfa_cui: CUI-ul PFA-ului

    Returns:
        bytes — conținutul fișierului XLSX
    """
    try:
        import openpyxl
        from openpyxl.styles import (
            Font, PatternFill, Alignment, Border, Side, numbers
        )
        from openpyxl.utils import get_column_letter
    except ImportError:
        logger.error("openpyxl not installed — falling back to CSV")
        return generate_registru_csv(transactions, year, pfa_name, pfa_cui)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Registru {year}"

    # ── Stiluri ──────────────────────────────────────────────────────────────
    header_fill = PatternFill("solid", fgColor="1F3864")   # albastru închis
    subheader_fill = PatternFill("solid", fgColor="2E75B6")  # albastru
    income_fill = PatternFill("solid", fgColor="E2EFDA")   # verde deschis
    expense_fill = PatternFill("solid", fgColor="FCE4D6")  # roșu deschis
    total_fill = PatternFill("solid", fgColor="FFF2CC")    # galben
    alt_fill = PatternFill("solid", fgColor="F5F5F5")      # gri deschis

    white_bold = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    dark_bold = Font(name="Calibri", bold=True, color="1F3864", size=10)
    normal = Font(name="Calibri", size=10)
    small = Font(name="Calibri", size=9, color="595959")

    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)
    right = Alignment(horizontal="right", vertical="center")

    thin = Side(style="thin", color="BFBFBF")
    thick = Side(style="medium", color="1F3864")
    thin_border = Border(left=thin, right=thin, top=thin, bottom=thin)
    thick_border = Border(left=thick, right=thick, top=thick, bottom=thick)
    header_border = Border(
        left=thick, right=thick, top=thick, bottom=thick
    )

    num_fmt = '#,##0.00 "RON"'
    date_fmt = "DD.MM.YYYY"

    # ── Lățimi coloane ───────────────────────────────────────────────────────
    col_widths = {
        "A": 6,   # Nr
        "B": 13,  # Data
        "C": 45,  # Explicații
        "D": 16,  # Încasări numerar
        "E": 16,  # Încasări bancă
        "F": 16,  # Total încasări
        "G": 16,  # Plăți numerar
        "H": 16,  # Plăți bancă
        "I": 16,  # Total plăți
        "J": 16,  # Sold
    }
    for col, width in col_widths.items():
        ws.column_dimensions[col].width = width

    row = 1

    # ── Titlu principal ───────────────────────────────────────────────────────
    ws.merge_cells(f"A{row}:J{row}")
    c = ws[f"A{row}"]
    c.value = f"REGISTRU DE ÎNCASĂRI ȘI PLĂȚI — ANUL {year}"
    c.font = Font(name="Calibri", bold=True, color="FFFFFF", size=14)
    c.fill = header_fill
    c.alignment = center
    ws.row_dimensions[row].height = 30
    row += 1

    # ── Info PFA ─────────────────────────────────────────────────────────────
    ws.merge_cells(f"A{row}:J{row}")
    c = ws[f"A{row}"]
    c.value = f"{pfa_name}  |  CUI: {pfa_cui}  |  Sistem real de impunere"
    c.font = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
    c.fill = subheader_fill
    c.alignment = center
    ws.row_dimensions[row].height = 20
    row += 1

    # Linie goală
    row += 1

    # ── Header tabel ─────────────────────────────────────────────────────────
    headers = [
        ("A", "Nr.\ncrt."),
        ("B", "Data"),
        ("C", "Explicații\n(natura operațiunii)"),
        ("D", "Încasări\nNumerar (cash)"),
        ("E", "Încasări\nBancă (card)"),
        ("F", "TOTAL\nÎNCASĂRI"),
        ("G", "Plăți\nNumerar (cash)"),
        ("H", "Plăți\nBancă (card)"),
        ("I", "TOTAL\nPLĂȚI"),
        ("J", "SOLD\nCumulat"),
    ]

    for col, label in headers:
        c = ws[f"{col}{row}"]
        c.value = label
        c.font = white_bold
        c.fill = subheader_fill
        c.alignment = center
        c.border = header_border
    ws.row_dimensions[row].height = 35
    row += 1

    # ── Procesare tranzacții ──────────────────────────────────────────────────
    # Filtrăm și sortăm: doar INCOME și EXPENSE, sortate cronologic
    relevant_txs = [
        tx for tx in transactions
        if tx.tx_type in ("INCOME", "EXPENSE")
    ]
    relevant_txs.sort(key=lambda tx: (
        tx.occurred_on or date(year, 1, 1),
        tx.id
    ))

    # Sold inițial = 0 (registrul începe de la 0 pentru fiecare an)
    sold_curent = 0.0
    nr_crt = 0
    data_start_row = row  # pentru total final

    # Sold inițial row
    ws.merge_cells(f"C{row}:I{row}")
    for col in ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]:
        c = ws[f"{col}{row}"]
        c.border = thin_border
        c.font = dark_bold
        c.fill = total_fill
    ws[f"A{row}"].value = "—"
    ws[f"A{row}"].alignment = center
    ws[f"B{row}"].value = f"01.01.{year}"
    ws[f"B{row}"].alignment = center
    ws[f"C{row}"].value = "SOLD INIȚIAL"
    ws[f"C{row}"].alignment = left
    ws[f"J{row}"].value = 0.00
    ws[f"J{row}"].number_format = num_fmt
    ws[f"J{row}"].alignment = right
    ws.row_dimensions[row].height = 18
    row += 1

    current_month = 0

    for tx in relevant_txs:
        tx_date = tx.occurred_on or date(year, 1, 1)
        tx_month = tx_date.month

        # Separator lunar
        if tx_month != current_month:
            current_month = tx_month
            luni = {
                1: "IANUARIE", 2: "FEBRUARIE", 3: "MARTIE", 4: "APRILIE",
                5: "MAI", 6: "IUNIE", 7: "IULIE", 8: "AUGUST",
                9: "SEPTEMBRIE", 10: "OCTOMBRIE", 11: "NOIEMBRIE", 12: "DECEMBRIE"
            }
            ws.merge_cells(f"A{row}:J{row}")
            c = ws[f"A{row}"]
            c.value = f"── {luni.get(tx_month, str(tx_month))} {year} ──"
            c.font = Font(name="Calibri", bold=True, color="2E75B6", size=9)
            c.fill = PatternFill("solid", fgColor="DEEAF1")
            c.alignment = center
            c.border = thin_border
            ws.row_dimensions[row].height = 14
            row += 1

        nr_crt += 1
        is_income = tx.tx_type == "INCOME"

        # Calcul sume
        if is_income:
            inc_cash = tx.amount_brut - (tx.amount_net or tx.amount_brut) if False else 0.0
            # Pentru venituri: folosim cash și bancă din tranzacție
            # amount_brut = total brut, dar noi vrem să afișăm cash și card separat
            # Vom folosi payment_method pentru a decide
            if tx.payment_method == "CASH":
                inc_cash = tx.amount_net if tx.amount_net else tx.amount_brut
                inc_bank = 0.0
            elif tx.payment_method == "CARD":
                inc_cash = 0.0
                inc_bank = tx.amount_net if tx.amount_net else tx.amount_brut
            else:
                # Mixed — split din amount_net
                inc_bank = tx.amount_net if tx.amount_net else tx.amount_brut
                inc_cash = 0.0
            total_inc = inc_cash + inc_bank
            pay_cash = 0.0
            pay_bank = 0.0
            total_pay = 0.0
            sold_curent += total_inc
        else:
            inc_cash = 0.0
            inc_bank = 0.0
            total_inc = 0.0
            if tx.payment_method == "CASH":
                pay_cash = tx.amount_brut
                pay_bank = 0.0
            else:
                pay_cash = 0.0
                pay_bank = tx.amount_brut
            total_pay = pay_cash + pay_bank
            sold_curent -= total_pay

        # Descriere
        cat_labels = {
            "ride_revenue": "Venituri curse Bolt/Uber",
            "tip_revenue": "Bacșișuri",
            "fuel": "Combustibil auto",
            "platform_commission": "Comision platformă Bolt/Uber",
            "registration": "Taxe autorizații/înregistrare",
            "other_expense": "Alte cheltuieli",
        }
        descriere = cat_labels.get(tx.category, tx.category or "—")
        if tx.counterparty and tx.counterparty not in ("N/A", "Bolt", "Uber"):
            descriere += f" — {tx.counterparty}"

        # Row fill
        fill = income_fill if is_income else expense_fill
        if nr_crt % 2 == 0 and not is_income:
            fill = PatternFill("solid", fgColor="FBE9E7")
        elif nr_crt % 2 == 0 and is_income:
            fill = PatternFill("solid", fgColor="F1F8EC")

        data = {
            "A": (nr_crt, center),
            "B": (tx_date.strftime("%d.%m.%Y"), center),
            "C": (descriere, left),
            "D": (inc_cash if inc_cash else None, right),
            "E": (inc_bank if inc_bank else None, right),
            "F": (total_inc if total_inc else None, right),
            "G": (pay_cash if pay_cash else None, right),
            "H": (pay_bank if pay_bank else None, right),
            "I": (total_pay if total_pay else None, right),
            "J": (sold_curent, right),
        }

        for col, (val, align) in data.items():
            c = ws[f"{col}{row}"]
            c.value = val
            c.alignment = align
            c.font = normal
            c.fill = fill
            c.border = thin_border
            if col in ("D", "E", "F", "G", "H", "I", "J") and val is not None:
                c.number_format = num_fmt
            if col == "J":
                c.font = Font(name="Calibri", bold=True, size=10,
                              color="1F6B2A" if sold_curent >= 0 else "C00000")

        ws.row_dimensions[row].height = 16
        row += 1

    # ── Total general ─────────────────────────────────────────────────────────
    row += 1
    total_labels = {
        "A": "TOTAL",
        "B": "",
        "C": f"TOTAL GENERAL {year}",
        "D": f"=SUM(D{data_start_row + 1}:D{row - 2})",
        "E": f"=SUM(E{data_start_row + 1}:E{row - 2})",
        "F": f"=SUM(F{data_start_row + 1}:F{row - 2})",
        "G": f"=SUM(G{data_start_row + 1}:G{row - 2})",
        "H": f"=SUM(H{data_start_row + 1}:H{row - 2})",
        "I": f"=SUM(I{data_start_row + 1}:I{row - 2})",
        "J": sold_curent,
    }

    for col, val in total_labels.items():
        c = ws[f"{col}{row}"]
        c.value = val
        c.font = Font(name="Calibri", bold=True, size=11, color="FFFFFF")
        c.fill = header_fill
        c.alignment = center if col in ("A", "B") else (
            left if col == "C" else right
        )
        c.border = header_border
        if col in ("D", "E", "F", "G", "H", "I"):
            c.number_format = num_fmt
        elif col == "J":
            c.number_format = num_fmt
    ws.row_dimensions[row].height = 22
    row += 2

    # ── Semnătură ─────────────────────────────────────────────────────────────
    ws.merge_cells(f"A{row}:E{row}")
    ws[f"A{row}"].value = f"Data întocmirii: {datetime.now().strftime('%d.%m.%Y')}"
    ws[f"A{row}"].font = small
    ws[f"A{row}"].alignment = left

    ws.merge_cells(f"F{row}:J{row}")
    ws[f"F{row}"].value = "Semnătura titularului PFA: ___________________"
    ws[f"F{row}"].font = small
    ws[f"F{row}"].alignment = right
    row += 1

    ws.merge_cells(f"A{row}:J{row}")
    ws[f"A{row}"].value = (
        "⚠️ Document generat automat de Bot Contabil PFA. "
        "Verificați cu contabilul autorizat înainte de depunere."
    )
    ws[f"A{row}"].font = Font(name="Calibri", size=8, color="FF0000", italic=True)
    ws[f"A{row}"].alignment = center

    # ── Freeze header ─────────────────────────────────────────────────────────
    ws.freeze_panes = f"A{data_start_row}"

    # ── Print setup ──────────────────────────────────────────────────────────
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = 9  # A4
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.print_title_rows = f"1:{data_start_row - 1}"

    # Save to bytes
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def generate_registru_csv(
    transactions,
    year: int,
    pfa_name: str = "IARAI STEFAN PFA",
    pfa_cui: str = "53067338",
) -> bytes:
    """
    Fallback CSV dacă openpyxl nu e disponibil.
    """
    import csv
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")

    writer.writerow([f"REGISTRU DE ÎNCASĂRI ȘI PLĂȚI — {year}"])
    writer.writerow([pfa_name, f"CUI: {pfa_cui}"])
    writer.writerow([])
    writer.writerow([
        "Nr.", "Data", "Explicații",
        "Încasări numerar", "Încasări bancă", "Total încasări",
        "Plăți numerar", "Plăți bancă", "Total plăți", "Sold"
    ])

    sold = 0.0
    nr = 0
    relevant = sorted(
        [tx for tx in transactions if tx.tx_type in ("INCOME", "EXPENSE")],
        key=lambda tx: (tx.occurred_on or date(year, 1, 1), tx.id)
    )

    for tx in relevant:
        nr += 1
        tx_date = tx.occurred_on.strftime("%d.%m.%Y") if tx.occurred_on else ""
        is_income = tx.tx_type == "INCOME"

        cat_labels = {
            "ride_revenue": "Venituri curse Bolt/Uber",
            "tip_revenue": "Bacșișuri",
            "fuel": "Combustibil",
            "platform_commission": "Comision Bolt/Uber",
            "registration": "Autorizații",
            "other_expense": "Alte cheltuieli",
        }
        desc = cat_labels.get(tx.category, tx.category or "")

        if is_income:
            net = tx.amount_net if tx.amount_net else tx.amount_brut
            if tx.payment_method == "CASH":
                inc_cash, inc_bank = net, 0.0
            else:
                inc_cash, inc_bank = 0.0, net
            total_inc = inc_cash + inc_bank
            pay_cash = pay_bank = total_pay = 0.0
            sold += total_inc
        else:
            inc_cash = inc_bank = total_inc = 0.0
            if tx.payment_method == "CASH":
                pay_cash, pay_bank = tx.amount_brut, 0.0
            else:
                pay_cash, pay_bank = 0.0, tx.amount_brut
            total_pay = pay_cash + pay_bank
            sold -= total_pay

        writer.writerow([
            nr, tx_date, desc,
            f"{inc_cash:.2f}" if inc_cash else "",
            f"{inc_bank:.2f}" if inc_bank else "",
            f"{total_inc:.2f}" if total_inc else "",
            f"{pay_cash:.2f}" if pay_cash else "",
            f"{pay_bank:.2f}" if pay_bank else "",
            f"{total_pay:.2f}" if total_pay else "",
            f"{sold:.2f}",
        ])

    return buf.getvalue().encode("utf-8-sig")


def filename_registru(year: int, fmt: str = "xlsx") -> str:
    return f"registru_incasari_plati_{year}.{fmt}"
