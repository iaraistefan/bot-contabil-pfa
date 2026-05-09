"""
Tax engine — agregare din transactions pentru rapoarte fiscale.

PRINCIPIU CONTABIL CORECT (PFA sistem real, OMFP 170/2015):
- Venitul = BRUT (cifra de afaceri reală — toate plățile pentru curse)
- Comisionul Bolt = cheltuială deductibilă SEPARATĂ
- Profit fiscal = Venit brut - Cheltuieli deductibile (incluzând comisionul)
"""

import logging
from typing import Dict, Any

from sqlalchemy.orm import Session

from app.models import Transaction

logger = logging.getLogger(__name__)

LUNI_RO = {
    1: "Ianuarie", 2: "Februarie", 3: "Martie", 4: "Aprilie",
    5: "Mai", 6: "Iunie", 7: "Iulie", 8: "August",
    9: "Septembrie", 10: "Octombrie", 11: "Noiembrie", 12: "Decembrie"
}


def compute_period(
    session: Session,
    *,
    user_id: int,
    year: int,
    month: int,
) -> Dict[str, Any]:
    txs = (
        session.query(Transaction)
        .filter(
            Transaction.user_id == user_id,
            Transaction.period_year == year,
            Transaction.period_month == month,
            Transaction.locked == False,
        )
        .all()
    )

    income_rides = 0.0
    income_tips = 0.0
    income_cash = 0.0
    income_bank = 0.0
    expense_fuel_brut = 0.0
    expense_commission = 0.0
    expense_other = 0.0
    expense_registration = 0.0
    vat_out = 0.0
    vat_in = 0.0

    for tx in txs:
        if tx.tx_type == "INCOME":
            # ── CORECT FISCAL: folosim BRUT (cifra de afaceri reală)
            # Comisionul Bolt apare separat ca EXPENSE platform_commission
            if tx.category == "ride_revenue":
                income_rides += tx.amount_brut
            elif tx.category == "tip_revenue":
                income_tips += tx.amount_brut
            else:
                income_rides += tx.amount_brut  # fallback

            # Split cash vs bancă (pentru afișare)
            if tx.payment_method == "CASH":
                income_cash += tx.amount_brut
            elif tx.payment_method == "CARD":
                income_bank += tx.amount_brut
            else:
                income_bank += tx.amount_brut

        elif tx.tx_type == "EXPENSE":
            if tx.category == "fuel":
                expense_fuel_brut += tx.amount_brut
            elif tx.category == "platform_commission":
                expense_commission += tx.amount_brut
            elif tx.category == "registration":
                expense_registration += tx.amount_brut
            else:
                expense_other += tx.amount_brut

        elif tx.tx_type == "VAT_OUT":
            vat_out += tx.amount_brut

        elif tx.tx_type == "VAT_IN":
            vat_in += tx.amount_brut

    # Calcule derivate
    income_total = round(income_rides + income_tips, 2)
    expense_fuel_deductible = round(expense_fuel_brut * 0.50, 2)
    expense_deductible_total = round(
        expense_fuel_deductible + expense_commission +
        expense_other + expense_registration, 2
    )
    expense_total_brut = round(
        expense_fuel_brut + expense_commission +
        expense_other + expense_registration, 2
    )
    vat_net = round(vat_out - vat_in, 2)
    profit_estimated = round(income_total - expense_deductible_total, 2)

    return {
        "year": year,
        "month": month,
        "month_name": LUNI_RO.get(month, str(month)),
        "income_total": income_total,
        "income_rides": round(income_rides, 2),
        "income_tips": round(income_tips, 2),
        "income_cash": round(income_cash, 2),
        "income_bank": round(income_bank, 2),
        "expense_total_brut": expense_total_brut,
        "expense_fuel_brut": round(expense_fuel_brut, 2),
        "expense_fuel_deductible": expense_fuel_deductible,
        "expense_commission": round(expense_commission, 2),
        "expense_other": round(expense_other, 2),
        "expense_registration": round(expense_registration, 2),
        "expense_deductible_total": expense_deductible_total,
        "vat_out_total": round(vat_out, 2),
        "vat_in_total": round(vat_in, 2),
        "vat_net": round(vat_net, 2),
        "profit_estimated": profit_estimated,
        "tx_count": len(txs),
    }


def format_report_message(totals: Dict[str, Any]) -> str:
    t = totals
    has_fuel = t["expense_fuel_brut"] > 0
    has_commission = t["expense_commission"] > 0
    has_vat = t["vat_out_total"] > 0
    has_other = t["expense_other"] > 0
    has_reg = t["expense_registration"] > 0

    lines = [
        f"📊 *RAPORT {t['month_name'].upper()} {t['year']}*",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"",
        f"💰 *VENITURI BRUTE* (cifra de afaceri)",
        f"  Curse: `{t['income_rides']:.2f} RON`",
    ]

    if t["income_tips"] > 0:
        lines.append(f"  Bacșișuri: `{t['income_tips']:.2f} RON`")

    lines += [
        f"  *TOTAL: {t['income_total']:.2f} RON*",
    ]

    if t["income_cash"] > 0 or t["income_bank"] > 0:
        lines += [
            f"  💵 Cash: `{t['income_cash']:.2f} RON`",
            f"  💳 Card/Bancă: `{t['income_bank']:.2f} RON`",
        ]

    lines += [
        f"",
        f"💸 *CHELTUIELI*",
    ]

    if has_commission:
        lines.append(
            f"  Comision Bolt/Uber: `{t['expense_commission']:.2f} RON` (100%)"
        )

    if has_fuel:
        lines.append(
            f"  Combustibil: `{t['expense_fuel_brut']:.2f} RON` "
            f"→ deductibil `{t['expense_fuel_deductible']:.2f} RON` (50%)"
        )

    if has_reg:
        lines.append(f"  Autorizații/Înreg.: `{t['expense_registration']:.2f} RON`")

    if has_other:
        lines.append(f"  Alte cheltuieli: `{t['expense_other']:.2f} RON`")

    lines += [
        f"  *Total deductibil: {t['expense_deductible_total']:.2f} RON*",
        f"",
    ]

    if has_vat:
        lines += [
            f"🏛️ *TVA (taxare inversă D301)*",
            f"  Bază facturi comision: `{t['vat_out_total'] / 0.21:.2f} RON`",
            f"  TVA colectat (D301): `{t['vat_out_total']:.2f} RON`",
            f"  TVA deductibil: `{t['vat_in_total']:.2f} RON`",
            f"  *Net TVA de plătit: {t['vat_net']:.2f} RON*",
            f"",
        ]

    lines += [
        f"━━━━━━━━━━━━━━━━━━━━",
        f"📈 *Profit estimat: {t['profit_estimated']:.2f} RON*",
        f"  _(venit brut − cheltuieli deductibile)_",
        f"",
        f"_📋 {t['tx_count']} tranzacții procesate_",
        f"_⚠️ Estimat — verificați cu contabilul._",
    ]

    return "\n".join(lines)
