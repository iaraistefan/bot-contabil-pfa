"""
Fiscal #7 — termen anual cu roll-forward, SURSĂ UNICĂ pentru v1 (Telegram,
get_annual_alerts) și v2 (web, compute_obligation).

Bug: v1 hardcoda date(year, m, d) fără roll-forward → după ce termenul trecea,
Telegram arăta data trecută ca „depășit" (fals-alarm pt userii care AU depus),
iar web (v2) arăta corect următorul termen. Fix: ambele folosesc
`_compute_termen_anual_rolling` → nu pot diverge.

+ Fiscal #6 (frontend): ov-net citește venit_net ANUAL (getD212), nu
  profit_estimated lunar (care pe luna curentă incompletă ieșea fals-negativ).
"""

from datetime import date
from pathlib import Path

from app.domain import fiscal_calendar as fc

_ROOT = Path(__file__).resolve().parent.parent


# ── #7: helper roll-forward (regula pură) ───────────────────────────

def test_rolling_dupa_luna_termenului_trece_la_anul_urmator():
    # iunie (6) > mai (5) → anul următor
    assert fc._compute_termen_anual_rolling(2026, 6, 5, 25) == date(2027, 5, 25)


def test_rolling_inainte_de_luna_termenului_ramane_anul_curent():
    # ianuarie (1) <= mai (5) → anul curent
    assert fc._compute_termen_anual_rolling(2026, 1, 5, 25) == date(2026, 5, 25)


def test_rolling_boundary_luna_egala():
    # mai (5) == mai (5) → anul curent (nu rola încă)
    assert fc._compute_termen_anual_rolling(2026, 5, 5, 25) == date(2026, 5, 25)


# ── #7: get_annual_alerts (v1) cu roll-forward ──────────────────────

def _d212(alerts):
    return next(a for a in alerts if a["code"] == "D212")


def test_v1_iunie_d212_termen_2027_nu_depasit():
    a = _d212(fc.get_annual_alerts(2026, today=date(2026, 6, 15)))
    assert a["deadline"] == "25.05.2027"          # următorul, NU 2026 trecut
    assert a["status"] != "overdue"               # nu mai e fals „depășit"


def test_v1_ianuarie_d212_termen_2026_neschimbat():
    a = _d212(fc.get_annual_alerts(2026, today=date(2026, 1, 15)))
    assert a["deadline"] == "25.05.2026"          # luna ≤ termen → an curent


# ── #7: DOVADA v1 == v2 (nu pot diverge) ────────────────────────────

def test_v1_egal_v2_pe_aceeasi_zi():
    today = date(2026, 6, 15)
    # v2: compute_obligation pentru D212, perioada curentă
    o = fc.compute_obligation(
        fc.DEFINITII_OBLIGATII["D212"],
        year=2026, month=today.month,
        forma_juridica="PFA", activity_code="ridesharing", today=today,
    )
    # v1: get_annual_alerts
    a = _d212(fc.get_annual_alerts(2026, today=today))
    # ACEEAȘI dată — sursă unică (_compute_termen_anual_rolling)
    assert a["deadline"] == o.termen.strftime("%d.%m.%Y") == "25.05.2027"


def test_v1_egal_v2_si_inainte_de_termen():
    today = date(2026, 3, 10)                      # martie ≤ mai
    o = fc.compute_obligation(
        fc.DEFINITII_OBLIGATII["D212"],
        year=2026, month=today.month,
        forma_juridica="PFA", activity_code="ridesharing", today=today,
    )
    a = _d212(fc.get_annual_alerts(2026, today=today))
    assert a["deadline"] == o.termen.strftime("%d.%m.%Y") == "25.05.2026"


# ── #7: roll-forward uniform pe toate cele 4 anuale (nu doar D212) ──

def test_roll_forward_uniform_pe_toate_anualele():
    # iunie: D207(feb) și D212/CAS/CASS(mai) au trecut toate → toate 2027
    alerts = fc.get_annual_alerts(2026, today=date(2026, 6, 15))
    by_code = {a["code"]: a for a in alerts}
    assert by_code["D207"]["deadline"] == "28.02.2027"
    for cod in ("D212", "CAS", "CASS"):
        assert by_code[cod]["deadline"].endswith("2027")


# ── #6: ov-net din venit_net ANUAL, nu profit_estimated lunar ───────

def test_6_ov_net_din_venit_net_anual():
    html = (_ROOT / "app/http/templates/dashboard.html").read_text(encoding="utf-8")
    assert 'setNum("ov-net", fisc.venit_net' in html          # anual YTD (= bot)
    assert 'setNum("ov-net", p.profit_estimated' not in html  # NU lunar (bug #6)
