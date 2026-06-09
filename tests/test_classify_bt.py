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
from pathlib import Path

import pytest

from app.activities.ridesharing import RidesharingActivity as ACT
from app.integrations.imports.bank_statement import BankTxn
from app.integrations.imports.classify import (
    classify_bt,
    BankTxnClasificat,
    ObligatieHint,
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
    # FORMAT REAL BT: suma e LIPITĂ de monedă ("0.00RON"), fără spațiu.
    txn = _t("OUT", "Plata POS Kaufland SRL comision tranzactie 0.00RON")
    r = classify_bt(txn, ACT)
    assert r.bucket == DE_VERIFICAT
    assert r.categorie != "platform_commission"
    assert r.categorie is None


def test_denoise_pastreaza_keyword_real():
    # Zgomotul e curățat, dar combustibilul real rămâne detectat.
    txn = _t("OUT", "Plata POS OMV MOTORINA comision tranzactie 0.00RON")
    r = classify_bt(txn, ACT)
    assert r.bucket == CHELTUIALA_BUSINESS
    assert r.categorie == "fuel"


def test_denoise_regresie_string_real_pos_persoana_fizica():
    # REGRESIE: string-ul EXACT dintr-o plată POS din extrasul BT real
    # (anonimizat). BT lipește suma de monedă ("6.05EUR", "0.00RON"). Denoise-ul
    # vechi cerea spațiu (\s+ron) → NU prindea → „comision" supraviețuia →
    # plata către o PERSOANĂ FIZICĂ era marcată FALS platform_commission 100%.
    # Acest test ar fi prins bug-ul de la început.
    descr = (
        "Plata la POS non-BT cu card VISA EPOS 01/04/2026 XXXXXXXXXXXXXX "
        "TID:XXXXXXXX MERCHANTUS +10000000000 US 0000000000v0a0loare "
        "tranzactie: 6.05EUR RRN: 609108383488 comision tranzactie 0.00RON; "
        "POPESICOUN PERSOANA FIZICA AUTORI; REF: 000XXXX000000XX"
    )
    r = classify_bt(_t("OUT", descr), ACT)
    assert r.bucket == DE_VERIFICAT
    assert r.categorie != "platform_commission"
    assert r.categorie is None


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


# ----------------------------------------------------------------------
# GOLDEN pe FIXTURE REAL — clasificarea întregului extras BT (aprilie 2026).
# Sintetic mințea (denoise pe „0.00 RON" cu spațiu); datele reale spun adevărul.
# Cele 6 plăți POS către persoane fizice trebuie să fie DE_VERIFICAT, NU business.
# ----------------------------------------------------------------------
_FIXTURE = Path(__file__).parent / "fixtures" / "extras_bt_anon.pdf"


@pytest.fixture(scope="module")
def fixture_clasificat():
    from app.integrations.imports.bt_parser import parse_bt_pdf
    txns = parse_bt_pdf(_FIXTURE.read_bytes())
    return [classify_bt(t, ACT) for t in txns]


def test_fixture_golden_count_per_bucket(fixture_clasificat):
    cl = fixture_clasificat
    counts = {b: sum(1 for r in cl if r.bucket == b) for b in (
        VENIT_BOLT, PLATA_TAXA, RETURNARE_TAXA,
        COMISION_BANCAR, CHELTUIALA_BUSINESS, DE_VERIFICAT,
    )}
    assert len(cl) == 34
    assert counts[VENIT_BOLT] == 3
    assert counts[PLATA_TAXA] == 8
    assert counts[RETURNARE_TAXA] == 8
    assert counts[COMISION_BANCAR] == 9
    assert counts[CHELTUIALA_BUSINESS] == 0     # ZERO fals-pozitive pe plăți POS
    assert counts[DE_VERIFICAT] == 6            # plățile POS → userul decide


def test_fixture_sume_per_bucket(fixture_clasificat):
    cl = fixture_clasificat
    def s(b):
        return round(sum(r.txn.suma for r in cl if r.bucket == b), 2)
    assert s(VENIT_BOLT) == 699.45
    assert s(PLATA_TAXA) == 320.00
    assert s(RETURNARE_TAXA) == 320.00          # = plățile → se anulează net 0
    assert s(DE_VERIFICAT) == 442.19


def test_fixture_zero_fals_pozitiv_platform_commission(fixture_clasificat):
    # Nicio plată POS către persoană fizică nu trebuie să fie comision deductibil.
    pos = [r for r in fixture_clasificat
           if "POS non-BT" in (r.txn.descriere or "")]
    assert pos, "fixture trebuie să conțină plăți POS non-BT"
    for r in pos:
        assert r.categorie != "platform_commission"
        assert r.bucket == DE_VERIFICAT


# ----------------------------------------------------------------------
# FELIA 5a PAS 1 — hint structurat al obligației (ObligatieHint), aditiv.
# Eticheta rămâne BIT-IDENTICĂ; câmpul nou `oblig` e populat pe PLATA/RETURNARE.
# ----------------------------------------------------------------------
def test_oblig_plata_structurat_si_eticheta_neschimbata():
    r = classify_bt(_t("OUT", "Plata Trezorerie TVA D301 Ianuarie 2026"), ACT)
    assert r.bucket == PLATA_TAXA
    assert r.oblig == ObligatieHint(
        tip="TVA", declaratie="D301", luna=1, an=2026, luna_nume="Ianuarie")
    # eticheta = exact ca înainte (regresie)
    assert r.eticheta == "Plată obligație fiscală (TVA D301 Ianuarie 2026)"


def test_oblig_returnare_structurat():
    r = classify_bt(_t("IN", "Returnare plata Impozit D100 Decembrie 2025"), ACT)
    assert r.bucket == RETURNARE_TAXA
    assert r.oblig == ObligatieHint(
        tip="Impozit", declaratie="D100", luna=12, an=2025, luna_nume="Decembrie")
    assert r.eticheta == "Returnare taxă respinsă (Impozit D100 Decembrie 2025)"


def test_oblig_none_fara_pattern():
    # plată de taxă fără hint parsabil → oblig=None, etichetă fără hint (neschimbată)
    r = classify_bt(_t("OUT", "Plata Trezorerie obligatii bugetare"), ACT)
    assert r.bucket == PLATA_TAXA
    assert r.oblig is None
    assert r.eticheta == "Plată obligație fiscală"


def test_oblig_none_pe_alte_buckete():
    assert classify_bt(_t("IN", "Incasare OP BOLT"), ACT).oblig is None
    assert classify_bt(_t("OUT", "Plata POS LUKOIL MOTORINA"), ACT).oblig is None


def test_fixture_oblig_populat_pe_toate_taxele(fixture_clasificat):
    taxa = [r for r in fixture_clasificat
            if r.bucket in (PLATA_TAXA, RETURNARE_TAXA)]
    assert len(taxa) == 16                       # 8 plăți + 8 returnări
    assert all(r.oblig is not None for r in taxa)   # toate au hint pe fixture
    # spot-check: plata TVA D301 Ianuarie 2026 = 138,00
    plati = [r for r in fixture_clasificat if r.bucket == PLATA_TAXA]
    tva_ian = [r for r in plati if r.oblig.tip == "TVA"
               and r.oblig.declaratie == "D301"
               and r.oblig.luna == 1 and r.oblig.an == 2026]
    assert len(tva_ian) == 1
    assert round(tva_ian[0].txn.suma, 2) == 138.00
