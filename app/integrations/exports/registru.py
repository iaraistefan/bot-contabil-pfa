"""
Generator Registru de Încasări și Plăți pentru PFA.

Format conform Ordinului MFP 170/2015 (PFA sistem real).

PRINCIPIU CONTABIL:
- Încasări = VENIT BRUT total (card + cash) — cifra de afaceri reală
- Plăți = TOATE cheltuielile (inclusiv comisionul Bolt din raport)
- Sold cumulat = flux real al banilor în business
"""

import io
import logging
from datetime import date, datetime
from typing import List, Optional

logger = logging.getLogger(__name__)


def _parse_date(date_str: Optional[str]) -> Optional[date]:
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
    try:
        import openpyxl
        from openpyxl.styles import (
            Font, PatternFill, Alignment, Border, Side
        )
    except ImportError:
        logger.error("openpyxl not installed — falling back to CSV")
        return generate_registru_csv(transactions, year, pfa_name, pfa_cui)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Registru {year}"

    # ── Stiluri ──────────────────────────────────────────────────────────────
    header_fill = PatternFill("solid", fgColor="1F3864")
    subheader_fill = PatternFill("solid", fgColor="2E75B6")
    income_fill = PatternFill("solid", fgColor="E2EFDA")
    expense_fill = PatternFill("solid", fgColor="FCE4D6")
    total_fill = PatternFill("solid", fgColor="FFF2CC")

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
    header_border = Border(left=thick, right=thick, top=thick, bottom=thick)

    num_fmt = '#,##0.00 "RON"'

    # ── Lățimi coloane ───────────────────────────────────────────────────────
    col_widths = {
        "A": 6, "B": 13, "C": 45,
        "D": 16, "E": 16, "F": 16,
        "G": 16, "H": 16, "I": 16, "J": 16,
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
    relevant_txs = [
        tx for tx in transactions
        if tx.tx_type in ("INCOME", "EXPENSE")
    ]
    relevant_txs.sort(key=lambda tx: (
        tx.occurred_on or date(year, 1, 1),
        tx.id
    ))

    sold_curent = 0.0
    nr_crt = 0
    data_start_row = row

    # ── Sold inițial ──────────────────────────────────────────────────────────
    for col in ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]:
        c = ws[f"{col}{row}"]
        c.border = thin_border
        c.font = dark_bold
        c.fill = total_fill
    ws.merge_cells(f"C{row}:I{row}")
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

        # ── Calcul sume — FOLOSIM AMOUNT_BRUT (corect fiscal) ──
        if is_income:
            amount = tx.amount_brut
            if tx.payment_method == "CASH":
                inc_cash, inc_bank = amount, 0.0
            elif tx.payment_method == "CARD":
                inc_cash, inc_bank = 0.0, amount
            else:
                # Default: card/bancă
                inc_cash, inc_bank = 0.0, amount
            total_inc = inc_cash + inc_bank
            pay_cash = pay_bank = total_pay = 0.0
            sold_curent += total_inc
        else:
            inc_cash = inc_bank = total_inc = 0.0
            amount = tx.amount_brut
            if tx.payment_method == "CASH":
                pay_cash, pay_bank = amount, 0.0
            else:
                pay_cash, pay_bank = 0.0, amount
            total_pay = pay_cash + pay_bank
            sold_curent -= total_pay

        # Descriere
        cat_labels = {
            "ride_revenue": "Venituri brute curse Bolt/Uber",
            "tip_revenue": "Bacșișuri",
            "fuel": "Combustibil auto",
            "platform_commission": "Comision platformă Bolt/Uber",
            "registration": "Taxe autorizații/înregistrare",
            "other_expense": "Alte cheltuieli",
        }
        descriere = cat_labels.get(tx.category, tx.category or "—")
        if tx.counterparty and tx.counterparty not in ("N/A", "Bolt", "Uber", "APP"):
            descriere += f" — {tx.counterparty}"

        # Row fill alternant
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
                c.font = Font(
                    name="Calibri", bold=True, size=10,
                    color="1F6B2A" if sold_curent >= 0 else "C00000"
                )

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
        if col in ("D", "E", "F", "G", "H", "I", "J"):
            c.number_format = num_fmt
    ws.row_dimensions[row].height = 22
    row += 2

    # ── Sumar fiscal final ──
    ws.merge_cells(f"A{row}:J{row}")
    c = ws[f"A{row}"]
    c.value = (
        f"💡 PROFIT BRUT (Total Încasări − Total Plăți) = {sold_curent:.2f} RON"
    )
    c.font = Font(name="Calibri", bold=True, size=11, color="1F3864")
    c.fill = total_fill
    c.alignment = center
    c.border = header_border
    ws.row_dimensions[row].height = 22
    row += 1

    ws.merge_cells(f"A{row}:J{row}")
    c = ws[f"A{row}"]
    c.value = (
        "ℹ️ Profitul deductibil fiscal poate diferi (combustibilul auto e "
        "deductibil 50%). Vezi raportul lunar pentru detalii."
    )
    c.font = small
    c.alignment = center
    ws.row_dimensions[row].height = 16
    row += 2

    # ── Semnătură ─────────────────────────────────────────────────────────────
    ws.merge_cells(f"A{row}:E{row}")
    ws[f"A{row}"].value = (
        f"Data întocmirii: {datetime.now().strftime('%d.%m.%Y')}"
    )
    ws[f"A{row}"].font = small
    ws[f"A{row}"].alignment = left

    ws.merge_cells(f"F{row}:J{row}")
    ws[f"F{row}"].value = "Semnătura titularului PFA: ___________________"
    ws[f"F{row}"].font = small
    ws[f"F{row}"].alignment = right
    row += 1

    ws.merge_cells(f"A{row}:J{row}")
    ws[f"A{row}"].value = (
        "⚠️ Document generat automat de Bot Contabil PFA conform OMFP "
        "170/2015. Verificați cu contabilul autorizat înainte de depunere."
    )
    ws[f"A{row}"].font = Font(
        name="Calibri", size=8, color="FF0000", italic=True
    )
    ws[f"A{row}"].alignment = center

    ws.freeze_panes = f"A{data_start_row}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = 9
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.print_title_rows = f"1:{data_start_row - 1}"

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
    """Fallback CSV dacă openpyxl nu e disponibil."""
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
            "ride_revenue": "Venituri brute curse Bolt/Uber",
            "tip_revenue": "Bacșișuri",
            "fuel": "Combustibil",
            "platform_commission": "Comision Bolt/Uber",
            "registration": "Autorizații",
            "other_expense": "Alte cheltuieli",
        }
        desc = cat_labels.get(tx.category, tx.category or "")

        if is_income:
            # FOLOSIM BRUT
            amount = tx.amount_brut
            if tx.payment_method == "CASH":
                inc_cash, inc_bank = amount, 0.0
            else:
                inc_cash, inc_bank = 0.0, amount
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
