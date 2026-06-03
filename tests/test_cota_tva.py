"""
Teste pentru cota TVA centralizată (Problema #2).

Sursa de adevăr: app.domain.tax_rules.cota_tva(data) + apply_reverse_charge.
Context fiscal: 21% din 01.08.2025; 19% până la 31.07.2025.
"""

from datetime import date

import pytest

from app.domain.tax_rules import (
    cota_tva,
    apply_reverse_charge,
    PRAG_TVA_21,
    VAT_REVERSE_CHARGE_PCT,
)


# ────────────────────────────────────────────────────────────
# A. cota_tva — pragul 01.08.2025
# ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("data, asteptat", [
    (date(2025, 7, 31), 0.19),   # ultima zi cu 19%
    (date(2025, 8, 1), 0.21),    # prima zi cu 21% (exact pe prag)
    (date(2025, 7, 1), 0.19),
    (date(2025, 8, 15), 0.21),
    (date(2026, 6, 3), 0.21),    # azi
    (date(2024, 1, 1), 0.19),    # istoric — NU "21% din 2024"
])
def test_cota_tva_prag(data, asteptat):
    assert cota_tva(data) == asteptat


def test_pragul_e_01_08_2025():
    assert PRAG_TVA_21 == date(2025, 8, 1)


# ────────────────────────────────────────────────────────────
# B. apply_reverse_charge — cu dată, cu override, fără nimic
# ────────────────────────────────────────────────────────────

def test_reverse_charge_pe_data_21():
    assert apply_reverse_charge(346.81, data=date(2025, 8, 1)) == 72.83


def test_reverse_charge_pe_data_19():
    assert apply_reverse_charge(346.81, data=date(2025, 7, 31)) == 65.89


def test_reverse_charge_override_vat_pct():
    # override explicit are prioritate față de dată
    assert apply_reverse_charge(100.0, vat_pct=19) == 19.0
    assert apply_reverse_charge(100.0, vat_pct=19, data=date(2026, 1, 1)) == 19.0


def test_reverse_charge_default_neschimbat():
    # fără dată și fără override → cota standard curentă (regression guard)
    assert apply_reverse_charge(346.81) == round(346.81 * VAT_REVERSE_CHARGE_PCT / 100, 2)
    assert apply_reverse_charge(346.81) == 72.83


# ────────────────────────────────────────────────────────────
# C. Round-trip bază ↔ TVA (coerența inversării)
# ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("data", [date(2025, 8, 1), date(2025, 7, 31), date(2026, 1, 1)])
def test_round_trip_baza_tva(data):
    baza = 712.65
    tva = apply_reverse_charge(baza, data=data)
    # inversăm folosind ACEEAȘI cotă (pe aceeași dată)
    baza_recuperata = tva / cota_tva(data)
    assert abs(baza_recuperata - baza) < 0.05  # toleranță la rotunjirea TVA-ului


# ────────────────────────────────────────────────────────────
# D. Regression — banii nu se schimbă pe datele reale (toate ≥ aug 2025)
# ────────────────────────────────────────────────────────────

def test_regression_657_ianuarie_2026():
    # comision real ian 2026 = 657 RON, 21% = 137.97 RON (657 * 0.21, neschimbat).
    # NB: 137.97, nu 138 — round(657 * 0.21, 2) = 137.97.
    assert apply_reverse_charge(657, data=date(2026, 1, 1)) == 137.97
    # calea default veche (fără dată) trebuie să dea EXACT același rezultat
    assert apply_reverse_charge(657) == apply_reverse_charge(657, data=date(2026, 1, 1))
    assert apply_reverse_charge(657) == 137.97
