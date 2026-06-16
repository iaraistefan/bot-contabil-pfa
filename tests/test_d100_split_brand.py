"""
Uber sub-pas B — split D100 per-platformă (multi-brand).

D100 (poz. 634) = O SINGURĂ poziție agregată la ANAF; cota diferă pe platformă
(Bolt 2%/16%, Uber 0%/16% după CRF) → suma = Σ pe brand cu cotă>0. D301/D390 NU
se ating (taxare inversă identică UE).

Rotunjire (decizie #B): suma DECLARATĂ = round(Σ baza×cota) în LEI ÎNTREGI, O
SINGURĂ rotunjire pe TOTAL (anti dublă-rotunjire). Defalcarea informativă cu bani.

Status mixt (opțiunea 1): brand RECUNOSCUT cu regim nesetat (cota None) → BLOCHEAZĂ
tot D100 ('neconfigurat'); neatribuit (detect_brand=None) → exclus + nudge, NU
blochează.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import tax_engine
from app.services.tax_engine import compute_d100_plan, vat_out_by_brand, _d100_brand_key
from app.domain.fiscal_profile import from_user_dict
from app.integrations.anaf import d100_generator as d100
from app.integrations.anaf import declaratii_service as decl
from app.models import User, Transaction

Y, M = 2026, 1


def _profile(bolt=None, uber=None):
    return from_user_dict({
        "firma_forma_juridica": "PFA",
        "regim_nerezident_bolt": bolt,
        "regim_nerezident_uber": uber,
    })


# cota_tva=1.0 → baza == vat_out (cifre curate: by_brand poartă direct baza).
def _plan(by_brand, bolt=None, uber=None, cota_tva=1.0):
    return compute_d100_plan(by_brand, cota_tva, _profile(bolt, uber))


# ════════════════════════════════════════════════════════
# 1. Normalizarea brandului (pură) — bolt/uber/None
# ════════════════════════════════════════════════════════

def test_brand_key_normalizare():
    assert _d100_brand_key("Bolt Operations OÜ") == "bolt"
    assert _d100_brand_key("Uber B.V.") == "uber"
    assert _d100_brand_key("Uber Eats") == "uber"
    assert _d100_brand_key("AWS EMEA SARL") is None      # brand non-rideshare → neatribuit
    assert _d100_brand_key("Furnizor Necunoscut SRL") is None
    assert _d100_brand_key(None) is None


# ════════════════════════════════════════════════════════
# 2. vat_out_by_brand — grupare + INVARIANT (Σ == vat_out_total)
# ════════════════════════════════════════════════════════

def _db(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    u = User(telegram_id=7)
    s.add(u); s.commit()
    return s, u.id


def _vat_out(uid, counterparty, amount):
    return Transaction(
        user_id=uid, document_id=1, tx_type="VAT_OUT",
        category="REVERSE_CHARGE_VAT", amount_brut=amount, amount_vat=amount,
        amount_net=0.0, currency="RON", deductibility_pct=0, payment_method="CARD",
        counterparty=counterparty, vat_treatment="REVERSE_CHARGE",
        period_year=Y, period_month=M, locked=False,
    )


def test_vat_out_by_brand_grupare_si_invariant(tmp_path):
    s, uid = _db(tmp_path)
    s.add_all([
        _vat_out(uid, "Bolt Operations OÜ", 90.51),
        _vat_out(uid, "Bolt Operations OÜ", 9.49),
        _vat_out(uid, "Uber B.V.", 63.0),
        _vat_out(uid, "Mister X SRL", 12.0),       # neatribuit
    ])
    s.commit()

    by_brand = vat_out_by_brand(s, user_id=uid, year=Y, month=M)
    assert by_brand["bolt"] == 100.0
    assert by_brand["uber"] == 63.0
    assert by_brand[None] == 12.0

    # INVARIANT: Σ pe brand == vat_out_total (compute_period, sursă unică)
    totals = tax_engine.compute_period(s, user_id=uid, year=Y, month=M)
    assert round(sum(by_brand.values()), 2) == totals["vat_out_total"] == 175.0


# ════════════════════════════════════════════════════════
# 3. compute_d100_plan — matricea sub-pas B
# ════════════════════════════════════════════════════════

def test_bolt_2pct_plus_uber_scutit():
    # Bolt(431, 2%) + Uber(300, 0% cert) → declarat 9 (round 8,62); Uber exclus.
    p = _plan({"bolt": 431, "uber": 300}, bolt="BOLT_CU_CRF", uber="UBER_CU_CRF")
    assert p.status == "de_depus"
    assert p.suma_declarata == 9.0                 # round(431×0.02)=round(8.62)
    assert len(p.segmente) == 1 and p.segmente[0].brand == "bolt"
    assert p.segmente[0].suma == 8.62              # defalcare CU BANI
    assert "uber" in p.scutite                     # Uber 0% → D207


def test_bolt_2pct_plus_uber_16pct_agregat():
    # Bolt(431, 2%) + Uber(300, 16%) → declarat 57 (round 56,62 agregat).
    p = _plan({"bolt": 431, "uber": 300}, bolt="BOLT_CU_CRF", uber="UBER_FARA_CRF")
    assert p.status == "de_depus"
    assert p.suma_exact == 56.62                   # 8,62 + 48,00 (transparență)
    assert p.suma_declarata == 57.0                # round PE TOTAL o singură dată
    sume = {s.brand: s.suma for s in p.segmente}
    assert sume == {"bolt": 8.62, "uber": 48.0}    # defalcare exactă


def test_bolt_only_regresie_identica():
    # UN segment → round-pe-total ≡ round-pe-segment → IDENTIC cu azi.
    assert _plan({"bolt": 657}, bolt="BOLT_CU_CRF").suma_declarata == 13.0   # round(13,14)
    assert _plan({"bolt": 657}, bolt="BOLT_FARA_CRF").suma_declarata == 105.0  # round(105,12)


def test_brand_recunoscut_nesetat_blocheaza_tot():
    # Bolt(2%) + Uber prezent dar regim NESETAT (None) → BLOCAT TOT (opțiunea 1).
    p = _plan({"bolt": 431, "uber": 300}, bolt="BOLT_CU_CRF", uber=None)
    assert p.status == "neconfigurat"              # anti-subdeclarare la ANAF
    assert p.suma_declarata is None                # NU emite doar Bolt
    assert p.neconfig_brands == ["uber"]


def test_neatribuit_exclus_plus_nudge():
    # Bolt(2%) + factură neatribuită (detect_brand=None) → Bolt declarat, neatribuit nudge.
    p = _plan({"bolt": 431, None: 200}, bolt="BOLT_CU_CRF")
    assert p.status == "de_depus"
    assert p.suma_declarata == 9.0                 # doar Bolt
    assert p.neatribuit_lei == 200                 # nudge „verifică furnizorul"


def test_tot_neatribuit_fara_baza_pe_d100():
    # Tot VAT_OUT neatribuit → D100 fără bază (NU blochează nimic) + nudge.
    p = _plan({None: 500})
    assert p.status == "fara_baza"
    assert p.suma_declarata is None
    assert p.neatribuit_lei == 500


def test_fara_vat_out():
    p = _plan({})
    assert p.status == "fara_baza" and p.suma_declarata is None


def test_toate_scutite():
    # Doar Uber la 0% (cert) → toate scutite → D207, D100 nu se depune.
    p = _plan({"uber": 300}, uber="UBER_CU_CRF")
    assert p.status == "scutit" and p.suma_declarata == 0.0
    assert "uber" in p.scutite


# ════════════════════════════════════════════════════════
# 4. genereaza_d100 (XML) — segmente, round pe total, shim Bolt-only
# ════════════════════════════════════════════════════════

def _ident():
    return d100.IdentitateD100(
        cui="12345678", denumire="X PFA", adresa="ADR",
        nume_declarant="A", prenume_declarant="B", functie_declarant="TITULAR",
    )


def test_xml_segmente_round_pe_total():
    xml = d100.genereaza_d100(Y, M, _ident(), segmente=[(431, 0.02), (300, 0.16)])
    assert 'suma_dat="57"' in xml                  # round(8,62 + 48) = 57
    assert 'suma_plata="57"' in xml


def test_xml_shim_bolt_only_identic():
    # apelul vechi (baza, cota) ≡ un segment → suma identică cu azi.
    vechi = d100.genereaza_d100(Y, M, _ident(), 657, cota=0.02)
    nou = d100.genereaza_d100(Y, M, _ident(), segmente=[(657, 0.02)])
    assert 'suma_dat="13"' in vechi and 'suma_dat="13"' in nou


@pytest.mark.parametrize("segmente", [
    [(431, 0.0)],            # cota 0 → niciun XML
    [(431, None)],           # cota None
    [(431, 0.02), (300, 0)],  # un segment invalid în lot
    [],                      # lot gol
])
def test_xml_garda_cota_invalida(segmente):
    with pytest.raises(ValueError):
        d100.genereaza_d100(Y, M, _ident(), segmente=segmente)


# ════════════════════════════════════════════════════════
# 5. declaratii_service.genereaza — calea cu plan (D100)
# ════════════════════════════════════════════════════════

def test_genereaza_din_plan_de_depus():
    p = _plan({"bolt": 431, "uber": 300}, bolt="BOLT_CU_CRF", uber="UBER_FARA_CRF")
    rez = decl.genereaza("D100", Y, M, 731, d100_plan=p)   # baza total ignorată la calc
    assert rez.generat is True
    assert rez.suma_plata == 57.0
    assert 'suma_dat="57"' in rez.xml
    assert "Bolt" in rez.ghid_telegram and "Uber" in rez.ghid_telegram  # defalcare


def test_genereaza_din_plan_neconfigurat_blocat():
    p = _plan({"bolt": 431, "uber": 300}, bolt="BOLT_CU_CRF", uber=None)
    rez = decl.genereaza("D100", Y, M, 731, d100_plan=p)
    assert rez.generat is False
    assert rez.motiv_negenerat == "neconfigurat"
    assert rez.xml == ""                            # CRITIC: niciun XML parțial
    assert "Uber" in rez.ghid_telegram              # numește platforma nesetată


def test_genereaza_din_plan_scutit():
    p = _plan({"uber": 300}, uber="UBER_CU_CRF")
    rez = decl.genereaza("D100", Y, M, 300, d100_plan=p)
    assert rez.generat is False and rez.motiv_negenerat == "scutit"
    assert rez.xml == "" and "D207" in rez.ghid_telegram


# ════════════════════════════════════════════════════════
# 6. D301/D390 — neschimbate (planul D100 NU le afectează)
# ════════════════════════════════════════════════════════

def test_d301_d390_ignora_planul_d100():
    p = _plan({"bolt": 431, "uber": 300}, bolt="BOLT_CU_CRF", uber="UBER_FARA_CRF")
    for tip in ("D301", "D390"):
        fara = decl.genereaza(tip, Y, M, 657)
        cu = decl.genereaza(tip, Y, M, 657, d100_plan=p)
        assert fara.xml == cu.xml                   # plan D100 ignorat — total neschimbat
