"""
VAT Engine — Motor de detecție automată TVA pentru orice tranzacție.

Determină automat tratamentul TVA bazat pe:
1. VAT_ID al furnizorului (dacă apare pe factură)
2. Brand recognition (matching pe ~70 furnizori populari în România)
3. Categoria tranzacției (din activitate)
4. Profilul fiscal al user-ului (plătitor/neplătitor TVA)

ARHITECTURĂ:
- Funcții pure (fără I/O, fără DB)
- Returnează DECIZIA — nu modifică nimic
- Apelat de posting.py la fiecare tranzacție nouă

CONTEXT LEGAL (2026):
- Cota TVA standard: 21% (OUG 115/2023)
- Cota redusă alimente/medicamente: 9% (art. 291 alin. 2)
- Cota redusă cărți/locuințe sociale: 5% (art. 291 alin. 3)
- Reverse charge intracomunitar: art. 307 alin. 2 Cod Fiscal
- Scutire fără drept deducere (educație/medical): art. 292
- Scutire cu drept deducere (export): art. 294

CHANGELOG:
- Pas 8.2: Versiunea inițială cu brand_database + extract_vat_id
- Pas 8.4b-fix:
  * extract_vat_id: validare cifre minime (evită false-positives gen "ROMPETROL")
  * detect_brand: 2 strategii (substring + first-word) pentru a prinde brand-uri scurte
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple, List

from app.domain.tax_rules import BOLT_VAT_ID   # cod TVA Bolt — sursă unică

logger = logging.getLogger(__name__)


# ============================================================
#                    CONSTANTE
# ============================================================

# Prefixe VAT pentru țările UE (excluzând România)
EU_VAT_PREFIXES = {
    "AT": "Austria", "BE": "Belgia", "BG": "Bulgaria", "CY": "Cipru",
    "CZ": "Cehia", "DE": "Germania", "DK": "Danemarca", "EE": "Estonia",
    "ES": "Spania", "FI": "Finlanda", "FR": "Franța", "GR": "Grecia",
    "EL": "Grecia",  # uneori GR e EL
    "HR": "Croația", "HU": "Ungaria", "IE": "Irlanda", "IT": "Italia",
    "LT": "Lituania", "LU": "Luxembourg", "LV": "Letonia", "MT": "Malta",
    "NL": "Olanda", "PL": "Polonia", "PT": "Portugalia", "SE": "Suedia",
    "SI": "Slovenia", "SK": "Slovacia",
}

# Prefixe non-UE (pentru identificare import servicii)
NON_EU_VAT_PREFIXES = {
    "GB": "Marea Britanie",  # post-Brexit
    "CH": "Elveția",
    "NO": "Norvegia",
}

# România
RO_VAT_PREFIX = "RO"

# Cote TVA standard
VAT_RATE_STANDARD = 21
VAT_RATE_REDUCED_9 = 9
VAT_RATE_REDUCED_5 = 5

# Validare VAT_ID — minim cifre (anti false-positive)
VAT_ID_MIN_DIGITS = 2
VAT_ID_MIN_LENGTH = 4


# ============================================================
#         BRAND RECOGNITION DATABASE (~70 furnizori)
# ============================================================

# Format: cuvinte_cheie -> (country_code, vat_id_known, brand_name)
# Cuvintele cheie sunt în lowercase și pot fi parțiale (substring match)
# vat_id_known e VAT_ID-ul oficial pentru a-l completa automat când lipsește

BRAND_DATABASE = {
    # ─── 🇪🇺 UE — MARKETPLACE-URI & RIDESHARING ─────────────
    "bolt operations": ("EE", BOLT_VAT_ID, "Bolt"),
    "bolt technology": ("EE", BOLT_VAT_ID, "Bolt"),
    "uber bv": ("NL", "NL852071589B01", "Uber"),
    "uber b.v": ("NL", "NL852071589B01", "Uber"),
    "uber eats": ("NL", "NL852071589B01", "Uber Eats"),
    "etsy ireland": ("IE", "IE9777587C", "Etsy"),
    "amazon eu sarl": ("LU", "LU20260743", "Amazon EU"),
    "amazon eu": ("LU", "LU20260743", "Amazon EU"),
    "ebay europe": ("LU", "LU26375245", "eBay"),
    "wolt enterprises": ("FI", "FI28456833", "Wolt"),
    "glovo": ("ES", "ESB66362906", "Glovo"),
    "booking.com": ("NL", "NL805734958B01", "Booking"),
    "airbnb ireland": ("IE", "IE9827384N", "Airbnb"),

    # ─── 🇪🇺 UE — CLOUD & SAAS ───────────────────────────────
    "google ireland": ("IE", "IE6388047V", "Google Ireland"),
    "google ads": ("IE", "IE6388047V", "Google Ads"),
    "google cloud emea": ("IE", "IE6388047V", "Google Cloud"),
    "facebook ireland": ("IE", "IE9692928F", "Meta/Facebook"),
    "meta platforms ireland": ("IE", "IE9692928F", "Meta"),
    "linkedin ireland": ("IE", "IE9740425P", "LinkedIn"),
    "tiktok information technologies": ("IE", "IE3308006KH", "TikTok"),
    "microsoft ireland": ("IE", "IE8256796U", "Microsoft Ireland"),
    "stripe payments europe": ("IE", "IE3206488LH", "Stripe"),
    "stripe ireland": ("IE", "IE3206488LH", "Stripe"),
    "shopify international": ("IE", "IE3568998CH", "Shopify"),
    "vercel inc.": ("IE", None, "Vercel"),
    "notion labs": ("IE", None, "Notion"),
    "figma ireland": ("IE", None, "Figma"),
    "slack technologies": ("IE", "IE9806660R", "Slack"),
    "zoom video": ("IE", "IE3729437LH", "Zoom"),
    "atlassian": ("NL", "NL821875707B01", "Atlassian"),
    "gitlab b.v": ("NL", "NL859533370B01", "GitLab"),
    "spotify ab": ("SE", "SE556703748501", "Spotify"),
    "netflix international": ("NL", "NL852017488B01", "Netflix"),

    # ─── 🇺🇸 NON-UE — IMPORT SERVICII ───────────────────────
    "amazon web services": ("US", None, "AWS"),
    "amazon.com": ("US", None, "Amazon US"),
    "google llc": ("US", None, "Google LLC"),
    "microsoft corporation": ("US", None, "Microsoft Corp"),
    "openai": ("US", None, "OpenAI"),
    "anthropic": ("US", None, "Anthropic"),
    "github inc": ("US", None, "GitHub"),
    "apple inc": ("US", None, "Apple"),
    "apple distribution international": ("IE", "IE9700053D", "Apple Ireland"),
    "adobe systems": ("IE", "IE6364992H", "Adobe Ireland"),
    "adobe inc": ("US", None, "Adobe US"),
    "cloudflare": ("US", None, "Cloudflare"),
    "digitalocean": ("US", None, "DigitalOcean"),
    "moonshot ai": ("SG", None, "Moonshot AI"),  # Singapore (non-UE pentru România)

    # ─── 🇷🇴 ROMÂNIA — MARKETPLACE & RETAIL ─────────────────
    "emag": ("RO", None, "eMAG"),
    "olx": ("RO", None, "OLX Romania"),
    "altex": ("RO", None, "Altex"),
    "decathlon": ("RO", None, "Decathlon"),
    "kaufland": ("RO", None, "Kaufland"),
    "lidl": ("RO", None, "Lidl"),
    "carrefour": ("RO", None, "Carrefour"),
    "auchan": ("RO", None, "Auchan"),

    # ─── 🇷🇴 ROMÂNIA — BENZINĂRII & TRANSPORT ───────────────
    "lukoil": ("RO", None, "Lukoil"),
    "omv": ("RO", None, "OMV"),
    "petrom": ("RO", None, "Petrom"),
    "rompetrol": ("RO", None, "Rompetrol"),
    "mol": ("RO", None, "MOL"),
    "shell romania": ("RO", None, "Shell"),
    "socar": ("RO", None, "Socar"),

    # ─── 🇷🇴 ROMÂNIA — TELECOM & UTILITĂȚI ──────────────────
    "orange romania": ("RO", None, "Orange"),
    "vodafone romania": ("RO", None, "Vodafone"),
    "digi": ("RO", None, "Digi"),
    "telekom": ("RO", None, "Telekom"),
    "rcs": ("RO", None, "RCS"),
    "rds": ("RO", None, "RDS"),
    "enel": ("RO", None, "Enel"),
    "engie": ("RO", None, "Engie"),
    "electrica": ("RO", None, "Electrica"),

    # ─── 🇷🇴 ROMÂNIA — ASIGURĂRI & FINANCIAR ────────────────
    "allianz tiriac": ("RO", None, "Allianz Țiriac"),
    "groupama": ("RO", None, "Groupama"),
    "city insurance": ("RO", None, "City Insurance"),
    "asirom": ("RO", None, "Asirom"),
    "omniasig": ("RO", None, "Omniasig"),
    "euroins": ("RO", None, "Euroins"),

    # ─── 🇷🇴 ROMÂNIA — CURIERAT ─────────────────────────────
    "fan courier": ("RO", None, "FAN Courier"),
    "cargus": ("RO", None, "Cargus"),
    "sameday": ("RO", None, "Sameday"),
    "dpd romania": ("RO", None, "DPD"),
    "gls": ("RO", None, "GLS"),
}


# ============================================================
#                    ENUMS
# ============================================================

class VATTreatment(str, Enum):
    """Tipul de tratament TVA aplicat."""
    NA = "NA"
    STANDARD_21 = "STANDARD_21"
    REDUCED_9 = "REDUCED_9"
    REDUCED_5 = "REDUCED_5"
    REVERSE_CHARGE = "REVERSE_CHARGE"
    IMPORT_NON_EU = "IMPORT_NON_EU"
    EXEMPT_ART_292 = "EXEMPT_ART_292"
    EXEMPT_ART_294 = "EXEMPT_ART_294"
    UNKNOWN = "UNKNOWN"


class CountryGroup(str, Enum):
    """Grup geografic al furnizorului."""
    ROMANIA = "ROMANIA"
    EU = "EU"
    NON_EU = "NON_EU"
    UNKNOWN = "UNKNOWN"


# ============================================================
#                    DECIZIE — RESULT
# ============================================================

@dataclass
class VATDecision:
    """Rezultatul analizei TVA pentru o tranzacție."""

    treatment: VATTreatment
    country_code: Optional[str] = None
    country_group: CountryGroup = CountryGroup.UNKNOWN
    vat_rate: int = 0
    detected_brand: Optional[str] = None
    detected_vat_id: Optional[str] = None

    requires_d300: bool = False
    requires_d301: bool = False
    requires_d390: bool = False

    confidence: int = 0
    explanation: str = ""

    def to_dict(self) -> dict:
        return {
            "treatment": self.treatment.value,
            "country_code": self.country_code,
            "country_group": self.country_group.value,
            "vat_rate": self.vat_rate,
            "detected_brand": self.detected_brand,
            "detected_vat_id": self.detected_vat_id,
            "requires_d300": self.requires_d300,
            "requires_d301": self.requires_d301,
            "requires_d390": self.requires_d390,
            "confidence": self.confidence,
            "explanation": self.explanation,
        }


# ============================================================
#              EXTRACTORI & DETECTORI
# ============================================================

# Pattern pentru VAT_ID UE: 2 litere + cifre (uneori cu litere amestecate)
VAT_ID_PATTERN = re.compile(
    r"\b([A-Z]{2})[\s-]?([A-Z0-9]{2,12})\b"
)


def extract_vat_id(text: Optional[str]) -> Optional[str]:
    """
    Extrage VAT_ID dintr-un text liber (factură, descriere).

    Recunoaște formate:
    - "EE102090374" / "EE 102090374" / "EE-102090374"
    - "VAT: EE102090374"
    - "CUI: RO12345678"

    Validare strictă (Pas 8.4b-fix):
    - Prefix trebuie să fie țară cunoscută (RO/UE/non-UE specific)
    - Lungime minimă: 4 caractere alfanumerice după prefix
    - CEL PUȚIN 2 CIFRE (anti false-positive: "ROMPETROL" rejectat,
      "ROBINSON" rejectat, "EE102090374" acceptat)

    Returnează VAT_ID-ul în format normalizat (FĂRĂ spații/dash-uri).
    """
    if not text:
        return None

    text_upper = text.upper()
    matches = VAT_ID_PATTERN.findall(text_upper)

    for prefix, number in matches:
        # Validare 1: prefix trebuie să fie țară cunoscută
        if not (prefix in EU_VAT_PREFIXES or
                prefix in NON_EU_VAT_PREFIXES or
                prefix == RO_VAT_PREFIX):
            continue

        # Validare 2: lungime minimă
        if len(number) < VAT_ID_MIN_LENGTH:
            continue

        # Validare 3 (NEW Pas 8.4b-fix): CEL PUȚIN 2 cifre
        # VAT_ID-uri reale au cifre. Cuvintele românești (ROMPETROL, ROBINSON)
        # sau alte coincidențe de litere nu sunt VAT_ID-uri valide.
        digit_count = sum(1 for c in number if c.isdigit())
        if digit_count < VAT_ID_MIN_DIGITS:
            continue

        return f"{prefix}{number}"

    return None


def detect_country_from_vat_id(vat_id: Optional[str]) -> Tuple[Optional[str], CountryGroup]:
    """
    Determină țara și grupul (RO/UE/non-UE) din VAT_ID.

    Returnează (country_code, country_group).
    Ex: "EE102090374" → ("EE", CountryGroup.EU)
    Ex: "RO12345678" → ("RO", CountryGroup.ROMANIA)
    Ex: None → (None, CountryGroup.UNKNOWN)
    """
    if not vat_id:
        return None, CountryGroup.UNKNOWN

    vat_clean = vat_id.strip().upper().replace(" ", "").replace("-", "")
    if len(vat_clean) < 2:
        return None, CountryGroup.UNKNOWN

    prefix = vat_clean[:2]

    if prefix == RO_VAT_PREFIX:
        return "RO", CountryGroup.ROMANIA
    if prefix in EU_VAT_PREFIXES:
        return prefix, CountryGroup.EU
    if prefix in NON_EU_VAT_PREFIXES:
        return prefix, CountryGroup.NON_EU

    return None, CountryGroup.UNKNOWN


def detect_brand(text: Optional[str]) -> Optional[Tuple[str, str, Optional[str], str]]:
    """
    Recunoaște brand-ul dintr-un text liber.

    Strategie cu 2 nivele (Pas 8.4b-fix):
    1. Substring match — cea mai specifică (ex: "bolt operations" în "Bolt Operations OU")
    2. First-word match — pentru cazul când AI returnează doar primul cuvânt
       (ex: "Bolt" simplu → match cu keyword "bolt operations")

    Returnează tuple (matched_keyword, country_code, vat_id_known, brand_name)
    sau None dacă nu match-uie.

    Ex:
    - "Bolt Operations OU" → ("bolt operations", "EE", "EE...", "Bolt")  [substring]
    - "Bolt" → ("bolt operations", "EE", "EE...", "Bolt")  [first-word, NEW]
    - "AWS hosting EC2" → ("amazon web services", "US", None, "AWS")  [first-word AWS=3 chars... NU prinde, trebuie >= 4]
    - "Lukoil benzinărie" → ("lukoil", "RO", None, "Lukoil")  [substring]
    - "Rompetrol" → ("rompetrol", "RO", None, "Rompetrol")  [substring]
    """
    if not text:
        return None

    text_lower = text.lower()
    text_words = set(text_lower.split())  # cuvinte separate
    best_match = None
    best_match_score = 0

    for keyword, (country, vat_id, brand_name) in BRAND_DATABASE.items():
        # ── Strategy 1: Substring match (cel mai specific) ──
        if keyword in text_lower:
            # Priority dublă pentru substring match (e mai specific decât first-word)
            score = len(keyword) * 2
            if score > best_match_score:
                best_match = (keyword, country, vat_id, brand_name)
                best_match_score = score
            continue  # nu mai testăm strategy 2 dacă strategy 1 a match-uit

        # ── Strategy 2: First-word match (NEW Pas 8.4b-fix) ──
        # Util când AI returnează "Bolt" în loc de "Bolt Operations OU"
        keyword_words = keyword.split()
        if not keyword_words:
            continue

        primary_word = keyword_words[0]

        # Cerințe pentru a evita false positives:
        # - primary word ≥ 4 caractere (evită "aws", "olx" cu doar 3)
        # - primary word să fie un cuvânt SEPARAT în text (nu doar substring)
        if len(primary_word) >= 4 and primary_word in text_words:
            score = len(primary_word)  # priority simplă (mai mică decât substring)
            if score > best_match_score:
                best_match = (keyword, country, vat_id, brand_name)
                best_match_score = score

    return best_match


# ============================================================
#                    MOTORUL PRINCIPAL
# ============================================================

def analyze(
    *,
    platforma: Optional[str] = None,
    detalii: Optional[str] = None,
    vat_id: Optional[str] = None,
    user_is_vat_payer: bool = False,
    transaction_type: str = "EXPENSE",
) -> VATDecision:
    """
    Analizează o tranzacție și returnează tratamentul TVA corect.

    Args:
        platforma: numele furnizorului (text liber)
        detalii: descrierea tranzacției
        vat_id: VAT_ID dacă e disponibil pe factură
        user_is_vat_payer: True dacă user-ul nostru e plătitor TVA
        transaction_type: tipul tranzacției ("INCOME" / "EXPENSE" / "FACTURA_COMISION")

    Returns:
        VATDecision cu tratament + obligații + explicație

    Strategia:
    1. Dacă avem vat_id explicit → cea mai sigură detecție (95%)
    2. Altfel, extragere VAT_ID din text (cu validare strictă) (85%)
    3. Altfel, brand recognition pe text combinat (75/65%)
    4. Altfel, presupunem RO (fallback sigur, confidence 30%)
    """
    full_text = f"{platforma or ''} {detalii or ''}".strip()

    # ── Strategy 1: VAT_ID explicit ─────────────────────────
    country_code = None
    country_group = CountryGroup.UNKNOWN
    detected_vat_id = vat_id
    detected_brand = None
    confidence = 0

    if vat_id:
        country_code, country_group = detect_country_from_vat_id(vat_id)
        confidence = 95

    # ── Strategy 2: Extract VAT_ID from text ───────────────
    if not country_code:
        extracted_vat = extract_vat_id(full_text)
        if extracted_vat:
            country_code, country_group = detect_country_from_vat_id(extracted_vat)
            detected_vat_id = extracted_vat
            confidence = 85

    # ── Strategy 3: Brand recognition ──────────────────────
    if not country_code:
        brand_result = detect_brand(full_text)
        if brand_result:
            keyword, country_code, vat_id_known, brand_name = brand_result
            country_group = (
                CountryGroup.ROMANIA if country_code == "RO"
                else CountryGroup.EU if country_code in EU_VAT_PREFIXES
                else CountryGroup.NON_EU if country_code in NON_EU_VAT_PREFIXES
                else CountryGroup.UNKNOWN
            )
            detected_brand = brand_name
            if vat_id_known and not detected_vat_id:
                detected_vat_id = vat_id_known
            confidence = 75 if vat_id_known else 65

    # ── Strategy 4: Fallback — presupunem RO ─────────────
    if not country_code:
        country_code = "RO"
        country_group = CountryGroup.ROMANIA
        confidence = 30

    # ────────────────────────────────────────────────────────
    # APLICĂM REGULILE FISCALE PE GRUP COUNTRY
    # ────────────────────────────────────────────────────────

    decision = _apply_vat_rules(
        country_code=country_code,
        country_group=country_group,
        detected_vat_id=detected_vat_id,
        detected_brand=detected_brand,
        confidence=confidence,
        user_is_vat_payer=user_is_vat_payer,
        transaction_type=transaction_type,
    )

    return decision


def _apply_vat_rules(
    *,
    country_code: str,
    country_group: CountryGroup,
    detected_vat_id: Optional[str],
    detected_brand: Optional[str],
    confidence: int,
    user_is_vat_payer: bool,
    transaction_type: str,
) -> VATDecision:
    """
    Aplică regulile fiscale pe baza grupului țării furnizorului.

    Logica:
    - RO → TVA standard 21% (sau scutit dacă neplătitor + neplătitor)
    - EU → REVERSE CHARGE (pentru servicii intracomunitare)
    - non-EU → IMPORT (similar reverse charge dar fără D390)
    """
    decision = VATDecision(
        treatment=VATTreatment.UNKNOWN,
        country_code=country_code,
        country_group=country_group,
        detected_vat_id=detected_vat_id,
        detected_brand=detected_brand,
        confidence=confidence,
    )

    brand_label = detected_brand or country_code or "furnizor necunoscut"

    # ─── ROMÂNIA ────────────────────────────────────────────
    if country_group == CountryGroup.ROMANIA:
        decision.treatment = VATTreatment.STANDARD_21
        decision.vat_rate = VAT_RATE_STANDARD
        decision.requires_d300 = user_is_vat_payer
        decision.explanation = (
            f"Furnizor RO ({brand_label}) — TVA 21% standard. "
            f"{'Deductibil prin D300.' if user_is_vat_payer else 'Inclus în preț (neplătitor TVA).'}"
        )

    # ─── UE — REVERSE CHARGE ────────────────────────────────
    elif country_group == CountryGroup.EU:
        decision.treatment = VATTreatment.REVERSE_CHARGE
        decision.vat_rate = VAT_RATE_STANDARD
        decision.requires_d301 = True
        decision.requires_d390 = True
        country_name = EU_VAT_PREFIXES.get(country_code, country_code)
        decision.explanation = (
            f"Furnizor UE — {brand_label} ({country_name}). "
            f"Aplicăm TAXARE INVERSĂ (art. 307 alin. 2 Cod Fiscal). "
            f"Trebuie depuse D301 + D390 până pe data 25 a lunii următoare."
        )

    # ─── NON-UE — IMPORT SERVICII ───────────────────────────
    elif country_group == CountryGroup.NON_EU:
        decision.treatment = VATTreatment.IMPORT_NON_EU
        decision.vat_rate = VAT_RATE_STANDARD
        decision.requires_d301 = True
        decision.requires_d390 = False
        country_name = NON_EU_VAT_PREFIXES.get(country_code, country_code)
        decision.explanation = (
            f"Furnizor non-UE — {brand_label} ({country_name}). "
            f"Import de servicii — TVA datorat la ANAF prin D301. "
            f"Nu se include în VIES (D390)."
        )

    # ─── UNKNOWN — Manual review ────────────────────────────
    else:
        decision.treatment = VATTreatment.UNKNOWN
        decision.explanation = (
            "Țară furnizor necunoscută — verificare manuală necesară. "
            "Implicit aplicăm TVA standard RO 21%."
        )
        decision.vat_rate = VAT_RATE_STANDARD

    return decision


# ============================================================
#                    UTILITARE PUBLICE
# ============================================================

def is_intracom_supplier(vat_id: Optional[str], platforma: Optional[str] = None) -> bool:
    """Quick check: e furnizor intracomunitar (UE)?"""
    if vat_id:
        _, group = detect_country_from_vat_id(vat_id)
        return group == CountryGroup.EU

    if platforma:
        brand_result = detect_brand(platforma)
        if brand_result:
            _, country_code, _, _ = brand_result
            return country_code in EU_VAT_PREFIXES

    return False


def get_brand_database_size() -> dict:
    """Returnează statistica brand-urilor (pentru debugging)."""
    ro_count = sum(1 for v in BRAND_DATABASE.values() if v[0] == "RO")
    eu_count = sum(1 for v in BRAND_DATABASE.values() if v[0] in EU_VAT_PREFIXES)
    non_eu_count = sum(1 for v in BRAND_DATABASE.values() if v[0] in NON_EU_VAT_PREFIXES)
    return {
        "total": len(BRAND_DATABASE),
        "ro": ro_count,
        "eu": eu_count,
        "non_eu": non_eu_count,
    }
