"""
Tax engine — agregare din transactions pentru rapoarte fiscale.
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
    expense_fuel_brut = 0.0
    expense_commission = 0.0
    expense_other = 0.0
    expense_registration = 0.0
    vat_out = 0.0
    vat_in = 0.0

    for tx in txs:
        if tx.tx_type == "INCOME":
            # ── FIX: folosim amount_net (câștigul real după comision Bolt)
            # amount_brut = brut înainte de comision (3848.57)
            # amount_net  = net după comision = ce primești efectiv (2909.29)
            net_value = tx.amount_net if tx.amount_net and tx.amount_net > 0 else tx.amount_brut
            if tx.category == "ride_revenue":
                income_rides += net_value
            elif tx.category == "tip_revenue":
                income_tips += net_value
            else:
                income_rides += net_value  # fallback

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
        f"💰 *VENITURI*",
        f"  Curse: `{t['income_rides']:.2f} RON`",
    ]

    if t["income_tips"] > 0:
        lines.append(f"  Bacșișuri: `{t['income_tips']:.2f} RON`")

    lines += [
        f"  *TOTAL: {t['income_total']:.2f} RON*",
        f"",
        f"💸 *CHELTUIELI*",
    ]

    if has_fuel:
        lines.append(
            f"  Combustibil: `{t['expense_fuel_brut']:.2f} RON` "
            f"→ deductibil `{t['expense_fuel_deductible']:.2f} RON` (50%)"
        )

    if has_commission:
        lines.append(f"  Comisioane Bolt/Uber: `{t['expense_commission']:.2f} RON`")

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
            f"🏛️ *TVA (taxare inversă)*",
            f"  Bază comisioane: `{t['expense_commission']:.2f} RON`",
            f"  TVA colectat (D301): `{t['vat_out_total']:.2f} RON`",
            f"  TVA deductibil: `{t['vat_in_total']:.2f} RON`",
            f"  *Net TVA de plătit: {t['vat_net']:.2f} RON*",
            f"",
        ]

    lines += [
        f"━━━━━━━━━━━━━━━━━━━━",
        f"📈 *Profit estimat: {t['profit_estimated']:.2f} RON*",
        f"  _(venituri − cheltuieli deductibile)_",
        f"",
        f"_📋 {t['tx_count']} tranzacții procesate_",
        f"_⚠️ Estimat — verificați cu contabilul._",
    ]

    return "\n".join(lines)
