"""
Teste pentru sursa unica de contributii CAS/CASS (Problema #3).

Sursa: app.domain.contributii.
Valori de referinta (SMB plafoane = 4050, valabil 2025 SI 2026):
  6 SMB = 24.300 | 12 SMB = 48.600 | 24 SMB = 97.200
Plafon SUPERIOR CASS depinde de an (Legea 141/2025):
  60 SMB = 243.000 (venituri 2025) | 72 SMB = 291.600 (venituri 2026+)
"""

import pytest

from app.domain.contributii import (
    calcul_cas,
    calcul_cass,
    salariu_minim,
    _params,
)

SMB = 4050


# ────────────────────────────────────────────────────────────
# A. CAS — praguri (an 2026, SMB 4050)
# ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("venit, asteptat, baza_ast", [
    (40_000, 0.0, 0.0),          # < 12 SMB (48.600) -> 0
    (48_600, 12_150.0, 48_600),  # = 12 SMB (frontiera) -> baza 12 SMB
    (60_000, 12_150.0, 48_600),  # 12-24 SMB -> baza 12 SMB
    (97_200, 24_300.0, 97_200),  # = 24 SMB -> baza 24 SMB
    (300_000, 24_300.0, 97_200), # > 24 SMB -> baza plafon 24 SMB
])
def test_cas_praguri(venit, asteptat, baza_ast):
    r = calcul_cas(venit, 2026)
    assert r["valoare"] == asteptat
    assert r["baza"] == baza_ast


def test_cas_pensionar_scutit():
    r = calcul_cas(60_000, 2026, pensionar=True)
    assert r["valoare"] == 0.0
    assert r["aplicabil"] is False


def test_cas_baza_aleasa_mai_mare():
    # contribuabilul alege o baza peste minim (pensie mai mare)
    r = calcul_cas(60_000, 2026, baza_aleasa=80_000)
    assert r["baza"] == 80_000
    assert r["valoare"] == 20_000.0  # 80.000 * 25%


def test_cas_baza_aleasa_sub_minim_ignorata():
    r = calcul_cas(60_000, 2026, baza_aleasa=10_000)  # sub baza minima 48.600
    assert r["baza"] == 48_600
    assert r["valoare"] == 12_150.0


# ────────────────────────────────────────────────────────────
# B. CASS — praguri. Plafonul SUPERIOR depinde de an (Legea 141/2025):
#    60 SMB = 243.000 (2025) | 72 SMB = 291.600 (2026+). SMB plafoane = 4050.
# ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("venit, an, asteptat, baza_ast", [
    # sub plafon — identic pe ambii ani
    (15_000, 2026, 2_430.0, 24_300),    # < 6 SMB -> baza MINIMA 6 SMB (NU 0!)
    (24_300, 2026, 2_430.0, 24_300),    # = 6 SMB -> venit real = 6 SMB
    (60_000, 2026, 6_000.0, 60_000),    # peste podea, sub plafon -> 10% pe venit real
    # plafon 2025 = 60 SMB = 243.000 -> CASS max 24.300 (REGRESIE 0)
    (243_000, 2025, 24_300.0, 243_000), # = 60 SMB (2025)
    (500_000, 2025, 24_300.0, 243_000), # > 60 SMB -> plafonat la 60 SMB (2025)
    # plafon 2026 = 72 SMB = 291.600 -> CASS max 29.160 (Legea 141/2025)
    (243_000, 2026, 24_300.0, 243_000), # sub plafonul 2026 -> 10% pe real (DIFERA de 2025)
    (291_600, 2026, 29_160.0, 291_600), # = 72 SMB (2026)
    (500_000, 2026, 29_160.0, 291_600), # > 72 SMB -> plafonat la 72 SMB (2026)
])
def test_cass_praguri(venit, an, asteptat, baza_ast):
    r = calcul_cass(venit, an)
    assert r["valoare"] == asteptat
    assert r["baza"] == baza_ast


def test_cass_sub_prag_nu_e_zero():
    # regresia bug-ului din tax_calculator: sub 6 SMB NU e 0, e minimul pe 6 SMB
    r = calcul_cass(15_000, 2026)
    assert r["valoare"] == 2_430.0
    assert r["aplicabil"] is True


def test_cass_asigurat_salariat_sub_prag_pe_net_real():
    # CORECTIE (varianta b): asigurat prin alta sursa + sub 6 SMB → 10% × net REAL
    # (NU 0, NU minimul 2.430). Confirmare numerica: 13.950 → 1.395.
    r = calcul_cass(13_950, 2026, asigurat_salariat=True)
    assert r["valoare"] == 1_395.0
    assert r["baza"] == 13_950.0
    assert r["aplicabil"] is True
    # generic: 15.000 → 1.500
    assert calcul_cass(15_000, 2026, asigurat_salariat=True)["valoare"] == 1_500.0


def test_cass_venit_zero_sau_pierdere():
    assert calcul_cass(0, 2026)["valoare"] == 0.0
    assert calcul_cass(-5_000, 2026)["valoare"] == 0.0


# ────────────────────────────────────────────────────────────
# C. Parametri pe an — regresie anti-4325
# ────────────────────────────────────────────────────────────

def test_smb_2026_e_4050_nu_4325():
    assert salariu_minim(2026) == 4050
    assert _params(2026)["salariu_minim"] == 4050


def test_cas_60k_2026_e_12150_nu_12975():
    # guard explicit pe valoarea GRESITA care ar rezulta din SMB=4325
    r = calcul_cas(60_000, 2026)
    assert r["valoare"] == 12_150.0
    assert r["valoare"] != 12_975.0  # = ce ar da 4325 (gresit)


def test_2025_si_2026_difera_doar_plafon_cass():
    # 2025 si 2026 au parametri IDENTICI cu o singura exceptie: plafonul superior
    # CASS urca 60->72 SMB pentru venituri 2026+ (Legea 141/2025). Sub plafonul
    # 2025 (243.000) totul e identic; CAS ramane identic pe orice venit (plafon
    # CAS 24 SMB neschimbat).
    for venit in (15_000, 60_000, 200_000):   # toate sub 243.000
        assert calcul_cas(venit, 2025) == calcul_cas(venit, 2026)
        assert calcul_cass(venit, 2025) == calcul_cass(venit, 2026)
    # CAS — identic chiar si la venit mare (plafon CAS neschimbat)
    assert calcul_cas(300_000, 2025) == calcul_cas(300_000, 2026)
    # CASS — DIFERA peste plafonul 2025: 2025 plafonat la 24.300, 2026 urca la 29.160
    assert calcul_cass(300_000, 2025)["valoare"] == 24_300.0
    assert calcul_cass(300_000, 2026)["valoare"] == 29_160.0


def test_an_necunoscut_fallback_ultim():
    # an in afara tabelului -> foloseste ultimul an cunoscut (2026)
    assert calcul_cas(60_000, 2099)["valoare"] == calcul_cas(60_000, 2026)["valoare"]


# ────────────────────────────────────────────────────────────
# D. Echivalenta cu d212_calc ACTUAL (lock anti-regresie D212)
# ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("venit_net", [20_000, 50_000, 60_000, 100_000, 300_000])
@pytest.mark.parametrize("an", [2025, 2026])
def test_echivalenta_cu_d212_calc(venit_net, an):
    from app.integrations.anaf import d212_calc
    r = d212_calc.calculeaza_d212(venit_brut=venit_net, cheltuieli_deductibile=0, an=an)
    assert calcul_cas(venit_net, an)["valoare"] == r.cas
    assert calcul_cass(venit_net, an)["valoare"] == r.cass


# ────────────────────────────────────────────────────────────
# E. Rotunjire — 2 zecimale (pastreaza D212 bit-identic)
# ────────────────────────────────────────────────────────────

def test_cass_rotunjire_2_zecimale():
    # venit non-rotund in banda 6-60 SMB -> 10% poate avea zecimale
    r = calcul_cass(55_555, 2026)
    assert r["valoare"] == 5_555.5  # 55.555 * 0.10, rotunjit la 2 zecimale
