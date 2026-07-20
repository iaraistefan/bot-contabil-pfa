"""
N3 (audit pre-lansare) — butonul „✅ Marchează plătit" e ASCUNS până la Pas 12.
Handlerul nu persista nimic (promisiune falsă). Regresie: butonul nu reapare, iar
restul ecranului de plată (Înapoi/Închide) rămâne intact.
"""
from app.services.plata_fiscala import _build_payment_detail_buttons


def _callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_butonul_paid_nu_apare():
    markup = _build_payment_detail_buttons("D212", 2026, 5)
    cbs = _callbacks(markup)
    assert not any(c.startswith("plata|paid") for c in cbs)


def test_inapoi_si_inchide_raman():
    # Nu am stricat markup-ul: rândul de navigare e intact.
    markup = _build_payment_detail_buttons("D212", 2026, 5)
    cbs = _callbacks(markup)
    assert "plata|back" in cbs
    assert "nav|close" in cbs
