"""
Calendar fiscal pentru PFA Ridesharing România 2026.

Date bazate pe:
- Calendarul ANAF 2026 (publicat oficial)
- Codul Fiscal Legea 227/2015 actualizat 2026
- OUG 115/2023 (TVA 21%)
- Ghid PFA sistem real 2026

IMPORTANT: Verificați întotdeauna cu contabilul autorizat.
Termenele pot fi modificate prin acte normative ulterioare.
"""

from datetime import date, datetime
from typing import List, Optional


# ── Obligații lunare PFA Ridesharing ──────────────────────────────────────────

MONTHLY_DEADLINES = [
    {
        "code": "D301",
        "name": "Decont TVA — Taxare inversă",
        "day": 25,
        "description": (
            "Declari TVA-ul colectat prin taxare inversă pe comisioanele "
            "Bolt/Uber (servicii intracomunitare). "
            "Baza: valoarea facturilor Bolt/Uber × 21%."
        ),
        "condition": "doar dacă ai factură comision Bolt/Uber în luna respectivă",
        "where": "ANAF ePortal → Depunere declarații → D301",
        "urgency": "high",
    },
    {
        "code": "D390",
        "name": "Declarație recapitulativă VIES",
        "day": 25,
        "description": (
            "Declari achizițiile intracomunitare de servicii. "
            "Se completează cu valoarea netă a comisioanelor Bolt Operations OÜ (Estonia, EE...)."
        ),
        "condition": "doar dacă ai factură comision Bolt/Uber în luna respectivă",
        "where": "ANAF ePortal → Depunere declarații → D390",
        "urgency": "high",
    },
]

# ── Obligații anuale PFA sistem real ─────────────────────────────────────────

ANNUAL_DEADLINES = [
    {
        "code": "D212",
        "name": "Declarația Unică (D212)",
        "month": 5,
        "day": 25,
        "description": (
            "Declari veniturile și cheltuielile PFA din anul anterior. "
            "Se calculează automat: impozit venit (10%), CAS (25%), CASS (10%). "
            "Dacă plătești înainte de 15 aprilie → bonificație 3% din impozitul pe venit."
        ),
        "where": "ANAF ePortal → Declarația Unică (D212) sau anaf.ro/duf",
        "urgency": "high",
        "bonus_tip": "Plătești înainte de 15 aprilie → economisești 3% din impozitul pe venit!",
    },
    {
        "code": "CAS",
        "name": "Plată CAS (pensie 25%)",
        "month": 5,
        "day": 25,
        "description": (
            "Contribuția la pensie: 25% × baza de calcul. "
            "Obligatorie dacă venit net > 12 salarii minime brute (12 × 4.050 = 48.600 RON). "
            "Baza maximă: 24 salarii minime = 97.200 RON/an."
        ),
        "where": "Prin D212 sau direct la Trezorerie",
        "urgency": "medium",
    },
    {
        "code": "CASS",
        "name": "Plată CASS (sănătate 10%)",
        "month": 5,
        "day": 25,
        "description": (
            "Contribuția la sănătate: 10% × baza de calcul. "
            "Plafonul maxim 2026: 60 salarii minime = 243.000 RON. "
            "Suma maximă CASS: 24.300 RON/an."
        ),
        "where": "Prin D212",
        "urgency": "medium",
    },
]

# ── Taxe speciale Ridesharing ─────────────────────────────────────────────────

SPECIAL_NOTES = [
    {
        "code": "IMPOZIT_NEREZIDENȚI",
        "name": "Impozit nerezidenți (withholding 2%)",
        "description": (
            "Bolt reține automat 2% din comision și îl virează la Trezoreria României "
            "(conform convenției de evitare a dublei impuneri România-Estonia). "
            "Apare pe factura Bolt ca 'Withholding tax'. NU mai trebuie plătit de tine."
        ),
        "urgency": "info",
    },
    {
        "code": "REGISTRU_JURNAL",
        "name": "Registru jurnal de încasări și plăți",
        "description": (
            "Ca PFA sistem real, ești obligat să ții un registru jurnal. "
            "Bot-ul tău generează datele necesare prin /export. "
            "Consultați contabilul pentru formatul oficial."
        ),
        "urgency": "info",
    },
]


def get_monthly_alerts(year: int, month: int, has_bolt_invoice: bool = False) -> List[dict]:
    """
    Returnează alertele pentru luna dată.

    Args:
        year: Anul
        month: Luna (1-12)
        has_bolt_invoice: True dacă luna are facturi de comision Bolt/Uber

    Returns:
        Lista de alerte cu deadline-ul calculat
    """
    alerts = []
    today = date.today()

    for decl in MONTHLY_DEADLINES:
        # D301 și D390 doar dacă există facturi Bolt
        if not has_bolt_invoice:
            continue

        deadline = date(year, month, decl["day"])
        days_left = (deadline - today).days

        urgency = decl["urgency"]
        if days_left < 0:
            status = "overdue"
        elif days_left <= 3:
            status = "critical"
        elif days_left <= 7:
            status = "warning"
        else:
            status = "ok"

        alerts.append({
            **decl,
            "deadline": deadline.strftime("%d.%m.%Y"),
            "days_left": days_left,
            "status": status,
            "year": year,
            "month": month,
        })

    return alerts


def get_annual_alerts(year: int) -> List[dict]:
    """Returnează alertele anuale pentru un an dat."""
    alerts = []
    today = date.today()

    for decl in ANNUAL_DEADLINES:
        deadline = date(year, decl["month"], decl["day"])
        days_left = (deadline - today).days

        if days_left < 0:
            status = "overdue"
        elif days_left <= 14:
            status = "critical"
        elif days_left <= 30:
            status = "warning"
        else:
            status = "ok"

        alerts.append({
            **decl,
            "deadline": deadline.strftime("%d.%m.%Y"),
            "days_left": days_left,
            "status": status,
        })

    return alerts


def format_fiscal_message(
    year: int,
    month: int,
    has_bolt_invoice: bool = False,
) -> str:
    """
    Formatează mesajul cu obligațiile fiscale pentru o lună.
    Pentru Telegram (Markdown).
    """
    from app.services.tax_engine import LUNI_RO

    lines = [
        f"🏛️ *CALENDAR FISCAL — {LUNI_RO.get(month, str(month)).upper()} {year}*",
        f"━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    # Alerte lunare
    monthly = get_monthly_alerts(year, month, has_bolt_invoice=has_bolt_invoice)
    if monthly:
        lines.append("📋 *DECLARAȚII LUNARE (până pe 25):*")
        for a in monthly:
            icon = "🔴" if a["status"] in ("overdue","critical") else "🟡" if a["status"] == "warning" else "🟢"
            days_str = f"(DEPĂȘIT cu {abs(a['days_left'])} zile!)" if a["days_left"] < 0 else f"({a['days_left']} zile rămase)"
            lines.append(f"{icon} *{a['code']}* — {a['name']} {days_str}")
            lines.append(f"   📅 Termen: `{a['deadline']}`")
            lines.append(f"   ℹ️ {a['description'][:120]}...")
            lines.append(f"   🖥️ {a['where']}")
            lines.append("")
    else:
        lines.append("✅ *Declarații lunare:*")
        lines.append("Nicio factură Bolt/Uber în această lună → D301/D390 nu se depun.")
        lines.append("")

    # Alerte anuale relevante (în lunile apropiate)
    annual = [a for a in get_annual_alerts(year) if -30 <= a["days_left"] <= 60]
    if annual:
        lines.append("📅 *OBLIGAȚII ANUALE APROPIATE:*")
        for a in annual:
            icon = "🔴" if a["status"] in ("overdue","critical") else "🟡" if a["status"] == "warning" else "🟢"
            days_str = f"(DEPĂȘIT!)" if a["days_left"] < 0 else f"({a['days_left']} zile)"
            lines.append(f"{icon} *{a['code']}* — {a['name']} {days_str}")
            lines.append(f"   📅 Termen: `{a['deadline']}`")
            if a.get("bonus_tip"):
                lines.append(f"   💡 {a['bonus_tip']}")
            lines.append("")

    lines += [
        "━━━━━━━━━━━━━━━━━━━━",
        "_⚠️ Verificați întotdeauna cu contabilul autorizat._",
        "_Termenele pot fi modificate prin acte normative._",
    ]

    return "\n".join(lines)
