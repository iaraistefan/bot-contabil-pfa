"""
Teste pentru prag_cas_status (Faza 3 — alerte „aproape de plafon" CAS).

Prag CAS = 12 SMB = 12 × 4050 = 48.600. Status OK (<80%) / APROAPE (≥80%) /
DEPASIT (≥100%). remaining_ron = cât a mai rămas până la prag.
"""

import pytest

from app.domain.contributii import prag_cas_status

PRAG = 48_600        # 12 × 4050
P80 = 38_880         # 80% din prag


@pytest.mark.parametrize("venit_net, status_ast", [
    (10_000, "OK"),               # ~20%
    (38_879, "OK"),               # chiar sub 80%
    (38_880, "APROAPE_PLAFON"),   # exact 80% (boundary)
    (45_000, "APROAPE_PLAFON"),   # ~93%
    (48_599, "APROAPE_PLAFON"),   # chiar sub 100%
    (48_600, "DEPASIT_PLAFON"),   # exact prag (boundary)
    (60_000, "DEPASIT_PLAFON"),   # peste
])
def test_status_praguri(venit_net, status_ast):
    assert prag_cas_status(venit_net, 2026)["status"] == status_ast


def test_campuri_si_remaining():
    r = prag_cas_status(45_000, 2026)
    assert r["threshold_ron"] == 48_600
    assert round(r["utilized_pct"]) == 93              # 45000/48600
    assert r["remaining_ron"] == 3_600                 # 48600 - 45000
    assert "Mai ai ~3600 lei" in r["message"]
    assert "12.150" in r["message"] or "12150" in r["message"]  # CAS obligatoriu ~12150


def test_remaining_zero_la_depasire():
    r = prag_cas_status(60_000, 2026)
    assert r["remaining_ron"] == 0.0
    assert r["status"] == "DEPASIT_PLAFON"
    assert "obligatoriu" in r["message"].lower()


def test_foloseste_smb_din_params():
    # pragul derivă din SMB-ul anului (params), nu hardcodat
    assert prag_cas_status(0, 2025)["threshold_ron"] == 48_600   # 12 × 4050
    assert prag_cas_status(0, 2026)["threshold_ron"] == 48_600
