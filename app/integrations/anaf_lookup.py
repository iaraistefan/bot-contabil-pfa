"""
Client pentru API-ul public ANAF — căutare informații firmă după CUI.

API V9: https://webservicesp.anaf.ro/api/PlatitorTvaRest/v9/tva
Documentație oficială: https://static.anaf.ro/static/10/Anaf/Informatii_R/Servicii_web/doc_WS_V9.txt
"""

import json
import logging
from datetime import date
from typing import Optional, Dict, Any

import httpx

logger = logging.getLogger(__name__)

ANAF_API_URL = "https://webservicesp.anaf.ro/api/PlatitorTvaRest/v9/tva"
TIMEOUT_SECONDS = 15


ANAF_FORMA_JURIDICA_MAP = {
    "PERSOANA FIZICA AUTORIZATA": "PFA",
    "PFA": "PFA",
    "INTREPRINDERE INDIVIDUALA": "II",
    "INTREPRINDERE FAMILIALA": "IF",
    "SOCIETATE CU RASPUNDERE LIMITATA": "SRL_MICRO",
    "SOCIETATE COMERCIALA CU RASPUNDERE LIMITATA": "SRL_MICRO",
    "S.R.L.": "SRL_MICRO",
    "SRL": "SRL_MICRO",
    "SOCIETATE PE ACTIUNI": "SRL_NORMAL",
    "S.A.": "SRL_NORMAL",
    "CABINET MEDICAL INDIVIDUAL": "PROFESIE_LIBERALA",
    "CABINET INDIVIDUAL": "PROFESIE_LIBERALA",
    "BIROU INDIVIDUAL": "PROFESIE_LIBERALA",
}


def _normalize_cui(cui: str) -> str:
    return "".join(c for c in str(cui) if c.isdigit())


def _detect_forma_juridica_from_name(denumire: str) -> Optional[str]:
    if not denumire:
        return None
    upper = denumire.upper()
    if "PERSOANA FIZICA AUTORIZATA" in upper or " PFA" in upper:
        return "PFA"
    if "INTREPRINDERE INDIVIDUALA" in upper or " II " in upper:
        return "II"
    if "INTREPRINDERE FAMILIALA" in upper or " IF " in upper:
        return "IF"
    if any(kw in upper for kw in ["S.R.L.", " SRL", "SRL "]):
        return "SRL_MICRO"
    if "S.A." in upper or " SA " in upper:
        return "SRL_NORMAL"
    if any(kw in upper for kw in [
        "CABINET INDIVIDUAL", "BIROU INDIVIDUAL", "CABINET MEDICAL"
    ]):
        return "PROFESIE_LIBERALA"
    return None


def _map_forma_juridica(forma_anaf: str, denumire: str) -> Optional[str]:
    if forma_anaf:
        upper = forma_anaf.strip().upper()
        if upper in ANAF_FORMA_JURIDICA_MAP:
            return ANAF_FORMA_JURIDICA_MAP[upper]
        for key, val in ANAF_FORMA_JURIDICA_MAP.items():
            if key in upper:
                return val
    return _detect_forma_juridica_from_name(denumire)


def _parse_anaf_response(item: Dict[str, Any]) -> Dict[str, Any]:
    date_gen = item.get("date_generale", {}) or {}
    tva = item.get("inregistrare_scop_Tva", {}) or {}
    stare_inactiv = item.get("stare_inactiv", {}) or {}
    sediu = item.get("adresa_sediu_social", {}) or {}
    domiciliu = item.get("adresa_domiciliu_fiscal", {}) or {}

    denumire = (date_gen.get("denumire") or "").strip()
    cui = str(date_gen.get("cui") or "").strip()
    cod_caen = (date_gen.get("cod_CAEN") or "").strip()
    nr_reg_com = (date_gen.get("nrRegCom") or "").strip()
    forma_juridica_anaf = (date_gen.get("forma_juridica") or "").strip()
    forma_organizare = (date_gen.get("forma_organizare") or "").strip()
    stare_inreg = (date_gen.get("stare_inregistrare") or "").strip()
    data_inreg = (date_gen.get("data_inregistrare") or "").strip()

    is_platitor_tva = bool(tva.get("scpTVA"))
    regim_tva = "PLATITOR_21" if is_platitor_tva else "NEPLATITOR"
    forma_juridica = _map_forma_juridica(forma_juridica_anaf, denumire)

    judet = (sediu.get("sdenumire_Judet") or domiciliu.get("ddenumire_Judet") or "").strip()
    localitate = (
        sediu.get("sdenumire_Localitate")
        or domiciliu.get("ddenumire_Localitate") or ""
    ).strip()
    strada = (
        sediu.get("sdenumire_Strada")
        or domiciliu.get("ddenumire_Strada") or ""
    ).strip()
    numar = (
        sediu.get("snumar_Strada")
        or domiciliu.get("dnumar_Strada") or ""
    ).strip()
    cod_postal = (
        sediu.get("scod_Postal")
        or domiciliu.get("dcod_Postal") or ""
    ).strip()

    adresa_parts = []
    if strada:
        adresa_parts.append(f"Str. {strada}")
    if numar:
        adresa_parts.append(f"nr. {numar}")
    if localitate:
        adresa_parts.append(localitate)
    if judet:
        adresa_parts.append(f"jud. {judet}")
    if cod_postal:
        adresa_parts.append(cod_postal)
    adresa_completa = ", ".join(adresa_parts)

    is_inactiv = bool(stare_inactiv.get("statusInactivi"))

    return {
        "found": True,
        "cui": cui,
        "denumire": denumire,
        "forma_juridica_detectata": forma_juridica,
        "forma_juridica_anaf": forma_juridica_anaf,
        "forma_organizare": forma_organizare,
        "regim_tva": regim_tva,
        "is_platitor_tva": is_platitor_tva,
        "is_inactiv": is_inactiv,
        "stare_inregistrare": stare_inreg,
        "cod_caen": cod_caen,
        "nr_reg_com": nr_reg_com,
        "data_inregistrare": data_inreg,
        "judet": judet,
        "localitate": localitate,
        "strada": strada,
        "numar": numar,
        "cod_postal": cod_postal,
        "adresa_completa": adresa_completa,
    }


def lookup_cui(cui: str) -> Dict[str, Any]:
    """Caută o firmă după CUI în registrul ANAF."""
    cui_normalized = _normalize_cui(cui)

    if not cui_normalized:
        return {"found": False, "error": "CUI invalid (gol)"}

    if len(cui_normalized) < 2 or len(cui_normalized) > 10:
        return {"found": False, "error": f"CUI invalid (lungime {len(cui_normalized)})"}

    today_iso = date.today().isoformat()
    payload = [{"cui": int(cui_normalized), "data": today_iso}]

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "ContabilPFA-Bot/1.0",
    }

    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            response = client.post(ANAF_API_URL, json=payload, headers=headers)
            logger.info(
                f"ANAF response status={response.status_code} "
                f"for CUI {cui_normalized}"
            )
            response.raise_for_status()
            raw_text = response.text
            logger.info(f"ANAF raw response (first 500 chars): {raw_text[:500]}")
            data = response.json()
    except httpx.TimeoutException:
        logger.warning(f"ANAF timeout for CUI={cui_normalized}")
        return {"found": False, "error": "ANAF timeout"}
    except httpx.HTTPStatusError as e:
        logger.error(f"ANAF HTTP error: {e}")
        return {"found": False, "error": f"ANAF HTTP {e.response.status_code}"}
    except Exception as e:
        logger.error(f"ANAF unexpected error: {e}")
        return {"found": False, "error": f"Eroare API: {str(e)[:100]}"}

    # === Logică tolerantă: prioritate la conținut, nu la cod ===
    found_items = data.get("found", []) or []
    not_found_items = data.get("notFound", []) or data.get("notfound", []) or []

    # Dacă avem item în "found" → succes, indiferent de cod
    if found_items:
        item = found_items[0]
        parsed = _parse_anaf_response(item)
        logger.info(
            f"ANAF lookup OK: CUI={parsed.get('cui')} "
            f"denumire={parsed.get('denumire')!r} "
            f"forma={parsed.get('forma_juridica_detectata')} "
            f"tva={parsed.get('regim_tva')}"
        )
        return parsed

    # Dacă CUI-ul e explicit în "notFound"
    if not_found_items:
        return {
            "found": False,
            "error": f"CUI {cui_normalized} nu există în registrul ANAF",
            "_raw_response": raw_text[:500],
        }

    # Caz necunoscut: returnăm raw response pentru debug
    return {
        "found": False,
        "error": "Răspuns ANAF neașteptat",
        "_raw_response": raw_text[:500],
        "_keys": list(data.keys()) if isinstance(data, dict) else "not dict",
    }


def format_lookup_result(result: Dict[str, Any]) -> str:
    """Formatează rezultatul ANAF ca mesaj Telegram (Markdown)."""
    if not result.get("found"):
        err = result.get("error", "necunoscut")
        msg = f"❌ Nu am găsit firma în registrul ANAF.\n_Motiv: {err}_"

        # Dacă avem raw response (pentru debug), îl adăugăm
        raw = result.get("_raw_response")
        if raw:
            msg += f"\n\n*🔧 DEBUG — răspuns brut ANAF:*\n```\n{raw[:300]}\n```"

        keys = result.get("_keys")
        if keys:
            msg += f"\n*Chei JSON:* `{keys}`"

        return msg

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
            "SRL_NORMAL": "SRL/SA (impozit profit)",
            "PROFESIE_LIBERALA": "Profesie liberală",
        }.get(forma, forma)
        lines.append(f"🧾 Formă juridică: *{forma_label}*")

    if result.get("is_platitor_tva"):
        lines.append(f"💰 TVA: *Plătitor* (21%)")
    else:
        lines.append(f"💰 TVA: *Neplătitor*")

    cod_caen = result.get("cod_caen")
    if cod_caen:
        lines.append(f"🏷️ CAEN: `{cod_caen}`")

    nr_reg = result.get("nr_reg_com")
    if nr_reg:
        lines.append(f"📑 Reg. Com.: `{nr_reg}`")

    if result.get("is_inactiv"):
        lines.append(f"⚠️ *Firmă INACTIVĂ în ANAF*")

    adresa = result.get("adresa_completa", "")
    if adresa:
        lines.append(f"📍 {adresa}")

    return "\n".join(lines)
