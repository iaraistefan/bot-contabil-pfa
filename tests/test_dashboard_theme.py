"""
C9-A — temă adaptivă Mini App (branded-dark + chrome sync).

NU există runner JS în proiect → gardian la nivel de TEMPLATE (string/structură): verifică
că logica de temă există + invarianții de brand/fallback NU se pierd accidental. Nu testează
comportamentul JS în runtime, ci prezența contractului (anti-regresie pe refactor).
"""

from pathlib import Path

_HTML = (Path(__file__).resolve().parent.parent
         / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")


def test_functia_de_tema_exista():
    assert "function applyTelegramTheme()" in _HTML
    assert "applyTelegramTheme();" in _HTML                  # apelată la init


def test_fallback_browser_early_return():
    # fără tg (browser) → return imediat, :root navy rămâne
    assert "if(!tg) return;" in _HTML


def test_chrome_sync_ambele_scheme():
    assert "setHeaderColor" in _HTML and "setBackgroundColor" in _HTML
    assert "header_bg_color" in _HTML and "bg_color" in _HTML


def test_neutre_adaptate_doar_pe_dark():
    # gardul de schemă: neutrele se ating DOAR pe dark (light → dark-surface păstrat)
    assert "colorScheme" in _HTML
    assert 'if(dark && tp.bg_color)' in _HTML
    # neutrele mapate
    for v in ('"--ink"', '"--night"', '"--card"', '"--cream"', '"--muted"'):
        assert f"set({v}," in _HTML, f"neutrul {v} nu e mapat la temă"


def test_accentele_brand_raman_hardcodate():
    # accentele NU se adaptează (nu sunt în set(...) din applyTelegramTheme)
    for accent in ('set("--emerald"', 'set("--gold"', 'set("--red"', 'set("--blue"', 'set("--pos"'):
        assert accent not in _HTML, f"accentul {accent} NU trebuie adaptat la temă (brand)"
    # și rămân definite hardcodat în :root
    assert "#2DD4BF" in _HTML        # teal (emerald)
    assert "#F5B945" in _HTML        # gold
    assert "#F2685C" in _HTML        # red


def test_reaplicare_la_schimbarea_temei():
    assert 'themeChanged' in _HTML   # re-aplică live când userul schimbă tema
