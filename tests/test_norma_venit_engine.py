"""
PAS 1 — motor D212 REGIM-AWARE (normă vs sistem real) + nomenclator + gardian tranziție.

Bug latent reparat: calea D212 (numărul afișat peste tot) ignora regim_impunere și calcula
mereu sistem real. Acum: NORMA_VENIT → impozit 10% × normă (cheltuielile NU reduc baza;
CAS/CASS pe normă). Reverse-charge/D100/D301/D390 NEatinse (deja regim-independente).
"""

import pytest

from app.integrations.anaf.d212_calc import calculeaza_d212, COTA_IMPOZIT
from app.integrations.anaf import declaratii_service as decl
from app.domain import norma_venit
from app.services import tax_engine

AN = 2026
SMB = 4050
NORMA = 50_000.0   # ∈ [12×4050=48.600, 24×4050=97.200) → CAS pe 48.600; CASS pe 50.000


# ════════════ D212 pe NORMĂ ════════════
def test_norma_impozit_pe_norma_nu_pe_venit_real():
    # impozit = 10% × normă, INDIFERENT de venitul/cheltuielile reale
    r = calculeaza_d212(venit_brut=200_000, cheltuieli_deductibile=80_000,
                        an=AN, salariu_minim=SMB, regim="NORMA_VENIT", norma_anuala=NORMA)
    assert r.regim == "NORMA_VENIT"
    assert r.venit_impozabil == NORMA                 # baza impozit = norma (nu net real)
    assert r.impozit == round(NORMA * COTA_IMPOZIT, 2)  # 5000


def test_norma_cheltuielile_nu_reduc_baza():
    # aceeași normă, cheltuieli DIFERITE → impozit/CAS/CASS IDENTICE (cheltuieli nedeductibile)
    fara = calculeaza_d212(120_000, 0, an=AN, salariu_minim=SMB,
                           regim="NORMA_VENIT", norma_anuala=NORMA)
    cu = calculeaza_d212(120_000, 90_000, an=AN, salariu_minim=SMB,
                         regim="NORMA_VENIT", norma_anuala=NORMA)
    assert (fara.impozit, fara.cas, fara.cass) == (cu.impozit, cu.cas, cu.cass)


def test_norma_cas_cass_pe_baza_norma():
    r = calculeaza_d212(0, 0, an=AN, salariu_minim=SMB,
                        regim="NORMA_VENIT", norma_anuala=NORMA)
    # CAS: norma ≥ 12 SMB și < 24 SMB → baza 12 SMB = 48.600 → 25% = 12.150
    assert r.cas_baza == 12 * SMB and r.cas == round(12 * SMB * 0.25, 2)
    # CASS: norma ∈ [6 SMB, 60 SMB] → 10% × normă (pe normă, nu pe venit real)
    assert r.cass_baza == NORMA and r.cass == round(NORMA * 0.10, 2)


def test_norma_necompletata_impozit_zero_plus_avertisment():
    r = calculeaza_d212(100_000, 20_000, an=AN, salariu_minim=SMB,
                        regim="NORMA_VENIT", norma_anuala=0.0)
    assert r.impozit == 0.0
    assert any("norma" in a.lower() and "completeaza" in a.lower() for a in r.avertismente)


# ════════════ D212 pe REAL — REGRESSION (neschimbat) ════════════
def test_real_neschimbat_default_egal_sistem_real_explicit():
    implicit = calculeaza_d212(90_000, 30_000, an=AN, salariu_minim=SMB)
    explicit = calculeaza_d212(90_000, 30_000, an=AN, salariu_minim=SMB, regim="SISTEM_REAL")
    assert implicit.regim == "SISTEM_REAL"
    assert (implicit.venit_net, implicit.cas, implicit.cass, implicit.impozit,
            implicit.total_plata, implicit.bonificatie) == \
           (explicit.venit_net, explicit.cas, explicit.cass, explicit.impozit,
            explicit.total_plata, explicit.bonificatie)


def test_real_cifre_cunoscute():
    # venit net = 90.000 − 30.000 = 60.000; CAS 12.150; CASS 6.000;
    # impozit = 10% × (60.000 − 12.150 − 6.000) = 10% × 41.850 = 4.185
    r = calculeaza_d212(90_000, 30_000, an=AN, salariu_minim=SMB)
    assert r.venit_net == 60_000
    assert r.cas == 12_150.0 and r.cass == 6_000.0
    assert r.impozit == 4_185.0


def test_norma_difera_de_real_pe_aceleasi_date():
    real = calculeaza_d212(90_000, 30_000, an=AN, salariu_minim=SMB)
    norm = calculeaza_d212(90_000, 30_000, an=AN, salariu_minim=SMB,
                           regim="NORMA_VENIT", norma_anuala=NORMA)
    assert real.impozit != norm.impozit          # 4.185 (real) ≠ 5.000 (normă)


# ════════════ Nomenclator ════════════
def test_nomenclator_lookup_salaj():
    assert norma_venit.norma_anuala("SJ", "municipiu", 2026) == 54_300.0
    assert norma_venit.norma_anuala("SJ", "oras", 2026) == 51_300.0
    assert norma_venit.norma_anuala("SJ", "comuna", 2026) == 48_600.0


def test_nomenclator_alias_nume_judet():
    assert norma_venit.norma_anuala("Sălaj", "oras", 2026) == 51_300.0


def test_nomenclator_judet_lipsa_fallback_none():
    # BN încă necompletat → None (fallback manual, NU crapă, NU inventează cifră)
    assert norma_venit.norma_anuala("BN", "municipiu", 2026) is None
    assert norma_venit.norma_anuala(None, "municipiu", 2026) is None
    assert norma_venit.norma_anuala("SJ", "tip_inexistent", 2026) is None


# ════════════ Gardian tranziție (predicat pur) ════════════
def test_norma_permisa_ridesharing_doar_din_2026():
    assert norma_venit.norma_permisa(2025, "ridesharing") is False
    assert norma_venit.norma_permisa(2026, "ridesharing") is True
    assert norma_venit.norma_permisa(2025, "it_freelance") is True   # alte activități neafectate


# ════════════ Gardian tranziție — în motorul D212 (cale reală) ════════════
def _patch_profil(monkeypatch, regim, activity, norma):
    # compute_period e însumat pe 12 luni → lunar 7.500/2.500 = anual 90.000/30.000
    monkeypatch.setattr(tax_engine, "compute_period",
                        lambda *a, **k: {"income_total": 7_500.0, "expense_deductible_total": 2_500.0})
    import app.repositories.users as users_repo
    monkeypatch.setattr(users_repo, "get_profile_dict",
                        lambda s, uid: {"regim_impunere": regim, "activity_code": activity,
                                        "norma_venit_anuala": norma})


def test_gardian_2025_ridesharing_norma_tratat_ca_real(monkeypatch):
    _patch_profil(monkeypatch, "NORMA_VENIT", "ridesharing", NORMA)
    r = tax_engine._compute_d212_anual_uncached(object(), user_id=1, an=2025)
    assert r.regim == "SISTEM_REAL"                       # gardian: 2025 → real
    assert r.venit_net == 60_000                          # calcul pe venit real, nu pe normă
    assert any("2025" in a and "real" in a.lower() for a in r.avertismente)


def test_gardian_2026_ridesharing_norma_aplicata(monkeypatch):
    _patch_profil(monkeypatch, "NORMA_VENIT", "ridesharing", NORMA)
    r = tax_engine._compute_d212_anual_uncached(object(), user_id=1, an=2026)
    assert r.regim == "NORMA_VENIT"                       # 2026 → normă permisă
    assert r.impozit == round(NORMA * COTA_IMPOZIT, 2)    # impozit pe normă


def test_session_none_ramane_real(monkeypatch):
    # apel pur (test/legacy) fără sesiune → SISTEM_REAL, regresie 0
    monkeypatch.setattr(tax_engine, "compute_period",
                        lambda *a, **k: {"income_total": 7_500.0, "expense_deductible_total": 2_500.0})
    r = tax_engine._compute_d212_anual_uncached(None, user_id=1, an=2026)
    assert r.regim == "SISTEM_REAL" and r.venit_net == 60_000
