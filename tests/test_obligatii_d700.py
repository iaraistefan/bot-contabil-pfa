"""
Teste pentru garda D700 (Faza 1, bucata #2 — fix fals pozitiv).

D700 = inregistrarea codului special TVA art. 317, procedura UNICA (one-time).
Trebuie sa apara DOAR daca user-ul NU e inca inregistrat (has_cod_special_tva
False). Pentru cei deja inregistrati (cazul Stefan) NU trebuie sa apara.

today fixat pentru determinism.

Termenul UNICA nu mai e „today + 7 zile": se derivă din prima cursă (primul
venit înregistrat), fiindcă art. 317 alin. (1) lit. c) leagă înregistrarea de
primirea serviciului. De aceea `_codes` pasează `prima_activitate` — fără ea
obligația e prospectivă și nu apare deloc în calendar. Cazul acela, împreună cu
recomandarea de prevenție care rămâne aprinsă pentru el, e acoperit în
`test_d700_termen_eveniment.py`.
"""

from datetime import date

from app.domain.fiscal_calendar import get_obligations_for_user

TODAY = date(2026, 6, 4)
PRIMA_CURSA = date(2026, 2, 10)


def _codes(prima_activitate=PRIMA_CURSA, **kw):
    obl = get_obligations_for_user(
        2026, 6, "PFA", "ridesharing", today=TODAY,
        prima_activitate=prima_activitate, **kw
    )
    return {o.definitie.cod for o in obl}


# ────────────────────────────────────────────────────────────
# Cazul Stefan — deja inregistrat: D700 NU apare
# ────────────────────────────────────────────────────────────

def test_d700_nu_apare_daca_deja_inregistrat():
    codes = _codes(
        has_cod_special_tva=True,
        has_intracom_invoice=True,
        intracom_base_amount=712.65,
    )
    assert "D700" not in codes


# ────────────────────────────────────────────────────────────
# PFA nou, neinregistrat: D700 APARE (caz legitim, nu-l stricam)
# ────────────────────────────────────────────────────────────

def test_d700_apare_daca_neinregistrat():
    codes = _codes(has_cod_special_tva=False)
    assert "D700" in codes


def test_pfa_nou_fara_factura_doar_d700():
    # A inceput sa conduca, dar inca nu are factura de comision: D700 da
    # (declansatorul e prima cursa, nu factura — vezi PR #158); declaratiile
    # lunare NU (cer baza intracom / cod special).
    codes = _codes(has_cod_special_tva=False, has_intracom_invoice=False)
    assert "D700" in codes
    assert "D301" not in codes
    assert "D390" not in codes
    assert "D100 poz. 634" not in codes


# ────────────────────────────────────────────────────────────
# Regresie — D301/D390/D100 neafectate de garda noua
# ────────────────────────────────────────────────────────────

def test_declaratii_lunare_neafectate():
    # cu factura intracom + cod special -> cele 3 declaratii lunare apar normal
    codes = _codes(
        has_cod_special_tva=True,
        has_intracom_invoice=True,
        intracom_base_amount=712.65,
    )
    assert "D301" in codes
    assert "D390" in codes
    assert "D100 poz. 634" in codes
    # iar D700 nu (deja inregistrat)
    assert "D700" not in codes
