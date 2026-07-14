"""
Clasa abstractă pentru activități și tipuri de bază.

Fiecare activitate concretă moștenește BaseActivity și definește:
  - code, name, caen_codes
  - expense_categories (lista de ExpenseCategory)
  - vat_treatments per categorie
  - deductibility_rules per categorie
  - hint pentru AI extraction
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Tuple


class VATTreatment(str, Enum):
    """Tratamentul TVA pentru o tranzacție."""
    NA = "NA"                              # Nu se aplică (PFA neplătitor)
    STANDARD_21 = "STANDARD_21"            # TVA standard 21% (după 01.08.2025)
    STANDARD_19 = "STANDARD_19"            # TVA standard 19% (înainte de 01.08.2025)
    REDUCED_9 = "REDUCED_9"                # TVA redus 9% (alimente, medicamente)
    REDUCED_5 = "REDUCED_5"                # TVA redus 5% (cărți, locuințe sociale)
    REVERSE_CHARGE = "REVERSE_CHARGE"      # Taxare inversă (intracom: Bolt, Uber, AWS)
    EXEMPT_ART_292 = "EXEMPT_ART_292"      # Scutit fără drept de deducere (educație, medical)
    EXEMPT_ART_294 = "EXEMPT_ART_294"      # Scutit cu drept de deducere (export)


class DeductibilityRule(str, Enum):
    """Cum se aplică deductibilitatea pentru o cheltuială."""
    FULL = "FULL"              # 100% deductibil
    HALF = "HALF"              # 50% deductibil (auto mixt, protocol)
    LIMITED = "LIMITED"        # Plafonat (ex: 4.5 RON/zi diurnă)
    NON_DEDUCTIBLE = "NON_DEDUCTIBLE"  # Nedeductibil
    CUSTOM = "CUSTOM"          # Procent custom (definit în percent)


@dataclass
class ExpenseCategory:
    """
    O categorie de cheltuială specifică unei activități.

    Ex: pentru Ridesharing — "combustibil_auto", "comision_platforma"
    Ex: pentru IT — "servicii_cloud", "hardware", "licente_software"
    """
    code: str                   # ID intern (ex: "fuel", "platform_commission")
    label: str                  # Nume afișat user (ex: "Combustibil auto")
    icon: str = "📌"            # Emoji pentru UI
    keywords: List[str] = field(default_factory=list)
    # Cuvinte cheie pentru AI/regex matching (lukoil, omv, mol → fuel)

    # Deductibilitate
    deductibility: DeductibilityRule = DeductibilityRule.FULL
    deductibility_percent: int = 100  # Folosit dacă deductibility=CUSTOM
    deductibility_note: str = ""      # Explicație pentru user
    # Cheltuială auto pe VEHICUL cu utilizare mixtă (art. 25 alin. (3) lit. l)):
    # 50% când mașina e mixtă (personal+business), 100% dacă e exclusiv business
    # justificat prin foaie de parcurs. Flag DESCRIPTIV — marchează categoriile a
    # căror deductibilitate depinde de regimul de utilizare al vehiculului (NU
    # telefonul, care e 50% din alt motiv). Momentan nimeni nu-l citește (pur
    # aditiv); pregătește regimul auto configurabil MIXT/EXCLUSIV.
    is_auto_mixt: bool = False
    # Deductibilitatea acestei categorii auto depinde de TIPUL DE DEȚINERE al
    # vehiculului (proprietate/leasing vs comodat), NU doar de regimul de
    # utilizare. Marcat pe RCA/CASCO (car_insurance): pe comodat asigurarea e
    # nedeductibilă (0%), pe proprietate 50-100% — logică separată (felia 5B).
    # Aprinderea EXCLUSIV→100 din felia 5A SARE peste categoriile cu acest flag
    # (rămân pe procentul de bază până la 5B).
    depinde_tip_detinere: bool = False

    # TVA
    default_vat_treatment: VATTreatment = VATTreatment.STANDARD_21
    vat_note: str = ""

    # Tip tranzacție (pentru clasificare automată)
    is_income: bool = False  # True = venit, False = cheltuială

    # Cont contabil (pentru export contabil viitor)
    accounting_code: str = ""   # ex: "6022" pentru combustibil

    def get_effective_deductibility(self) -> int:
        """Returnează procentul efectiv de deductibilitate (0-100)."""
        if self.deductibility == DeductibilityRule.FULL:
            return 100
        if self.deductibility == DeductibilityRule.HALF:
            return 50
        if self.deductibility == DeductibilityRule.NON_DEDUCTIBLE:
            return 0
        if self.deductibility == DeductibilityRule.CUSTOM:
            return max(0, min(100, self.deductibility_percent))
        if self.deductibility == DeductibilityRule.LIMITED:
            return 100  # Plafonarea se face în altă parte
        return 100


@dataclass
class IncomeCategory:
    """O categorie de venit specifică unei activități."""
    code: str
    label: str
    icon: str = "💰"
    keywords: List[str] = field(default_factory=list)
    default_vat_treatment: VATTreatment = VATTreatment.STANDARD_21
    accounting_code: str = ""   # ex: "704" pentru servicii prestate


# ============================================================
#                    BASE ACTIVITY
# ============================================================

class BaseActivity:
    """
    Clasă de bază pentru toate activitățile.

    Subclasele trebuie să suprascrie:
      - code (str): identificator intern
      - name (str): nume afișat
      - caen_codes (List[str]): coduri CAEN asociate
      - expense_categories (List[ExpenseCategory])
      - income_categories (List[IncomeCategory])

    Pot suprascrie opțional:
      - ai_prompt_hints() pentru a personaliza extracția AI
      - get_fiscal_obligations() pentru calendar fiscal personalizat
    """

    # === Atribute ce TREBUIE suprascrise ===
    code: str = ""
    name: str = ""
    caen_codes: List[str] = []
    description: str = ""
    icon: str = "📌"

    # === Categorii (suprascrise în subclase) ===
    expense_categories: List[ExpenseCategory] = []
    income_categories: List[IncomeCategory] = []

    # ========================================================
    #                    METHODS
    # ========================================================

    @classmethod
    def get_expense_category(cls, code: str) -> Optional[ExpenseCategory]:
        """Returnează categoria de cheltuieli după cod."""
        for cat in cls.expense_categories:
            if cat.code == code:
                return cat
        return None

    @classmethod
    def get_income_category(cls, code: str) -> Optional[IncomeCategory]:
        """Returnează categoria de venituri după cod."""
        for cat in cls.income_categories:
            if cat.code == code:
                return cat
        return None

    @classmethod
    def get_all_expense_codes(cls) -> List[str]:
        """Listă cu toate codurile de cheltuieli."""
        return [c.code for c in cls.expense_categories]

    @classmethod
    def get_all_income_codes(cls) -> List[str]:
        """Listă cu toate codurile de venituri."""
        return [c.code for c in cls.income_categories]

    # ========================================================
    #          DETECȚIE SEMANTICĂ (algoritm cu scor)
    # ========================================================

    @classmethod
    def _score_keyword_match(cls, keyword: str, text: str) -> int:
        """
        Calculează scorul unui keyword pentru un text.

        Reguli:
        - Keyword nu apare în text → 0
        - Keyword cu spații (compus, ex: "ulei motor", "schimb ulei") → scor mare (10 + lungime)
        - Keyword simplu (ex: "lukoil", "ulei") → scor mediu (lungime caracterelor)
        - Match pe cuvânt întreg (delimitat de spații/punctuație) → bonus +5

        Asta înseamnă:
        - "ulei motor" în "Lukoil ulei motor 5W30" → scor mare (12)
        - "lukoil" în același text → scor mai mic (6)
        - Câștigă "ulei motor" → categoria car_service ✅
        """
        kw_lower = keyword.lower().strip()
        text_lower = text.lower()

        if not kw_lower or kw_lower not in text_lower:
            return 0

        # Score de bază = lungimea keyword-ului
        score = len(kw_lower)

        # BONUS 1: keyword compus (cu spațiu) — mult mai specific
        if " " in kw_lower:
            score += 10

        # BONUS 2: match pe cuvânt întreg
        # Verificăm că nu e o substring accidentală (ex: "ulei" în "uleios")
        idx = text_lower.find(kw_lower)
        before_ok = (idx == 0) or not text_lower[idx - 1].isalnum()
        end_idx = idx + len(kw_lower)
        after_ok = (end_idx >= len(text_lower)) or not text_lower[end_idx].isalnum()
        if before_ok and after_ok:
            score += 5

        return score

    @classmethod
    def detect_expense_category(
        cls, platforma: Optional[str], detalii: Optional[str]
    ) -> Tuple[Optional[ExpenseCategory], int]:
        """
        Detectează categoria de cheltuieli pe baza textului furnizor + detalii.

        Algoritm:
        1. Pentru fiecare categorie, calculează scorul cumulat al keyword-urilor match-uite
        2. Câștigă categoria cu cel mai mare scor
        3. Returnează (categorie, scor_total) sau (None, 0) dacă niciun match

        Exemplu: bon "Lukoil - ulei auto 52.99 lei"
        - fuel: "lukoil"=6 → total 6 (sau 11 cu word-bound bonus)
        - car_service: "ulei"=4 + "ulei auto"=14 → total 18+ → CÂȘTIGĂ ✅
        """
        text = f"{platforma or ''} {detalii or ''}".strip()
        if not text:
            return None, 0

        best_cat = None
        best_score = 0

        for cat in cls.expense_categories:
            if not cat.keywords:
                continue
            cat_score = 0
            for kw in cat.keywords:
                cat_score += cls._score_keyword_match(kw, text)
            if cat_score > best_score:
                best_score = cat_score
                best_cat = cat

        return best_cat, best_score

    @classmethod
    def categorize_by_keywords(cls, text: str) -> Optional[ExpenseCategory]:
        """
        DEPRECATED — folosit pentru compatibilitate.
        Folosește detect_expense_category() pentru detecție corectă.
        """
        cat, _ = cls.detect_expense_category(None, text)
        return cat

    @classmethod
    def get_deductibility_for_category(cls, category_code: str) -> int:
        """Returnează procentul de deductibilitate pentru o categorie."""
        cat = cls.get_expense_category(category_code)
        if cat is None:
            return 100  # Default: 100%
        return cat.get_effective_deductibility()

    # Alias-uri pentru compatibilitate
    @classmethod
    def get_deductibility_pct(cls, category_code: str) -> int:
        return cls.get_deductibility_for_category(category_code)

    @classmethod
    def get_vat_treatment_for_category(cls, category_code: str) -> VATTreatment:
        """Returnează tratamentul TVA default pentru o categorie."""
        cat = cls.get_expense_category(category_code)
        if cat is None:
            cat = cls.get_income_category(category_code)
        if cat is None:
            return VATTreatment.STANDARD_21
        return cat.default_vat_treatment

    @classmethod
    def ai_prompt_hints(cls) -> str:
        """
        Returnează hint-uri specifice activității pentru promptul AI.
        Folosit la extracția documentelor.

        Subclase pot suprascrie cu hint-uri specifice:
          - Pentru Ridesharing: "Combustibil = lukoil/omv/mol/petrom"
          - Pentru IT: "Servicii cloud = AWS/Google/Microsoft/DigitalOcean"
        """
        if not cls.expense_categories:
            return ""

        lines = [f"\n## Categorii specifice {cls.name}:\n"]
        for cat in cls.expense_categories:
            kw_str = ", ".join(cat.keywords[:5]) if cat.keywords else ""
            line = f"- *{cat.label}* (code: `{cat.code}`)"
            if kw_str:
                line += f" — keywords: {kw_str}"
            lines.append(line)
        return "\n".join(lines)

    @classmethod
    def get_summary(cls) -> Dict:
        """Returnează un sumar al activității (pentru UI/dashboard)."""
        return {
            "code": cls.code,
            "name": cls.name,
            "icon": cls.icon,
            "description": cls.description,
            "caen_codes": cls.caen_codes,
            "expense_count": len(cls.expense_categories),
            "income_count": len(cls.income_categories),
        }
