"""
Teste pentru clasificatorul determinist de extras bancar (felia 2).

Acoperă:
- golden count per bucket (toate cele 6 buckete, fiecare exact o dată)
- precedența RETURNARE ≠ PLATA (același text fiscal, direcția dezambiguizează)
- etichete canonice (cu/fără hint obligație) + deductibilitate corectă
- denoise anti „comision tranzactie 0.00 RON" (cod sensibil pe bani: NU fals-pozitiv)
- vocabular separat bucket (DE_VERIFICAT) ≠ incredere (INCERT)  — P3
- robustețe pe descriere goală

Clasificatorul reutilizează `detect_expense_category` / `get_deductibility_pct`
din activitatea reală (NU clasificator paralel), deci testăm cu
`RidesharingActivity` ca în producție.
"""
from datetime import date

import pytest

from app.activities.ridesharing import RidesharingActivity as ACT
from app.integrations.imports.bank_statement import BankTxn
from app.integrations.imports.classify import (
    classify_bt,
    BankTxnClasificat,
    VENIT_BOLT,
    PLATA_TAXA,
    RETURNARE_TAXA,
    COMISION_BANCAR,
    CHELTUIALA_BUSINESS,
    DE_VERIFICAT,
    SIGUR,
    INCERT,
)


def _t(directie: str, descriere: str, suma: float = 100.0) -> BankTxn:
    return BankTxn(date(2026, 5, 10), suma, directie, descriere)


# ----------------------------------------------------------------------
# Golden: câte un reprezentant pentru fiecare bucket, în ordinea precedenței
# ----------------------------------------------------------------------
def _golden() -> list[BankTxn]:
    return [
        _t("IN",  "Incasare OP BOLT OPERATIONS"),                     # VENIT_BOLT
        _t("OUT", "Plata Trezorerie Stat TVA D301 Ianuarie 2026"),   # PLATA_TAXA
        _t("IN",  "Returnare plata respinsa TVA D301 Ianuarie 2026"),  # RETURNARE_TAXA
        _t("OUT", "Comision plata OP intrabancar"),                  # COMISION_BANCAR
        _t("OUT", "Plata POS LUKOIL MOTORINA 200 RON"),              # CHELTUIALA_BUSINESS (fuel)
        _t("OUT", "Plata POS Kaufland SRL"),                         # DE_VERIFICAT
    ]


def test_golden_count_per_bucket():
    buckets = [classify_bt(t, ACT).bucket for t in _golden()]
    # ordinea reflectă precedența: returnare→plata→comision→bolt→business→fallback
    assert buckets == [
        VENIT_BOLT,
        PLATA_TAXA,
        RETURNARE_TAXA,
        COMISION_BANCAR,
        CHELTUIALA_BUSINESS,
        DE_VERIFICAT,
    ]
    # fiecare bucket apare exact o dată
    for b in (VENIT_BOLT, PLATA_TAXA, RETURNARE_TAXA,
              COMISION_BANCAR, CHELTUIALA_BUSINESS, DE_VERIFICAT):
        assert buckets.count(b) == 1


# ----------------------------------------------------------------------
# VENIT_BOLT
# ----------------------------------------------------------------------
def test_venit_bolt():
    r = classify_bt(_t("IN", "Incasare OP BOLT"), ACT)
    assert r.bucket == VENIT_BOLT
    assert r.categorie == "ride_revenue"
    assert r.eticheta == "Venit Bolt"
    assert r.incredere == SIGUR


# ----------------------------------------------------------------------
# PLATA_TAXA — etichetă canonică + hint obligație
# ----------------------------------------------------------------------
def test_plata_taxa_cu_hint():
    r = classify_bt(_t("OUT", "Plata Trezorerie TVA D301 Ianuarie 2026"), ACT)
    assert r.bucket == PLATA_TAXA
    assert r.eticheta == "Plată obligație fiscală (TVA D301 Ianuarie 2026)"
    # decontare de obligație, NU cheltuială de activitate → fără procent
    assert r.deductibil is None
    assert r.incredere == SIGUR


def test_plata_taxa_fara_hint():
    r = classify_bt(_t("OUT", "Plata Trezorerie Stat obligatii bugetare"), ACT)
    assert r.bucket == PLATA_TAXA
    assert r.eticheta == "Plată obligație fiscală"


# ----------------------------------------------------------------------
# RETURNARE_TAXA — etichetă canonică (P1 păstrat) + hint
# ----------------------------------------------------------------------
def test_returnare_taxa_cu_hint():
    r = classify_bt(_t("IN", "Returnare plata respinsa TVA D301 Ianuarie 2026"), ACT)
    assert r.bucket == RETURNARE_TAXA
    assert r.eticheta == "Returnare taxă respinsă (TVA D301 Ianuarie 2026)"
    assert r.incredere == SIGUR


def test_returnare_taxa_fara_hint():
    r = classify_bt(_t("IN", "Returnare plata respinsa"), ACT)
    assert r.bucket == RETURNARE_TAXA
    assert r.eticheta == "Returnare taxă (plată respinsă)"


# ----------------------------------------------------------------------
# PRECEDENȚĂ: același text fiscal, direcția decide returnare vs plată
# ----------------------------------------------------------------------
def test_precedenta_returnare_diferita_de_plata_dupa_directie():
    text = "Trezorerie TVA D301 Ianuarie 2026"
    plata = classify_bt(_t("OUT", "Plata " + text), ACT)
    retur = classify_bt(_t("IN", "Returnare " + text), ACT)
    assert plata.bucket == PLATA_TAXA
    assert retur.bucket == RETURNARE_TAXA
    # un IN cu textul plății returnate NU devine PLATA_TAXA
    assert retur.bucket != PLATA_TAXA


# ----------------------------------------------------------------------
# COMISION_BANCAR — deductibil 100%
# ----------------------------------------------------------------------
def test_comision_bancar_deductibil_100():
    r = classify_bt(_t("OUT", "Comision plata OP intrabancar"), ACT)
    assert r.bucket == COMISION_BANCAR
    assert r.eticheta == "Comision bancar"
    assert r.deductibil == 100
    assert r.incredere == SIGUR


@pytest.mark.parametrize("desc", [
    "Comision plata OP",
    "Taxa rapoarte cont curent",
    "Nota contabila administrare cont",
])
def test_comision_bancar_keywords(desc):
    r = classify_bt(_t("OUT", desc), ACT)
    assert r.bucket == COMISION_BANCAR
    assert r.deductibil == 100


# ----------------------------------------------------------------------
# CHELTUIALA_BUSINESS — reutilizare clasificator fiscal (fuel/service = 50%)
# ----------------------------------------------------------------------
def test_cheltuiala_business_fuel_50():
    r = classify_bt(_t("OUT", "Plata POS LUKOIL MOTORINA 200 RON"), ACT)
    assert r.bucket == CHELTUIALA_BUSINESS
    assert r.categorie == "fuel"
    assert r.deductibil == 50            # HALF (auto mixt)
    assert r.eticheta == "Combustibil auto"   # = cat.label
    assert r.incredere == SIGUR


def test_cheltuiala_business_service_50():
    r = classify_bt(_t("OUT", "Plata POS service auto reparatii"), ACT)
    assert r.bucket == CHELTUIALA_BUSINESS
    assert r.categorie == "car_service"
    assert r.deductibil == 50


# ----------------------------------------------------------------------
# DENOISE — cod sensibil pe bani: zgomotul „comision tranzactie 0.00 RON"
# NU trebuie să producă fals-pozitiv pe comision (platform_commission)
# ----------------------------------------------------------------------
def test_denoise_comision_tranzactie_nu_da_fals_pozitiv():
    # Plată card la comerciant neutru, dar extrasul atașează zgomotul BT.
    # Fără denoise, „comision" ar match-ui platform_commission → business greșit.
    txn = _t("OUT", "Plata POS Kaufland SRL comision tranzactie 0.00 RON")
    r = classify_bt(txn, ACT)
    assert r.bucket == DE_VERIFICAT
    assert r.categorie != "platform_commission"
    assert r.categorie is None


def test_denoise_pastreaza_keyword_real():
    # Zgomotul e curățat, dar combustibilul real rămâne detectat.
    txn = _t("OUT", "Plata POS OMV MOTORINA comision tranzactie 0.00 RON")
    r = classify_bt(txn, ACT)
    assert r.bucket == CHELTUIALA_BUSINESS
    assert r.categorie == "fuel"


# ----------------------------------------------------------------------
# P3 — vocabular separat: bucket (ce e) ≠ incredere (cât de sigur)
# ----------------------------------------------------------------------
def test_de_verificat_si_vocabular_incredere_separat():
    r = classify_bt(_t("OUT", "Plata POS Kaufland SRL"), ACT)
    assert r.bucket == DE_VERIFICAT
    assert r.incredere == INCERT
    assert r.categorie is None
    assert r.deductibil is None
    # P3: increderea NU mai e același string ca bucket-ul
    assert INCERT != DE_VERIFICAT
    assert r.incredere != r.bucket


# ----------------------------------------------------------------------
# Robustețe — descriere goală nu crapă, cade pe DE_VERIFICAT
# ----------------------------------------------------------------------
@pytest.mark.parametrize("directie", ["IN", "OUT"])
def test_descriere_goala_nu_crapa(directie):
    r = classify_bt(_t(directie, ""), ACT)
    assert isinstance(r, BankTxnClasificat)
    assert r.bucket == DE_VERIFICAT
    assert r.incredere == INCERT


def test_descriere_none_nu_crapa():
    # Parserul produce mereu str, dar pad-ul defensiv ne apără dacă se schimbă:
    # ramura BUSINESS (_denoise pe OUT) nu trebuie să crape pe None.
    txn = BankTxn(date(2026, 5, 1), 10.0, "OUT", None)
    r = classify_bt(txn, ACT)
    assert r.bucket == DE_VERIFICAT
    assert r.incredere == INCERT
