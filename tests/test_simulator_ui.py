"""
A3.1 — gardian UI simulator regim (dashboard.html).

Verifică prezența slotului + funcțiilor + dicționarului de mesaje (cele 5 coduri din
A1/A2). Sintaxa JS e validată separat de test_dashboard_js_syntax.py (node --check).
"""

from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parent.parent
        / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")


def test_slot_si_buton():
    assert 'id="ov-simulator"' in HTML
    assert 'id="sim-body"' in HTML
    assert 'onclick="loadSimulare()"' in HTML
    assert "Află ce regim e mai avantajos" in HTML


def test_functii_si_fetch():
    assert "async function getSimulare(y)" in HTML
    assert "/api/v1/simulare-regim/" in HTML          # fetch ca declaratie-unica
    assert "function renderSimulator(d)" in HTML
    assert "async function loadSimulare()" in HTML
    assert "window.loadSimulare=loadSimulare" in HTML


def test_cele_5_coduri_traduse():
    assert "const SIM_AVERT" in HTML
    for cod in ("NORMA_INDISPONIBILA", "NORMA_DOAR_DIN_2026", "PLAFON_DEPASIT",
                "REVENIRE_NORMA_2ANI", "SCHIMBARE_ANUL_URMATOR"):
        assert cod in HTML, cod


def test_cazuri_speciale_si_disclaimer():
    assert "fara_venituri" in HTML                    # caz fără venituri tratat în UI
    assert "Estimare orientativă — verifică cu contabilul" in HTML
    # textele rafinate (fără majuscule de accentuare)
    assert "o obligație legală" in HTML               # PLAFON_DEPASIT rafinat
    assert "termen 25 mai" in HTML                    # SCHIMBARE_ANUL_URMATOR rafinat
