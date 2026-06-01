"""
Motor de calcul pentru Declaratia Unica (D212) — PFA sistem real.

Calculeaza, pentru veniturile dintr-un an:
  - impozit pe venit (10%)
  - CAS (contributia la pensie, 25%) cu praguri
  - CASS (contributia la sanatate, 10%) cu praguri
  - total de plata + bonificatie

⚠️ IMPORTANT — ORIENTATIV, NU DEFINITIV:
  Regulile D212 sunt complexe si se schimba des (praguri, OUG-uri, exceptii).
  Acest modul implementeaza regulile STANDARD pentru veniturile 2025
  (D212 depusa in 2026, salariu minim 4050 lei). Rezultatul e o ESTIMARE
  transparenta (arata fiecare pas), dar TREBUIE verificata cu un contabil
  inainte de depunere. Nu inlocuieste consultanta fiscala.

REGULI IMPLEMENTATE (venituri 2025, salariu minim 4050 lei):
  Venit net = venit brut - cheltuieli deductibile
  CAS (25%):
    - venit net < 12 sal (48.600)        -> CAS = 0 (neobligat)
    - 12 sal <= venit net < 24 sal       -> baza 48.600  -> CAS 12.150
    - venit net >= 24 sal (97.200)       -> baza 97.200  -> CAS 24.300
  CASS (10%), pentru venit net > 0:
    - baza = clamp(venit net, 6 sal, 60 sal) = clamp(venit, 24.300, 243.000)
    - CASS = baza * 10%   (minim 2.430, maxim 24.300)
    - venit net <= 0 -> CASS = 0
  Impozit (10%):
    - venit impozabil = max(0, venit net - CAS - CASS)
    - impozit = venit impozabil * 10%
  Bonificatie (OUG 8/2026): 3% din impozit la plata integrala pana la termen.

Surse: HG 1506/2024 (salariu minim), OUG 156/2024, OUG 8/2026.
"""

from dataclasses import dataclass, field
from typing import List, Optional


# ============================================================
#         CONSTANTE 2025/2026 (D212 depusa in 2026)
# ============================================================

SALARIU_MINIM_2025 = 4050  # HG 1506/2024 — valabil tot 2025

COTA_IMPOZIT = 0.10
COTA_CAS = 0.25
COTA_CASS = 0.10
COTA_BONIFICATIE = 0.03

# Praguri exprimate in nr. de salarii minime
CAS_PRAG_MIN_SAL = 12   # sub 12 salarii: fara CAS
CAS_PRAG_MAX_SAL = 24   # peste 24 salarii: baza plafonata la 24
CASS_PRAG_MIN_SAL = 6   # baza CASS minima
CASS_PRAG_MAX_SAL = 60  # baza CASS maxima


# ============================================================
#                    DATACLASS REZULTAT
# ============================================================

@dataclass
class RezultatD212:
    an: int
    salariu_minim: int

    venit_brut: float
    cheltuieli: float
    venit_net: float

    cas: float
    cas_baza: float
    cas_explicatie: str

    cass: float
    cass_baza: float
    cass_explicatie: str

    venit_impozabil: float
    impozit: float

    total_plata: float
    bonificatie: float          # cat economisesti daca platesti la timp
    total_cu_bonificatie: float

    avertismente: List[str] = field(default_factory=list)


# ============================================================
#                    CALCUL
# ============================================================

def calculeaza_d212(
    venit_brut: float,
    cheltuieli_deductibile: float,
    an: int = 2025,
    salariu_minim: int = SALARIU_MINIM_2025,
) -> RezultatD212:
    """
    Calculeaza impozitul + CAS + CASS pentru un PFA in sistem real.

    Args:
        venit_brut: total incasari din activitate (pe an)
        cheltuieli_deductibile: total cheltuieli deductibile (pe an)
        an: anul pentru care se face declaratia (default 2025)
        salariu_minim: salariul minim de referinta (default 4050)

    Returns:
        RezultatD212 cu toate componentele + explicatii + avertismente.
    """
    venit_brut = max(0.0, float(venit_brut))
    cheltuieli = max(0.0, float(cheltuieli_deductibile))
    venit_net = round(venit_brut - cheltuieli, 2)

    prag_6 = CASS_PRAG_MIN_SAL * salariu_minim   # 24.300
    prag_12 = CAS_PRAG_MIN_SAL * salariu_minim   # 48.600
    prag_24 = CAS_PRAG_MAX_SAL * salariu_minim   # 97.200
    prag_60 = CASS_PRAG_MAX_SAL * salariu_minim  # 243.000

    avert = [
        "Calcul ORIENTATIV. Verifica cu un contabil inainte de depunere — "
        "regulile D212 au exceptii si se schimba des.",
    ]

    # --- CAS (pensie 25%) ---
    if venit_net < prag_12:
        cas_baza = 0.0
        cas = 0.0
        cas_expl = (
            f"Venit net {venit_net:.0f} lei < {CAS_PRAG_MIN_SAL} salarii "
            f"({prag_12:.0f} lei) -> CAS neobligatoriu (0 lei). "
            f"Poti opta voluntar sa platesti."
        )
    elif venit_net < prag_24:
        cas_baza = float(prag_12)
        cas = round(cas_baza * COTA_CAS, 2)
        cas_expl = (
            f"Venit net intre {CAS_PRAG_MIN_SAL} si {CAS_PRAG_MAX_SAL} salarii "
            f"-> baza {cas_baza:.0f} lei × 25% = {cas:.0f} lei."
        )
    else:
        cas_baza = float(prag_24)
        cas = round(cas_baza * COTA_CAS, 2)
        cas_expl = (
            f"Venit net >= {CAS_PRAG_MAX_SAL} salarii ({prag_24:.0f} lei) "
            f"-> baza plafonata {cas_baza:.0f} lei × 25% = {cas:.0f} lei."
        )

    # --- CASS (sanatate 10%) ---
    if venit_net <= 0:
        cass_baza = 0.0
        cass = 0.0
        cass_expl = "Venit net <= 0 -> fara CASS."
    else:
        cass_baza = min(max(venit_net, prag_6), prag_60)
        cass = round(cass_baza * COTA_CASS, 2)
        if venit_net < prag_6:
            cass_expl = (
                f"Venit net {venit_net:.0f} < {CASS_PRAG_MIN_SAL} salarii "
                f"-> baza minima {prag_6:.0f} lei × 10% = {cass:.0f} lei."
            )
        elif venit_net > prag_60:
            cass_expl = (
                f"Venit net peste plafon -> baza maxima {prag_60:.0f} lei "
                f"× 10% = {cass:.0f} lei."
            )
        else:
            cass_expl = f"Baza {cass_baza:.0f} lei × 10% = {cass:.0f} lei."

    # --- Impozit (10% pe venit net - CAS - CASS) ---
    venit_impozabil = max(0.0, round(venit_net - cas - cass, 2))
    impozit = round(venit_impozabil * COTA_IMPOZIT, 2)

    total = round(cas + cass + impozit, 2)
    bonificatie = round(impozit * COTA_BONIFICATIE, 2)
    total_cu_bonif = round(total - bonificatie, 2)

    if venit_net <= 0:
        avert.append("Venit net 0 sau pierdere: depui D212 cu valori 0 "
                     "(daca PFA-ul nu e suspendat).")

    return RezultatD212(
        an=an, salariu_minim=salariu_minim,
        venit_brut=venit_brut, cheltuieli=cheltuieli, venit_net=venit_net,
        cas=cas, cas_baza=cas_baza, cas_explicatie=cas_expl,
        cass=cass, cass_baza=cass_baza, cass_explicatie=cass_expl,
        venit_impozabil=venit_impozabil, impozit=impozit,
        total_plata=total, bonificatie=bonificatie,
        total_cu_bonificatie=total_cu_bonif,
        avertismente=avert,
    )


# ============================================================
#                    GHID / SUMAR
# ============================================================

def genereaza_ghid_d212(r: RezultatD212, plain: bool = False) -> str:
    """Sumar lizibil al calculului D212, cu fiecare pas vizibil."""
    b = (lambda s: s) if plain else (lambda s: f"*{s}*")
    h = "" if plain else "🧮 "
    sep = "──────────────────────────"

    L = []
    L.append(f"{h}{b(f'Declaratia Unica (D212) — estimare {r.an}')}")
    L.append(sep)
    L.append(f"{'' if plain else '📥 '}Venit brut: {r.venit_brut:,.0f} lei".replace(",", "."))
    L.append(f"{'' if plain else '📤 '}Cheltuieli deductibile: {r.cheltuieli:,.0f} lei".replace(",", "."))
    L.append(f"{'' if plain else '💼 '}{b(f'Venit net: {r.venit_net:,.0f} lei')}".replace(",", "."))
    L.append("")
    L.append(f"{'' if plain else '🏦 '}{b(f'CAS (pensie 25%): {r.cas:,.0f} lei')}".replace(",", "."))
    L.append(f"   {r.cas_explicatie}")
    L.append("")
    L.append(f"{'' if plain else '🏥 '}{b(f'CASS (sanatate 10%): {r.cass:,.0f} lei')}".replace(",", "."))
    L.append(f"   {r.cass_explicatie}")
    L.append("")
    L.append(f"{'' if plain else '🧾 '}{b(f'Impozit (10%): {r.impozit:,.0f} lei')}".replace(",", "."))
    L.append(f"   baza impozit = venit net - CAS - CASS = {r.venit_impozabil:,.0f} lei".replace(",", "."))
    L.append("")
    L.append(sep)
    L.append(f"{'' if plain else '💰 '}{b(f'TOTAL DE PLATA: {r.total_plata:,.0f} lei')}".replace(",", "."))
    if r.bonificatie > 0:
        L.append(f"   _cu plata la timp: {r.total_cu_bonificatie:,.0f} lei "
                 f"(economisesti {r.bonificatie:,.0f} lei bonificatie 3%)_".replace(",", "."))
    L.append("")
    for a in r.avertismente:
        L.append(("⚠️ " if not plain else "ATENTIE: ") + a)
    return "\n".join(L)


# ============================================================
#                    TEST / DEMO
# ============================================================

if __name__ == "__main__":
    print("=== Exemplu 1: PFA Bolt mic (venit net sub 12 salarii) ===")
    r1 = calculeaza_d212(venit_brut=34000, cheltuieli_deductibile=12000)
    print(genereaza_ghid_d212(r1, plain=True))
    print()
    print("=== Exemplu 2: venit net 60.000 (peste 12 salarii, sub 24) ===")
    r2 = calculeaza_d212(venit_brut=90000, cheltuieli_deductibile=30000)
    print(genereaza_ghid_d212(r2, plain=True))
    print()
    print("=== Exemplu 3: venit net 0 (pierdere) ===")
    r3 = calculeaza_d212(venit_brut=10000, cheltuieli_deductibile=15000)
    print(f"Venit net: {r3.venit_net}, CAS: {r3.cas}, CASS: {r3.cass}, Impozit: {r3.impozit}, Total: {r3.total_plata}")
