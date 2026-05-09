"""
Client pentru API-ul public ANAF — căutare informații firmă după CUI.

API: https://webservicesp.anaf.ro/PlatitorTvaRest/api/v9/ws/tva
Documentație oficială: https://static.anaf.ro/static/10/Anaf/Informatii_R/API/Api_GetVer9.html

NU necesită autentificare. Rate limit: ~100 cereri/minut.

Returnează: denumire, adresă, status TVA, formă juridică, etc.
"""

import logging
from datetime import date
from typing import Optional, Dict, Any, List

import httpx

logger = logging.getLogger(__name__)

ANAF_API_URL = "https://webservicesp.anaf.ro/PlatitorTvaRest/api/v9/ws/tva"
TIMEOUT_SECONDS = 10


def _normalize_cui(cui: str) -> str:
    """
    Normalizează CUI-ul: păstrează doar cifrele.
    Exemple:
      'RO53067338' -> '53067338'
      '53067338'   -> '53067338'
      'RO 530 67 338' -> '53067338'
    """
    return "".join(c for c in str(cui) if c.isdigit())


def _detect_forma_juridica(denumire: str) -> Optional[str]:
    """
    Detectează forma juridică din denumire.
    Returnează codul nostru intern (PFA, SRL_MICRO, etc.) sau None.
    """
    if not denumire:
        return None
    upper = denumire.upper()

    # PFA / II / IF
    if "PERSOANA FIZICA AUTORIZATA" in upper or "PFA" in upper:
        return "PFA"
    if "INTREPRINDERE INDIVIDUALA" in upper or " II " in upper or upper.endswith(" II"):
        return "II"
    if "INTREPRINDERE FAMILIALA" in upper or " IF " in upper:
        return "IF"

    # SRL / SA
    if "S.R.L." in upper or " SRL" in upper or "SRL " in upper or upper.endswith("SRL"):
        # Nu putem ști dacă e MICRO sau NORMAL doar din denumire
        # → returnăm SRL_MICRO ca default (cel mai comun)
        return "SRL_MICRO"
    if "S.A." in upper or " SA " in upper or upper.endswith(" SA"):
        return "SRL_NORMAL"

    # Profesii liberale
    if any(kw in upper for kw in [
        "CABINET INDIVIDUAL", "BIROU INDIVIDUAL", "CABINET MEDICAL",
        "CABINET AVOCAT", "CABINET NOTAR", "BIROU NOTAR"
    ]):
        return "PROFESIE_LIBERALA"

    return None


def _parse_anaf_response(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transformă răspunsul brut ANAF într-un dict cu cheile noastre interne.
    """
    # Răspunsul ANAF are structura: { date_generale: {...}, inregistrare_scop_Tva: {...},
    #                                  stare_inactiv: {...}, adresa_sediu_social: {...} }

    date_gen = item.get("date_generale", {}) or {}
    tva = item.get("inregistrare_scop_Tva", {}) or {}
    stare_inactiv = item.get("stare_inactiv", {}) or {}
    sediu = item.get("adresa_sediu_social", {}) or {}

    denumire = date_gen.get("denumire") or ""
    cui = str(date_gen.get("cui") or "").strip()

    # Status TVA
    is_platitor_tva = bool(tva.get("scpTVA"))
    regim_tva = "PLATITOR_21" if is_platitor_tva else "NEPLATITOR"

    # Formă juridică detectată din denumire
    forma_juridica = _detect_forma_juridica(denumire)

    # Adresă sediu — câmpurile ANAF
    judet = (sediu.get("sdenumire_Judet") or "").strip()
    localitate = (sediu.get("sdenumire_Localitate") or "").strip()
    strada = (sediu.get("sdenumire_Strada") or "").strip()
    numar = (sediu.get("snumar_Strada") or "").strip()
    cod_postal = (sediu.get("scod_Postal") or "").strip()

    adresa_completa_parts = [strada, numar, localitate, judet, cod_postal]
    adresa_completa = ", ".join(p for p in adresa_completa_parts if p)

    # Status (activ/inactiv)
    is_inactiv = bool(stare_inactiv.get("statusInactivi"))

    return {
        "found": True,
        "cui": cui,
        "denumire": denumire,
        "forma_juridica_detectata": forma_juridica,
        "regim_tva": regim_tva,
        "is_platitor_tva": is_platitor_tva,
        "is_inactiv": is_inactiv,
        "judet": judet,
        "localitate": localitate,
        "strada": strada,
        "numar": numar,
        "cod_postal": cod_postal,
        "adresa_completa": adresa_completa,
        "data_inregistrare": date_gen.get("data_inregistrare"),
        "raw": item,  # păstrăm răspunsul brut pentru debugging
    }


def lookup_cui(cui: str) -> Dict[str, Any]:
    """
    Caută o firmă după CUI în registrul ANAF.

    Args:
        cui: CUI cu sau fără prefix RO. Exemple: "RO53067338", "53067338"

    Returns:
        dict cu structura:
        {
            "found": True/False,
            "error": str | None,  # mesaj de eroare dacă found=False
            "cui": str,
            "denumire": str,
            "forma_juridica_detectata": str | None,
            "regim_tva": "PLATITOR_21" | "NEPLATITOR",
            "is_platitor_tva": bool,
            "is_inactiv": bool,
            "judet": str,
            "localitate": str,
            "adresa_completa": str,
            ...
        }
    """
    cui_normalized = _normalize_cui(cui)

    if not cui_normalized:
        return {"found": False, "error": "CUI invalid (gol)"}

    if len(cui_normalized) < 2 or len(cui_normalized) > 10:
        return {"found": False, "error": f"CUI invalid (lungime {len(cui_normalized)})"}

    # Data pentru care vrem informațiile (azi)
    today_iso = date.today().isoformat()

    payload = [{"cui": int(cui_normalized), "data": today_iso}]

    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            response = client.post(
                ANAF_API_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        logger.warning(f"ANAF lookup timeout for CUI={cui_normalized}")
        return {"found": False, "error": "ANAF timeout — încearcă din nou"}
    except httpx.HTTPStatusError as e:
        logger.error(f"ANAF lookup HTTP error: {e}")
        return {"found": False, "error": f"ANAF HTTP {e.response.status_code}"}
    except Exception as e:
        logger.error(f"ANAF lookup unexpected error: {e}")
        return {"found": False, "error": f"Eroare API: {str(e)[:100]}"}

    # Verificăm răspunsul
    found_items = data.get("found", []) or []
    not_found_items = data.get("notfound", []) or []

    if not found_items:
        if not_found_items:
            logger.info(f"ANAF: CUI {cui_normalized} not found in registry")
            return {
                "found": False,
                "error": f"CUI {cui_normalized} nu există în registrul ANAF",
            }
        return {
            "found": False,
            "error": "Răspuns ANAF gol — CUI necunoscut",
        }

    # Avem cel puțin un rezultat
    item = found_items[0]
    parsed = _parse_anaf_response(item)
    logger.info(
        f"ANAF lookup OK: CUI={parsed.get('cui')} "
        f"denumire={parsed.get('denumire')!r} "
        f"tva={parsed.get('regim_tva')}"
    )
    return parsed


def format_lookup_result(result: Dict[str, Any]) -> str:
    """
    Formatează rezultatul ANAF ca mesaj Telegram (Markdown).
    Folosit pentru a afișa user-ului ce am găsit.
    """
    if not result.get("found"):
        err = result.get("error", "necunoscut")
        return f"❌ Nu am găsit firma în registrul ANAF.\n_Motiv: {err}_"

    lines = [
        f"✅ *Firma găsită în ANAF:*",
        f"",
        f"🏢 *{result.get('denumire', '?')}*",
        f"📋 CUI: `{result.get('cui', '?')}`",
    ]

    forma = result.get("forma_juridica_detectata")
    if forma:
        forma_label = {
            "PFA": "Persoană Fizică Autorizată",
            "II": "Întreprindere Individuală",
            "IF": "Întreprindere Familială",
            "SRL_MICRO": "SRL (microîntreprindere)",
            "SRL_NORMAL": "SRL (impozit profit)",
            "PROFESIE_LIBERALA": "Profesie liberală",
        }.get(forma, forma)
        lines.append(f"🧾 Formă juridică: *{forma_label}*")

    if result.get("is_platitor_tva"):
        lines.append(f"💰 TVA: *Plătitor* (21%)")
    else:
        lines.append(f"💰 TVA: *Neplătitor*")

    if result.get("is_inactiv"):
        lines.append(f"⚠️ *Firmă INACTIVĂ în ANAF*")

    adresa = result.get("adresa_completa", "")
    if adresa:
        lines.append(f"📍 {adresa}")

    return "\n".join(lines)
