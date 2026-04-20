"""
Monitorizare fiscală cu OpenAI Web Search.

Folosește gpt-4o-search-preview pentru a căuta modificări legislative
relevante pentru PFA Ridesharing România.

Surse prioritare căutate automat:
- anaf.ro (legislatie, calendare, ordine)
- legislatie.just.ro (Monitorul Oficial)
- codfiscal.net
- portalcontabilitate.ro
- avocatnet.ro
- fiscalitate.ro

Cost estimat: ~$0.01-0.02 per query lunar.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from openai import OpenAI

from config import settings

logger = logging.getLogger(__name__)

_client = OpenAI(api_key=settings.openai_api_key)

LUNI_RO = {
    1: "ianuarie", 2: "februarie", 3: "martie", 4: "aprilie",
    5: "mai", 6: "iunie", 7: "iulie", 8: "august",
    9: "septembrie", 10: "octombrie", 11: "noiembrie", 12: "decembrie"
}

# Promptul de system — foarte specific pentru a minimiza hallucinations
FISCAL_MONITOR_SYSTEM = """
Ești un expert contabil și fiscal specializat în PFA-uri din România, 
cu focus pe activități de ridesharing (Bolt, Uber).

Sarcina ta: caută și analizează modificările legislative recente 
relevante pentru un PFA sistem real care desfășoară activitate de ridesharing.

DOMENII DE INTERES (în ordinea importanței):
1. TVA și taxare inversă (reverse charge) pentru servicii intracomunitare Bolt/Uber
2. Impozit pe venit PFA (cota 10%, excepții)
3. CAS (contribuție pensie 25%) — plafoane, termene
4. CASS (contribuție sănătate 10%) — plafoane, termene  
5. Declarația Unică (D212) — modificări de formular sau termene
6. D301, D390 VIES — modificări de procedură
7. Deductibilitate cheltuieli auto (50% mixt)
8. e-Factura obligații pentru PFA
9. Salariu minim brut (afectează plafoanele CAS/CASS)
10. Orice OUG sau lege care modifică Codul Fiscal pentru PFA

REGULI STRICTE:
- Caută DOAR informații din ultimele 60 de zile
- Citează ÎNTOTDEAUNA sursa exactă (URL oficial ANAF, Monitorul Oficial, etc.)
- Dacă nu găsești modificări recente, spune explicit "Nu există modificări relevante"
- Nu inventa sau extrapola — doar ce găsești confirmat în surse oficiale
- Menționează numărul actului normativ (ex: OUG nr. X/2026, OPANAF nr. Y/2026)

FORMAT RĂSPUNS JSON (strict, fără text în afara JSON-ului):
{
  "has_changes": true/false,
  "urgency": "critical" | "warning" | "info" | "none",
  "title": "Titlu scurt (max 80 caractere)",
  "summary": "Rezumat în română, max 500 caractere, limbaj simplu pentru non-contabil",
  "changes": [
    {
      "what": "Ce s-a schimbat",
      "impact": "Impactul concret pentru PFA ridesharing",
      "action_required": "Ce trebuie să faci tu",
      "deadline": "Termen limită dacă există",
      "source_url": "URL-ul sursei oficiale",
      "source_name": "Numele sursei (ex: ANAF.ro, Monitorul Oficial nr. X)"
    }
  ],
  "no_changes_reason": "Explicație dacă has_changes=false"
}

CRITERII URGENCY:
- critical: modificare cu impact imediat (termen în 30 zile, cotă schimbată)
- warning: modificare cu impact viitor (termen 31-90 zile)  
- info: informație utilă fără acțiune urgentă
- none: nu există modificări relevante
"""


def run_fiscal_research(year: int, month: int) -> dict:
    """
    Rulează research-ul fiscal pentru luna dată.

    Returns:
        dict cu câmpurile din FORMAT RĂSPUNS JSON de mai sus,
        plus "raw_response" și "error" (None dacă succes).
    """
    luna = LUNI_RO.get(month, str(month))
    month_prev = month - 1 if month > 1 else 12
    year_prev = year if month > 1 else year - 1
    luna_prev = LUNI_RO.get(month_prev, str(month_prev))

    user_prompt = f"""
Caută modificările legislative din {luna_prev} {year_prev} și {luna} {year} 
relevante pentru un PFA sistem real care face ridesharing în România cu Bolt și Uber.

Context specific:
- PFA înregistrat în România, cod CAEN 4932 (transport taxi)
- Primește facturi de comision de la Bolt Operations OÜ (Estonia, VAT EE102090374)
- Aplică taxare inversă (reverse charge) pe comisioanele Bolt/Uber — depune D301 și D390
- Folosește un autoturism mixt (50% deductibilitate)
- Nu este plătitor de TVA înregistrat (sub plafonul de 300.000 RON)
- Depune Declarația Unică anual

Caută în special pe:
- anaf.ro/anaf/internet/RO/modificari-legislative
- legislatie.just.ro (Monitorul Oficial)
- codfiscal.net/noutati
- portalcontabilitate.ro/stiri
- avocatnet.ro/categorie/fiscalitate

Răspunde STRICT în formatul JSON specificat, fără text în afara JSON-ului.
"""

    try:
        logger.info(f"Running fiscal research for {year}/{month:02d}...")

        response = _client.chat.completions.create(
            model="gpt-4o-search-preview",
            messages=[
                {"role": "system", "content": FISCAL_MONITOR_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=2000,
        )

        raw_response = response.choices[0].message.content or ""
        logger.info(f"Fiscal research completed, {len(raw_response)} chars")

        # Curățăm și parsăm JSON-ul
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip()

        try:
            result = json.loads(cleaned)
            result["raw_response"] = raw_response
            result["error"] = None
            result["research_year"] = year
            result["research_month"] = month
            return result
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error in fiscal research: {e}")
            logger.error(f"Raw: {raw_response[:500]}")
            return {
                "has_changes": False,
                "urgency": "none",
                "title": "Eroare parsare răspuns AI",
                "summary": "Nu s-a putut parsa răspunsul. Verificați manual ANAF.ro.",
                "changes": [],
                "raw_response": raw_response,
                "error": f"json_parse_error: {e}",
                "research_year": year,
                "research_month": month,
            }

    except Exception as e:
        logger.error(f"OpenAI fiscal research error: {e}")
        return {
            "has_changes": False,
            "urgency": "none",
            "title": "Eroare conexiune AI",
            "summary": "Nu s-a putut efectua research-ul. Verificați manual ANAF.ro.",
            "changes": [],
            "raw_response": "",
            "error": str(e),
            "research_year": year,
            "research_month": month,
        }


def format_alert_telegram(result: dict) -> Optional[str]:
    """
    Formatează rezultatul research-ului ca mesaj Telegram.
    Returnează None dacă nu există modificări (urgency=none).
    """
    if result.get("urgency") == "none" or not result.get("has_changes", False):
        return None

    urgency = result.get("urgency", "info")
    icon = {"critical": "🔴", "warning": "🟡", "info": "🟢"}.get(urgency, "ℹ️")

    luna_map = {
        1: "Ianuarie", 2: "Februarie", 3: "martie", 4: "Aprilie",
        5: "Mai", 6: "Iunie", 7: "Iulie", 8: "August",
        9: "Septembrie", 10: "Octombrie", 11: "Noiembrie", 12: "Decembrie"
    }
    month_name = luna_map.get(result.get("research_month", 1), "")
    year = result.get("research_year", "")

    lines = [
        f"{icon} *ALERTĂ FISCALĂ — {month_name.upper()} {year}*",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"",
        f"📋 *{result.get('title', 'Modificări legislative')}*",
        f"",
        f"{result.get('summary', '')}",
        f"",
    ]

    changes = result.get("changes", [])
    if changes:
        lines.append("*📌 Detalii modificări:*")
        lines.append("")
        for i, change in enumerate(changes[:3], 1):  # max 3 modificări
            lines.append(f"*{i}. {change.get('what', '')}*")
            if change.get("impact"):
                lines.append(f"   💼 Impact: {change['impact']}")
            if change.get("action_required"):
                lines.append(f"   ✅ Acțiune: {change['action_required']}")
            if change.get("deadline"):
                lines.append(f"   📅 Termen: {change['deadline']}")
            if change.get("source_name"):
                lines.append(f"   🔗 Sursă: {change['source_name']}")
            lines.append("")

    lines += [
        "━━━━━━━━━━━━━━━━━━━━",
        "_⚠️ Informație generată automat cu web search._",
        "_Verificați întotdeauna cu contabilul autorizat._",
        "_Folosiți /alerte pentru istoricul alertelor._",
    ]

    return "\n".join(lines)
