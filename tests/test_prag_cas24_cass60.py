"""
Teste pentru pragurile noi (Faza 3 — extensie plafoane):
- prag_cas24_status: CAS 24 SMB = 97.200 → baza CAS se DUBLEAZĂ ("rău").
- prag_cass60_status: CASS 60 SMB = 243.000 → CASS se PLAFONEAZĂ ("bine"/informativ).

Aceeași formă ca prag_cas_status (status OK/APROAPE/DEPASIT, prin _prag_core).
Boundary exact + mesaje corecte fiscal (dublare vs plafonare).
"""

import pytest

from app.domain.contributii import prag_cas24_status, prag_cass60_status


# ────────────────────────────────────────────────────────────
# CAS 24 SMB — baza se dublează ("rău")
# ────────────────────────────────────────────────────────────

CAS24 = 97_200       # 24 × 4050
CAS24_80 = 77_760    # 80% din prag


@pytest.mark.parametrize("venit_net, status_ast", [
    (50_000, "OK"),               # ~51%
    (77_759, "OK"),               # chiar sub 80%
    (77_760, "APROAPE_PLAFON"),   # exact 80% (boundary)
    (90_000, "APROAPE_PLAFON"),   # ~93%
    (97_199, "APROAPE_PLAFON"),   # chiar sub 100%
    (97_200, "DEPASIT_PLAFON"),   # exact prag (boundary)
    (120_000, "DEPASIT_PLAFON"),  # peste
])
def test_cas24_status_praguri(venit_net, status_ast):
    assert prag_cas24_status(venit_net, 2026)["status"] == status_ast


def test_cas24_campuri_si_remaining():
    r = prag_cas24_status(90_000, 2026)
    assert r["threshold_ron"] == 97_200
    assert round(r["utilized_pct"]) == 93              # 90000/97200
    assert r["remaining_ron"] == 7_200                 # 97200 - 90000
    assert "Mai ai ~7200 lei" in r["message"]


def test_cas24_mesaj_dublare_la_depasire():
    r = prag_cas24_status(120_000, 2026)
    assert r["status"] == "DEPASIT_PLAFON"
    assert r["remaining_ron"] == 0.0
    assert "dublează" in r["message"].lower()
    assert "24.300" in r["message"] or "24300" in r["message"]   # CAS dublu ~24.300
    assert "12.150" in r["message"] or "12150" in r["message"]   # vs pragul minim
    assert "🔴" in r["message"]                                  # ton "rău"


def test_cas24_smb_din_params():
    assert prag_cas24_status(0, 2025)["threshold_ron"] == 97_200
    assert prag_cas24_status(0, 2026)["threshold_ron"] == 97_200


# ────────────────────────────────────────────────────────────
# CASS 60 SMB — plafonare ("bine"/informativ)
# ────────────────────────────────────────────────────────────

CASS60 = 243_000     # 60 × 4050
CASS60_80 = 194_400  # 80% din prag


@pytest.mark.parametrize("venit_net, status_ast", [
    (100_000, "OK"),               # ~41%
    (194_399, "OK"),               # chiar sub 80%
    (194_400, "APROAPE_PLAFON"),   # exact 80% (boundary)
    (220_000, "APROAPE_PLAFON"),   # ~91%
    (242_999, "APROAPE_PLAFON"),   # chiar sub 100%
    (243_000, "DEPASIT_PLAFON"),   # exact plafon (boundary)
    (300_000, "DEPASIT_PLAFON"),   # peste
])
def test_cass60_status_praguri(venit_net, status_ast):
    assert prag_cass60_status(venit_net, 2026)["status"] == status_ast


def test_cass60_mesaj_plafonare_la_atingere():
    r = prag_cass60_status(300_000, 2026)
    assert r["status"] == "DEPASIT_PLAFON"
    assert "plafon" in r["message"].lower()
    assert "nu mai crește" in r["message"].lower()
    assert "rămâne de plată" in r["message"].lower()             # NU "scapi"
    assert "24.300" in r["message"] or "24300" in r["message"]   # CASS max ~24.300
    # ton informativ, NU alarmant
    assert "ℹ️" in r["message"]
    assert "🔴" not in r["message"]


def test_cass60_smb_din_params():
    assert prag_cass60_status(0, 2025)["threshold_ron"] == 243_000
    assert prag_cass60_status(0, 2026)["threshold_ron"] == 243_000
