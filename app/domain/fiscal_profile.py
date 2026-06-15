"""
FiscalProfile — Router Fiscal Central pentru Bot Contabil PFA.

Acesta e MOTORUL DE DECIZIE care, dat un user, răspunde la toate întrebările
fiscale: ce impozit, ce TVA, ce contribuții, ce declarații.

CONTEXT LEGAL (2026):
- Cod Fiscal Legea 227/2015 (republicat 2024)
- OUG 115/2023 — TVA standard 21% (din 01.01.2024)
- OUG nr. 31/2024 — modificări microîntreprinderi (1% / 3%)
- OPANAF 2541/2024 — D212 (Declarația Unică)
- Salariu minim brut 2026: 4.050 RON (estimat — verificare ANAF)

ARHITECTURĂ:
- FiscalProfile e o clasă "value object" — nu modifică nimic, doar răspunde
- Construită din profilul DB al user-ului (User.firma_forma_juridica etc.)
- Folosită de tax_engine, posting, registru, calendar fiscal — toți o întreabă

DECIZII FISCALE ACOPERITE:
1. income_tax_rate — cota impozit pe venit/profit
2. income_tax_base — baza de calcul (venit, profit, cifra afaceri, normă)
3. requires_cas / requires_cass — contribuții sociale obligatorii?
4. cas_threshold / cass_threshold — plafoane de declanșare
5. is_vat_payer — plătitor TVA?
6. vat_thresholds — plafoane înregistrare TVA
7. required_declarations — D212 / D300 / D301 / D390 / D100 / D101
8. accounting_method — sistem real / normă / micro
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict, Any
import logging

from app.domain.contributii import PARAMETRI_CONTRIBUTII, salariu_minim as _salariu_minim_an

logger = logging.getLogger(__name__)


# ============================================================
#                    CONSTANTE FISCALE 2026
# ============================================================

# Salariu minim brut 2026 pentru plafoane CAS/CASS — derivat din sursa unica
# app.domain.contributii (NU duplicat aici). Valoarea de la 1 ianuarie = 4050.
SALARIU_MINIM_BRUT_2026 = float(_salariu_minim_an(2026))

# Plafon TVA general (cifra afaceri RON, fără TVA)
# OG 22/2025, MO 806/29.08.2025, în vigoare 01.09.2025 (de la 300.000).
VAT_THRESHOLD_RON = 395_000.0

# Plafon TVA e-commerce intracomunitar (EUR)
VAT_THRESHOLD_EU_ECOMMERCE_EUR = 10_000.0  # OSS pentru e-commerce
VAT_THRESHOLD_EU_GENERAL_EUR = 100_000.0   # vechi

# Plafon SRL Microîntreprindere (cifra afaceri EUR)
SRL_MICRO_THRESHOLD_EUR = 500_000.0

# Plafoane CAS/CASS pentru PFA (multipli ai salar minim brut) — sursa unica:
# app.domain.contributii.PARAMETRI_CONTRIBUTII.
_P = PARAMETRI_CONTRIBUTII[2026]
CAS_THRESHOLD_MULTIPLIER = _P["cas_jos"]    # 12 → 48.600 RON/an
CASS_THRESHOLD_MULTIPLIER = _P["cass_jos"]  # 6  → 24.300 RON/an
CAS_MAX_BASE_MULTIPLIER = _P["cas_sus"]     # 24 → 97.200 RON/an (plafon maxim CAS)
CASS_MAX_BASE_MULTIPLIER = _P["cass_sus"]   # 60 → 243.000 RON/an (plafon maxim CASS)

# Cote impozit
IMPOZIT_VENIT_PFA_PCT = 10
IMPOZIT_PROFIT_SRL_PCT = 16
IMPOZIT_MICRO_1_PCT = 1   # micro cu salariat
IMPOZIT_MICRO_3_PCT = 3   # micro fără salariat

# Cote contribuții — sursa unica: app.domain.contributii.
CAS_PCT = _P["cota_cas"]    # 25
CASS_PCT = _P["cota_cass"]  # 10


# ============================================================
#                    ENUMURI
# ============================================================

class FormaJuridica(str, Enum):
    """Formele juridice acceptate."""
    PFA = "PFA"
    II = "II"
    IF = "IF"
    SRL_MICRO = "SRL_MICRO"
    SRL_NORMAL = "SRL_NORMAL"
    PROFESIE_LIBERALA = "PROFESIE_LIBERALA"


class RegimImpunere(str, Enum):
    """Regimuri de impunere fiscală."""
    SISTEM_REAL = "SISTEM_REAL"        # PFA cheltuieli reale, impozit pe venit net
    NORMA_VENIT = "NORMA_VENIT"        # PFA cu normă de venit fixă
    MICRO_1 = "MICRO_1"                # SRL Micro 1% (cu salariat)
    MICRO_3 = "MICRO_3"                # SRL Micro 3% (fără salariat)


class RegimTVA(str, Enum):
    """Regimuri TVA."""
    NEPLATITOR = "NEPLATITOR"
    PLATITOR_21 = "PLATITOR_21"
    SPECIAL_INTRACOM = "SPECIAL_INTRACOM"


class RegimNerezident(str, Enum):
    """
    Regim impozit nerezident pe comisionul platformelor de ridesharing.

    PER-PLATFORMĂ — Bolt și Uber au tratamente fiscale DIFERITE (convenții de
    evitare a dublei impuneri diferite). Un șofer cu ambele are regim distinct
    pe fiecare (ex. 2% pe Bolt ȘI 0% pe Uber în același D207).

    BOLT (Bolt Operations OÜ, Estonia) — Convenția RO-Estonia ARE Art. 12
    „Comisioane": cu certificatul de rezidență fiscală al Bolt → cota 2% (cota
    LEGALĂ a Convenției, NU o interpretare). Fără certificat → 16% (art. 224
    Cod Fiscal, stopaj la sursă). NU există 0% pentru Bolt.
      - BOLT_CU_CRF   → 2%  → D100 lunar + D207 anual
      - BOLT_FARA_CRF → 16% → D100 lunar + D207 anual

    UBER (Uber B.V., Olanda) — Convenția RO-Olanda NU are articol de comisioane
    → se aplică art. 7 „profituri": cu certificat → 0% (scutire), DOAR D207
    (fără D100); fără certificat → 16%. [Definite pentru extensibilitate;
    NU sunt activate în UI/validator încă — vezi VALID_REGIMURI_NEREZIDENT.]
      - UBER_CU_CRF   → 0%  → DOAR D207 (fără D100)
      - UBER_FARA_CRF → 16% → D100 + D207

    NU există o valoare implicită: absența (None) = neconfigurat. A presupune
    o cotă pentru toți era exact bug-ul fiscal #3.
    """
    BOLT_CU_CRF = "BOLT_CU_CRF"
    BOLT_FARA_CRF = "BOLT_FARA_CRF"
    # Extensie Uber — definite pentru engine (cota 0%/16%), NU în UI încă:
    UBER_CU_CRF = "UBER_CU_CRF"
    UBER_FARA_CRF = "UBER_FARA_CRF"


# Sursă UNICĂ a cotei nerezident (consumată și de bot, și de web). Cheie = enum.
# Engine-ul gestionează toate cotele (inclusiv 0% pentru Uber); ce se poate SETA
# din UI e restrâns separat de VALID_REGIMURI_NEREZIDENT (doar Bolt acum).
COTA_NEREZIDENT = {
    RegimNerezident.BOLT_CU_CRF: 0.02,
    RegimNerezident.BOLT_FARA_CRF: 0.16,
    RegimNerezident.UBER_CU_CRF: 0.0,
    RegimNerezident.UBER_FARA_CRF: 0.16,
}


class TaxBase(str, Enum):
    """Pe ce se calculează impozitul."""
    VENIT_NET = "VENIT_NET"            # PFA sistem real: venit - cheltuieli deductibile
    NORMA_VENIT = "NORMA_VENIT"        # PFA normă: sumă fixă din nomenclator
    PROFIT = "PROFIT"                  # SRL Normal: venituri - cheltuieli (16%)
    CIFRA_AFACERI = "CIFRA_AFACERI"    # SRL Micro: doar veniturile (1%/3%)


class Declaratie(str, Enum):
    """Declarații fiscale care pot fi necesare."""
    D212 = "D212"  # Declarația Unică — venituri PFA
    D100 = "D100"  # Declarație impozit profit SRL — anuală
    D101 = "D101"  # Declarație finalizare impozit profit
    D300 = "D300"  # Decont TVA (lunar/trimestrial pentru plătitori RO)
    D301 = "D301"  # Decont special TVA (reverse charge)
    D390 = "D390"  # Recapitulativ VIES (achiziții/livrări intracomunitare)
    D394 = "D394"  # Recapitulativ tranzacții interne (informativ)


# ============================================================
#                    FISCAL PROFILE — DATACLASS
# ============================================================

@dataclass
class FiscalProfile:
    """
    Profilul fiscal complet al unui user.

    Construit o singură dată per request din profilul DB.
    Răspunde la toate întrebările fiscale fără query-uri suplimentare.
    """

    # === Date sursă din User ===
    forma_juridica: FormaJuridica
    regim_impunere: RegimImpunere
    regim_tva: RegimTVA
    activity_code: str

    # Regim nerezident D100 — Optional: None = neconfigurat (NU presupunem rată)
    regim_nerezident: Optional[RegimNerezident] = None

    # === Date derivate (computed la __post_init__) ===
    income_tax_rate: int = 0           # 10% / 16% / 1% / 3%
    income_tax_base: TaxBase = TaxBase.VENIT_NET
    accounting_method: str = "real"    # real / norma / micro

    # === Contribuții sociale ===
    requires_cas: bool = False         # Pentru PFA, da; SRL nu
    requires_cass: bool = False
    cas_pct: int = CAS_PCT
    cass_pct: int = CASS_PCT
    cas_threshold_ron: float = 0.0
    cass_threshold_ron: float = 0.0

    # === TVA ===
    is_vat_payer: bool = False
    vat_standard_pct: int = 0          # 0 dacă neplătitor, 21 dacă plătitor

    # === Nerezident D100 (derivat din regim_nerezident) ===
    # None = neconfigurat → consumatorii afișează un prompt de configurare,
    # NU o cifră (vezi #3). 0.0 / 0.02 / 0.16 dacă e setat.
    cota_nerezident: Optional[float] = None

    def __post_init__(self):
        """Calculează atributele derivate din intrările date."""
        self._compute_income_tax()
        self._compute_contributions()
        self._compute_vat()
        self._compute_nerezident()

    # ========================================================
    #          DECIZII FISCALE — IMPOZIT VENIT
    # ========================================================

    def _compute_income_tax(self):
        """
        Calculează cota impozitului și baza de calcul.

        Reguli (Cod Fiscal 2026):
        - PFA / II / IF / Profesie liberală + Sistem Real → 10% × venit_net
        - PFA + Normă → 10% × normă (fixă din nomenclator)
        - SRL Micro 1% → 1% × cifra_afaceri (cu salariat)
        - SRL Micro 3% → 3% × cifra_afaceri (fără salariat)
        - SRL Normal → 16% × profit
        """
        f = self.forma_juridica
        r = self.regim_impunere

        # PFA, II, IF, Profesie liberală
        if f in (FormaJuridica.PFA, FormaJuridica.II, FormaJuridica.IF,
                 FormaJuridica.PROFESIE_LIBERALA):
            if r == RegimImpunere.NORMA_VENIT:
                self.income_tax_rate = IMPOZIT_VENIT_PFA_PCT
                self.income_tax_base = TaxBase.NORMA_VENIT
                self.accounting_method = "norma"
            else:  # SISTEM_REAL (default)
                self.income_tax_rate = IMPOZIT_VENIT_PFA_PCT
                self.income_tax_base = TaxBase.VENIT_NET
                self.accounting_method = "real"

        # SRL Microîntreprindere
        elif f == FormaJuridica.SRL_MICRO:
            if r == RegimImpunere.MICRO_1:
                self.income_tax_rate = IMPOZIT_MICRO_1_PCT
            elif r == RegimImpunere.MICRO_3:
                self.income_tax_rate = IMPOZIT_MICRO_3_PCT
            else:
                # Fallback: SRL Micro fără regim specificat → MICRO_3 (mai sigur)
                self.income_tax_rate = IMPOZIT_MICRO_3_PCT
            self.income_tax_base = TaxBase.CIFRA_AFACERI
            self.accounting_method = "micro"

        # SRL Normal (impozit pe profit 16%)
        elif f == FormaJuridica.SRL_NORMAL:
            self.income_tax_rate = IMPOZIT_PROFIT_SRL_PCT
            self.income_tax_base = TaxBase.PROFIT
            self.accounting_method = "real"

        else:
            logger.warning(f"Forma juridica necunoscuta: {f} — folosesc default PFA")
            self.income_tax_rate = IMPOZIT_VENIT_PFA_PCT
            self.income_tax_base = TaxBase.VENIT_NET
            self.accounting_method = "real"

    # ========================================================
    #          DECIZII FISCALE — CONTRIBUȚII (CAS/CASS)
    # ========================================================

    def _compute_contributions(self):
        """
        Determină dacă user-ul plătește CAS/CASS și plafoanele.

        Reguli:
        - PFA / II / IF / Profesie liberală → DA, în funcție de venit
        - SRL (orice tip) → NU (administratorii plătesc ca salariați separat)
        """
        f = self.forma_juridica

        if f in (FormaJuridica.PFA, FormaJuridica.II, FormaJuridica.IF,
                 FormaJuridica.PROFESIE_LIBERALA):
            self.requires_cas = True
            self.requires_cass = True
            self.cas_threshold_ron = (
                CAS_THRESHOLD_MULTIPLIER * SALARIU_MINIM_BRUT_2026
            )
            self.cass_threshold_ron = (
                CASS_THRESHOLD_MULTIPLIER * SALARIU_MINIM_BRUT_2026
            )
        else:
            # SRL — fără CAS/CASS la nivel de firmă
            self.requires_cas = False
            self.requires_cass = False

    # ========================================================
    #                  DECIZII FISCALE — TVA
    # ========================================================

    def _compute_vat(self):
        """
        Determină dacă user-ul e plătitor TVA și cota standard.

        Reguli:
        - PLATITOR_21 / SPECIAL_INTRACOM → plătitor TVA, cota 21%
        - NEPLATITOR → nu colectează TVA pe vânzări proprii
          (DAR poate avea reverse charge pe achiziții intracomunitare!)
        """
        r = self.regim_tva

        if r in (RegimTVA.PLATITOR_21, RegimTVA.SPECIAL_INTRACOM):
            self.is_vat_payer = True
            self.vat_standard_pct = 21
        else:
            self.is_vat_payer = False
            self.vat_standard_pct = 0

    # ========================================================
    #          DECIZII FISCALE — IMPOZIT NEREZIDENT (D100)
    # ========================================================

    def _compute_nerezident(self):
        """
        Derivă cota impozitului nerezident din regim_nerezident.

        IMPORTANT: NU există fallback la o rată. Dacă regim_nerezident e None
        (neconfigurat) → cota_nerezident rămâne None, iar consumatorii (banner,
        web, fisa D100) afișează un prompt de configurare în loc de o cifră
        posibil greșită (date la ANAF — vezi fiscal #3).
        """
        if self.regim_nerezident is None:
            self.cota_nerezident = None
        else:
            self.cota_nerezident = COTA_NEREZIDENT.get(self.regim_nerezident)

    # ========================================================
    #          API PUBLICĂ — Întrebări care primesc răspuns
    # ========================================================

    def get_required_declarations(
        self, has_intracom_invoice: bool = False
    ) -> List[Declaratie]:
        """
        Returnează lista de declarații fiscale necesare pentru acest profil.

        Args:
            has_intracom_invoice: True dacă user are facturi intracomunitare
                                  (declanșează D301 + D390 chiar pentru neplătitori TVA)
        """
        declarations = []
        f = self.forma_juridica

        # Declarații pe forma juridică
        if f in (FormaJuridica.PFA, FormaJuridica.II, FormaJuridica.IF,
                 FormaJuridica.PROFESIE_LIBERALA):
            declarations.append(Declaratie.D212)  # Declarația Unică

        elif f == FormaJuridica.SRL_NORMAL:
            declarations.append(Declaratie.D101)  # Declarație impozit profit

        elif f == FormaJuridica.SRL_MICRO:
            declarations.append(Declaratie.D100)  # Declarație impozit micro

        # Declarații TVA
        if self.is_vat_payer:
            declarations.append(Declaratie.D300)  # Decont TVA standard

        # Reverse charge — necesar și pentru neplătitori dacă au facturi UE
        if has_intracom_invoice:
            declarations.append(Declaratie.D301)  # Decont special TVA
            declarations.append(Declaratie.D390)  # Recapitulativ VIES

        return declarations

    def vat_threshold_status(self, total_income_ron: float) -> Dict[str, Any]:
        """
        Verifică statusul față de plafoanele TVA.

        Returnează dict cu:
        - status: "OK" / "APROAPE_PLAFON" / "DEPASIT_PLAFON"
        - threshold_ron: plafonul aplicabil
        - utilized_pct: cât % din plafon a fost folosit
        - message: explicație umană
        """
        threshold = VAT_THRESHOLD_RON

        if self.is_vat_payer:
            # Deja plătitor — nu mai contează plafonul
            return {
                "status": "OK",
                "threshold_ron": None,
                "utilized_pct": None,
                "message": "Plătitor TVA — fără plafon de monitorizat",
                "is_payer": True,
            }

        utilized_pct = (total_income_ron / threshold) * 100 if threshold else 0

        if total_income_ron >= threshold:
            status = "DEPASIT_PLAFON"
            message = (
                f"⚠️ ATENȚIE — ai depășit plafonul TVA "
                f"({total_income_ron:.0f} / {threshold:.0f} RON). "
                f"Trebuie să te înregistrezi ca plătitor TVA în 10 zile!"
            )
        elif utilized_pct >= 80:
            status = "APROAPE_PLAFON"
            message = (
                f"🟡 Aproape de plafon TVA: "
                f"{utilized_pct:.0f}% folosit "
                f"({total_income_ron:.0f} / {threshold:.0f} RON)"
            )
        else:
            status = "OK"
            message = (
                f"✅ Sub plafon TVA: "
                f"{utilized_pct:.0f}% folosit "
                f"({total_income_ron:.0f} / {threshold:.0f} RON)"
            )

        return {
            "status": status,
            "threshold_ron": threshold,
            "utilized_pct": utilized_pct,
            "message": message,
            "is_payer": False,
        }

    def srl_micro_threshold_status(
        self, total_income_eur: float
    ) -> Optional[Dict[str, Any]]:
        """
        Verifică plafonul SRL Micro (500.000 EUR cifra afaceri).
        Returnează None dacă nu e SRL Micro.
        """
        if self.forma_juridica != FormaJuridica.SRL_MICRO:
            return None

        threshold = SRL_MICRO_THRESHOLD_EUR
        utilized_pct = (total_income_eur / threshold) * 100 if threshold else 0

        if total_income_eur >= threshold:
            return {
                "status": "DEPASIT_MICRO",
                "message": (
                    f"⚠️ Ai depășit plafonul de microîntreprindere "
                    f"({threshold:.0f} EUR). Trebuie să treci la impozit pe "
                    f"profit (16%) începând cu trimestrul următor."
                ),
            }
        elif utilized_pct >= 80:
            return {
                "status": "APROAPE_MICRO",
                "message": (
                    f"🟡 Aproape de plafonul micro: {utilized_pct:.0f}% "
                    f"({total_income_eur:.0f} / {threshold:.0f} EUR)"
                ),
            }

        return {
            "status": "OK",
            "message": f"✅ Sub plafon micro: {utilized_pct:.0f}%",
        }

    def to_summary(self) -> Dict[str, Any]:
        """Returnează un sumar pentru afișare/debug."""
        return {
            "forma_juridica": self.forma_juridica.value,
            "regim_impunere": self.regim_impunere.value,
            "regim_tva": self.regim_tva.value,
            "activity_code": self.activity_code,
            "income_tax_rate": self.income_tax_rate,
            "income_tax_base": self.income_tax_base.value,
            "accounting_method": self.accounting_method,
            "requires_cas": self.requires_cas,
            "requires_cass": self.requires_cass,
            "cas_threshold_ron": self.cas_threshold_ron,
            "cass_threshold_ron": self.cass_threshold_ron,
            "is_vat_payer": self.is_vat_payer,
            "vat_standard_pct": self.vat_standard_pct,
            "regim_nerezident": (
                self.regim_nerezident.value if self.regim_nerezident else None
            ),
            "cota_nerezident": self.cota_nerezident,
        }


# ============================================================
#                       FACTORY
# ============================================================

def from_user_dict(profile_dict: Optional[Dict[str, Any]]) -> FiscalProfile:
    """
    Construiește un FiscalProfile dintr-un dict de profil DB
    (rezultatul lui users_repo.get_profile_dict()).

    Aplică defaults SIGURI dacă lipsesc câmpuri:
    - forma_juridica default = PFA (cel mai comun)
    - regim_impunere default = SISTEM_REAL
    - regim_tva default = NEPLATITOR (mai sigur — nu colectăm TVA fără confirmare)
    """
    profile_dict = profile_dict or {}

    # Forma juridică
    forma_str = profile_dict.get("firma_forma_juridica") or "PFA"
    try:
        forma = FormaJuridica(forma_str)
    except ValueError:
        logger.warning(f"Forma juridica invalida '{forma_str}' — fallback PFA")
        forma = FormaJuridica.PFA

    # Regim impunere
    regim_imp_str = profile_dict.get("regim_impunere") or "SISTEM_REAL"
    try:
        regim_impunere = RegimImpunere(regim_imp_str)
    except ValueError:
        logger.warning(
            f"Regim impunere invalid '{regim_imp_str}' — fallback SISTEM_REAL"
        )
        regim_impunere = RegimImpunere.SISTEM_REAL

    # Regim TVA
    regim_tva_str = profile_dict.get("regim_tva") or "NEPLATITOR"
    try:
        regim_tva = RegimTVA(regim_tva_str)
    except ValueError:
        logger.warning(
            f"Regim TVA invalid '{regim_tva_str}' — fallback NEPLATITOR"
        )
        regim_tva = RegimTVA.NEPLATITOR

    # Activity code (string, nu enum)
    activity_code = profile_dict.get("activity_code") or "generic"

    # Regim nerezident — FĂRĂ fallback la o rată. Absent/invalid → None
    # (neconfigurat), NU o cotă presupusă. Asta e miezul fixului #3.
    regim_nerez_str = profile_dict.get("regim_nerezident")
    regim_nerezident = None
    if regim_nerez_str:
        try:
            regim_nerezident = RegimNerezident(regim_nerez_str)
        except ValueError:
            logger.warning(
                f"Regim nerezident invalid '{regim_nerez_str}' — None "
                f"(neconfigurat, FĂRĂ rată presupusă)"
            )
            regim_nerezident = None

    return FiscalProfile(
        forma_juridica=forma,
        regim_impunere=regim_impunere,
        regim_tva=regim_tva,
        activity_code=activity_code,
        regim_nerezident=regim_nerezident,
    )


def from_user_id(session, user_id: int) -> FiscalProfile:
    """
    Construiește un FiscalProfile direct din DB pentru un user_id.
    Convenience function care apelează users_repo + from_user_dict.
    """
    from app.repositories import users as users_repo
    profile_dict = users_repo.get_profile_dict(session, user_id)
    return from_user_dict(profile_dict)
