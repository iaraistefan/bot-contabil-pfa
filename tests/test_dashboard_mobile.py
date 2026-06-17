"""
C9-C — mobile-first Mini App (viewport stable + card-rows plati + touch targets).

Gardian la nivel de TEMPLATE (nu există runner JS): verifică prezența contractului
mobil (anti-regresie pe refactor). Nu testează randarea reală, ci structura/config-ul.
"""

from pathlib import Path

_HTML = (Path(__file__).resolve().parent.parent
         / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")


def test_viewport_stable_height():
    # .app folosește înălțimea reală a Mini App-ului, cu fallback 100vh în browser
    assert "var(--tg-viewport-stable-height,100vh)" in _HTML
    assert "viewportStableHeight" in _HTML
    assert 'setProperty("--tg-viewport-stable-height"' in _HTML
    assert "viewportChanged" in _HTML            # re-set la chrome/tastatură


def test_plati_card_rows_pe_mobil():
    assert 'class="t-cards"' in _HTML            # tabelul plati marcat
    assert ".t-cards thead{display:none}" in _HTML   # antet ascuns → carduri
    assert ".t-cards td::before{content:attr(data-label)" in _HTML  # label:valoare
    # render-ul pune data-label pe celule
    assert 'data-label="Obligație"' in _HTML and 'data-label="Sumă"' in _HTML


def test_touch_targets_44px_mobil():
    assert ".ybtn{width:44px;height:44px" in _HTML       # selector an (era 25px)
    assert ".pchip{padding:0 14px;min-height:44px" in _HTML
    assert ".doc-dl{min-height:44px" in _HTML


def test_registru_scroll_x():
    assert 'class="t-scroll"' in _HTML
    assert ".t-scroll{overflow-x:auto" in _HTML


def test_grafice_responsive():
    # confirmă config responsive (nu se taie/deformează pe îngust)
    assert "responsive:true" in _HTML and "maintainAspectRatio:false" in _HTML


def test_card_rows_doar_pe_mobil():
    # regulile .t-cards sunt în media query mobil → desktop rămâne tabel normal
    mobile = _HTML.split("@media(max-width:860px)", 1)[1]
    assert ".t-cards thead{display:none}" in mobile
