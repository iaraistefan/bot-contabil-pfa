"""
Test IZOLAT pentru _resolve_auto_deductibility (regim auto felia 1, pasul 3).

Garantează ZERO schimbare de comportament: helper-ul întoarce ACUM exact
procentul de bază (auto MIXT → 50, non-auto → static), identic cu
get_deductibility_pct. Structura e pregătită pt EXCLUSIV→100 (pasul 5), dar
încă NEactivată. Helper-ul NU e apelat din posting (fluxul rămâne byte-identic).
"""

from types import SimpleNamespace

from app.services import posting
from app.activities.ridesharing import RidesharingActivity


def _cat(code):
    return RidesharingActivity.get_expense_category(code)


def test_auto_mixt_ramane_50_fara_vehicul(monkeypatch):
    # Fără vehicul (get_default → None) → fallback pe procentul de bază (50).
    monkeypatch.setattr(posting.vehicule_repo, "get_default", lambda s, u: None)
    for code in ("fuel", "car_service", "car_insurance", "car_wash", "car_supplies"):
        cat = _cat(code)
        assert cat.is_auto_mixt is True
        assert posting._resolve_auto_deductibility(None, 1, cat) == 50


def test_auto_mixt_ramane_50_cu_vehicul_mixt(monkeypatch):
    # Vehicul MIXT → 50 (identic cu acum).
    veh = SimpleNamespace(regim_utilizare="MIXT")
    monkeypatch.setattr(posting.vehicule_repo, "get_default", lambda s, u: veh)
    assert posting._resolve_auto_deductibility(None, 1, _cat("fuel")) == 50


def test_auto_mixt_ramane_50_chiar_pe_exclusiv(monkeypatch):
    # ⚠️ EXCLUSIV NU e încă activat (pasul 5) → tot 50 (zero schimbare garantată).
    veh = SimpleNamespace(regim_utilizare="EXCLUSIV")
    monkeypatch.setattr(posting.vehicule_repo, "get_default", lambda s, u: veh)
    assert posting._resolve_auto_deductibility(None, 1, _cat("fuel")) == 50


def test_non_auto_identic_cu_get_deductibility_pct():
    # Non-auto: helper == get_deductibility_pct (comision 100, telecom 50 phone).
    for code in ("platform_commission", "registration", "telecom", "other_expense"):
        cat = _cat(code)
        assert cat.is_auto_mixt is False
        assert posting._resolve_auto_deductibility(None, 1, cat) == \
            RidesharingActivity.get_deductibility_pct(code)
