"""
Tax engine — agregare din transactions pentru rapoarte fiscale.

ACTIVITY-AWARE: folosește activitatea user-ului pentru:
  - Etichete/icon-uri categorii (din BaseActivity)
  - Reguli de deductibilitate per categorie (din tx.deductibility_pct)

PRINCIPII CONTABILE (PFA sistem real, OMFP 170/2015):
- Venitul = BRUT (cifra de afaceri reală)
- Cheltuielile au deductibilitate per-categorie (stocată în tx.deductibility_pct)
- Profit fiscal = Venit brut − Σ(amount_brut × deductibility_pct / 100)
"""

import logging
from collections import defaultdict
from typing import Dict, Any, List, Type

from sqlalchemy.orm import Session

from app.models import Transaction, User
from app.activities.registry import get_activity
from app.activities.base import BaseActivity

logger = logging.getLogger(__name__)

LUNI_RO = {
    1: "Ianuarie", 2: "Februarie", 3: "Martie", 4: "Aprilie",
    5: "Mai", 6: "Iunie", 7: "Iulie", 8: "August",
    9: "Septembrie", 10: "Octombrie", 11: "Noiembrie", 12: "Decembrie",
}


def _get_user_activity(session: Session, user_id: int) -> Type[BaseActivity]:
    """Returnează clasa de activitate a user-ului (Generic dacă lipsește)."""
    user = session.query(User).filter(User.id == user_id).first()
    if not user or not user.activity_code:
        return get_activity(None)  # GenericActivity
    return get_activity(user.activity_code)


def compute_period(
    session: Session,
    *,
    user_id: int,
    year: int,
    month: int,
) -> Dict[str, Any]:
    """
    Calculează totalurile fiscale pentru o perioadă.
    Folosește activitatea user-ului pentru deductibilitate și labels.
    """
    activity = _get_user_activity(session, user_id)

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

    # Agregări per categorie
    income_by_cat: Dict[str, float] = defaultdict(float)
    expense_brut_by_cat: Dict[str, float] = defaultdict(float)
    expense_deductible_by_cat: Dict[str, float] = defaultdict(float)
    expense_pct_by_cat: Dict[str, int] = {}

    income_cash = 0.0
    income_bank = 0.0
    vat_out = 0.0
    vat_in = 0.0

    for tx in txs:
        if tx.tx_type == "INCOME":
            income_by_cat[tx.category] += tx.amount_brut

            if tx.payment_method == "CASH":
                income_cash += tx.amount_brut
            else:
                income_bank += tx.amount_brut

        elif tx.tx_type == "EXPENSE":
            # ⭐ CHEIA: folosim pct stocat în DB (din regula activității la momentul salvării)
            pct = tx.deductibility_pct if tx.deductibility_pct is not None else 100
            deductible = round(tx.amount_brut * pct / 100.0, 2)

            expense_brut_by_cat[tx.category] += tx.amount_brut
            expense_deductible_by_cat[tx.category] += deductible
            expense_pct_by_cat[tx.category] = pct

        elif tx.tx_type == "VAT_OUT":
            vat_out += tx.amount_brut
        elif tx.tx_type == "VAT_IN":
            vat_in += tx.amount_brut

    # Breakdown îmbogățit cu metadata din activitate (label, icon, note)
    income_breakdown: List[Dict[str, Any]] = []
    for code, amount in income_by_cat.items():
        cat = activity.get_income_category(code)
        income_breakdown.append({
            "code": code,
            "label": cat.label if cat else code.replace("_", " ").title(),
            "icon": cat.icon if cat else "💰",
            "amount": round(amount, 2),
        })

    expense_breakdown: List[Dict[str, Any]] = []
    for code, brut in expense_brut_by_cat.items():
        cat = activity.get_expense_category(code)
        pct = expense_pct_by_cat.get(code, 100)
        expense_breakdown.append({
            "code": code,
            "label": cat.label if cat else code.replace("_", " ").title(),
            "icon": cat.icon if cat else "💸",
            "amount_brut": round(brut, 2),
            "deductibility_pct": pct,
            "amount_deductible": round(expense_deductible_by_cat[code], 2),
            "note": cat.deductibility_note if cat and cat.deductibility_note else "",
        })

    income_breakdown.sort(key=lambda x: -x["amount"])
    expense_breakdown.sort(key=lambda x: -x["amount_brut"])

    # Totaluri
    income_total = round(sum(income_by_cat.values()), 2)
    expense_total_brut = round(sum(expense_brut_by_cat.values()), 2)
    expense_deductible_total = round(sum(expense_deductible_by_cat.values()), 2)
    vat_net = round(vat_out - vat_in, 2)
    profit_estimated = round(income_total - expense_deductible_total, 2)

    return {
        "year": year,
        "month": month,
        "month_name": LUNI_RO.get(month, str(month)),
        # ── Activitate ──
        "activity_code": activity.code,
        "activity_name": activity.name,
        "activity_icon": activity.icon,
        # ── Venituri ──
        "income_total": income_total,
        "income_breakdown": income_breakdown,
        "income_cash": round(income_cash, 2),
        "income_bank": round(income_bank, 2),
        # ── Cheltuieli ──
        "expense_total_brut": expense_total_brut,
        "expense_deductible_total": expense_deductible_total,
        "expense_breakdown": expense_breakdown,
        # ── TVA ──
        "vat_out_total": round(vat_out, 2),
        "vat_in_total": round(vat_in, 2),
        "vat_net": vat_net,
        # ── Final ──
        "profit_estimated": profit_estimated,
        "tx_count": len(txs),
    }


def format_report_message(totals: Dict[str, Any]) -> str:
    """Formatează raportul fiscal pentru Telegram (Markdown)."""
    t = totals
    has_vat = t["vat_out_total"] > 0

    lines = [
        f"📊 *RAPORT {t['month_name'].upper()} {t['year']}*",
        f"{t['activity_icon']} _{t['activity_name']}_",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"",
    ]

    # ── VENITURI ──
    if t["income_breakdown"]:
        lines.append("💰 *VENITURI BRUTE* (cifra de afaceri)")
        for item in t["income_breakdown"]:
            lines.append(
                f"  {item['icon']} {item['label']}: `{item['amount']:.2f} RON`"
            )
        lines.append(f"  *TOTAL: {t['income_total']:.2f} RON*")

        if t["income_cash"] > 0 or t["income_bank"] > 0:
            lines += [
                f"  💵 Cash: `{t['income_cash']:.2f} RON`",
                f"  💳 Card/Bancă: `{t['income_bank']:.2f} RON`",
            ]
        lines.append("")

    # ── CHELTUIELI (cu deductibilitate dinamică per categorie) ──
    if t["expense_breakdown"]:
        lines.append("💸 *CHELTUIELI*")
        for item in t["expense_breakdown"]:
            pct = item["deductibility_pct"]
            if pct == 100:
                lines.append(
                    f"  {item['icon']} {item['label']}: "
                    f"`{item['amount_brut']:.2f} RON` (100%)"
                )
            elif pct == 0:
                lines.append(
                    f"  {item['icon']} {item['label']}: "
                    f"`{item['amount_brut']:.2f} RON` _(nedeductibil)_"
                )
            else:
                lines.append(
                    f"  {item['icon']} {item['label']}: "
                    f"`{item['amount_brut']:.2f} RON` → "
                    f"deductibil `{item['amount_deductible']:.2f} RON` ({pct}%)"
                )
        lines.append(
            f"  *Total deductibil: {t['expense_deductible_total']:.2f} RON*"
        )
        lines.append("")

    # ── TVA ──
    if has_vat:
        lines += [
            "🏛️ *TVA (taxare inversă D301)*",
            f"  Bază facturi: `{t['vat_out_total'] / 0.21:.2f} RON`",
            f"  TVA colectat (D301): `{t['vat_out_total']:.2f} RON`",
            f"  TVA deductibil: `{t['vat_in_total']:.2f} RON`",
            f"  *Net TVA de plătit: {t['vat_net']:.2f} RON*",
            "",
        ]

    # ── FINAL ──
    lines += [
        "━━━━━━━━━━━━━━━━━━━━",
        f"📈 *Profit estimat: {t['profit_estimated']:.2f} RON*",
        f"  _(venit brut − cheltuieli deductibile)_",
        "",
        f"_📋 {t['tx_count']} tranzacții procesate_",
        f"_⚠️ Estimat — verificați cu contabilul._",
    ]

    return "\n".join(lines)
