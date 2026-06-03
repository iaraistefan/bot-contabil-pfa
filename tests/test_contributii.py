"""
Teste pentru sursa unica de contributii CAS/CASS (Problema #3).

Sursa: app.domain.contributii.
Valori de referinta (SMB plafoane = 4050, valabil 2025 SI 2026):
  6 SMB = 24.300 | 12 SMB = 48.600 | 24 SMB = 97.200 | 60 SMB = 243.000
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
# B. CASS — praguri (an 2026, SMB 4050)
# ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("venit, asteptat, baza_ast", [
    (15_000, 2_430.0, 24_300),   # < 6 SMB -> baza MINIMA 6 SMB (NU 0!)
    (24_300, 2_430.0, 24_300),   # = 6 SMB -> venit real = 6 SMB
    (60_000, 6_000.0, 60_000),   # 6-60 SMB -> 10% pe venit real
    (243_000, 24_300.0, 243_000),# = 60 SMB
    (500_000, 24_300.0, 243_000),# > 60 SMB -> plafon 60 SMB
])
def test_cass_praguri(venit, asteptat, baza_ast):
    r = calcul_cass(venit, 2026)
    assert r["valoare"] == asteptat
    assert r["baza"] == baza_ast


def test_cass_sub_prag_nu_e_zero():
    # regresia bug-ului din tax_calculator: sub 6 SMB NU e 0, e minimul pe 6 SMB
    r = calcul_cass(15_000, 2026)
    assert r["valoare"] == 2_430.0
    assert r["aplicabil"] is True


def test_cass_asigurat_salariat_sub_prag_scutit():
    r = calcul_cass(15_000, 2026, asigurat_salariat=True)
    assert r["valoare"] == 0.0
    assert r["aplicabil"] is False


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


def test_2025_si_2026_identice():
    for venit in (15_000, 60_000, 300_000):
        assert calcul_cas(venit, 2025) == calcul_cas(venit, 2026)
        assert calcul_cass(venit, 2025) == calcul_cass(venit, 2026)


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
