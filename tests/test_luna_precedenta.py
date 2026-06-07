"""
Teste pentru helper-ul luna_precedenta (Faza 3 PAS 2).

Loc clasic de bug: wrap ianuarie -> decembrie anul anterior.
"""

from datetime import date, datetime

import pytest

from app.services.scheduler import luna_precedenta


@pytest.mark.parametrize("d, asteptat", [
    (date(2026, 2, 2), (2026, 1)),    # februarie -> ianuarie
    (date(2026, 1, 2), (2025, 12)),   # ← cazul critic: ianuarie -> decembrie an-1
    (date(2026, 7, 2), (2026, 6)),    # iulie -> iunie
    (date(2026, 12, 2), (2026, 11)),  # decembrie -> noiembrie
])
def test_luna_precedenta(d, asteptat):
    assert luna_precedenta(d) == asteptat


def test_accepta_si_datetime():
    # jobul primește un datetime (now în RO) — trebuie să meargă la fel
    assert luna_precedenta(datetime(2026, 1, 2, 9, 0)) == (2025, 12)
    assert luna_precedenta(datetime(2026, 3, 15, 23, 59)) == (2026, 2)
