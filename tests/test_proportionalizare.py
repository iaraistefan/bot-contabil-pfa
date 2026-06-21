"""
PAS 4a — proportionalizare mid-an (D212).

Sursa primara: ANAF Cluj „Completarea D212", 22 apr 2026 (confirmat 2026):
  - NORMA prorata pe zile/365 (denominator FIX). Confirmat ANAF/SOLO:
    48.600 × 122 / 365 = 16.244.
  - CAS la INCEPERE mid-an: plafonul de 12 SMB se recalculeaza proportional
    (12 SMB × luni/12); venit ≤ plafon recalculat → CAS 0; peste → CAS pe baza
    recalculata.
  - CAS la INCETARE: zona ambigua — DOAR semnal, NU formula fortata.
  - CASS: praguri INTREGI, neatins.
  - Fara date mid-an → calcul IDENTIC cu actualul (regresie 0).
"""

from datetime import date

import pytest

from app.domain import proportionalizare as prop
from app.domain import contributii
from app.integrations.anaf.d212_calc import calculeaza_d212, COTA_IMPOZIT

AN = 2026
SMB = 4050
PLAFON_CAS_JOS = 12 * SMB            # 48.600 (12 SMB)


# ════════════════════════════════════════════════════════════
#   HELPER PUR — zile / luni / prorata / plafon recalculat
# ════════════════════════════════════════════════════════════

def test_zile_activitate_incepere_1_septembrie():
    # 1 sept → 31 dec inclusiv = 122 zile (exemplul ANAF/SOLO)
    assert prop.zile_activitate(date(AN, 9, 1), None, AN) == 122


def test_zile_activitate_an_intreg_365():
    assert prop.zile_activitate(None, None, AN) == 365
    # date in afara anului → clampate la 1 ian / 31 dec → tot 365
    assert prop.zile_activitate(date(2020, 3, 1), date(2030, 1, 1), AN) == 365


def test_luni_activitate_prima_luna_e_luna_inceput():
    # sept, oct, nov, dec = 4 luni (prima luna = luna depunerii D212)
    assert prop.luni_activitate(date(AN, 9, 1), None, AN) == 4
    assert prop.luni_activitate(None, None, AN) == 12


def test_predicate_incepere_incetare():
    assert prop.este_incepere_mid_an(date(AN, 9, 1), AN) is True
    assert prop.este_incepere_mid_an(date(AN, 1, 1), AN) is False   # 1 ian NU e mid-an
    assert prop.este_incepere_mid_an(date(2025, 6, 1), AN) is False  # an anterior → intreg
    assert prop.este_incetare(date(AN, 6, 30), AN) is True
    assert prop.este_incetare(date(AN, 12, 31), AN) is False         # 31 dec NU e incetare
    assert prop.este_incetare(None, AN) is False


def test_prorata_norma_exemplul_confirmat_anaf():
    # ⭐ Cifra confirmata: 48.600 × 122 / 365 = 16.244 (rotunjit la leu)
    val = prop.prorata_norma(48_600, 122)
    assert round(val) == 16_244
    assert val == round(48_600 * 122 / 365, 2)       # 16.244,38 exact


def test_prorata_norma_an_intreg_identitate():
    # 365 zile → norma intreaga (denominator fix 365) → regresie 0
    assert prop.prorata_norma(48_600, 365) == 48_600.0


def test_plafon_cas_recalculat_formula_anaf():
    # „(plafon / 12 luni) × Numar luni" — 4 luni → 48.600 × 4/12 = 16.200
    assert prop.plafon_cas_recalculat(PLAFON_CAS_JOS, 4) == 16_200.0
    assert prop.plafon_cas_recalculat(PLAFON_CAS_JOS, 12) == float(PLAFON_CAS_JOS)


def test_plafon_cas_jos_sursa_unica():
    # contributii expune plafonul de 12 SMB folosit la recalcul (single source)
    assert contributii.plafon_cas_jos(AN, SMB) == float(PLAFON_CAS_JOS)


# ════════════════════════════════════════════════════════════
#   NORMA mid-an — prorata in MOTOR (cifra confirmata)
# ════════════════════════════════════════════════════════════

def test_norma_mid_an_16244_in_motor():
    # ⭐ norma 48.600, incepere 1 sept → venit impozabil = 48.600 × 122/365 = 16.244
    r = calculeaza_d212(0, 0, an=AN, salariu_minim=SMB,
                        regim="NORMA_VENIT", norma_anuala=48_600,
                        data_inceput=date(AN, 9, 1))
    assert round(r.venit_net) == 16_244                       # norma prorata
    assert round(r.venit_impozabil) == 16_244
    assert r.impozit == round(r.venit_net * COTA_IMPOZIT, 2)  # impozit pe norma prorata
    # avertisment despre prorata pe zile
    assert any("prorata" in a.lower() and "122" in a for a in r.avertismente)


def test_norma_mid_an_accepta_iso_string():
    # profilul expune ISO str — motorul trebuie sa o parseze identic cu obiectul date
    r_str = calculeaza_d212(0, 0, an=AN, salariu_minim=SMB, regim="NORMA_VENIT",
                            norma_anuala=48_600, data_inceput="2026-09-01")
    r_date = calculeaza_d212(0, 0, an=AN, salariu_minim=SMB, regim="NORMA_VENIT",
                             norma_anuala=48_600, data_inceput=date(AN, 9, 1))
    assert r_str.venit_net == r_date.venit_net == round(48_600 * 122 / 365, 2)


# ════════════════════════════════════════════════════════════
#   CAS la INCEPERE mid-an — plafon recalculat
# ════════════════════════════════════════════════════════════

def test_cas_incepere_venit_sub_plafon_recalculat_zero():
    # incepere 1 sept → plafon recalculat = 16.200. Net 16.000 ≤ 16.200 → CAS 0
    r = calculeaza_d212(16_000, 0, an=AN, salariu_minim=SMB, data_inceput=date(AN, 9, 1))
    assert r.cas == 0.0


def test_cas_incepere_venit_peste_plafon_recalculat():
    # Net 20.000 > 16.200 → CAS pe baza recalculata = 16.200 × 25% = 4.050
    r = calculeaza_d212(20_000, 0, an=AN, salariu_minim=SMB, data_inceput=date(AN, 9, 1))
    assert r.cas_baza == 16_200.0
    assert r.cas == round(16_200 * 0.25, 2)                   # 4.050
    assert any("recalculat" in a.lower() and "CECCAR" in a for a in r.avertismente)


def test_cas_incepere_contrast_cu_an_intreg():
    # Acelasi net (20.000): an INTREG → sub 12 SMB → CAS 0; INCEPERE mid-an → CAS 4.050.
    # Exact diferenta pe care o aduce recalcularea plafonului.
    intreg = calculeaza_d212(20_000, 0, an=AN, salariu_minim=SMB)
    mid = calculeaza_d212(20_000, 0, an=AN, salariu_minim=SMB, data_inceput=date(AN, 9, 1))
    assert intreg.cas == 0.0
    assert mid.cas == 4_050.0


def test_contributii_override_plafon_recalculat_direct():
    # Override direct in sursa unica (contributii)
    sub = contributii.calcul_cas(16_000, AN, salariu_minim=SMB, plafon_recalculat=16_200)
    peste = contributii.calcul_cas(20_000, AN, salariu_minim=SMB, plafon_recalculat=16_200)
    assert sub["valoare"] == 0.0 and sub["aplicabil"] is False
    assert peste["valoare"] == 4_050.0 and peste["baza"] == 16_200.0
    # pensionarul ramane scutit chiar si cu plafon recalculat (art. 150)
    pens = contributii.calcul_cas(20_000, AN, salariu_minim=SMB,
                                  plafon_recalculat=16_200, pensionar=True)
    assert pens["valoare"] == 0.0


# ════════════════════════════════════════════════════════════
#   INCETARE — semnal de prudenta, FARA formula fortata
# ════════════════════════════════════════════════════════════

def test_incetare_semnal_prudenta_nu_formula():
    # sfarsit 30 iunie, norma → norma prorata, dar CAS NU se recalculeaza (ambiguu)
    r = calculeaza_d212(0, 0, an=AN, salariu_minim=SMB, regim="NORMA_VENIT",
                        norma_anuala=48_600, data_sfarsit=date(AN, 6, 30))
    # norma prorata pe zile (1 ian → 30 iun = 181 zile) → sub norma intreaga
    assert r.venit_net == round(48_600 * 181 / 365, 2)
    assert r.venit_net < 48_600
    # semnal explicit: ambiguu + contabil, NU formula fortata
    assert any("incetare" in a.lower() and "contabil" in a.lower()
               and "ambigu" in a.lower() for a in r.avertismente)
    # CAS pe cale STANDARD (nu recalculat): nota CAS nu mentioneaza recalcul mid-an
    assert "recalculat" not in r.cas_explicatie.lower()


# ════════════════════════════════════════════════════════════
#   REGRESIE 0 — an intreg / fara date == calcul actual
# ════════════════════════════════════════════════════════════

def _egal(a, b):
    return (a.venit_net, a.cas, a.cass, a.impozit, a.total_plata, a.bonificatie) == \
           (b.venit_net, b.cas, b.cass, b.impozit, b.total_plata, b.bonificatie)


def test_regresie_fara_date_neschimbat_real():
    baza = calculeaza_d212(90_000, 30_000, an=AN, salariu_minim=SMB)
    cu_none = calculeaza_d212(90_000, 30_000, an=AN, salariu_minim=SMB,
                              data_inceput=None, data_sfarsit=None)
    assert _egal(baza, cu_none)


def test_regresie_an_intreg_explicit_neschimbat_real():
    # 1 ian → 31 dec = an intreg → NU e mid-an → identic cu fara date
    baza = calculeaza_d212(90_000, 30_000, an=AN, salariu_minim=SMB)
    intreg = calculeaza_d212(90_000, 30_000, an=AN, salariu_minim=SMB,
                             data_inceput=date(AN, 1, 1), data_sfarsit=date(AN, 12, 31))
    assert _egal(baza, intreg)


def test_regresie_an_intreg_neschimbat_norma():
    baza = calculeaza_d212(0, 0, an=AN, salariu_minim=SMB,
                           regim="NORMA_VENIT", norma_anuala=50_000)
    intreg = calculeaza_d212(0, 0, an=AN, salariu_minim=SMB, regim="NORMA_VENIT",
                             norma_anuala=50_000, data_inceput=date(AN, 1, 1))
    assert _egal(baza, intreg)
    assert intreg.venit_impozabil == 50_000                  # norma intreaga, neprorata
