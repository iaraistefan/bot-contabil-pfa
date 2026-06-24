"""
Plafon SUPERIOR CASS versionat pe an fiscal (Legea 141/2025).

- Venituri 2025 (D212 depusă în 2026): plafon = 60 SMB = 243.000 → CASS max 24.300.
- Venituri 2026+ (D212 depusă în 2027): plafon = 72 SMB = 291.600 → CASS max 29.160.
- SMB de plafoane = 4.050 lei (cel de la 1 ian) pe AMBII ani — majorarea la 4.325
  de la 1 iul NU afectează plafoanele.

Diferențiatorul: la 280.000 venit net, 2025 plafonează (24.300), 2026 încă NU (28.000).
Regresie 0 pe 2025 — plafonul vechi de 60 SMB trebuie să rămână valabil pentru 2025.
"""

import pytest

from app.domain.contributii import calcul_cass, prag_cass60_status


# (venit_net, an, cass_ast, baza_ast)
@pytest.mark.parametrize("venit, an, cass_ast, baza_ast", [
    # ── diferențiatorul: 280.000 ──
    (280_000, 2025, 24_300.0, 243_000),   # 2025: plafonat la 60 SMB
    (280_000, 2026, 28_000.0, 280_000),   # 2026: SUB plafonul de 72 SMB → 10% pe real
    # ── plafonare efectivă 2026 ──
    (300_000, 2026, 29_160.0, 291_600),   # 2026: plafonat la 72 SMB
    (300_000, 2025, 24_300.0, 243_000),   # REGRESIE 0: 2025 rămâne 60 SMB
    # ── boundary exact ──
    (243_000, 2025, 24_300.0, 243_000),   # exact 60 SMB (2025) — la plafon
    (291_600, 2026, 29_160.0, 291_600),   # exact 72 SMB (2026) — la plafon
])
def test_cass_plafon_versionat_pe_an(venit, an, cass_ast, baza_ast):
    r = calcul_cass(venit, an)
    assert r["valoare"] == cass_ast
    assert r["baza"] == baza_ast


def test_threshold_ron_urca_de_la_2025_la_2026():
    # Plafonul (threshold_ron al prag_cass60_status) urcă 243.000 → 291.600.
    assert prag_cass60_status(0, 2025)["threshold_ron"] == 243_000
    assert prag_cass60_status(0, 2026)["threshold_ron"] == 291_600
