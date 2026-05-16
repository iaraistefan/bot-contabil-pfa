"""
ANAF Treasury IBAN Database — Baza oficială de conturi IBAN pentru plăți fiscale.

Sursa oficială: https://static.anaf.ro/static/10/Anaf/AsistentaContribuabili_r/iban2014/
Ultima actualizare: 16.05.2026

ARHITECTURĂ:
- Bază de date statică (Python dict) cu IBAN-uri per:
  • Județ
  • Tip obligație fiscală (TVA, impozit nerezidenți, impozit venit, etc.)
  • Cod buget (format ANAF: 20.A.XX.XX.XX)
- Versiune inițială: județul Bistrița-Năsăud (TREZ100)
- Extensibilă: structura permite adăugare ușoară altor județe

UTILIZARE:
    from app.integrations.anaf_iban_db import (
        get_iban_for_obligation,
        validate_payment_iban,
        TipObligatie,
    )

    # Obține IBAN-ul corect
    iban = get_iban_for_obligation("BN", TipObligatie.D301_TVA_INTRACOM)

    # Validează un IBAN folosit la plată
    is_valid, msg = validate_payment_iban(
        used_iban="RO82TREZ10120A1203000001",
        expected_obligation=TipObligatie.D301_TVA_INTRACOM,
        judet="BN",
    )

CHANGELOG:
- v1 (16.05.2026): Versiune inițială cu județul Bistrița-Năsăud
  • Mapping D100 poz. 634 (impozit comisioane nerezidenți) → IBAN corect
  • Mapping D301 (TVA achiziții intracom) → IBAN corect
  • Mapping D212 (decl. unică PFA) → cont unic pe CNP
  • Funcție de validare IBAN folosit vs IBAN așteptat
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple, List, Dict

logger = logging.getLogger(__name__)


# ============================================================
#                    ENUMS
# ============================================================

class Judet(str, Enum):
    """Codurile județelor (ISO 3166-2:RO simplificat)."""
    ALBA = "AB"
    ARAD = "AR"
    ARGES = "AG"
    BACAU = "BC"
    BIHOR = "BH"
    BISTRITA_NASAUD = "BN"
    BOTOSANI = "BT"
    BRAILA = "BR"
    BRASOV = "BV"
    BUCURESTI = "B"
    BUZAU = "BZ"
    CALARASI = "CL"
    CARAS_SEVERIN = "CS"
    CLUJ = "CJ"
    CONSTANTA = "CT"
    COVASNA = "CV"
    DAMBOVITA = "DB"
    DOLJ = "DJ"
    GALATI = "GL"
    GIURGIU = "GR"
    GORJ = "GJ"
    HARGHITA = "HR"
    HUNEDOARA = "HD"
    IALOMITA = "IL"
    IASI = "IS"
    ILFOV = "IF"
    MARAMURES = "MM"
    MEHEDINTI = "MH"
    MURES = "MS"
    NEAMT = "NT"
    OLT = "OT"
    PRAHOVA = "PH"
    SALAJ = "SJ"
    SATU_MARE = "SM"
    SIBIU = "SB"
    SUCEAVA = "SV"
    TELEORMAN = "TR"
    TIMIS = "TM"
    TULCEA = "TL"
    VALCEA = "VL"
    VASLUI = "VS"
    VRANCEA = "VN"


class TipObligatie(str, Enum):
    """
    Tipuri de obligații fiscale.

    Aliniate cu nomenclatorul ANAF (poziții din D100, declarații specifice).
    """
    # Impozite pe veniturile nerezidenților (D100)
    D100_NEREZID_DIVIDENDE = "D100_NEREZID_DIVIDENDE"           # poz. 631
    D100_NEREZID_DOBANZI = "D100_NEREZID_DOBANZI"               # poz. 632
    D100_NEREZID_REDEVENTE = "D100_NEREZID_REDEVENTE"           # poz. 633
    D100_NEREZID_COMISIOANE = "D100_NEREZID_COMISIOANE"         # poz. 634 — Bolt 2%
    D100_NEREZID_SPORTIV = "D100_NEREZID_SPORTIV"               # poz. 635
    D100_NEREZID_SERVICII = "D100_NEREZID_SERVICII"             # poz. 637

    # TVA
    D300_TVA_DECONT = "D300_TVA_DECONT"                         # plătitor TVA normal
    D301_TVA_INTRACOM = "D301_TVA_INTRACOM"                     # neplătitor cu cod special

    # PFA / activități independente
    D212_IMPOZIT_INDEPENDENTE = "D212_IMPOZIT_INDEPENDENTE"     # impozit anual PFA
    D212_CONT_UNIC_PF = "D212_CONT_UNIC_PF"                     # cont unic 5504 (CAS+CASS+impozit)

    # SRL
    D101_IMPOZIT_PROFIT = "D101_IMPOZIT_PROFIT"                 # SRL impozit profit 16%
    D700_IMPOZIT_MICROINTREPRINDERI = "D700_IMPOZIT_MICRO"      # SRL Micro 1%/3%


class IdentificareBeneficiar(str, Enum):
    """Tipul de identificare pentru beneficiar pe OP."""
    CUI = "CUI"   # Codul de Identificare Fiscală (firmă)
    CNP = "CNP"   # Cod Numeric Personal (persoană fizică)


# ============================================================
#                    DATACLASSES
# ============================================================

@dataclass
class IbanCont:
    """
    Un cont IBAN al Trezoreriei pentru o obligație fiscală.
    """
    iban: str                              # ex: "RO24TREZ10120A100101XTVA"
    cod_buget: str                          # ex: "20.A.10.01.01"
    denumire: str                           # descrierea oficială ANAF
    judet: Judet                            # județul
    cod_trezorerie: str                     # ex: "TREZ101"
    tip_identificare_beneficiar: IdentificareBeneficiar = IdentificareBeneficiar.CUI
    valid_pentru_forma_juridica: List[str] = field(default_factory=list)
    observatii: str = ""

    def __str__(self) -> str:
        return f"{self.iban} ({self.denumire})"


# ============================================================
#                    BAZA DE DATE PE JUDEȚ
# ============================================================

# Mapping județ → trezorerie operativă reședință + cod ANAF
JUDET_TO_TREZORERIE = {
    Judet.BISTRITA_NASAUD: ("TREZ101", "Trezoreria operativă Municipiul Bistrița"),
    # TODO: extend pentru toate județele
}


# ─────────────────────────────────────────────────────────────
# BISTRIȚA-NĂSĂUD (TREZ101)
# Sursa: https://static.anaf.ro/static/10/Anaf/AsistentaContribuabili_r/iban2014/iban_TREZ100_TREZ101.pdf
# ─────────────────────────────────────────────────────────────

BISTRITA_NASAUD_IBANS: Dict[TipObligatie, IbanCont] = {
    # ─── IMPOZITE NEREZIDENȚI (pentru factură Bolt etc.) ──────
    TipObligatie.D100_NEREZID_COMISIOANE: IbanCont(
        iban="RO10TREZ10120A050104XXXX",
        cod_buget="20.A.05.01.04",
        denumire=(
            "Impozit pe veniturile din comisioane obținute din "
            "România de persoane nerezidente (D100 poz. 634)"
        ),
        judet=Judet.BISTRITA_NASAUD,
        cod_trezorerie="TREZ101",
        tip_identificare_beneficiar=IdentificareBeneficiar.CUI,
        valid_pentru_forma_juridica=["PFA", "II", "IF", "SRL_MICRO", "SRL_NORMAL"],
        observatii=(
            "Cota 2% conform CDI România-Estonia (cu certificat de rezidență "
            "fiscală). Fără certificat: 16%. Folosit pentru factură Bolt."
        ),
    ),

    TipObligatie.D100_NEREZID_DIVIDENDE: IbanCont(
        iban="RO72TREZ10120A050101XXXX",
        cod_buget="20.A.05.01.01",
        denumire=(
            "Impozit pe veniturile din dividende obținute din "
            "România de persoane nerezidente"
        ),
        judet=Judet.BISTRITA_NASAUD,
        cod_trezorerie="TREZ101",
        valid_pentru_forma_juridica=["SRL_MICRO", "SRL_NORMAL"],
    ),

    TipObligatie.D100_NEREZID_DOBANZI: IbanCont(
        iban="RO19TREZ10120A050102XXXX",
        cod_buget="20.A.05.01.02",
        denumire=(
            "Impozit pe veniturile din dobânzi obținute din "
            "România de persoane nerezidente"
        ),
        judet=Judet.BISTRITA_NASAUD,
        cod_trezorerie="TREZ101",
        valid_pentru_forma_juridica=["PFA", "SRL_MICRO", "SRL_NORMAL"],
    ),

    TipObligatie.D100_NEREZID_REDEVENTE: IbanCont(
        iban="RO63TREZ10120A050103XXXX",
        cod_buget="20.A.05.01.03",
        denumire=(
            "Impozit pe veniturile din redevențe obținute din "
            "România de persoane nerezidente"
        ),
        judet=Judet.BISTRITA_NASAUD,
        cod_trezorerie="TREZ101",
        valid_pentru_forma_juridica=["PFA", "SRL_MICRO", "SRL_NORMAL"],
    ),

    TipObligatie.D100_NEREZID_SERVICII: IbanCont(
        iban="RO45TREZ10120A050107XXXX",
        cod_buget="20.A.05.01.07",
        denumire=(
            "Impozit pe veniturile din servicii prestate în România "
            "și în afara României de persoane nerezidente"
        ),
        judet=Judet.BISTRITA_NASAUD,
        cod_trezorerie="TREZ101",
        valid_pentru_forma_juridica=["PFA", "SRL_MICRO", "SRL_NORMAL"],
    ),

    # ─── TVA ──────────────────────────────────────────────────
    TipObligatie.D301_TVA_INTRACOM: IbanCont(
        iban="RO24TREZ10120A100101XTVA",
        cod_buget="20.A.10.01.01",
        denumire=(
            "TVA încasată pentru operațiuni interne — folosit și pentru "
            "D301 (decont special TVA — achiziții intracomunitare servicii)"
        ),
        judet=Judet.BISTRITA_NASAUD,
        cod_trezorerie="TREZ101",
        tip_identificare_beneficiar=IdentificareBeneficiar.CUI,
        valid_pentru_forma_juridica=[
            "PFA_neplatitor_TVA_cu_cod_special",
            "PFA_platitor_TVA",
            "SRL_neplatitor_TVA_cu_cod_special",
            "SRL_platitor_TVA",
        ],
        observatii=(
            "Pentru PFA neplătitor cu cod special TVA (D700): TVA datorat "
            "pe achiziții intracom (Bolt Estonia) se plătește aici."
        ),
    ),

    TipObligatie.D300_TVA_DECONT: IbanCont(
        iban="RO24TREZ10120A100101XTVA",  # același cont ca D301
        cod_buget="20.A.10.01.01",
        denumire="TVA încasată pentru operațiuni interne (D300)",
        judet=Judet.BISTRITA_NASAUD,
        cod_trezorerie="TREZ101",
        valid_pentru_forma_juridica=["PFA_platitor_TVA", "SRL_platitor_TVA"],
    ),

    # ─── PFA — IMPOZIT PE VENIT ───────────────────────────────
    TipObligatie.D212_IMPOZIT_INDEPENDENTE: IbanCont(
        iban="RO19TREZ10120030101XXXXX",
        cod_buget="20.A.03.01.00",
        denumire="Impozit pe venituri din activități independente",
        judet=Judet.BISTRITA_NASAUD,
        cod_trezorerie="TREZ101",
        tip_identificare_beneficiar=IdentificareBeneficiar.CNP,
        valid_pentru_forma_juridica=["PFA", "II", "IF"],
        observatii=(
            "Impozit 10% pe venitul net anual al PFA sistem real. "
            "Plătit anual prin D212 (Decl. Unică), până 25 mai."
        ),
    ),

    # ─── PFA — CONT UNIC 5504 (CAS+CASS+impozit combined) ────
    # NOTĂ: Contul unic 5504 e calculat pe baza CNP-ului user-ului
    # Aici punem doar placeholder; calculul real se face în alta funcție
    TipObligatie.D212_CONT_UNIC_PF: IbanCont(
        iban="RO__TREZ____55.04_<CNP>__XXX",  # template — se completează cu CNP
        cod_buget="55.04",
        denumire=(
            "Cont unic persoană fizică — Impozit pe venit + CAS + CASS "
            "(Declarația Unică D212)"
        ),
        judet=Judet.BISTRITA_NASAUD,
        cod_trezorerie="TREZ101",
        tip_identificare_beneficiar=IdentificareBeneficiar.CNP,
        valid_pentru_forma_juridica=["PFA", "II", "IF"],
        observatii=(
            "ATENȚIE: Contul unic 5504 e deschis pe CNP-ul tău la "
            "Trezoreria de domiciliu. Verifică în SPV contul exact "
            "sau plătește prin ghiseul.ro."
        ),
    ),

    # ─── SRL ──────────────────────────────────────────────────
    TipObligatie.D101_IMPOZIT_PROFIT: IbanCont(
        iban="RO68TREZ10120010101XXXXX",
        cod_buget="20.A.01.01.00",
        denumire="Impozit pe profit de la agenții economici",
        judet=Judet.BISTRITA_NASAUD,
        cod_trezorerie="TREZ101",
        tip_identificare_beneficiar=IdentificareBeneficiar.CUI,
        valid_pentru_forma_juridica=["SRL_NORMAL"],
        observatii="Impozit 16% pe profitul SRL Normal.",
    ),

    TipObligatie.D700_IMPOZIT_MICROINTREPRINDERI: IbanCont(
        iban="RO73TREZ10120020106XXXXX",
        cod_buget="20.A.02.01.06",
        denumire="Impozit pe venitul microîntreprinderilor",
        judet=Judet.BISTRITA_NASAUD,
        cod_trezorerie="TREZ101",
        tip_identificare_beneficiar=IdentificareBeneficiar.CUI,
        valid_pentru_forma_juridica=["SRL_MICRO"],
        observatii=(
            "Impozit 1% (cu salariați) sau 3% (fără salariați) pe cifra "
            "de afaceri. Termene: trimestrial — 25 a lunii următoare "
            "fiecărui trimestru."
        ),
    ),
}


# Master mapping: județ → bază date IBAN
JUDET_TO_IBANS: Dict[Judet, Dict[TipObligatie, IbanCont]] = {
    Judet.BISTRITA_NASAUD: BISTRITA_NASAUD_IBANS,
    # TODO: alte județe
}


# ============================================================
#                    FUNCȚII PUBLICE
# ============================================================

def get_iban_for_obligation(
    judet: str,
    tip_obligatie: TipObligatie,
) -> Optional[IbanCont]:
    """
    Returnează IBAN-ul oficial pentru o obligație fiscală într-un județ.

    Args:
        judet: cod județ (ex: "BN" pentru Bistrița-Năsăud)
        tip_obligatie: tipul obligației (enum TipObligatie)

    Returns:
        IbanCont sau None dacă județul/obligația nu sunt în bază.
    """
    try:
        judet_enum = Judet(judet) if isinstance(judet, str) else judet
    except ValueError:
        logger.warning(f"Județ necunoscut: {judet}")
        return None

    ibans = JUDET_TO_IBANS.get(judet_enum)
    if not ibans:
        logger.warning(
            f"Județul {judet_enum.value} nu e în baza de date IBAN încă. "
            f"Doar Bistrița-Năsăud e populat momentan."
        )
        return None

    return ibans.get(tip_obligatie)


def validate_payment_iban(
    used_iban: str,
    expected_obligation: TipObligatie,
    judet: str,
) -> Tuple[bool, str]:
    """
    Validează dacă IBAN-ul folosit pentru o plată corespunde cu
    obligația fiscală așteptată.

    Args:
        used_iban: IBAN-ul efectiv folosit pe OP
        expected_obligation: ce tip de plată ar trebui să fie
        judet: județul user-ului

    Returns:
        (is_valid, message) — message conține explicația
    """
    expected_iban_cont = get_iban_for_obligation(judet, expected_obligation)

    if not expected_iban_cont:
        return False, (
            f"⚠️ Nu pot valida — județul {judet} sau obligația "
            f"{expected_obligation.value} nu e în baza de date."
        )

    # Normalizăm IBAN-urile pentru comparație (eliminăm spații, ne-asigurăm uppercase)
    used_clean = used_iban.strip().upper().replace(" ", "").replace("-", "")
    expected_clean = expected_iban_cont.iban.strip().upper()

    # Pentru conturi cu placeholder XTVA / XXXX / <CNP>, comparăm doar prefixul
    if "X" in expected_clean or "<" in expected_clean:
        # Extragem partea fără placeholder
        # Pattern: primul "X" sau "<" e începutul placeholder-ului
        match = re.match(r"^([A-Z0-9]+?)(?:X{3,}|<)", expected_clean)
        if match:
            prefix = match.group(1)
            if used_clean.startswith(prefix):
                return True, (
                    f"✅ IBAN corect pentru {expected_obligation.value}: "
                    f"{used_iban}"
                )

    if used_clean == expected_clean:
        return True, (
            f"✅ IBAN corect pentru {expected_obligation.value}: {used_iban}"
        )

    return False, (
        f"❌ IBAN GREȘIT!\n"
        f"   Folosit: {used_iban}\n"
        f"   Corect:  {expected_iban_cont.iban}\n"
        f"   Pentru:  {expected_iban_cont.denumire}\n"
        f"   Cod buget: {expected_iban_cont.cod_buget}"
    )


def identify_obligation_from_iban(
    iban: str,
    judet: str,
) -> Optional[Tuple[TipObligatie, IbanCont]]:
    """
    Reverse lookup: dat un IBAN, identifică ce obligație fiscală reprezintă.

    Util pentru a interpreta un extras bancar — "ce a plătit user-ul aici?"

    Args:
        iban: IBAN-ul din extrasul bancar
        judet: județul user-ului

    Returns:
        (TipObligatie, IbanCont) sau None dacă IBAN-ul nu match.
    """
    try:
        judet_enum = Judet(judet) if isinstance(judet, str) else judet
    except ValueError:
        return None

    ibans = JUDET_TO_IBANS.get(judet_enum, {})
    iban_clean = iban.strip().upper().replace(" ", "").replace("-", "")

    for obligatie, cont in ibans.items():
        cont_iban = cont.iban.strip().upper()

        # Match exact
        if iban_clean == cont_iban:
            return (obligatie, cont)

        # Match cu placeholder (XTVA, XXXX, <CNP>)
        if "X" in cont_iban or "<" in cont_iban:
            match = re.match(r"^([A-Z0-9]+?)(?:X{3,}|<)", cont_iban)
            if match:
                prefix = match.group(1)
                if iban_clean.startswith(prefix):
                    return (obligatie, cont)

    return None


def list_obligations_for_forma_juridica(
    judet: str,
    forma_juridica: str,
) -> List[Tuple[TipObligatie, IbanCont]]:
    """
    Listează toate obligațiile fiscale aplicabile unei forme juridice
    într-un județ.

    Args:
        judet: cod județ
        forma_juridica: ex "PFA", "SRL_MICRO", "SRL_NORMAL", etc.

    Returns:
        listă de (TipObligatie, IbanCont)
    """
    try:
        judet_enum = Judet(judet) if isinstance(judet, str) else judet
    except ValueError:
        return []

    ibans = JUDET_TO_IBANS.get(judet_enum, {})
    result = []

    for obligatie, cont in ibans.items():
        # Verificăm dacă forma juridică e în lista de valid_pentru
        # (cu match parțial pentru variante gen "PFA_neplatitor_TVA_cu_cod_special")
        for valid_fj in cont.valid_pentru_forma_juridica:
            if forma_juridica in valid_fj or valid_fj.startswith(forma_juridica):
                result.append((obligatie, cont))
                break

    return result


def get_cont_unic_pf_for_cnp(cnp: str, judet: str) -> str:
    """
    Construiește contul unic 5504 pentru o persoană fizică pe baza CNP-ului.

    Format: RO__TREZ____55.04_<CNP_HASH>__XXX

    NOTĂ: Acest format e generic — contul exact se obține:
    1. Pe SPV (Spațiul Privat Virtual ANAF)
    2. La Trezoreria de domiciliu
    3. Prin ghiseul.ro (calcul automat)

    Args:
        cnp: CNP-ul persoanei fizice (13 cifre)
        judet: județul de domiciliu

    Returns:
        Template IBAN cu instrucțiuni — utilizatorul trebuie să verifice
        contul exact pe SPV sau ghiseul.ro
    """
    if not cnp or len(cnp) != 13 or not cnp.isdigit():
        return (
            "⚠️ CNP invalid. Contul unic 5504 se obține:\n"
            "  • Pe SPV (Spațiul Privat Virtual ANAF)\n"
            "  • La Trezoreria de domiciliu\n"
            "  • Sau prin ghiseul.ro (selectează 'Persoane fizice')"
        )

    # Format general cont unic 5504
    # IBAN-ul real se calculează după algoritm specific ANAF + CNP
    # Aici returnăm doar instrucțiunea
    return (
        f"Cont unic 5504 pentru CNP {cnp[:6]}*****{cnp[-2:]}:\n"
        f"  ⚠️ Contul exact se generează pe baza CNP la "
        f"Trezoreria de domiciliu (jud. {judet}).\n"
        f"  Recomandare: plătește prin ghiseul.ro — alegi automat "
        f"contul corect din CNP."
    )


# ============================================================
#                    METADATE ȘI STATISTICĂ
# ============================================================

def get_database_stats() -> Dict[str, int]:
    """Returnează statistici despre baza de date IBAN (pentru debugging)."""
    return {
        "judete_acoperite": len(JUDET_TO_IBANS),
        "tipuri_obligatii": len(list(TipObligatie)),
        "total_iban_intrari": sum(
            len(ibans) for ibans in JUDET_TO_IBANS.values()
        ),
    }


__all__ = [
    "Judet",
    "TipObligatie",
    "IdentificareBeneficiar",
    "IbanCont",
    "get_iban_for_obligation",
    "validate_payment_iban",
    "identify_obligation_from_iban",
    "list_obligations_for_forma_juridica",
    "get_cont_unic_pf_for_cnp",
    "get_database_stats",
]
