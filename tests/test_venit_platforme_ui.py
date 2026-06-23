"""
B2 — gardian UI donut „Venit pe platformă" (dashboard.html).

Verifică panoul + canvas + funcția de render + logica de afișare (≥2 platforme reale →
vizibil; <2 → ascuns). Sintaxa JS validată separat de test_dashboard_js_syntax.py.
"""

from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent
        / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")


def test_panou_si_canvas():
    assert 'id="ven-platforme-panel"' in HTML
    assert "display:none" in HTML.split('id="ven-platforme-panel"', 1)[1][:80]  # ascuns implicit
    assert 'id="venPlatforme"' in HTML
    assert "Venit pe platformă" in HTML


def test_functie_render_si_apel():
    assert "function renderVenPlatforme(items)" in HTML
    assert "renderVenPlatforme(p.income_by_platform" in HTML       # apelat în loadVenituri
    assert "BRAND_COLOR" in HTML


def test_logica_afisare_doar_2_platforme_reale():
    # condiția numără platforme REALE (brand truthy); <2 → ascuns
    assert "filter(i=>i.brand).length" in HTML
    assert "reale<2" in HTML
    assert 'panel.style.display="none"' in HTML


def test_drawdonut_extins_cu_culori():
    # param colors opțional, default = paletă (regresie 0 ovDonut/chDonut)
    assert "function drawDonut(canvasId,items,key,colors)" in HTML
    assert "(colors||palette.slice(0,data.length))" in HTML


def test_culori_brand_distincte():
    # Bolt/Uber culori de brand; Altele → gri neutru (fallback C.txt)
    assert "bolt:C.emerald" in HTML and "uber:C.blue" in HTML
    assert "BRAND_COLOR[i.brand]||C.txt" in HTML
