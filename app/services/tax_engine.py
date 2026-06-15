"""
Tax engine — agregare din transactions pentru rapoarte fiscale.

ACTIVITY-AWARE + PROFILE-AWARE (Pas 8.4a):
  - Etichete/icon-uri categorii (din BaseActivity)
  - Reguli de deductibilitate per categorie (din tx.deductibility_pct)
  - Calcul fiscal corect per FORMĂ JURIDICĂ (PFA/SRL/Micro/Normal)
  - Estimare CAS/CASS pentru PFA (cu plafoane 2026)
  - Mesaj de raport DINAMIC adaptat profilului fiscal
"""

import logging
import threading
from collections import defaultdict
from datetime import date
from typing import Dict, Any, List, Type, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Transaction, User
from app.activities.registry import get_activity
from app.activities.base import BaseActivity

# === NEW (Pas 8.4a) — Rule Engine fiscal ===
from app.domain.fiscal_profile import (
    FiscalProfile,
    FormaJuridica,
    TaxBase,
    from_user_id as fiscal_profile_from_user_id,
)
from app.domain.tax_calculator import compute_full_estimate, TaxEstimate
from app.domain.tax_rules import cota_tva

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
        return get_activity(None)
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
    Folosește activitatea + profilul fiscal al user-ului.
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
            pct = tx.deductibility_pct if tx.deductibility_pct is not None else 100
            deductible = round(tx.amount_brut * pct / 100.0, 2)

            expense_brut_by_cat[tx.category] += tx.amount_brut
            expense_deductible_by_cat[tx.category] += deductible
            expense_pct_by_cat[tx.category] = pct

        elif tx.tx_type == "VAT_OUT":
            vat_out += tx.amount_brut
        elif tx.tx_type == "VAT_IN":
            vat_in += tx.amount_brut

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

    income_total = round(sum(income_by_cat.values()), 2)
    expense_total_brut = round(sum(expense_brut_by_cat.values()), 2)
    expense_deductible_total = round(sum(expense_deductible_by_cat.values()), 2)
    vat_net = round(vat_out - vat_in, 2)
    profit_estimated = round(income_total - expense_deductible_total, 2)

    # ════════════════════════════════════════════════════════
    # === NEW (Pas 8.4a) — Estimare fiscală inteligentă ===
    # ════════════════════════════════════════════════════════
    fiscal_estimate: Optional[TaxEstimate] = None
    try:
        profile = fiscal_profile_from_user_id(session, user_id)
        fiscal_estimate = compute_full_estimate(
            profile=profile,
            totals={
                "income_brut": income_total,
                "expenses_deductible": expense_deductible_total,
            },
            period_label=f"{LUNI_RO.get(month, str(month))} {year}",
            annualize_factor=12.0,
        )
        logger.info(
            f"✅ Fiscal estimate computed for user {user_id}: "
            f"forma={profile.forma_juridica.value}, "
            f"impozit={fiscal_estimate.income_tax.amount:.2f} RON"
        )
    except Exception as e:
        logger.exception(f"❌ Could not compute fiscal estimate for user {user_id}: {e}")
        fiscal_estimate = None

    return {
        "year": year,
        "month": month,
        "month_name": LUNI_RO.get(month, str(month)),
        "activity_code": activity.code,
        "activity_name": activity.name,
        "activity_icon": activity.icon,
        "income_total": income_total,
        "income_breakdown": income_breakdown,
        "income_cash": round(income_cash, 2),
        "income_bank": round(income_bank, 2),
        "expense_total_brut": expense_total_brut,
        "expense_deductible_total": expense_deductible_total,
        "expense_breakdown": expense_breakdown,
        "vat_out_total": round(vat_out, 2),
        "vat_in_total": round(vat_in, 2),
        "vat_net": vat_net,
        # Cota TVA a perioadei (sursă unică de adevăr; folosită la inversarea
        # bază = vat_out / cota_tva, pe backend și în dashboard).
        "cota_tva": cota_tva(date(year, month, 1)),
        "profit_estimated": profit_estimated,
        "tx_count": len(txs),
        "fiscal_estimate": fiscal_estimate.to_dict() if fiscal_estimate else None,
    }


def has_taxable_bolt_invoice(
    session: Session, *, user_id: int, year: int, month: int
) -> bool:
    """
    True dacă luna are o factură de comision Bolt taxabilă (reverse charge) —
    semnalul care declanșează obligațiile lunare D301/D390/D100.

    SURSĂ UNICĂ: `compute_period(...)["vat_out_total"] > 0` — EXACT semnalul
    folosit deja de web (`/api/v1/obligatii`) și de banner-ul TVA & Declarații.
    Refolosim compute_period (NU reimplementăm suma) ca să nu poată diverge.
    vat_out_total sumează tx_type 'VAT_OUT' (reverse charge din factura comision,
    `posting._post_factura_comision`).

    ⚠️ Fiscal #4: înlocuiește filtrul vechi `(EXPENSE + REVERSE_CHARGE)` — relicvă
    a modelului de postare de dinainte de vat-engine. După refactor, factura se
    stochează ca VAT_OUT (nu EXPENSE), iar comisionul din raport ca EXPENSE
    'AUTO_FROM_REPORT' (nu REVERSE_CHARGE) → combinația veche nu se mai potrivea
    cu niciun tx → has_bolt era structural mereu False.

    GRANIȚĂ (documentată, nerezolvată în #4): comisionul DOAR din raport Bolt
    (EXPENSE 'AUTO_FROM_REPORT', fără factură formală) nu produce VAT_OUT → False.
    Corect pe modelul actual (reverse charge se naște din factura formală).
    """
    totals = compute_period(session, user_id=user_id, year=year, month=month)
    return float(totals.get("vat_out_total") or 0.0) > 0


# Cache in-memory pentru compute_d212_anual, validat prin FINGERPRINT (versiunea
# datelor). Bot + scheduler + Flask sunt thread-uri in ACELASI proces -> dict
# partajat + lock. ZERO stale: fingerprint-ul = starea datelor; orice add/delete/
# lock/edit-suma muta fingerprint-ul -> recompute. Fara TTL, fara hooks.
_D212_CACHE: Dict = {}
_D212_CACHE_LOCK = threading.Lock()


def _d212_fingerprint(session: Session, user_id: int, an: int):
    """
    Amprenta ieftina a datelor care alimenteaza compute_d212_anual:
    (count, max_id, sum(amount_brut)) pe tranzactiile (user, an, locked=False)
    — FILTRU IDENTIC cu compute_period. Orice add/delete/lock/edit-suma o schimba.
    (Nu exista update in-place pe tx in cod -> count/max_id/sum sunt suficiente.)
    """
    cnt, max_id, total = (
        session.query(
            func.count(Transaction.id),
            func.coalesce(func.max(Transaction.id), 0),
            func.coalesce(func.sum(Transaction.amount_brut), 0.0),
        )
        .filter(
            Transaction.user_id == user_id,
            Transaction.period_year == an,
            Transaction.locked == False,
        )
        .one()
    )
    return (int(cnt or 0), int(max_id or 0), round(float(total or 0.0), 2))


def _compute_d212_anual_uncached(session: Session, *, user_id: int, an: int):
    """
    Estimare D212 anuala (impozit + CAS + CASS) pe baza venitului REALIZAT
    pana acum in anul `an` (suma lunilor cu date — lunile fara date dau 0).

    SURSA UNICA pentru numarul D212: exact aceeasi cale ca declaratia reala
    (Σ compute_period -> declaratii_service.genereaza_d212 -> d212_calc ->
    contributii). NU se cheama direct — vezi wrapper-ul compute_d212_anual.
    """
    # import lazy pentru a evita orice ciclu de import la incarcarea modulului
    from app.integrations.anaf import declaratii_service as _decl

    venit_brut = 0.0
    cheltuieli = 0.0
    for m in range(1, 13):
        try:
            t = compute_period(session, user_id=user_id, year=an, month=m)
            venit_brut += float(t.get("income_total") or 0.0)
            cheltuieli += float(t.get("expense_deductible_total") or 0.0)
        except Exception:
            continue
    return _decl.genereaza_d212(an, round(venit_brut, 2), round(cheltuieli, 2))


def compute_d212_anual(session: Session, *, user_id: int, an: int):
    """
    Wrapper cu cache validat prin fingerprint peste _compute_d212_anual_uncached.
    Semnatura + return (RezultatD212Service) IDENTICE — cei 6 apelanti nu se schimba.

    Cache HIT doar daca fingerprint-ul datelor e neschimbat -> NICIODATA stale
    (orice modificare a tranzactiilor pe (user, an) invalideaza automat).
    """
    key = (user_id, an)
    fp = _d212_fingerprint(session, user_id, an)

    with _D212_CACHE_LOCK:
        cached = _D212_CACHE.get(key)
        if cached is not None and cached[0] == fp:
            return cached[1]                 # HIT — fingerprint match, date neschimbate

    # MISS — calculam in afara lock-ului (greu: 12× compute_period), apoi stocam.
    result = _compute_d212_anual_uncached(session, user_id=user_id, an=an)
    with _D212_CACHE_LOCK:
        _D212_CACHE[key] = (fp, result)
    return result


def _format_fiscal_estimate_section(totals: Dict[str, Any]) -> List[str]:
    """Formatează secțiunea de estimare fiscală adaptată formei juridice."""
    fe = totals.get("fiscal_estimate")
    if not fe:
        return []

    lines = []
    income_tax = fe.get("income_tax", {})
    cas = fe.get("cas", {})
    cass = fe.get("cass", {})
    base_method = income_tax.get("base_method", "")
    rate = income_tax.get("rate_pct", 0)
    tax_amount = income_tax.get("amount", 0)
    tax_base = income_tax.get("base", 0)

    profile = fe.get("profile_summary") or {}

    if base_method == "venit_net":
        if tax_base > 0:
            lines.append(
                f"  💰 Impozit ({rate}% × venit net): "
                f"`{tax_amount:.2f} RON`"
            )
        else:
            lines.append(
                f"  💰 Impozit: `0 RON` _(fără venit net pozitiv)_"
            )
    elif base_method == "norma":
        lines.append(
            f"  💰 Impozit ({rate}% × normă anuală): "
            f"`{tax_amount:.2f} RON`"
        )
    elif base_method == "profit":
        lines.append(
            f"  💰 Impozit profit ({rate}% × profit): "
            f"`{tax_amount:.2f} RON`"
        )
    elif base_method == "cifra_afaceri":
        lines.append(
            f"  💰 Impozit micro ({rate}% × cifra afaceri): "
            f"`{tax_amount:.2f} RON`"
        )

    if cas.get("applicable"):
        lines.append(
            f"  🏥 CAS ({cas['rate_pct']}%): `{cas['amount']:.2f} RON` _anual_"
        )
    if cass.get("applicable"):
        lines.append(
            f"  ⚕️ CASS ({cass['rate_pct']}%): `{cass['amount']:.2f} RON` _anual_"
        )

    warnings = fe.get("warnings", [])
    for w in warnings:
        lines.append(f"  ⚠️ {w}")

    return lines


def _format_d212_section(d212, month_name, year) -> List[str]:
    """
    Secțiune fiscală pe REALIZAT year-to-date (din compute_d212_anual).
    Aceeași sursă ca dashboard-ul + declarația D212. Separată vizual de bilanțul
    lunar de deasupra, ca să nu se confunde profitul lunar cu baza anuală CASS.
    """
    return [
        "━━━━━━━━━━━━━━━━━━━━",
        f"📊 *Estimare fiscală anuală (realizat ian–{month_name} {year})*",
        f"  Venit net realizat ian–{month_name}: `{d212.venit_net:.2f} RON`",
        f"  💰 Impozit (10%): `{d212.impozit:.2f} RON`",
        f"  🏥 CAS: `{d212.cas:.2f} RON`",
        f"  ⚕️ CASS: `{d212.cass:.2f} RON`",
        f"  _taxe ANUALE pe realizat; bilanțul de sus e pe luna {month_name}_",
    ]


def format_report_message(totals: Dict[str, Any], d212=None) -> str:
    """
    Formatează raportul fiscal pentru Telegram (Markdown).

    d212: optional RezultatD212Service. Dacă e dat → secțiunea fiscală arată
    estimarea ANUALĂ pe REALIZAT year-to-date (CAS/CASS/impozit din D212 —
    aceeași sursă ca dashboard-ul). Dacă None → fallback la estimarea veche.
    """
    t = totals
    has_vat = t["vat_out_total"] > 0

    lines = [
        f"📊 *RAPORT {t['month_name'].upper()} {t['year']}*",
        f"{t['activity_icon']} _{t['activity_name']}_",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"",
    ]

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

    if has_vat:
        lines += [
            "🏛️ *TVA (taxare inversă D301)*",
            f"  Bază facturi: `{t['vat_out_total'] / t['cota_tva']:.2f} RON`",
            f"  TVA colectat (D301): `{t['vat_out_total']:.2f} RON`",
            f"  TVA deductibil: `{t['vat_in_total']:.2f} RON`",
            f"  *Net TVA de plătit: {t['vat_net']:.2f} RON*",
            "",
        ]

    lines += [
        "━━━━━━━━━━━━━━━━━━━━",
        f"📈 *Profit estimat: {t['profit_estimated']:.2f} RON*",
        f"  _(venit brut − cheltuieli deductibile)_",
    ]

    if d212 is not None:
        # estimare ANUALĂ pe realizat YTD (sursă unică, ca dashboard-ul)
        lines.append("")
        lines.extend(_format_d212_section(d212, t["month_name"], t["year"]))
    else:
        # fallback: estimarea veche (proiecție 1 lună × 12) — backward-compat
        fiscal_lines = _format_fiscal_estimate_section(t)
        if fiscal_lines:
            lines.append("")
            lines.append("🧾 *ESTIMARE FISCALĂ*")
            lines.extend(fiscal_lines)

    lines += [
        "",
        f"_📋 {t['tx_count']} tranzacții procesate_",
        f"_⚠️ Estimat — verificați cu contabilul._",
    ]

    return "\n".join(lines)
