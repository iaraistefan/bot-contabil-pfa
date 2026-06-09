"""
Teste PAS 4a felia 3 — logica pură UI confirmare (app/services/bank_import_ui.py).

State machine + text builders + mapare categorie. Zero Telegram, zero DB.
Acoperă: punctul 1 (UI filtrează — niciodată decizie pentru bucket nepostabil),
punctul 4 (mesaj rezultat transparent), jumătate din punctul 2 (suprascriere curată).
"""
from datetime import date

from app.integrations.imports.bank_statement import BankTxn
from app.integrations.imports.classify import (
    BankTxnClasificat,
    VENIT_BOLT, PLATA_TAXA, RETURNARE_TAXA, COMISION_BANCAR,
    CHELTUIALA_BUSINESS, DE_VERIFICAT,
)
from app.services import bank_import_ui as ui


def _cl(bucket, categorie=None, suma=10.0, descr="x", directie="OUT",
        d=date(2026, 4, 1)):
    return BankTxnClasificat(BankTxn(d, suma, directie, descr), bucket, "et",
                             categorie=categorie)


# ──────────────────────────────────────────────────────────────
# MAPARE CATEGORIE
# ──────────────────────────────────────────────────────────────
def test_category_from_choice():
    assert ui.category_from_choice("fuel") == "fuel"
    assert ui.category_from_choice("service") == "car_service"
    assert ui.category_from_choice("other") == "other_expense"
    assert ui.category_from_choice("bogus") is None


# ──────────────────────────────────────────────────────────────
# STATE MACHINE — flux normal
# ──────────────────────────────────────────────────────────────
def test_state_machine_flux():
    clasificate = [
        _cl(CHELTUIALA_BUSINESS, categorie="fuel", descr="lukoil"),
        _cl(DE_VERIFICAT, descr="pos a", d=date(2026, 4, 2)),
        _cl(DE_VERIFICAT, descr="pos b", d=date(2026, 4, 3)),
    ]
    state = ui.init_state(clasificate, source_file_id=7)
    assert state["source_file_id"] == 7
    assert state["deverificat_idx"] == [1, 2]      # doar DE_VERIFICAT cer decizie
    assert not ui.is_done(state)

    i0, c0 = ui.current_deverificat(state)
    assert i0 == 1
    assert ui.record_decision(state, 1, "fuel")    # business → fuel
    i1, c1 = ui.current_deverificat(state)
    assert i1 == 2
    assert ui.record_decision(state, 2, None)      # personală
    assert ui.is_done(state)
    assert ui.current_deverificat(state) is None

    decisions = ui.build_decisions(state)
    assert decisions[0] == "fuel"      # CHELTUIALA_BUSINESS auto
    assert decisions[1] == "fuel"      # DE_VERIFICAT confirmat business
    assert decisions[2] is None        # personală


def test_record_decision_stale_ignorat():
    clasificate = [_cl(DE_VERIFICAT, descr="a"), _cl(DE_VERIFICAT, descr="b")]
    state = ui.init_state(clasificate, 1)
    # curentul e idx 1 (primul DE_VERIFICAT); un buton stale pentru idx 2 → ignorat
    assert ui.record_decision(state, 2, "fuel") is False
    assert state["pos"] == 0                        # nu a avansat


# ──────────────────────────────────────────────────────────────
# 1. UI FILTREAZĂ — niciodată decizie pentru bucket nepostabil
# ──────────────────────────────────────────────────────────────
def test_build_decisions_doar_postabile():
    clasificate = [
        _cl(VENIT_BOLT, suma=100, directie="IN"),
        _cl(PLATA_TAXA, suma=40),
        _cl(RETURNARE_TAXA, suma=40, directie="IN"),
        _cl(COMISION_BANCAR, suma=0.51),
        _cl(CHELTUIALA_BUSINESS, categorie="fuel", suma=200),
        _cl(DE_VERIFICAT, suma=31.81),
    ]
    state = ui.init_state(clasificate, 1)
    cur = ui.current_deverificat(state)
    ui.record_decision(state, cur[0], "other_expense")   # DE_VERIFICAT → business
    decisions = ui.build_decisions(state)
    for i, r in enumerate(clasificate):
        if r.bucket in (CHELTUIALA_BUSINESS, DE_VERIFICAT):
            assert decisions[i] is not None
        else:
            assert decisions[i] is None                  # nepostabile → None


def test_build_decisions_garda_structurala():
    # Chiar dacă cineva corupe `decisions` cu o categorie pe un bucket nepostabil,
    # build_decisions forțează None (UI nu POATE emite decizie nepostabilă).
    clasificate = [_cl(VENIT_BOLT, suma=100, directie="IN")]
    state = ui.init_state(clasificate, 1)
    state["decisions"][0] = "ride_revenue"               # corupere intenționată
    assert ui.build_decisions(state)[0] is None          # gardă structurală


# ──────────────────────────────────────────────────────────────
# 2. SUPRASCRIERE CURATĂ (abandon + extras nou — partea de logică)
# ──────────────────────────────────────────────────────────────
def test_init_state_suprascrie_curat():
    # stare veche, avansată la jumătate
    vechi = ui.init_state(
        [_cl(DE_VERIFICAT, descr="a"), _cl(DE_VERIFICAT, descr="b")], 1
    )
    ui.record_decision(vechi, vechi["deverificat_idx"][0], "fuel")
    assert vechi["pos"] == 1

    # extras NOU → init_state întoarce o stare proaspătă, independentă
    nou = ui.init_state([_cl(CHELTUIALA_BUSINESS, categorie="fuel")], 2)
    assert nou["source_file_id"] == 2
    assert nou["pos"] == 0
    assert nou["deverificat_idx"] == []                  # noul extras n-are DE_VERIFICAT
    assert nou["decisions"] == {0: "fuel"}               # zero reziduu din starea veche


# ──────────────────────────────────────────────────────────────
# 4. MESAJ REZULTAT transparent (dubluri explicate)
# ──────────────────────────────────────────────────────────────
def test_format_result_dubluri_explicate():
    res = {"posted": 0, "deductibil_sum": 0.0, "skipped_personal": 0,
           "skipped_dup": 6, "skipped_blocked": 0}
    msg = ui.format_result(res)
    assert "6 dubluri" in msg
    assert "mai încărcat" in msg.lower()                 # explică DE CE


def test_format_result_complet():
    res = {"posted": 3, "deductibil_sum": 187.34, "skipped_personal": 2,
           "skipped_dup": 1, "skipped_blocked": 0}
    msg = ui.format_result(res)
    assert "3 cheltuieli" in msg
    assert "187,34 lei deductibili" in msg
    assert "2 sărite ca personale" in msg
    assert "1 dubluri" in msg


# ──────────────────────────────────────────────────────────────
# TEXT — Ecran 1 + prompt DE_VERIFICAT
# ──────────────────────────────────────────────────────────────
def test_format_screen1():
    clasificate = [
        _cl(CHELTUIALA_BUSINESS, categorie="fuel", suma=100.0),
        _cl(DE_VERIFICAT, suma=31.81),
        _cl(DE_VERIFICAT, suma=73.29),
    ]
    msg = ui.format_screen1(clasificate)
    assert "business clare: 1" in msg
    assert "De verificat: 2" in msg
    assert "105,10 lei" in msg                           # 31.81 + 73.29


def test_format_deverificat_prompt():
    c = _cl(DE_VERIFICAT, suma=242.01, descr="Plata POS persoana fizica",
            d=date(2026, 4, 23))
    msg = ui.format_deverificat_prompt(0, 6, c)
    assert "1/6" in msg
    assert "23.04.2026" in msg
    assert "242,01 lei" in msg
