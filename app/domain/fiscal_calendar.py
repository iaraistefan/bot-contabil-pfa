"""
Calendar Fiscal Personalizat — motor inteligent de obligații fiscale.

Lucrează cu FiscalProfile (forma juridică + activitate) și ANAF IBAN Database
pentru a furniza calendar fiscal personalizat pentru orice user.

ARHITECTURĂ:
- Definește toate obligațiile fiscale cunoscute (D100, D300, D301, D390,
  D207, D212, D101, D700)
- Filtrează automat per formă juridică + activitate
- Calculează termene + sume + IBAN-uri corecte
- Integrat cu anaf_iban_db (Pas 11.1)
- Backward compatible cu API-ul vechi (get_monthly_alerts, format_fiscal_message)

CHANGELOG:
- v1: Versiune inițială hardcoded pentru PFA Ridesharing
- v2 (16.05.2026, Pas 11.2):
  • CORECȚIE FISCALĂ: D100 nerezidenți 2% NU e reținut automat de Bolt,
    TREBUIE depus de PFA. Versiunea v1 era greșită.
  • Adăugat D100 poz. 634 (impozit nerezidenți comisioane)
  • Adăugat D207 (declarația informativă anuală, 28 februarie)
  • Adăugat D700 (înregistrare cod special TVA — o singură dată)
  • Profile-aware: lucrează cu FiscalProfile, suportă PFA/SRL Micro/Normal
  • Activity-aware: filtrare per activitate (ridesharing, ecommerce, etc.)
  • Integrare cu anaf_iban_db pentru IBAN corect + cod buget
  • Calcul automat suma de plată (21% × baza pentru D301, 2% pentru D100)
  • Backward compatible: API-ul vechi (get_monthly_alerts) încă funcționează
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

from app.integrations.anaf_iban_db import (
    TipObligatie,
    IbanCont,
    get_iban_for_obligation,
)
from app.domain.contributii import PARAMETRI_CONTRIBUTII, salariu_minim as _salariu_minim_an

logger = logging.getLogger(__name__)


# ============================================================
#                    CONSTANTE
# ============================================================

# CAS/CASS + salariu minim — sursa unica: app.domain.contributii.
SALARIU_MINIM_BRUT_2026 = _salariu_minim_an(2026)        # 4050 RON
COTA_IMPOZIT_PFA = 10                                     # %
COTA_CAS = PARAMETRI_CONTRIBUTII[2026]["cota_cas"]        # 25 %
COTA_CASS = PARAMETRI_CONTRIBUTII[2026]["cota_cass"]      # 10 %
COTA_IMPOZIT_PROFIT_SRL = 16    # %
COTA_TVA_STANDARD = 21          # %
COTA_RETINERE_NEREZIDENT_EE = 2 # %  CDI România-Estonia
COTA_RETINERE_NEREZIDENT_STD = 16  # %  fără tratat / fără certificat

LUNI_RO = {
    1: "Ianuarie", 2: "Februarie", 3: "Martie", 4: "Aprilie",
    5: "Mai", 6: "Iunie", 7: "Iulie", 8: "August",
    9: "Septembrie", 10: "Octombrie", 11: "Noiembrie", 12: "Decembrie"
}

LUNI_RO_UPPER = {k: v.upper() for k, v in LUNI_RO.items()}


# ============================================================
#                    ENUMS
# ============================================================

class FrecventaObligatie(str, Enum):
    """Cât de des trebuie depusă/plătită o obligație."""
    LUNARA = "LUNARA"               # până pe 25 a lunii următoare
    TRIMESTRIALA = "TRIMESTRIALA"   # până pe 25 a lunii după trimestru
    ANUALA = "ANUALA"               # data specifică
    UNICA = "UNICA"                 # o singură dată (ex: D700)


class StatusObligatie(str, Enum):
    """Status pentru o obligație (calculat din zile rămase)."""
    DEPASIT = "DEPASIT"           # > 0 zile depășite
    CRITIC = "CRITIC"             # ≤ 3 zile rămase
    AVERTISMENT = "AVERTISMENT"   # ≤ 7 zile rămase
    PROXIM = "PROXIM"             # ≤ 30 zile rămase
    DEPARTE = "DEPARTE"           # > 30 zile rămase


class UrgentaObligatie(str, Enum):
    """Importanță generală a obligației."""
    CRITICA = "CRITICA"     # penalități mari dacă nu se respectă
    INALTA = "INALTA"
    MEDIE = "MEDIE"
    INFO = "INFO"


# ============================================================
#                    DATACLASSES
# ============================================================

@dataclass
class DefinitieObligatie:
    """
    Definiția statică a unei obligații fiscale.

    NU conține termen sau sumă — acelea se calculează în context la cerere.
    """
    cod: str                                    # ex: "D100"
    nume: str                                   # ex: "Impozit nerezidenți"
    descriere: str
    tip_iban: Optional[TipObligatie]            # mapping în anaf_iban_db
    frecventa: FrecventaObligatie
    ziua_termenului: int                        # ziua din luna scadentă
    luna_anuala_termen: Optional[int] = None    # doar pt anuale (ex: 5 = mai)

    forme_juridice: List[str] = field(default_factory=list)
    activitati: List[str] = field(default_factory=lambda: ["*"])
    conditie_extra: Optional[str] = None        # text descriptiv

    urgenta_default: UrgentaObligatie = UrgentaObligatie.INALTA
    bonus_info: Optional[str] = None
    penalty_info: Optional[str] = None
    portal_anaf: str = "https://anaf.ro"
    nomenclator_anaf: Optional[str] = None      # ex: "634" pt D100 nerezidenți

    # Calcul sumă: callback opțional care primește baza și returnează suma
    formula_suma: Optional[str] = None          # text descriptiv


@dataclass
class ObligatieCalculate:
    """
    O obligație fiscală cu context calculat — termen + sumă + status.
    """
    definitie: DefinitieObligatie

    termen: date
    zile_ramase: int
    status: StatusObligatie

    suma_estimata: Optional[float] = None       # RON
    baza_calcul: Optional[float] = None         # baza din care s-a calculat
    iban_cont: Optional[IbanCont] = None        # IBAN-ul de plată

    perioada_an: Optional[int] = None
    perioada_luna: Optional[int] = None

    aplicabil_acum: bool = True                 # False dacă nu se aplică în context
    motiv_neaplicabil: Optional[str] = None

    def __str__(self) -> str:
        suma = f"{self.suma_estimata:.2f} RON" if self.suma_estimata else "—"
        return (
            f"{self.definitie.cod} ({self.definitie.nume}) → "
            f"termen {self.termen.strftime('%d.%m.%Y')} "
            f"({self.zile_ramase} zile) — {suma}"
        )


# ============================================================
#                BIBLIOTECA OBLIGAȚIILOR
# ============================================================

DEFINITII_OBLIGATII: Dict[str, DefinitieObligatie] = {

    # ─────────────────────────────────────────────────────────
    # D100 — Impozit pe veniturile nerezidenților (comisioane Bolt 2%)
    # ─────────────────────────────────────────────────────────
    "D100_634": DefinitieObligatie(
        cod="D100 poz. 634",
        nume="Impozit nerezidenți comisioane (2% Bolt)",
        descriere=(
            "Conform CDI România-Estonia (art. 12), comisioanele plătite "
            "către Bolt Operations OÜ (rezident estonian) se impozitează "
            "în România cu 2% (cu certificat de rezidență fiscală). "
            "TU ești obligat să reții și să virezi acest impozit la "
            "Trezorerie. NU îl reține Bolt automat."
        ),
        tip_iban=TipObligatie.D100_NEREZID_COMISIOANE,
        frecventa=FrecventaObligatie.LUNARA,
        ziua_termenului=25,
        forme_juridice=["PFA", "II", "IF", "SRL_MICRO", "SRL_NORMAL"],
        activitati=["ridesharing"],
        conditie_extra=(
            "Doar pentru lunile cu factură Bolt/Uber primită."
        ),
        urgenta_default=UrgentaObligatie.INALTA,
        nomenclator_anaf="634",
        formula_suma="2% × baza_factura_Bolt_fara_TVA",
        penalty_info=(
            "Nedepunerea / neplata atrage majorări de întârziere "
            "0.02%/zi + penalități."
        ),
        portal_anaf="https://www.anaf.ro/anaf/internet/ANAF/servicii_online/declaratii_electronice/",
    ),

    # ─────────────────────────────────────────────────────────
    # D207 — Declarația INFORMATIVĂ anuală (impozite reținute pentru nerezidenți)
    # ─────────────────────────────────────────────────────────
    "D207": DefinitieObligatie(
        cod="D207",
        nume="Declarația informativă privind impozitul reținut la sursă",
        descriere=(
            "Centralizează toate impozitele reținute la sursă în anul precedent "
            "pentru veniturile plătite nerezidenților (Bolt etc.). "
            "Se depune o dată pe an, până pe 28 februarie."
        ),
        tip_iban=None,  # nu se plătește — e doar declarativă
        frecventa=FrecventaObligatie.ANUALA,
        ziua_termenului=28,
        luna_anuala_termen=2,
        forme_juridice=["PFA", "II", "IF", "SRL_MICRO", "SRL_NORMAL"],
        activitati=["ridesharing"],
        conditie_extra=(
            "Doar dacă ai depus D100 pentru nerezidenți în anul precedent."
        ),
        urgenta_default=UrgentaObligatie.INALTA,
        formula_suma="N/A — doar declarație informativă",
    ),

    # ─────────────────────────────────────────────────────────
    # D301 — Decont special TVA (achiziții intracomunitare servicii)
    # ─────────────────────────────────────────────────────────
    "D301": DefinitieObligatie(
        cod="D301",
        nume="Decont special TVA (achiziții intracomunitare)",
        descriere=(
            "Pentru PFA/SRL neplătitor de TVA cu cod special TVA (D700). "
            "Declari TVA-ul datorat pe achizițiile intracomunitare de servicii "
            "(factură comision Bolt din Estonia). Plată: 21% × baza factură."
        ),
        tip_iban=TipObligatie.D301_TVA_INTRACOM,
        frecventa=FrecventaObligatie.LUNARA,
        ziua_termenului=25,
        forme_juridice=[
            "PFA_neplatitor_TVA_cu_cod_special",
            "SRL_neplatitor_TVA_cu_cod_special",
        ],
        activitati=["ridesharing", "ecommerce"],
        conditie_extra="Doar pentru lunile cu factură intracomunitară primită.",
        urgenta_default=UrgentaObligatie.INALTA,
        formula_suma="21% × baza_factura_intracom",
        penalty_info=(
            "Nedepunerea atrage amendă 1.000-5.000 RON + majorări 0.02%/zi pe TVA."
        ),
        portal_anaf="https://anaf.ro/anaf/internet/ANAF/servicii_online/declaratii_electronice/",
    ),

    # ─────────────────────────────────────────────────────────
    # D390 — Declarația recapitulativă VIES (achiziții/livrări intracom)
    # ─────────────────────────────────────────────────────────
    "D390": DefinitieObligatie(
        cod="D390",
        nume="Declarația recapitulativă VIES",
        descriere=(
            "Centralizează achizițiile intracomunitare de servicii (Bolt EE). "
            "Se depune odată cu D301, pentru aceleași luni."
        ),
        tip_iban=None,  # doar declarativă
        frecventa=FrecventaObligatie.LUNARA,
        ziua_termenului=25,
        forme_juridice=[
            "PFA_neplatitor_TVA_cu_cod_special",
            "PFA_platitor_TVA",
            "SRL_neplatitor_TVA_cu_cod_special",
            "SRL_platitor_TVA",
        ],
        activitati=["ridesharing", "ecommerce"],
        conditie_extra="Doar pentru lunile cu achiziție/livrare intracom.",
        urgenta_default=UrgentaObligatie.INALTA,
        formula_suma="N/A — declarație informativă",
    ),

    # ─────────────────────────────────────────────────────────
    # D300 — Decont TVA (pentru plătitori TVA)
    # ─────────────────────────────────────────────────────────
    "D300": DefinitieObligatie(
        cod="D300",
        nume="Decont TVA (lunar/trimestrial)",
        descriere=(
            "Pentru plătitori TVA. Declari TVA colectat - TVA deductibil. "
            "Plată: diferența pozitivă către ANAF."
        ),
        tip_iban=TipObligatie.D300_TVA_DECONT,
        frecventa=FrecventaObligatie.LUNARA,
        ziua_termenului=25,
        forme_juridice=["PFA_platitor_TVA", "SRL_platitor_TVA"],
        activitati=["*"],
        urgenta_default=UrgentaObligatie.INALTA,
        formula_suma="TVA_colectat - TVA_deductibil",
    ),

    # ─────────────────────────────────────────────────────────
    # D212 — Declarația Unică (PFA anual)
    # ─────────────────────────────────────────────────────────
    "D212": DefinitieObligatie(
        cod="D212",
        nume="Declarația Unică (impozit + CAS + CASS)",
        descriere=(
            "Pentru PFA sistem real. Declari veniturile și cheltuielile "
            "din anul anterior. Calcul automat: impozit venit (10%), "
            "CAS (25%), CASS (10%). Plată în cont unic 5504 pe CNP."
        ),
        tip_iban=TipObligatie.D212_CONT_UNIC_PF,
        frecventa=FrecventaObligatie.ANUALA,
        ziua_termenului=25,
        luna_anuala_termen=5,
        forme_juridice=["PFA", "II", "IF"],
        activitati=["*"],
        urgenta_default=UrgentaObligatie.CRITICA,
        bonus_info=(
            "Achiți INTEGRAL (impozit + CAS + CASS) până pe 15 aprilie → "
            "bonificație 3% DOAR din impozitul pe venit (CAS și CASS nu se reduc)."
        ),
        formula_suma="10% × venit_net + CAS(dacă > 12 sal.min.) + CASS(plafon)",
        portal_anaf="https://anaf.ro/duf",
    ),

    # ─────────────────────────────────────────────────────────
    # D101 — Impozit pe profit SRL Normal
    # ─────────────────────────────────────────────────────────
    "D101": DefinitieObligatie(
        cod="D101",
        nume="Impozit pe profit (SRL Normal)",
        descriere=(
            "Impozit 16% pe profitul SRL Normal. Termene: trimestrial "
            "(25 a lunii după trimestru) + declarație anuală (25 martie)."
        ),
        tip_iban=TipObligatie.D101_IMPOZIT_PROFIT,
        frecventa=FrecventaObligatie.TRIMESTRIALA,
        ziua_termenului=25,
        forme_juridice=["SRL_NORMAL"],
        activitati=["*"],
        urgenta_default=UrgentaObligatie.CRITICA,
        formula_suma="16% × profit_fiscal",
    ),

    # ─────────────────────────────────────────────────────────
    # D700 — Înregistrare cod special TVA (o singură dată)
    # ─────────────────────────────────────────────────────────
    "D700": DefinitieObligatie(
        cod="D700",
        nume="Înregistrare cod special TVA intracomunitar",
        descriere=(
            "Obligatorie pentru PFA/SRL neplătitor TVA care fac achiziții "
            "intracomunitare de servicii (Bolt EE). Se depune O SINGURĂ DATĂ, "
            "înainte de prima factură intracom. Fără D700 nu poți depune D301."
        ),
        tip_iban=None,  # doar declarativă, fără plată
        frecventa=FrecventaObligatie.UNICA,
        ziua_termenului=1,  # cât mai curând
        forme_juridice=["PFA", "SRL_MICRO", "SRL_NORMAL"],
        activitati=["ridesharing", "ecommerce"],
        urgenta_default=UrgentaObligatie.INALTA,
        formula_suma="N/A — doar înregistrare",
    ),
}


# ============================================================
#              CALCUL OBLIGAȚII PER CONTEXT
# ============================================================

def _compute_status(zile_ramase: int) -> StatusObligatie:
    """Determină status-ul în funcție de zilele rămase."""
    if zile_ramase < 0:
        return StatusObligatie.DEPASIT
    if zile_ramase <= 3:
        return StatusObligatie.CRITIC
    if zile_ramase <= 7:
        return StatusObligatie.AVERTISMENT
    if zile_ramase <= 30:
        return StatusObligatie.PROXIM
    return StatusObligatie.DEPARTE


def _compute_termen_lunar(year: int, month: int, ziua: int) -> date:
    """Termenul pentru o obligație LUNARĂ: ziua a lunii URMĂTOARE."""
    if month == 12:
        return date(year + 1, 1, ziua)
    return date(year, month + 1, ziua)


def _compute_termen_anual(
    year: int, luna_termen: int, ziua: int
) -> date:
    """Termenul pentru o obligație ANUALĂ."""
    return date(year, luna_termen, ziua)


def _compute_termen_trimestrial(
    year: int, month: int, ziua: int
) -> date:
    """Termenul pentru o obligație TRIMESTRIALĂ.

    Trimestre fiscale:
    - Q1 (ian-mar) → termen 25 apr
    - Q2 (apr-iun) → termen 25 iul
    - Q3 (iul-sep) → termen 25 oct
    - Q4 (oct-dec) → termen 25 ian an următor
    """
    if month <= 3:
        return date(year, 4, ziua)
    if month <= 6:
        return date(year, 7, ziua)
    if month <= 9:
        return date(year, 10, ziua)
    if month <= 12:
        return date(year + 1, 1, ziua)
    return date(year + 1, 1, ziua)


def _matches_forma_juridica(
    user_fj: str,
    is_vat_payer: bool,
    has_cod_special_tva: bool,
    valid_fj_list: List[str],
) -> bool:
    """
    Matching strict pentru forma juridică, cu suport pentru variante specifice.

    Reguli:
    - Match EXACT pe forma simplă (ex: "PFA" == "PFA")
    - Match pe varianta "_platitor_TVA" doar dacă user e plătitor TVA
    - Match pe varianta "_neplatitor_TVA_cu_cod_special" doar dacă user
      are cod special TVA (D700 depus) ȘI NU e plătitor TVA

    Asta previne ca un PFA neplătitor cu cod special să primească D300
    (care e doar pentru plătitori), sau invers.
    """
    for valid_fj in valid_fj_list:
        # Match exact pe forma simplă
        if user_fj == valid_fj:
            return True
        # Variantă: plătitor TVA
        if valid_fj == f"{user_fj}_platitor_TVA" and is_vat_payer:
            return True
        # Variantă: neplătitor TVA cu cod special (Bolt etc.)
        if (valid_fj == f"{user_fj}_neplatitor_TVA_cu_cod_special"
                and has_cod_special_tva and not is_vat_payer):
            return True
    return False


def _is_aplicabil(
    obligatie: DefinitieObligatie,
    forma_juridica: str,
    activity_code: str,
    has_intracom_invoice: bool,
    has_cod_special_tva: bool,
    is_vat_payer: bool = False,
) -> Tuple[bool, Optional[str]]:
    """
    Verifică dacă o obligație se aplică unui user în context.

    Returns:
        (aplicabil, motiv_neaplicabil)
    """
    # Match strict pe forma juridică
    if not _matches_forma_juridica(
        forma_juridica, is_vat_payer, has_cod_special_tva,
        obligatie.forme_juridice
    ):
        return False, f"Nu se aplică formei juridice {forma_juridica}"

    # Verifică activitatea
    if "*" not in obligatie.activitati and activity_code not in obligatie.activitati:
        return False, f"Nu se aplică activității {activity_code}"

    # Condiții specifice
    if obligatie.cod in ("D100 poz. 634", "D301", "D390"):
        if not has_intracom_invoice:
            return False, "Nu există factură intracomunitară în această lună"

    if obligatie.cod == "D301" and not has_cod_special_tva:
        return False, "Cod special TVA neînregistrat — depune D700 întâi"

    # D700 (înregistrare cod special, UNICA) apare DOAR dacă NU ești deja
    # înregistrat. Cu cod special deja obținut, nu mai e o obligație.
    if obligatie.cod == "D700" and has_cod_special_tva:
        return False, "Cod special TVA deja înregistrat — D700 nu mai e necesar"

    return True, None


def compute_obligation(
    definitie: DefinitieObligatie,
    year: int,
    month: int,
    forma_juridica: str,
    activity_code: str,
    has_intracom_invoice: bool = False,
    intracom_base_amount: float = 0.0,
    has_cod_special_tva: bool = False,
    is_vat_payer: bool = False,
    judet: Optional[str] = None,
    today: Optional[date] = None,
) -> ObligatieCalculate:
    """
    Calculează contextul unei obligații pentru o lună specifică.

    Args:
        definitie: definiția statică a obligației
        year, month: perioada de referință (pt obligație lunară: luna pentru care
                     se depune declarația; termenul real va fi în luna următoare)
        forma_juridica: ex "PFA"
        activity_code: ex "ridesharing"
        has_intracom_invoice: dacă în luna respectivă există factură intracom
        intracom_base_amount: baza factură (pt calcul sumă D301/D100)
        has_cod_special_tva: dacă PFA-ul are deja D700 depus
        judet: pt lookup IBAN (ex "BN")
        today: data de referință (default = azi)
    """
    if today is None:
        today = date.today()

    # Determină termenul
    if definitie.frecventa == FrecventaObligatie.LUNARA:
        termen = _compute_termen_lunar(year, month, definitie.ziua_termenului)
    elif definitie.frecventa == FrecventaObligatie.TRIMESTRIALA:
        termen = _compute_termen_trimestrial(
            year, month, definitie.ziua_termenului
        )
    elif definitie.frecventa == FrecventaObligatie.ANUALA:
        # Termenul e în anul URMĂTOR (declarăm pt anul anterior)
        # Excepție: dacă suntem la începutul anului, termenul e în anul curent
        luna_termen = definitie.luna_anuala_termen or 5
        if month <= luna_termen:
            termen = _compute_termen_anual(
                year, luna_termen, definitie.ziua_termenului
            )
        else:
            termen = _compute_termen_anual(
                year + 1, luna_termen, definitie.ziua_termenului
            )
    elif definitie.frecventa == FrecventaObligatie.UNICA:
        # Termenul "ASAP" — punem azi + 7 zile
        termen = today + timedelta(days=7)
    else:
        termen = today + timedelta(days=30)

    zile_ramase = (termen - today).days
    status = _compute_status(zile_ramase)

    # Verifică aplicabilitatea
    aplicabil, motiv = _is_aplicabil(
        definitie, forma_juridica, activity_code,
        has_intracom_invoice, has_cod_special_tva,
        is_vat_payer=is_vat_payer,
    )

    # Calculează suma estimată
    suma_estimata = None
    baza_calcul = None

    if aplicabil and has_intracom_invoice and intracom_base_amount > 0:
        if definitie.cod == "D301":
            suma_estimata = round(
                intracom_base_amount * COTA_TVA_STANDARD / 100, 2
            )
            baza_calcul = intracom_base_amount
        elif definitie.cod == "D100 poz. 634":
            suma_estimata = round(
                intracom_base_amount * COTA_RETINERE_NEREZIDENT_EE / 100, 2
            )
            baza_calcul = intracom_base_amount

    # Lookup IBAN dacă există județul
    iban_cont = None
    if aplicabil and judet and definitie.tip_iban:
        iban_cont = get_iban_for_obligation(judet, definitie.tip_iban)

    return ObligatieCalculate(
        definitie=definitie,
        termen=termen,
        zile_ramase=zile_ramase,
        status=status,
        suma_estimata=suma_estimata,
        baza_calcul=baza_calcul,
        iban_cont=iban_cont,
        perioada_an=year,
        perioada_luna=month,
        aplicabil_acum=aplicabil,
        motiv_neaplicabil=motiv,
    )


def get_obligations_for_user(
    year: int,
    month: int,
    forma_juridica: str,
    activity_code: str,
    *,
    has_intracom_invoice: bool = False,
    intracom_base_amount: float = 0.0,
    has_cod_special_tva: bool = False,
    is_vat_payer: bool = False,
    judet: Optional[str] = None,
    only_applicable: bool = True,
    today: Optional[date] = None,
) -> List[ObligatieCalculate]:
    """
    Returnează TOATE obligațiile fiscale pentru un user în luna respectivă.

    Args:
        year, month: perioada de referință
        forma_juridica: ex "PFA"
        activity_code: ex "ridesharing"
        has_intracom_invoice: dacă luna are factură intracom
        intracom_base_amount: baza factură (pt calcul sumă)
        has_cod_special_tva: dacă D700 e depus
        is_vat_payer: dacă user e plătitor TVA
        judet: pt IBAN lookup
        only_applicable: dacă True, returnează doar obligațiile aplicabile
        today: data de referință

    Returns:
        Lista de ObligatieCalculate, sortată după termen.
    """
    result = []
    for definitie in DEFINITII_OBLIGATII.values():
        obl = compute_obligation(
            definitie, year, month, forma_juridica, activity_code,
            has_intracom_invoice=has_intracom_invoice,
            intracom_base_amount=intracom_base_amount,
            has_cod_special_tva=has_cod_special_tva,
            is_vat_payer=is_vat_payer,
            judet=judet,
            today=today,
        )
        if only_applicable and not obl.aplicabil_acum:
            continue
        result.append(obl)

    # Sortare după termen
    result.sort(key=lambda o: o.termen)
    return result


# ============================================================
#              FORMATARE TELEGRAM (Markdown)
# ============================================================

def _status_emoji(status: StatusObligatie) -> str:
    return {
        StatusObligatie.DEPASIT: "🔴",
        StatusObligatie.CRITIC: "🟠",
        StatusObligatie.AVERTISMENT: "🟡",
        StatusObligatie.PROXIM: "🟢",
        StatusObligatie.DEPARTE: "⚪",
    }.get(status, "ℹ️")


def format_calendar_telegram(
    year: int,
    month: int,
    forma_juridica: str,
    activity_code: str,
    *,
    has_intracom_invoice: bool = False,
    intracom_base_amount: float = 0.0,
    has_cod_special_tva: bool = False,
    is_vat_payer: bool = False,
    judet: Optional[str] = None,
) -> str:
    """
    Format Telegram complet pentru calendar fiscal personalizat.
    """
    obligatii = get_obligations_for_user(
        year, month, forma_juridica, activity_code,
        has_intracom_invoice=has_intracom_invoice,
        intracom_base_amount=intracom_base_amount,
        has_cod_special_tva=has_cod_special_tva,
        is_vat_payer=is_vat_payer,
        judet=judet,
        only_applicable=True,
    )

    lines = [
        f"🏛️ *CALENDAR FISCAL PERSONALIZAT*",
        f"📅 _{LUNI_RO_UPPER.get(month, str(month))} {year}_",
        f"👤 _{forma_juridica} · activitate: {activity_code}_",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    if not obligatii:
        lines.append("✅ *Nicio obligație fiscală activă pentru această lună.*")
        lines.append("")
        lines.append("_Dacă crezi că e o eroare, verifică:")
        lines.append("  • Forma juridică în profil_")
        lines.append("  • Activitatea înregistrată_")
        return "\n".join(lines)

    # Separăm pe urgență
    critice = [o for o in obligatii if o.status in (
        StatusObligatie.DEPASIT, StatusObligatie.CRITIC
    )]
    avertismente = [o for o in obligatii if o.status == StatusObligatie.AVERTISMENT]
    normale = [o for o in obligatii if o.status in (
        StatusObligatie.PROXIM, StatusObligatie.DEPARTE
    )]

    if critice:
        lines.append("🚨 *URGENT — Termene critice sau depășite:*")
        for o in critice:
            lines.extend(_format_obligatie_telegram(o))
        lines.append("")

    if avertismente:
        lines.append("⚠️ *Atenție — Termene apropiate:*")
        for o in avertismente:
            lines.extend(_format_obligatie_telegram(o))
        lines.append("")

    if normale:
        lines.append("📋 *Obligații apropiate:*")
        for o in normale:
            lines.extend(_format_obligatie_telegram(o))
        lines.append("")

    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "_⚠️ Verificați întotdeauna cu contabilul autorizat._",
        "_Termenele și sumele sunt orientative._",
    ]

    return "\n".join(lines)


def _format_obligatie_telegram(o: ObligatieCalculate) -> List[str]:
    """Formatează o singură obligație pentru mesaj Telegram."""
    emoji = _status_emoji(o.status)
    zile_str = (
        f"DEPĂȘIT cu {abs(o.zile_ramase)} zile"
        if o.zile_ramase < 0
        else f"{o.zile_ramase} zile rămase"
    )

    lines = [
        f"{emoji} *{o.definitie.cod}* — {o.definitie.nume}",
        f"   📅 Termen: `{o.termen.strftime('%d.%m.%Y')}` _({zile_str})_",
    ]

    if o.suma_estimata is not None:
        lines.append(f"   💰 Sumă estimată: *{o.suma_estimata:.2f} RON*")
        if o.baza_calcul:
            lines.append(
                f"     _bază: {o.baza_calcul:.2f} RON × "
                f"{o.definitie.formula_suma}_"
            )

    if o.iban_cont:
        lines.append(f"   🏦 IBAN: `{o.iban_cont.iban}`")
        lines.append(f"   📋 Cod buget: `{o.iban_cont.cod_buget}`")

    if o.definitie.bonus_info:
        lines.append(f"   💡 {o.definitie.bonus_info}")

    lines.append("")
    return lines


# ============================================================
#         BACKWARD COMPATIBILITY (API VECHI)
# ============================================================

# Păstrăm API-ul vechi pentru ca bot_contabil.py să continue să funcționeze
# fără modificări. Pas 11.4 va trece pe API-ul nou.

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
        "condition": (
            "doar dacă ai factură comision Bolt/Uber în luna respectivă"
        ),
        "where": "ANAF ePortal → Depunere declarații → D301",
        "urgency": "high",
    },
    {
        "code": "D390",
        "name": "Declarație recapitulativă VIES",
        "day": 25,
        "description": (
            "Declari achizițiile intracomunitare de servicii. "
            "Se completează cu valoarea netă a comisioanelor Bolt "
            "Operations OÜ (Estonia, EE...)."
        ),
        "condition": "doar dacă ai factură comision Bolt/Uber în luna respectivă",
        "where": "ANAF ePortal → Depunere declarații → D390",
        "urgency": "high",
    },
    # ⭐ ADĂUGAT v2: D100 nerezidenți (FIX bug critic din v1)
    {
        "code": "D100 poz. 634",
        "name": "Impozit nerezidenți comisioane (2% Bolt)",
        "day": 25,
        "description": (
            "Conform CDI România-Estonia, TU virezi 2% din comisionul Bolt "
            "către Trezorerie. Bolt NU îl plătește automat — îl reține din "
            "comision și îți face cunoscut ca obligație personală. "
            "Baza: valoarea facturilor Bolt × 2%."
        ),
        "condition": "doar dacă ai factură comision Bolt în luna respectivă",
        "where": "ANAF ePortal → Depunere declarații → D100 poz. 634",
        "urgency": "high",
    },
]

ANNUAL_DEADLINES = [
    {
        "code": "D212",
        "name": "Declarația Unică (D212)",
        "month": 5,
        "day": 25,
        "description": (
            "Declari veniturile și cheltuielile PFA din anul anterior. "
            "Se calculează automat: impozit venit (10%), CAS (25%), CASS (10%). "
            "Dacă achiți integral (impozit + CAS + CASS) până pe 15 aprilie → "
            "bonificație 3% din impozit."
        ),
        "where": "ANAF ePortal → Declarația Unică (D212) sau anaf.ro/duf",
        "urgency": "high",
        "bonus_tip": (
            "Achiți INTEGRAL (impozit + CAS + CASS) până pe 15 aprilie → "
            "economisești 3% din impozitul pe venit (CAS/CASS nu se reduc)!"
        ),
    },
    # ⭐ ADĂUGAT v2: D207 (FIX bug critic din v1)
    {
        "code": "D207",
        "name": "Declarația informativă (D207)",
        "month": 2,
        "day": 28,
        "description": (
            "Centralizează toate impozitele reținute la sursă în anul "
            "anterior pentru veniturile plătite nerezidenților (Bolt etc.). "
            "Obligatorie dacă ai depus D100 nerezidenți în anul precedent."
        ),
        "where": "ANAF ePortal → Depunere declarații → D207",
        "urgency": "medium",
    },
    {
        "code": "CAS",
        "name": "Plată CAS (pensie 25%)",
        "month": 5,
        "day": 25,
        "description": (
            "Contribuția la pensie: 25% × baza de calcul. "
            f"Obligatorie dacă venit net > 12 salarii minime brute "
            f"(12 × {SALARIU_MINIM_BRUT_2026} = "
            f"{12 * SALARIU_MINIM_BRUT_2026} RON). "
            f"Baza maximă: 24 salarii minime = "
            f"{24 * SALARIU_MINIM_BRUT_2026} RON/an."
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
            f"Plafonul maxim 2026: 60 salarii minime = "
            f"{60 * SALARIU_MINIM_BRUT_2026} RON. "
            f"Suma maximă CASS: "
            f"{round(60 * SALARIU_MINIM_BRUT_2026 * COTA_CASS / 100, 2)} RON/an."
        ),
        "where": "Prin D212",
        "urgency": "medium",
    },
]

# ⭐ FIX v2: Înlocuit text-ul GREȘIT despre withholding 2%
SPECIAL_NOTES = [
    {
        "code": "IMPOZIT_NEREZIDENTI",
        "name": "Impozit nerezidenți 2% — clarificare critică",
        "description": (
            "ATENȚIE: Versiunea anterioară a botului afirma greșit că Bolt "
            "virează automat 2% la Trezorerie. CORECȚIE: Conform CDI "
            "România-Estonia, TU (PFA-ul) ești obligat să reții și să "
            "virezi 2% lunar prin D100 poz. 634. Pe factură scrie: "
            "'sumă care ar trebui virată de către beneficiarul serviciului'."
        ),
        "urgency": "info",
    },
    {
        "code": "D700",
        "name": "Cod special TVA intracom (D700)",
        "description": (
            "Înainte de prima factură Bolt EE, trebuie depusă D700 "
            "pentru a obține cod special TVA. Fără D700 NU poți depune D301. "
            "Se depune O SINGURĂ DATĂ la ANAF."
        ),
        "urgency": "info",
    },
    {
        "code": "REGISTRU_JURNAL",
        "name": "Registru jurnal de încasări și plăți",
        "description": (
            "Ca PFA sistem real, ești obligat să ții un registru jurnal "
            "conform OMFP 170/2015. Bot-ul generează acest registru automat."
        ),
        "urgency": "info",
    },
]


def get_monthly_alerts(
    year: int, month: int, has_bolt_invoice: bool = False,
    cota_nerezident: Optional[float] = None,
) -> List[dict]:
    """[Backward-compat] Returnează alertele pentru luna dată.

    D100 (impozit nerezident) depinde de regimul nerezident (CRF — fiscal #3):
      - cota > 0 (Bolt 2%/16%)        → D100 de depus, procent DINAMIC;
      - cota == 0 (scutit, ex. Uber)  → D100 OMIS (nu se depune; D207 anual acoperă);
      - cota None (neconfigurat)     → D100 ca nudge de configurare, FĂRĂ 2% presupus.
    """
    alerts = []
    today = date.today()

    for decl in MONTHLY_DEADLINES:
        if not has_bolt_invoice:
            continue

        is_d100 = decl["code"] == "D100 poz. 634"
        # Scutit (CRF 0%): D100 nu se depune lunar — îl omitem (D207 anual rămâne).
        if is_d100 and cota_nerezident is not None and cota_nerezident <= 0:
            continue

        # Termen e în luna URMĂTOARE (deadline 25)
        try:
            if month == 12:
                deadline = date(year + 1, 1, decl["day"])
            else:
                deadline = date(year, month + 1, decl["day"])
        except ValueError:
            deadline = date(year, month, decl["day"])

        days_left = (deadline - today).days

        if days_left < 0:
            status = "overdue"
        elif days_left <= 3:
            status = "critical"
        elif days_left <= 7:
            status = "warning"
        else:
            status = "ok"

        entry = {
            **decl,
            "deadline": deadline.strftime("%d.%m.%Y"),
            "days_left": days_left,
            "status": status,
            "year": year,
            "month": month,
        }

        # D100: nume/descriere reflectă cota din profil (sau prompt de setare).
        if is_d100:
            if cota_nerezident is None:
                entry["name"] = "Impozit nerezident — regim nesetat"
                entry["description"] = (
                    "Setează regimul nerezident (Setări / /start) ca să calculăm "
                    "D100 corect. Cu certificat de rezidență fiscală (CRF) → 0% "
                    "(depui D207, nu D100); 2% interpretare conservatoare; fără "
                    "CRF → 16%. Până atunci NU afișăm o sumă (ar putea fi greșită)."
                )
            else:
                pct = round(cota_nerezident * 100)
                entry["name"] = f"Impozit nerezidenți comisioane ({pct}% Bolt)"
                entry["description"] = (
                    f"Conform CDI România-Estonia, virezi {pct}% din comisionul "
                    f"Bolt prin D100 poz. 634. Baza: valoarea facturilor Bolt × {pct}%."
                )

        alerts.append(entry)

    return alerts


def get_annual_alerts(year: int) -> List[dict]:
    """[Backward-compat] Returnează alertele anuale."""
    alerts = []
    today = date.today()

    for decl in ANNUAL_DEADLINES:
        try:
            deadline = date(year, decl["month"], decl["day"])
        except ValueError:
            continue

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
    cota_nerezident: Optional[float] = None,
) -> str:
    """
    [Backward-compat] Formatează mesajul cu obligațiile fiscale (API vechi).

    `cota_nerezident` (fiscal #3) controlează D100: >0 de depus (procent dinamic),
    0 scutit (omis, D207 anual), None nesetat (nudge de configurare).

    NOTĂ: Pentru calendar personalizat per user, folosește
    format_calendar_telegram() (API nou v2).
    """
    lines = [
        f"🏛️ *CALENDAR FISCAL — "
        f"{LUNI_RO_UPPER.get(month, str(month))} {year}*",
        f"━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    monthly = get_monthly_alerts(year, month, has_bolt_invoice=has_bolt_invoice,
                                 cota_nerezident=cota_nerezident)
    if monthly:
        lines.append("📋 *DECLARAȚII LUNARE (până pe 25 a lunii următoare):*")
        for a in monthly:
            icon = (
                "🔴" if a["status"] in ("overdue", "critical")
                else "🟡" if a["status"] == "warning"
                else "🟢"
            )
            days_str = (
                f"(DEPĂȘIT cu {abs(a['days_left'])} zile!)"
                if a["days_left"] < 0
                else f"({a['days_left']} zile rămase)"
            )
            lines.append(f"{icon} *{a['code']}* — {a['name']} {days_str}")
            lines.append(f"   📅 Termen: `{a['deadline']}`")
            lines.append(f"   ℹ️ {a['description'][:140]}...")
            lines.append(f"   🖥️ {a['where']}")
            lines.append("")
    else:
        lines.append("✅ *Declarații lunare:*")
        lines.append(
            "Nicio factură Bolt/Uber în această lună → "
            "D301/D390/D100 nu se depun."
        )
        lines.append("")

    annual = [
        a for a in get_annual_alerts(year)
        if -30 <= a["days_left"] <= 60
    ]
    if annual:
        lines.append("📅 *OBLIGAȚII ANUALE APROPIATE:*")
        for a in annual:
            icon = (
                "🔴" if a["status"] in ("overdue", "critical")
                else "🟡" if a["status"] == "warning"
                else "🟢"
            )
            days_str = (
                f"(DEPĂȘIT!)" if a["days_left"] < 0
                else f"({a['days_left']} zile)"
            )
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


# ============================================================
#                    EXPORT API
# ============================================================

__all__ = [
    # API NOU v2 (Pas 11.2)
    "TipObligatie", "FrecventaObligatie", "StatusObligatie", "UrgentaObligatie",
    "DefinitieObligatie", "ObligatieCalculate",
    "DEFINITII_OBLIGATII",
    "compute_obligation",
    "get_obligations_for_user",
    "format_calendar_telegram",
    # API VECHI (backward compat)
    "MONTHLY_DEADLINES", "ANNUAL_DEADLINES", "SPECIAL_NOTES",
    "get_monthly_alerts", "get_annual_alerts", "format_fiscal_message",
    # Constante
    "LUNI_RO", "LUNI_RO_UPPER",
    "SALARIU_MINIM_BRUT_2026",
    "COTA_IMPOZIT_PFA", "COTA_CAS", "COTA_CASS",
    "COTA_TVA_STANDARD", "COTA_RETINERE_NEREZIDENT_EE",
]
