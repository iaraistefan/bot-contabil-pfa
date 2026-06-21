"""
PAS 4b — activitate mixtă (split temporal normă → real).

Sursă: OPANAF formular D212 pct. 3.5.11 — adăugarea unei activități NEeligibile pentru
normă în cursul anului → sistem real DE LA DATA respectivă. Venit net anual = fracțiunea
din normă (perioada pe normă, până la data adăugării) + venitul net real (perioada de
după). NU retroactiv tot anul — split temporal.

Granularitate (documentată): normă pe ZILE (ANAF) + real pe LUNI (pragul = luna
data_adăugare, însumat de tax_engine). Inconsistență de câteva zile la graniță, acceptată.
"""

from datetime import date

import pytest

from app.domain import proportionalizare as prop
from app.domain import norma_venit
from app.integrations.anaf.d212_calc import calculeaza_d212, COTA_IMPOZIT
from app.services import tax_engine

AN = 2026
SMB = 4050
NORMA = 48_600.0


# ════════════════════════════════════════════════════════════
#   GARDIAN — predicat sursă unică (normă + flag + dată → split)
# ════════════════════════════════════════════════════════════

def test_predicat_split_aplicat():
    assert norma_venit.activitate_mixta_split_de_la("NORMA_VENIT", True, "2026-09-01", AN) == date(AN, 9, 1)
    assert norma_venit.activitate_mixta_split_de_la("NORMA_VENIT", True, date(AN, 9, 1), AN) == date(AN, 9, 1)


def test_predicat_split_neaplicat():
    # regim real → fără split (deja pe real)
    assert norma_venit.activitate_mixta_split_de_la("SISTEM_REAL", True, "2026-09-01", AN) is None
    # flag neactivat → fără split
    assert norma_venit.activitate_mixta_split_de_la("NORMA_VENIT", False, "2026-09-01", AN) is None
    # dată lipsă → fără split (apelantul avertizează, nu inventează cifră)
    assert norma_venit.activitate_mixta_split_de_la("NORMA_VENIT", True, None, AN) is None
    # 1 ianuarie → real tot anul, fără fracțiune de normă
    assert norma_venit.activitate_mixta_split_de_la("NORMA_VENIT", True, "2026-01-01", AN) is None
    # dată în alt an → fără split pentru anul curent
    assert norma_venit.activitate_mixta_split_de_la("NORMA_VENIT", True, "2025-09-01", AN) is None


# ════════════════════════════════════════════════════════════
#   HELPER — zile pe norma (sub-interval până la data adăugării)
# ════════════════════════════════════════════════════════════

def test_zile_pe_norma_pana_la():
    # 1 ian → 31 aug (ziua dinaintea lui 1 sept) = 243 zile
    assert prop.zile_pe_norma_pana_la(None, date(AN, 9, 1), AN) == 243
    # refolosește prorata_norma EXACT pe sub-interval (helper 4a neatins)
    assert prop.prorata_norma(NORMA, 243, AN) == round(NORMA * 243 / 365, 2)


# ════════════════════════════════════════════════════════════
#   MOTOR — split: normă prorata + real, numeric verificat
# ════════════════════════════════════════════════════════════

def test_split_venit_net_norma_prorata_plus_real():
    # adăugare 1 sept → normă pe Jan1..Aug31 (243 zile) + real pe perioada de după
    r = calculeaza_d212(0, 0, an=AN, salariu_minim=SMB, regim="NORMA_VENIT",
                        norma_anuala=NORMA, are_activitate_neeligibila=True,
                        data_adaugare=date(AN, 9, 1),
                        venit_brut_post=30_000, cheltuieli_post=5_000)
    norma_half = prop.prorata_norma(NORMA, 243, AN)      # jumătatea normă, deterministă
    real_half = 25_000.0                                  # 30.000 − 5.000
    assert r.venit_net == round(norma_half + real_half, 2)
    assert r.regim == "NORMA_VENIT"


def test_split_jumatatea_norma_determinista():
    # cheltuielile reale NU ating jumătatea normă (e fixă pe zile_pre)
    a = calculeaza_d212(0, 0, an=AN, salariu_minim=SMB, regim="NORMA_VENIT", norma_anuala=NORMA,
                        are_activitate_neeligibila=True, data_adaugare=date(AN, 9, 1),
                        venit_brut_post=30_000, cheltuieli_post=0)
    b = calculeaza_d212(0, 0, an=AN, salariu_minim=SMB, regim="NORMA_VENIT", norma_anuala=NORMA,
                        are_activitate_neeligibila=True, data_adaugare=date(AN, 9, 1),
                        venit_brut_post=30_000, cheltuieli_post=20_000)
    norma_half = prop.prorata_norma(NORMA, 243, AN)
    # diferența de venit net = diferența de cheltuieli reale (20.000), normă neschimbată
    assert round(a.venit_net - b.venit_net, 2) == 20_000.0
    assert a.venit_net == round(norma_half + 30_000, 2)


def test_split_cas_cass_pe_combinat():
    r = calculeaza_d212(0, 0, an=AN, salariu_minim=SMB, regim="NORMA_VENIT", norma_anuala=NORMA,
                        are_activitate_neeligibila=True, data_adaugare=date(AN, 9, 1),
                        venit_brut_post=30_000, cheltuieli_post=5_000)
    # CAS/CASS pe net-ul COMBINAT (≈57.355) → CAS baza 12 SMB (între 12 și 24), CASS 10% pe net
    assert r.cas == round(12 * SMB * 0.25, 2)            # 12.150 (combinat ∈ [12,24) SMB)
    assert r.cass == round(r.venit_net * 0.10, 2)        # 10% pe net combinat


def test_split_impozit_norma_fara_deducere_real_cu_deducere():
    r = calculeaza_d212(0, 0, an=AN, salariu_minim=SMB, regim="NORMA_VENIT", norma_anuala=NORMA,
                        are_activitate_neeligibila=True, data_adaugare=date(AN, 9, 1),
                        venit_brut_post=30_000, cheltuieli_post=5_000)
    norma_half = prop.prorata_norma(NORMA, 243, AN)
    real_half = 25_000.0
    # impozabil = normă (fără deducere) + max(0, real − CAS − CASS)
    asteptat = norma_half + max(0.0, real_half - r.cas - r.cass)
    assert r.impozit == round(asteptat * COTA_IMPOZIT, 2)
    # avertisment explicit despre split + CECCAR
    assert any("MIXTA" in a and "CECCAR" in a for a in r.avertismente)


# ════════════════════════════════════════════════════════════
#   INTERACȚIUNE PAS 4a — start mid-an + activitate mixtă
# ════════════════════════════════════════════════════════════

def test_interactiune_4a_start_midan_plus_mixt():
    # start 1 martie (4a) + adăugare neeligibilă 1 sept (4b) → normă pe Mar1..Aug31 (184 zile)
    r = calculeaza_d212(0, 0, an=AN, salariu_minim=SMB, regim="NORMA_VENIT", norma_anuala=NORMA,
                        data_inceput=date(AN, 3, 1),
                        are_activitate_neeligibila=True, data_adaugare=date(AN, 9, 1),
                        venit_brut_post=30_000, cheltuieli_post=5_000)
    norma_half = prop.prorata_norma(NORMA, 184, AN)      # Mar1..Aug31 = 184 zile
    assert r.venit_net == round(norma_half + 25_000, 2)
    # CAS: start mid-an (4a) → plafon recalculat (10 luni active: Mar..Dec) = 48.600 × 10/12
    assert r.cas_baza == round(12 * SMB * 10 / 12, 2)    # 40.500


# ════════════════════════════════════════════════════════════
#   REGRESIE 0 — fără flag → calcul actual identic
# ════════════════════════════════════════════════════════════

def _egal(a, b):
    return (a.venit_net, a.cas, a.cass, a.impozit, a.total_plata, a.bonificatie) == \
           (b.venit_net, b.cas, b.cass, b.impozit, b.total_plata, b.bonificatie)


def test_regresie_fara_flag_norma_neschimbat():
    baza = calculeaza_d212(0, 0, an=AN, salariu_minim=SMB, regim="NORMA_VENIT", norma_anuala=NORMA)
    # parametri mixt prezenți dar flag False → fără split → normă întreagă
    fals = calculeaza_d212(0, 0, an=AN, salariu_minim=SMB, regim="NORMA_VENIT", norma_anuala=NORMA,
                           are_activitate_neeligibila=False, data_adaugare=date(AN, 9, 1),
                           venit_brut_post=30_000, cheltuieli_post=5_000)
    assert _egal(baza, fals)
    assert fals.venit_impozabil == NORMA                 # normă întreagă, nu split


def test_regresie_real_neschimbat():
    baza = calculeaza_d212(90_000, 30_000, an=AN, salariu_minim=SMB)
    # pe regim real, flag-ul mixt e irelevant (predicatul cere NORMA_VENIT)
    cu = calculeaza_d212(90_000, 30_000, an=AN, salariu_minim=SMB,
                         are_activitate_neeligibila=True, data_adaugare=date(AN, 9, 1))
    assert _egal(baza, cu)


# ════════════════════════════════════════════════════════════
#   BUCKETARE REALĂ (tax_engine) — doar lunile post-adăugare
# ════════════════════════════════════════════════════════════

def _patch_mixt(monkeypatch, inc_per_luna, exp_per_luna):
    monkeypatch.setattr(tax_engine, "compute_period",
                        lambda *a, **k: {"income_total": inc_per_luna,
                                         "expense_deductible_total": exp_per_luna})
    import app.repositories.users as users_repo
    monkeypatch.setattr(users_repo, "get_profile_dict",
                        lambda s, uid: {"regim_impunere": "NORMA_VENIT", "activity_code": "ridesharing",
                                        "norma_venit_anuala": NORMA,
                                        "are_activitate_neeligibila_norma": True,
                                        "data_activitate_neeligibila": "2026-09-01"})


def test_bucketare_doar_luni_post_adaugare(monkeypatch):
    # 1000/lună income, 200/lună cheltuieli; adăugare 1 sept → DOAR lunile 9-12 (4 luni)
    _patch_mixt(monkeypatch, 1_000.0, 200.0)
    r = tax_engine._compute_d212_anual_uncached(object(), user_id=1, an=AN)
    # real_net_post = 4 × (1000 − 200) = 3.200; normă pe Jan1..Aug31 (243 zile)
    norma_half = prop.prorata_norma(NORMA, 243, AN)
    assert r.venit_net == round(norma_half + 3_200, 2)


def test_bucketare_granita_luna(monkeypatch):
    # pragul e LUNA data_adăugare (1 sept = luna 9): lunile 1-8 excluse, 9-12 incluse
    _patch_mixt(monkeypatch, 1_200.0, 0.0)
    r = tax_engine._compute_d212_anual_uncached(object(), user_id=1, an=AN)
    norma_half = prop.prorata_norma(NORMA, 243, AN)
    assert r.venit_net == round(norma_half + 4 * 1_200, 2)   # 4 luni post (9,10,11,12)
