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
    assert "async function getSimulare(y,norma)" in HTML
    assert "/api/v1/simulare-regim/" in HTML          # fetch ca declaratie-unica
    assert "function renderSimulator(d" in HTML
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


# ════════════════════════════════════════════════════════════
#   A3.2 — selector tip localitate + re-simulare cu ?norma (ipoteză)
# ════════════════════════════════════════════════════════════

def test_getsimulare_accepta_norma():
    assert "async function getSimulare(y,norma)" in HTML
    assert "?norma=" in HTML                           # re-apel cu override
    assert "sim-${y}-${norma" in HTML                  # cache key include norma


def test_selector_tip_localitate():
    assert "function _simSelectorTip()" in HTML
    assert "async function simPickTip(tip)" in HTML
    assert "window.simPickTip=simPickTip" in HTML
    # cele 3 chip-uri reale (nu urban/rural) — valorile nomenclatorului
    for tip in ("municipiu", "oras", "comuna"):
        assert f'chip("{tip}")' in HTML
    assert "TIP_LBL" in HTML and "Municipiu" in HTML and "Comună" in HTML
    assert "/api/v1/norma-lookup?judet=" in HTML       # lookup live


def test_selector_doar_pentru_indisponibila():
    # gate: selectorul apare DOAR pe NORMA_INDISPONIBILA (lipsă date), NU pe DOAR_DIN_2026
    assert 'av.includes("NORMA_INDISPONIBILA") && !!d.judet' in HTML
    assert 'cod==="NORMA_INDISPONIBILA" && arataSelector' in HTML   # codul devine selector


def test_ipoteza_marcata():
    # re-simularea cu normă căutată e marcată ca ipoteză (nu acțiune)
    assert "ipotezaNote" in HTML
    assert "ipoteză" in HTML.lower()
