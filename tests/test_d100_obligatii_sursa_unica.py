"""
Uber sub-pas D — D100 din v2 obligatii = SURSĂ UNICĂ (planul B), nu 2% hardcodat.

Bug eliminat: compute_obligation hardcoda D100 la 2% (COTA_RETINERE_NEREZIDENT_EE,
relicvă pre-#3) → divergență față de _d100_block + GUARDIAN respingea o plată corectă
de 16%/Uber comparând-o cu 2%. Acum compute_obligation primește suma/status din
compute_d100_plan (toți cei 6 apelanți). Fără plan → None (NICIODATĂ 2% presupus).

Teste-cheie:
  - compute_obligation D100 = d100_suma (nu 2% × bază);
  - consistență: _d100_block == /api/v1/obligatii == plan (cele 2 ecrane nu mai diverg);
  - GUARDIAN: plata de 16% NU mai e respinsă (compară cu planul, nu 2%).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain import fiscal_calendar as fc
from app.domain.compliance_guardian import (
    validate_payment, IssueCategory, IssueSeverity,
)
from app.services import tax_engine
from app.http import app as webapp
from app.models import User, Transaction

Y, M = 2026, 1
D100 = "D100 poz. 634"
_DEF_D100 = fc.DEFINITII_OBLIGATII["D100_634"]
_DEF_D301 = fc.DEFINITII_OBLIGATII["D301"]


def _obl(definitie, **kw):
    base = dict(forma_juridica="PFA", activity_code="ridesharing",
                has_intracom_invoice=True, intracom_base_amount=657.0,
                has_cod_special_tva=True)
    base.update(kw)
    return fc.compute_obligation(definitie, Y, M, base.pop("forma_juridica"),
                                 base.pop("activity_code"), **base)


# ════════════════════════════════════════════════════════
# 1. compute_obligation D100 — din plan, NU 2% hardcodat
# ════════════════════════════════════════════════════════

def test_d100_de_depus_foloseste_planul_nu_2pct():
    # Bolt 16%: plan dă 105. Vechiul cod ar fi dat 657×2% = 13,14. Dovedim ≠ 2%.
    o = _obl(_DEF_D100, d100_suma=105.0, d100_status="de_depus")
    assert o.suma_estimata == 105.0
    assert o.suma_estimata != round(657 * 0.02, 2)     # NU mai e 2% hardcodat


def test_d100_scutit_zero():
    o = _obl(_DEF_D100, d100_suma=None, d100_status="scutit")
    assert o.suma_estimata == 0.0                      # Uber scutit → 0 (D207)


def test_d100_neconfigurat_none():
    o = _obl(_DEF_D100, d100_suma=None, d100_status="neconfigurat")
    assert o.suma_estimata is None                     # fără cifră presupusă


def test_d100_fara_plan_none_nu_2pct():
    # Niciun plan pasat → None (NU 2% hardcodat — relicva scoasă din calcul).
    o = _obl(_DEF_D100)
    assert o.suma_estimata is None


def test_d301_neschimbat_21pct():
    # Regresie: D301 rămâne 21% × bază (nu e atins de split-ul D100).
    o = _obl(_DEF_D301)
    assert o.suma_estimata == round(657 * 0.21, 2)


# ════════════════════════════════════════════════════════
# 2. Consistență: _d100_block == obligatii == plan (sursă unică)
# ════════════════════════════════════════════════════════

def _db(tmp_path, regim_bolt):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    u = User(telegram_id=9, activity_code="ridesharing", regim_nerezident_bolt=regim_bolt)
    s.add(u); s.commit()
    # VAT_OUT Bolt: vat_out 137.97 @ cotă 0.21 → bază 657.
    s.add(Transaction(
        user_id=u.id, document_id=1, tx_type="VAT_OUT", category="REVERSE_CHARGE_VAT",
        amount_brut=137.97, amount_vat=137.97, amount_net=0.0, currency="RON",
        deductibility_pct=0, payment_method="CARD", counterparty="Bolt Operations OÜ",
        vat_treatment="REVERSE_CHARGE", period_year=Y, period_month=M, locked=False,
    ))
    s.commit()
    return s, u.id


def test_consistenta_block_obligatii_plan_bolt_16(tmp_path):
    # Bolt FĂRĂ certificat → 16%. Cele două ecrane web + planul TREBUIE să coincidă.
    s, uid = _db(tmp_path, "BOLT_FARA_CRF")

    plan = tax_engine.d100_plan_for(s, user_id=uid, year=Y, month=M)
    assert plan.suma_declarata == 105.0                # round(657 × 0.16)

    # ecran 1: TVA & Declarații (_d100_block)
    totals = {"vat_out_total": 137.97, "cota_tva": 0.21}
    block = webapp._d100_block(s, uid, Y, M, totals)

    # ecran 2: timeline/plată (/api/v1/obligatii → get_obligations_for_user cu planul)
    obl = fc.get_obligations_for_user(
        Y, M, "PFA", "ridesharing",
        has_intracom_invoice=True, intracom_base_amount=657.0,
        has_cod_special_tva=True,
        d100_suma=plan.suma_declarata, d100_status=plan.status,
    )
    d100_obl = next(o for o in obl if o.definitie.cod == D100)

    # SURSĂ UNICĂ: toate trei egale, și ≠ 2% (13,14) — divergența eliminată.
    assert block["suma"] == d100_obl.suma_estimata == plan.suma_declarata == 105.0
    assert d100_obl.suma_estimata != round(657 * 0.02, 2)
    s.close()


def test_consistenta_uber_scutit(tmp_path):
    # Uber cu certificat → 0%. Ambele ecrane: scutit (suma 0), nu 2%.
    eng = create_engine(f"sqlite:///{(tmp_path / 'u.db').as_posix()}")
    User.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    u = User(telegram_id=11, activity_code="ridesharing", regim_nerezident_uber="UBER_CU_CRF")
    s.add(u); s.commit()
    s.add(Transaction(
        user_id=u.id, document_id=1, tx_type="VAT_OUT", category="REVERSE_CHARGE_VAT",
        amount_brut=137.97, amount_vat=137.97, amount_net=0.0, currency="RON",
        deductibility_pct=0, payment_method="CARD", counterparty="Uber B.V.",
        vat_treatment="REVERSE_CHARGE", period_year=Y, period_month=M, locked=False,
    ))
    s.commit()

    plan = tax_engine.d100_plan_for(s, user_id=u.id, year=Y, month=M)
    assert plan.status == "scutit"
    o = _obl(_DEF_D100, d100_suma=plan.suma_declarata, d100_status=plan.status)
    assert o.suma_estimata == 0.0                      # scutit → 0 (D207), nu 2%
    s.close()


# ════════════════════════════════════════════════════════
# 3. GUARDIAN — plata de 16% NU mai e respinsă (bug-ul cel mai grav)
# ════════════════════════════════════════════════════════

def _amount_mismatch_errors(res):
    return [i for i in res.issues
            if i.category == IssueCategory.AMOUNT_MISMATCH
            and i.severity == IssueSeverity.ERROR]


def test_guardian_nu_mai_respinge_plata_16pct():
    # Bolt fără cert → D100 corect = 105 (16%). Plata de 105 e CORECTĂ.
    # Înainte (2% hardcodat = 13) → guardian o respingea „prea mare". Acum: acceptată.
    res = validate_payment(
        "RO82TREZ10120A1203000001XX"[:24], 105.0, "D100", Y, M,
        forma_juridica="PFA", activity_code="ridesharing", judet="BN",
        has_cod_special_tva=True, has_intracom_invoice=True, intracom_base_amount=657.0,
        d100_suma=105.0, d100_status="de_depus",
    )
    assert _amount_mismatch_errors(res) == []          # 16% NU mai e respinsă


def test_guardian_compara_cu_planul_nu_cu_2pct():
    # Dovada că validează față de 105 (plan), nu 13 (2% vechi): o plată de 13
    # (cât ar fi fost „corectă" pe 2%) e acum semnalată ca nepotrivită.
    res = validate_payment(
        "RO82TREZ10120A1203000001XX"[:24], 13.0, "D100", Y, M,
        forma_juridica="PFA", activity_code="ridesharing", judet="BN",
        has_cod_special_tva=True, has_intracom_invoice=True, intracom_base_amount=657.0,
        d100_suma=105.0, d100_status="de_depus",
    )
    assert _amount_mismatch_errors(res)                # 13 ≠ 105 → semnalat


# ════════════════════════════════════════════════════════
# 4. Descrieri — ambele platforme (D2)
# ════════════════════════════════════════════════════════

def test_descrieri_ambele_platforme():
    d100 = _DEF_D100.descriere
    assert "Bolt" in d100 and "Uber" in d100
    assert "art. 12" in d100 and "art. 7" in d100      # temei dublu Estonia/Olanda
    assert "2%" not in _DEF_D100.nume                  # numele nu mai hardcodează 2% Bolt

    d207 = fc.DEFINITII_OBLIGATII["D207"].descriere
    assert "Uber" in d207 and "scut" in d207.lower()   # Uber scutit se declară aici

    d390 = fc.DEFINITII_OBLIGATII["D390"].descriere
    assert "Uber" in d390                              # Bolt EE și/sau Uber NL
