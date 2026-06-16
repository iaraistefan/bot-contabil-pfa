"""
E2E Uber (A+B+C+D) — fluxul COMPLET cap-coadă, nu sub-pași izolați.

Scenariu: șofer alege „Ambele" în onboarding → setează Bolt 2% (cu cert) + Uber 0%
(cu cert) → are facturi comision Bolt ȘI Uber în aceeași lună → D100 = DOAR Bolt
(Uber 0% exclus, scutit → D207), CONSISTENT pe toate suprafețele:
  C (onboarding) → A (storage per-platformă) → B (split D100) → D (toate suprafețele).

Verifică: web _d100_block == web /api/v1/obligatii == guardian == calendar — toate
din planul B, suma DECLARATĂ = round(431×2%) = 9 lei (Uber 0% nu contribuie).
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import onboarding as onb
from app.services import tax_engine
from app.domain import fiscal_calendar as fc
from app.domain.compliance_guardian import validate_payment, IssueCategory, IssueSeverity
from app.http import app as webapp
from app.models import User, Transaction

Y, M = 2026, 1
COTA = 0.21  # cotă TVA perioadă (sursă unică în plan via cota_tva)


# ── fake update/context pentru handler-ul de onboarding (async) ──
class _Q:
    def __init__(self, chat_id):
        self.message = SimpleNamespace(chat_id=chat_id)
    async def edit_message_text(self, *a, **k): pass


class _Bot:
    async def send_message(self, *a, **k): pass


def _upd(tg_id):
    return SimpleNamespace(callback_query=_Q(1), effective_user=SimpleNamespace(id=tg_id),
                           effective_chat=SimpleNamespace(id=1))


def _vat_out(uid, counterparty, baza):
    """O factură comision → VAT_OUT (taxare inversă). amount_brut = baza × cotă TVA."""
    return Transaction(
        user_id=uid, document_id=1, tx_type="VAT_OUT", category="REVERSE_CHARGE_VAT",
        amount_brut=round(baza * COTA, 2), amount_vat=round(baza * COTA, 2), amount_net=0.0,
        currency="RON", deductibility_pct=0, payment_method="CARD",
        counterparty=counterparty, vat_treatment="REVERSE_CHARGE",
        period_year=Y, period_month=M, locked=False,
    )


@pytest.mark.asyncio
async def test_e2e_ambele_bolt2_uber0_d100_doar_bolt(monkeypatch, tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 'e2e.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    monkeypatch.setattr(onb, "get_session", lambda: Session())

    # user ridesharing, ajuns la gate-ul de platforme (pas 8)
    s = Session()
    s.add(User(telegram_id=700, activity_code="ridesharing",
               onboarding_step=onb.STEP_REGIM_NEREZIDENT)); s.commit(); s.close()

    # ── C: onboarding „Ambele" → Bolt 2% (cu cert) → Uber 0% (cu cert) ──
    ctx = SimpleNamespace(user_data={}, bot=_Bot())
    upd = _upd(700)
    await onb.handle_onboarding_callback(upd, ctx, ["onb", "platforme", "AMBELE"])
    await onb.handle_onboarding_callback(upd, ctx, ["onb", "nerezident", "BOLT_CU_CRF"])
    await onb.handle_onboarding_callback(upd, ctx, ["onb", "nerezident", "UBER_CU_CRF"])

    # A: storage per-platformă scris corect (nu deprecatul)
    s = Session()
    u = s.query(User).filter_by(telegram_id=700).one()
    uid = u.id
    assert u.regim_nerezident_bolt == "BOLT_CU_CRF"   # 2%
    assert u.regim_nerezident_uber == "UBER_CU_CRF"   # 0%
    assert getattr(u, "regim_nerezident", None) is None  # NU deprecatul
    assert u.onboarding_step == onb.STEP_CONFIRMARE

    # facturi comision MIXTE în aceeași lună: Bolt bază 431 + Uber bază 300
    s.add_all([_vat_out(uid, "Bolt Operations OÜ", 431),
               _vat_out(uid, "Uber B.V.", 300)])
    s.commit(); s.close()

    # ── B: planul = sursă unică. D100 = DOAR Bolt (Uber 0% → scutit, exclus) ──
    s = Session()
    plan = tax_engine.d100_plan_for(s, user_id=uid, year=Y, month=M)
    assert plan.status == "de_depus"
    assert plan.suma_declarata == 9.0                 # round(431 × 0.02); Uber NU contribuie
    assert [seg.brand for seg in plan.segmente] == ["bolt"]
    assert "uber" in plan.scutite                     # Uber 0% → D207
    assert plan.neatribuit_lei == 0.0

    vat_out_total = round(431 * COTA + 300 * COTA, 2)
    intracom_base = round(vat_out_total / COTA, 2)    # = 731

    # ── D, suprafața 1: web _d100_block ──
    totals = {"vat_out_total": vat_out_total, "cota_tva": COTA}
    block = webapp._d100_block(s, uid, Y, M, totals)
    assert block["status"] == "de_depus"
    assert block["suma"] == 9.0
    assert {d["brand"]: d["suma"] for d in block["defalcare"]} == {"bolt": 8.62}  # defalcare cu bani

    # ── D, suprafața 2: web /api/v1/obligatii (get_obligations_for_user cu planul) ──
    obl = fc.get_obligations_for_user(
        Y, M, "PFA", "ridesharing",
        has_intracom_invoice=True, intracom_base_amount=intracom_base,
        has_cod_special_tva=True,
        d100_suma=plan.suma_declarata, d100_status=plan.status,
    )
    d100_obl = next(o for o in obl if o.definitie.cod == "D100 poz. 634")
    assert d100_obl.suma_estimata == 9.0              # IDENTIC cu _d100_block (sursă unică)
    assert d100_obl.suma_estimata != round(431 * 0.02 + 300 * 0.02, 2)  # NU 2% pe TOT (ar fi 14,62)

    # ── D, suprafața 3: guardian — plata corectă de 9 lei NU e respinsă ──
    res = validate_payment(
        "RO49AAAA1B31007593840000"[:24], 9.0, "D100", Y, M,
        forma_juridica="PFA", activity_code="ridesharing", judet="BN",
        has_cod_special_tva=True, has_intracom_invoice=True,
        intracom_base_amount=intracom_base,
        d100_suma=plan.suma_declarata, d100_status=plan.status,
    )
    assert not [i for i in res.issues
                if i.category == IssueCategory.AMOUNT_MISMATCH
                and i.severity == IssueSeverity.ERROR]

    # ── D, suprafața 4: calendar (get_monthly_alerts plan-aware) ──
    label = " · ".join(f"{seg.eticheta} {round(seg.cota*100)}%" for seg in plan.segmente)
    alerts = fc.get_monthly_alerts(Y, M, has_bolt_invoice=True,
                                   d100_status=plan.status, d100_pct_label=label)
    d100_alert = next((a for a in alerts if a["code"] == "D100 poz. 634"), None)
    assert d100_alert is not None                     # D100 prezent (de_depus)
    assert "Bolt 2%" in d100_alert["name"]            # label din plan (doar Bolt; Uber 0% exclus)
    s.close()


def test_e2e_user_existent_bolt_legacy_identic(tmp_path):
    """
    Backward-compat FINAL (stare cu toate sub-pașii): un user EXISTENT dinainte de
    Uber — regimul Bolt pe câmpul DEPRECAT `regim_nerezident`, _bolt/_uber NULL
    (ne-migrat). D100-ul lui rămâne IDENTIC cu azi (2% Bolt), via fallback-ul de
    citire din sub-pas A. Niciun Uber, nicio schimbare.
    """
    eng = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    s = Session()
    # User pre-migrare: DOAR câmpul vechi setat (cum era înainte de 014).
    u = User(telegram_id=800, activity_code="ridesharing", regim_nerezident="BOLT_CU_CRF")
    s.add(u); s.commit()
    uid = u.id
    s.add(_vat_out(uid, "Bolt Operations OÜ", 657))   # bază 657 @ 0.21
    s.commit(); s.close()

    s = Session()
    plan = tax_engine.d100_plan_for(s, user_id=uid, year=Y, month=M)
    assert plan.status == "de_depus"
    assert plan.suma_declarata == 13.0                # round(657 × 0.02) — IDENTIC cu azi
    assert [seg.brand for seg in plan.segmente] == ["bolt"]
    assert plan.scutite == [] and plan.neatribuit_lei == 0.0

    block = webapp._d100_block(s, uid, Y, M, {"vat_out_total": round(657 * COTA, 2), "cota_tva": COTA})
    assert block["status"] == "de_depus" and block["suma"] == 13.0 and block["cota"] == 0.02

    obl = fc.get_obligations_for_user(
        Y, M, "PFA", "ridesharing",
        has_intracom_invoice=True, intracom_base_amount=657.0, has_cod_special_tva=True,
        d100_suma=plan.suma_declarata, d100_status=plan.status,
    )
    d100_obl = next(o for o in obl if o.definitie.cod == "D100 poz. 634")
    assert d100_obl.suma_estimata == 13.0             # consistent, identic cu pre-Uber
    s.close()
