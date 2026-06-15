"""
Fiscal #3 — SUB-PAS E: captarea regimului nerezident (onboarding condiționat).

Testează piesele pure ale fluxului de captare:
  - pasul nerezident e inserat DOAR pentru ridesharing (ceilalți → confirmare);
  - captarea oferă DOAR cele 2 opțiuni reale Bolt (2%/16%), fără 0% (acela e Uber);
    codurile active == VALID_REGIMURI_NEREZIDENT ⊆ enum (extensibil pt Uber);
  - CONFIRMARE rămâne pasul 7 (tranziții explicite), nerezident inserat ca 8.
"""

from app.services import onboarding as onb
from app.repositories.users import VALID_REGIMURI_NEREZIDENT
from app.domain.fiscal_profile import RegimNerezident


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
