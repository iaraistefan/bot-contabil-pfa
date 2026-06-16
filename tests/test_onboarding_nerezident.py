"""
Fiscal #3 — SUB-PAS E: captarea regimului nerezident (onboarding condiționat).
Uber sub-pas C: gate platforme [Bolt/Uber/Ambele] + captare Uber per-platformă.

Testează piesele pure ale fluxului de captare:
  - pasul nerezident e inserat DOAR pentru ridesharing (ceilalți → confirmare);
  - captarea oferă DOAR cele 2 opțiuni reale Bolt (2%/16%), fără 0% (acela e Uber);
    codurile active == VALID_REGIMURI_NEREZIDENT ⊆ enum (extensibil pt Uber);
  - CONFIRMARE rămâne pasul 7 (tranziții explicite), nerezident inserat ca 8.
  + sub-pas C: gate rutează corect, codurile Uber == VALID_..._UBER (toate UBER_),
    seturile separate resping cross, captarea scrie câmpul per-platformă corect.
"""

from types import SimpleNamespace

import pytest

from app.services import onboarding as onb
from app.repositories import users as users_repo
from app.repositories.users import (
    VALID_REGIMURI_NEREZIDENT,
    VALID_REGIMURI_NEREZIDENT_BOLT,
    VALID_REGIMURI_NEREZIDENT_UBER,
)
from app.domain.fiscal_profile import RegimNerezident
from app.models import User
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_pas_nerezident_doar_ridesharing():
    assert onb.next_step_after_impunere("ridesharing") == onb.STEP_REGIM_NEREZIDENT


def test_non_ridesharing_merge_la_confirmare():
    for act in ("it_freelance", "ecommerce", "consulting", "generic", "", None):
        assert onb.next_step_after_impunere(act) == onb.STEP_CONFIRMARE


def test_coduri_active_sunt_doar_bolt():
    codes = {r["code"] for r in onb.REGIMURI_NEREZIDENT}
    # captarea oferă DOAR codurile ACTIVE (Bolt) = validatorul de input
    assert codes == VALID_REGIMURI_NEREZIDENT
    assert all(c.startswith("BOLT_") for c in codes)         # niciun Uber/0% în UI
    # toate sunt valori reale ale enum-ului (extensibil: enum ⊇ active)
    assert codes <= {e.value for e in RegimNerezident}


def test_label_pentru_fiecare_cod():
    for c in ("BOLT_CU_CRF", "BOLT_FARA_CRF"):
        lbl = onb.nerezident_label(c)
        assert lbl and lbl != "—"
    assert onb.nerezident_label("") == "—"                   # gol → fără etichetă
    assert onb.nerezident_label("CEVA") == "—"               # necunoscut → fără etichetă


def test_pas_inserat_fara_a_muta_confirmarea():
    assert onb.STEP_CONFIRMARE == 7
    assert onb.STEP_REGIM_NEREZIDENT == 8


def test_keyboard_are_2_optiuni_niciuna_preselectata():
    kb = onb._kb_regim_nerezident()
    flat = [b for row in kb.inline_keyboard for b in row]
    assert len(flat) == 2                                    # DOAR Bolt 2%/16%, fără 0%
    # callback_data: onb|nerezident|<cod> — cele 2 coduri active, fără marcaj de selecție
    cbs = {b.callback_data for b in flat}
    assert cbs == {f"onb|nerezident|{c}" for c in VALID_REGIMURI_NEREZIDENT}


# ════════════════════════════════════════════════════════
# Uber sub-pas C — gate platforme + captare per-platformă
# ════════════════════════════════════════════════════════

def test_pasi_nerezident_per_platforma():
    # GATE rămâne 8 (next_step_after_impunere îl întoarce); CONFIRMARE rămâne 7.
    assert onb.STEP_CONFIRMARE == 7
    assert onb.STEP_REGIM_NEREZIDENT == 8           # gate (pasul de intrare)
    assert onb.STEP_REGIM_NEREZIDENT_BOLT == 9
    assert onb.STEP_REGIM_NEREZIDENT_UBER == 10
    assert onb.next_step_after_impunere("ridesharing") == onb.STEP_REGIM_NEREZIDENT


def test_gate_platforme_3_optiuni():
    kb = onb._kb_platforme_nerezident()
    cbs = {b.callback_data for row in kb.inline_keyboard for b in row}
    assert cbs == {"onb|platforme|BOLT", "onb|platforme|UBER", "onb|platforme|AMBELE"}


def test_coduri_uber_sunt_doar_uber():
    codes = {r["code"] for r in onb.REGIMURI_NEREZIDENT_UBER}
    assert codes == VALID_REGIMURI_NEREZIDENT_UBER
    assert all(c.startswith("UBER_") for c in codes)         # niciun Bolt/2% în UI Uber
    assert codes <= {e.value for e in RegimNerezident}
    # keyboard Uber: 2 opțiuni, callback onb|nerezident|<cod uber>
    kb = onb._kb_regim_nerezident_uber()
    cbs = {b.callback_data for row in kb.inline_keyboard for b in row}
    assert cbs == {f"onb|nerezident|{c}" for c in VALID_REGIMURI_NEREZIDENT_UBER}


def test_seturi_valid_separate_resping_cross():
    # Seturile NU se intersectează → validatorul fiecărei platforme respinge codul celeilalte.
    assert VALID_REGIMURI_NEREZIDENT_BOLT.isdisjoint(VALID_REGIMURI_NEREZIDENT_UBER)
    assert not users_repo.is_valid_regim_nerezident_bolt("UBER_CU_CRF")   # Uber respins pe Bolt
    assert not users_repo.is_valid_regim_nerezident_uber("BOLT_CU_CRF")   # Bolt respins pe Uber
    assert users_repo.is_valid_regim_nerezident_bolt("BOLT_CU_CRF")
    assert users_repo.is_valid_regim_nerezident_uber("UBER_CU_CRF")


def test_label_pentru_coduri_uber():
    for c in ("UBER_CU_CRF", "UBER_FARA_CRF"):
        assert onb.nerezident_label(c) not in ("", "—")      # eticheta combinată acoperă Uber


# ── Integrare: captarea scrie câmpul PER-PLATFORMĂ corect (nu deprecatul) ──

class _FakeQuery:
    def __init__(self, chat_id):
        self.message = SimpleNamespace(chat_id=chat_id)
        self.edits = []
    async def edit_message_text(self, text, **kw):
        self.edits.append(text)


class _FakeBot:
    async def send_message(self, *a, **kw):
        pass


def _ctx():
    return SimpleNamespace(user_data={}, bot=_FakeBot())


def _update(tg_id, chat_id=999):
    q = _FakeQuery(chat_id)
    upd = SimpleNamespace(
        callback_query=q,
        effective_user=SimpleNamespace(id=tg_id),
        effective_chat=SimpleNamespace(id=chat_id),
    )
    return upd, q


def _db(monkeypatch, tmp_path, tg_id):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    monkeypatch.setattr(onb, "get_session", lambda: Session())
    s = Session()
    s.add(User(telegram_id=tg_id, activity_code="ridesharing",
               onboarding_step=onb.STEP_REGIM_NEREZIDENT))
    s.commit(); s.close()
    return Session


@pytest.mark.asyncio
async def test_captare_doar_uber_scrie_uber(monkeypatch, tmp_path):
    Session = _db(monkeypatch, tmp_path, tg_id=501)
    ctx = _ctx()
    upd, _ = _update(501)
    # GATE: alege „Uber" → rutează direct la întrebarea Uber.
    await onb.handle_onboarding_callback(upd, ctx, ["onb", "platforme", "UBER"])
    # Răspunde Uber: 0% (cu certificat).
    await onb.handle_onboarding_callback(upd, ctx, ["onb", "nerezident", "UBER_CU_CRF"])

    s = Session()
    u = s.query(User).filter_by(telegram_id=501).one()
    assert u.regim_nerezident_uber == "UBER_CU_CRF"     # scris pe câmpul Uber
    assert u.regim_nerezident_bolt is None              # Bolt NEatins
    assert getattr(u, "regim_nerezident", None) is None  # NU deprecatul
    s.close()


@pytest.mark.asyncio
async def test_captare_doar_bolt_scrie_bolt(monkeypatch, tmp_path):
    Session = _db(monkeypatch, tmp_path, tg_id=502)
    ctx = _ctx()
    upd, _ = _update(502)
    await onb.handle_onboarding_callback(upd, ctx, ["onb", "platforme", "BOLT"])
    await onb.handle_onboarding_callback(upd, ctx, ["onb", "nerezident", "BOLT_CU_CRF"])

    s = Session()
    u = s.query(User).filter_by(telegram_id=502).one()
    assert u.regim_nerezident_bolt == "BOLT_CU_CRF"     # scris pe câmpul Bolt (nu deprecatul)
    assert u.regim_nerezident_uber is None
    assert getattr(u, "regim_nerezident", None) is None
    s.close()


@pytest.mark.asyncio
async def test_captare_ambele_inlantuie_bolt_apoi_uber(monkeypatch, tmp_path):
    Session = _db(monkeypatch, tmp_path, tg_id=503)
    ctx = _ctx()
    upd, _ = _update(503)
    # „Ambele" → întâi Bolt, apoi (automat) Uber.
    await onb.handle_onboarding_callback(upd, ctx, ["onb", "platforme", "AMBELE"])
    await onb.handle_onboarding_callback(upd, ctx, ["onb", "nerezident", "BOLT_CU_CRF"])
    # După Bolt, fiindcă e „Ambele", pasul curent trebuie să fie întrebarea Uber.
    s = Session()
    assert s.query(User).filter_by(telegram_id=503).one().onboarding_step == onb.STEP_REGIM_NEREZIDENT_UBER
    s.close()
    await onb.handle_onboarding_callback(upd, ctx, ["onb", "nerezident", "UBER_FARA_CRF"])

    s = Session()
    u = s.query(User).filter_by(telegram_id=503).one()
    assert u.regim_nerezident_bolt == "BOLT_CU_CRF"     # 2% Bolt
    assert u.regim_nerezident_uber == "UBER_FARA_CRF"   # 16% Uber — ambele, regim distinct
    assert u.onboarding_step == onb.STEP_CONFIRMARE     # după Uber → confirmare
    s.close()
