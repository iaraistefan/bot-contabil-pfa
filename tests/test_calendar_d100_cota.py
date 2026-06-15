"""
Fiscal #3 — SUB-PAS C: calendarul fiscal (get_monthly_alerts / format_fiscal_message)
reflectă regimul nerezident pentru D100, aliniat la calculul corect din B.

  - cota > 0 (Bolt 2%/16%)        → D100 prezent, procent DINAMIC în nume;
  - cota == 0 (scutit, ex. Uber)  → D100 OMIS (nu se depune; D207 anual acoperă);
  - cota None (neconfigurat)     → D100 prezent ca nudge „regim nesetat", FĂRĂ 2%;
  - D301/D390 NU depind de cotă (rămân neschimbate, gated doar pe has_bolt).
"""

from app.domain import fiscal_calendar as fc

D100 = "D100 poz. 634"


def _codes(cota, has_bolt=True):
    return [a["code"] for a in fc.get_monthly_alerts(2026, 1,
                                                     has_bolt_invoice=has_bolt,
                                                     cota_nerezident=cota)]


def _d100_entry(cota):
    for a in fc.get_monthly_alerts(2026, 1, has_bolt_invoice=True, cota_nerezident=cota):
        if a["code"] == D100:
            return a
    return None


# ── cota > 0 → D100 prezent cu procent dinamic ──────────────────────

def test_crf_2pct_d100_prezent_dinamic():
    e = _d100_entry(0.02)
    assert e is not None
    assert "2%" in e["name"]
    assert "comisioane" in e["name"].lower()


def test_fara_crf_16pct_d100_dinamic():
    e = _d100_entry(0.16)
    assert e is not None
    assert "16%" in e["name"]
    # nu rămâne „2%" hardcodat
    assert "2%" not in e["name"]


# ── cota == 0 (scutit) → D100 OMIS ──────────────────────────────────

def test_crf_scutit_d100_omis():
    assert D100 not in _codes(0.0)
    assert _d100_entry(0.0) is None


# ── cota None (neconfigurat) → nudge, fără 2% presupus ──────────────

def test_neconfigurat_d100_nudge_fara_procent():
    e = _d100_entry(None)
    assert e is not None
    assert "nesetat" in e["name"].lower()
    assert "2%" not in e["name"]                  # NU o cifră/rată presupusă


# ── D301/D390 neafectate de cotă ────────────────────────────────────

def test_d301_d390_neafectate_de_cota():
    non_d100 = lambda cota: sorted(c for c in _codes(cota) if c != D100)
    baza = non_d100(0.02)
    assert baza == non_d100(0.0) == non_d100(0.16) == non_d100(None)
    assert len(baza) >= 1                          # exista alte declaratii lunare


def test_fara_bolt_nimic_indiferent_de_cota():
    for cota in (0.02, 0.16, 0.0, None):
        assert _codes(cota, has_bolt=False) == []


# ── format_fiscal_message propagă cota ──────────────────────────────

def test_mesaj_scutit_fara_linie_d100():
    # marker specific D100: codul „D100 poz. 634" (NU „comisioane", care apare
    # și în descrierea D301). La scutit, linia D100 lunară lipsește din mesaj.
    msg = fc.format_fiscal_message(2026, 1, has_bolt_invoice=True, cota_nerezident=0.0)
    assert D100 not in msg


def test_mesaj_2pct_contine_d100():
    msg = fc.format_fiscal_message(2026, 1, has_bolt_invoice=True, cota_nerezident=0.02)
    assert D100 in msg and "(2% Bolt)" in msg
