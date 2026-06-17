"""
C9-B — butoane native Telegram (BackButton/MainButton) + haptic.

Gardian la nivel de TEMPLATE (fără runner JS): verifică contractul nativ + fallback
browser (tot gated pe tg). Nu testează runtime, ci structura/gating-ul.
"""

from pathlib import Path

_HTML = (Path(__file__).resolve().parent.parent
         / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")


def test_currentpage_tracked_in_nav():
    assert "let currentPage" in _HTML
    assert "currentPage=page;" in _HTML          # setat la fiecare navigare
    assert "syncNative();" in _HTML              # nav() sincronizează butoanele


def test_backbutton_show_hide():
    assert "tg.BackButton.show()" in _HTML and "tg.BackButton.hide()" in _HTML
    assert 'currentPage!=="overview"' in _HTML   # vizibil pe sub-ecran
    assert 'nav("overview")' in _HTML            # Back → overview (nu închide app-ul)


def test_back_inchide_modalul_intai():
    # strat: Back → întâi închide modalul Plătește, apoi ecran
    assert "_modalOpen()" in _HTML and "closePlata()" in _HTML
    # openPlata/closePlata re-sincronizează BackButton
    assert _HTML.count("syncBackButton()") >= 3


def test_mainbutton_doar_pe_setari():
    assert 'currentPage==="setari"' in _HTML
    assert 'tg.MainButton.setText("Salvează")' in _HTML
    assert 'save.style.display="none"' in _HTML   # ascunde butonul in-page (zero duplicare)
    assert "tg.MainButton.hide()" in _HTML        # ascuns pe restul ecranelor


def test_haptic_subtil_gated():
    assert "selectionChanged()" in _HTML                       # tap nav
    assert 'notificationOccurred("success")' in _HTML          # salvare reușită
    assert 'notificationOccurred("error")' in _HTML            # eroare/validare
    assert "impactOccurred" not in _HTML                       # NU pe fiecare tap (excesiv)
    assert 'haptic("select")' in _HTML                         # apelat la tap nav-item


def test_fallback_browser_gated_pe_tg():
    # toate butoanele/haptic sunt gated pe tg → browser neschimbat
    assert "if(!tg || !tg.BackButton) return" in _HTML
    assert "if(!tg || !tg.MainButton) return" in _HTML
    assert "tg && tg.HapticFeedback" in _HTML
