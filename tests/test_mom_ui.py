"""
C2 — gardian UI badge-uri trend MoM (dashboard.html).

Verifică badge-urile + getMom + applyMomBadge + polaritatea (venit up=good, cost up=bad,
tva neutru) + ascundere la comparabil:false. Sintaxa JS validată de test_dashboard_js_syntax.
"""

from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent
        / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")


def test_badge_spans_in_top():
    for elid in ("ov-chelt-trend", "ov-tva-trend", "ven-brut-trend"):
        assert f'id="{elid}"' in HTML
        # fiecare badge e ascuns implicit (nu apare gol înainte de date)
    assert HTML.count('class="trend" id="ov-chelt-trend" style="display:none"') == 1


def test_clase_culoare_noi_decuplate():
    # clase noi good/bad/neutral (decuplate de săgeată); .up/.down (simulator) neatinse
    assert ".kpi .trend.good{" in HTML
    assert ".kpi .trend.bad{" in HTML
    assert ".kpi .trend.neutral{" in HTML
    assert ".kpi .trend.up{" in HTML and ".kpi .trend.down{" in HTML   # neatinse


def test_getmom_si_apply():
    assert "async function getMom()" in HTML
    assert "?mom=1" in HTML                                   # cere blocul opt-in
    assert "now.getMonth()" in HTML and "lm===0" in HTML      # ultima lună completă din azi
    assert "function applyMomBadge(elId, metricKey)" in HTML
    assert "!m.comparabil" in HTML                            # comparabil:false → ascuns


def test_polaritate_corecta():
    # maparea metrică → polaritate
    assert 'income_total:"venit"' in HTML
    assert 'expense_deductible_total:"cost"' in HTML
    assert 'vat_out_total:"neutru"' in HTML
    # cost: scădere = favorabil (invers față de venit)
    assert '(pol==="venit")?(m.dir==="up"):(m.dir==="down")' in HTML


def test_apel_pe_kpi_lunare():
    assert 'applyMomBadge("ven-brut-trend", "income_total")' in HTML
    assert 'applyMomBadge("ov-chelt-trend", "expense_deductible_total")' in HTML
    assert 'applyMomBadge("ov-tva-trend", "vat_out_total")' in HTML
    # ov-net (anual YTD) NU primește badge MoM
    assert 'applyMomBadge("ov-net' not in HTML


def test_eticheta_completa_la_hover():
    assert "față de luna trecută" in HTML                     # text complet (title)
