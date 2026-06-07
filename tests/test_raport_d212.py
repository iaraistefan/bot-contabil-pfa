"""
Teste pentru secțiunea fiscală pe REALIZAT YTD în format_report_message
(Faza 3 — fix CASS context). d212 dat → estimare anuală; None → fallback vechi.
"""

from types import SimpleNamespace

from app.services.tax_engine import format_report_message


def _totals(**over):
    t = {
        "month_name": "Mai", "year": 2026,
        "activity_icon": "🚗", "activity_name": "Ridesharing",
        "income_breakdown": [], "income_total": 0.0,
        "income_cash": 0.0, "income_bank": 0.0,
        "expense_breakdown": [], "expense_deductible_total": 0.0,
        "vat_out_total": 0.0, "vat_in_total": 0.0, "vat_net": 0.0,
        "cota_tva": 0.21, "profit_estimated": 182.32, "tx_count": 3,
        "fiscal_estimate": None,
    }
    t.update(over)
    return t


def _d212(venit_net, cas, cass, impozit):
    return SimpleNamespace(
        venit_net=venit_net, cas=cas, cass=cass, impozit=impozit,
        total_plata=cas + cass + impozit,
    )


# ────────────────────────────────────────────────────────────
# Cu d212 → secțiune anuală pe realizat YTD
# ────────────────────────────────────────────────────────────

def test_sectiune_anuala_din_d212():
    d = _d212(venit_net=182.32, cas=0.0, cass=2430.0, impozit=0.0)
    msg = format_report_message(_totals(), d212=d)
    assert "Estimare fiscală anuală (realizat ian–Mai 2026)" in msg
    assert "Venit net realizat ian–Mai" in msg
    assert "2430.00" in msg                    # CASS din d212
    assert "taxe ANUALE pe realizat" in msg    # caveat


def test_caz_venit_mic_context_corect():
    # exact scenariul de pe telefon: profit lunar mic + CASS minim anual
    d = _d212(venit_net=182.32, cas=0.0, cass=2430.0, impozit=0.0)
    msg = format_report_message(_totals(profit_estimated=182.32), d212=d)
    # profitul lunar (182.32) e in bilantul de sus
    assert "182.32" in msg
    # iar CASS 2430 e clar in sectiunea ANUALA, cu baza realizata afisata
    i_venit = msg.index("Venit net realizat ian–Mai")
    i_cass = msg.index("2430.00")
    assert i_venit < i_cass                     # contextul vine inainte de cifra


def test_separare_vizuala_inainte_de_sectiunea_fiscala():
    d = _d212(venit_net=50000.0, cas=12150.0, cass=5000.0, impozit=3000.0)
    msg = format_report_message(_totals(), d212=d)
    # linie de separare inainte de titlul sectiunii anuale
    bloc = msg.split("Estimare fiscală anuală")[0]
    assert "━━━" in bloc.rsplit("\n\n", 1)[-1] or "━━━" in bloc


# ────────────────────────────────────────────────────────────
# Fără d212 → fallback la calea veche (regresie)
# ────────────────────────────────────────────────────────────

def test_fallback_fara_d212_neschimbat():
    # fără d212 și fără fiscal_estimate → nicio secțiune anuală nouă
    msg = format_report_message(_totals())
    assert "Estimare fiscală anuală" not in msg
    # raportul de bază tot se produce
    assert "RAPORT MAI 2026" in msg
    assert "Profit estimat" in msg
