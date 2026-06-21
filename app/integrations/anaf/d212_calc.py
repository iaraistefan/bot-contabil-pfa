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

from app.domain import contributii
from app.domain import proportionalizare


# ============================================================
#         CONSTANTE 2025/2026 (D212 depusa in 2026)
# ============================================================

SALARIU_MINIM_2025 = 4050  # HG 1506/2024 — valabil tot 2025

COTA_IMPOZIT = 0.10
COTA_BONIFICATIE = 0.03

# CAS/CASS (cote + praguri) NU se mai definesc aici — sursa unica: app.domain.contributii.


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
    regim: str = "SISTEM_REAL"  # SISTEM_REAL / NORMA_VENIT (transparenta calcul)


# ============================================================
#                    CALCUL
# ============================================================

def calculeaza_d212(
    venit_brut: float,
    cheltuieli_deductibile: float,
    an: int = 2025,
    salariu_minim: int = SALARIU_MINIM_2025,
    *,
    regim: str = "SISTEM_REAL",
    norma_anuala: float = 0.0,
    pensionar: bool = False,
    asigurat_salariat: bool = False,
    data_inceput=None,
    data_sfarsit=None,
) -> RezultatD212:
    """
    Calculeaza impozitul + CAS + CASS pentru un PFA, REGIM-AWARE.

    SISTEM_REAL (default): venit net = venit brut − cheltuieli deductibile;
      impozit 10% × (venit net − CAS − CASS). Comportament NESCHIMBAT (regresie 0).

    NORMA_VENIT: impozitarea e pe NORMA fixa, nu pe venitul real:
      - impozit = 10% × norma anuala (cheltuielile NU se scad);
      - CAS/CASS pe BAZA = norma (venitul net considerat = norma);
      - venitul brut/cheltuielile reale raman doar informativ (nu intra in calcul).

    PROPORTIONALIZARE MID-AN (PAS 4a, sursa ANAF Cluj „Completarea D212", 22 apr 2026):
      - NORMA prorata pe zile: cand activitatea acopera doar o parte din an
        (incepere SAU incetare mid-an), norma se inmulteste cu zile/365.
      - CAS la INCEPERE mid-an: plafonul de 12 SMB se recalculeaza proportional
        (12 SMB × luni/12); sub plafonul recalculat → CAS 0, peste → CAS pe baza
        recalculata. La INCETARE NU fortam o formula (zona legal ambigua) — doar
        semnalam sa se verifice cu un contabil.
      - CASS: praguri INTREGI, NEatins.
      - Fara date mid-an (default) → totul identic cu calculul actual (regresie 0).

    Args:
        venit_brut: total incasari din activitate (pe an)
        cheltuieli_deductibile: total cheltuieli deductibile (pe an)
        an: anul pentru care se face declaratia (default 2025)
        salariu_minim: salariul minim de referinta (default 4050)
        regim: "SISTEM_REAL" / "NORMA_VENIT"
        norma_anuala: norma de venit (lei/an) — folosita DOAR pe NORMA_VENIT
        data_inceput: data inceperii activitatii (date | ISO str | None)
        data_sfarsit: data incetarii activitatii (date | ISO str | None)

    Returns:
        RezultatD212 cu toate componentele + explicatii + avertismente.
    """
    venit_brut = max(0.0, float(venit_brut))
    cheltuieli = max(0.0, float(cheltuieli_deductibile))
    norma_anuala = max(0.0, float(norma_anuala or 0.0))
    pe_norma = (str(regim) == "NORMA_VENIT")

    # --- Context proportionalizare mid-an (sursa unica: app.domain.proportionalizare) ---
    # Fara date / activitate pe tot anul → incepere/incetare False, zile=365, luni=12
    # → toate ramurile de mai jos sunt identice cu calculul actual (regresie 0).
    incepere_mid_an = proportionalizare.este_incepere_mid_an(data_inceput, an)
    incetare = proportionalizare.este_incetare(data_sfarsit, an)
    partial = incepere_mid_an or incetare
    zile = proportionalizare.zile_activitate(data_inceput, data_sfarsit, an)
    luni = proportionalizare.luni_activitate(data_inceput, data_sfarsit, an)

    avert = [
        "Calcul ORIENTATIV. Verifica cu un contabil inainte de depunere — "
        "regulile D212 au exceptii si se schimba des.",
    ]

    if pe_norma:
        # Pe NORMA: baza de impozit + de contributii = norma fixa. Venitul net
        # raportat = norma (cheltuielile reale NU sunt deductibile pe norma).
        # MID-AN: norma se prorata pe zile/365 DOAR cand anul e partial (altfel
        # norma intreaga, bit-identic cu inainte).
        norma_efectiva = (
            proportionalizare.prorata_norma(norma_anuala, zile, an)
            if partial else norma_anuala
        )
        venit_net = round(norma_efectiva, 2)
        baza_contrib = norma_efectiva
    else:
        venit_net = round(venit_brut - cheltuieli, 2)
        baza_contrib = venit_net

    # --- CAS (pensie 25%) + CASS (sanatate 10%) — sursa unica: contributii ---
    # salariu_minim pasat explicit pentru a pastra exact comportamentul anterior.
    # Cazuri-limita (PAS 2): pensionar -> CAS 0 (art. 150). Pentru CASS, „asigurat prin
    # alta sursa" = salariat SAU pensionar (ambii sunt deja asigurati) -> 10% pe net real
    # sub 6 SMB (nu urca la baza minima). Default ambele False -> comportament neschimbat.
    #
    # MID-AN incepere (PAS 4a): plafonul CAS de 12 SMB se recalculeaza proportional
    # (12 SMB × luni/12, ANAF Cluj). plafon_recalc=None cand NU e incepere mid-an →
    # contributii ramane pe logica standard (regresie 0). La incetare NU recalculam.
    plafon_recalc = None
    if incepere_mid_an:
        plafon_anual_cas = contributii.plafon_cas_jos(an, salariu_minim)
        plafon_recalc = proportionalizare.plafon_cas_recalculat(plafon_anual_cas, luni)
    cas_r = contributii.calcul_cas(baza_contrib, an, salariu_minim=salariu_minim,
                                   pensionar=pensionar, plafon_recalculat=plafon_recalc)
    cas = cas_r["valoare"]
    cas_baza = cas_r["baza"]
    cas_expl = cas_r["nota"]

    asigurat_cass = bool(asigurat_salariat or pensionar)
    cass_r = contributii.calcul_cass(baza_contrib, an, salariu_minim=salariu_minim,
                                     asigurat_salariat=asigurat_cass)
    cass = cass_r["valoare"]
    cass_baza = cass_r["baza"]
    cass_expl = cass_r["nota"]

    # --- Impozit ---
    if pe_norma:
        # Pe NORMA: impozit = 10% × norma (NU se deduc CAS/CASS din norma).
        # MID-AN: baza = norma PRORATA (= venit_net), nu norma intreaga. Pe an
        # intreg venit_net == norma_anuala (regresie 0).
        venit_impozabil = max(0.0, round(venit_net, 2))
    else:
        # Sistem real: impozit 10% pe (venit net − CAS − CASS).
        venit_impozabil = max(0.0, round(venit_net - cas - cass, 2))
    impozit = round(venit_impozabil * COTA_IMPOZIT, 2)

    total = round(cas + cass + impozit, 2)
    bonificatie = round(impozit * COTA_BONIFICATIE, 2)
    total_cu_bonif = round(total - bonificatie, 2)

    if pe_norma:
        avert.append(
            "Impozitare pe NORMA de venit: impozit 10% × norma anuala; "
            "cheltuielile NU sunt deductibile, iar CAS/CASS se calculeaza pe norma."
        )
        if norma_anuala <= 0:
            avert.append(
                "Norma anuala nu e completata in profil — impozitul apare 0. "
                "Completeaza valoarea normei (din decizia AJFP a judetului)."
            )
    elif venit_net <= 0:
        avert.append("Venit net 0 sau pierdere: depui D212 cu valori 0 "
                     "(daca PFA-ul nu e suspendat).")

    # --- Proportionalizare mid-an (PAS 4a) — avertismente ---
    if partial and pe_norma:
        avert.append(
            f"Activitate partiala in {an}: norma s-a prorata pe {zile} zile "
            f"({zile}/365 din norma anuala)."
        )
    if incepere_mid_an:
        avert.append(
            f"Incepere activitate in cursul anului ({luni} luni active): plafonul CAS "
            f"s-a recalculat proportional la {plafon_recalc:.0f} lei (12 SMB × {luni}/12). "
            f"⚠️ Surse oficiale CONTRADICTORII: Legea 296/2023 a eliminat recalcularea "
            f"CAS la incepere mid-an din 2024, dar documentul ANAF Cluj «Completarea D212» "
            f"(2026) o descrie ca activa. Aplicam recalcularea (sursa ANAF cea mai recenta), "
            f"dar RE-VALIDEAZA cu un contabil CECCAR inainte de a te baza pe ea."
        )
    if incetare:
        avert.append(
            "Incetare activitate in cursul anului: recalcularea CAS la incetare e o "
            "zona legal AMBIGUA (ANAF a recunoscut ca normele nu-s actualizate). "
            "Norma s-a prorata pe zilele de activitate, dar pentru CAS verifica "
            "recalcularea cu un contabil — NU am fortat o formula."
        )

    return RezultatD212(
        an=an, salariu_minim=salariu_minim,
        venit_brut=venit_brut, cheltuieli=cheltuieli, venit_net=venit_net,
        cas=cas, cas_baza=cas_baza, cas_explicatie=cas_expl,
        cass=cass, cass_baza=cass_baza, cass_explicatie=cass_expl,
        venit_impozabil=venit_impozabil, impozit=impozit,
        total_plata=total, bonificatie=bonificatie,
        total_cu_bonificatie=total_cu_bonif,
        avertismente=avert,
        regim=("NORMA_VENIT" if pe_norma else "SISTEM_REAL"),
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
        L.append(
            f"   _Dacă depui și achiți INTEGRAL (impozit + CAS + CASS) până pe "
            f"15 aprilie → plătești {r.total_cu_bonificatie:,.0f} lei._".replace(",", ".")
        )
        L.append(
            f"   _Reducerea de 3% e DOAR pe impozit (−{r.bonificatie:,.0f} lei); "
            f"CAS și CASS nu se reduc._".replace(",", ".")
        )
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
