"""
Test IZOLAT pentru _resolve_auto_deductibility (regim auto, felia 5A ACTIVĂ).

Aprinderea 5A: vehicul EXCLUSIV business → 100% pentru categoriile auto pure
(fuel/car_service/car_wash/car_supplies). MIXT → 50 (default protejat, opt-in),
fără vehicul → 50 (fallback), non-auto → procent static (get_deductibility_pct).
⚠️ RCA/CASCO (car_insurance, depinde_tip_detinere) e SĂRIT de 5A — rămâne pe
base_pct (50) pe EXCLUSIV; se aprinde la 5B (comodat 0%).
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


def test_auto_exclusiv_devine_100(monkeypatch):
    # Felia 5A ACTIVĂ: vehicul EXCLUSIV business → deductibilitate integrală 100%
    # pentru categoriile auto pure (justificat prin foaie de parcurs).
    veh = SimpleNamespace(regim_utilizare="EXCLUSIV")
    monkeypatch.setattr(posting.vehicule_repo, "get_default", lambda s, u: veh)
    assert posting._resolve_auto_deductibility(None, 1, _cat("fuel")) == 100


def test_fuel_exclusiv_100_mixt_50_fara_vehicul_50(monkeypatch):
    # Cele 3 stări pentru fuel, într-un singur loc:
    #  - EXCLUSIV → 100 (aprins la 5A)
    #  - MIXT → 50 (default protejat, neatins)
    #  - fără vehicul → 50 (fallback)
    fuel = _cat("fuel")

    monkeypatch.setattr(posting.vehicule_repo, "get_default",
                        lambda s, u: SimpleNamespace(regim_utilizare="EXCLUSIV"))
    assert posting._resolve_auto_deductibility(None, 1, fuel) == 100

    monkeypatch.setattr(posting.vehicule_repo, "get_default",
                        lambda s, u: SimpleNamespace(regim_utilizare="MIXT"))
    assert posting._resolve_auto_deductibility(None, 1, fuel) == 50

    monkeypatch.setattr(posting.vehicule_repo, "get_default", lambda s, u: None)
    assert posting._resolve_auto_deductibility(None, 1, fuel) == 50


def test_celelalte_categorii_auto_exclusiv_100(monkeypatch):
    # car_service/car_wash/car_supplies pe EXCLUSIV → 100 (la fel ca fuel).
    monkeypatch.setattr(posting.vehicule_repo, "get_default",
                        lambda s, u: SimpleNamespace(regim_utilizare="EXCLUSIV"))
    for code in ("car_service", "car_wash", "car_supplies"):
        assert posting._resolve_auto_deductibility(None, 1, _cat(code)) == 100


def test_insurance_exclusiv_ramane_base_nu_100(monkeypatch):
    # ⚠️ 5A NU atinge RCA/CASCO: depinde_tip_detinere=True → sărit din aprindere.
    # Pe EXCLUSIV rămâne pe base_pct (50), NU 100 — se face la 5B (comodat 0%).
    ins = _cat("car_insurance")
    assert ins.depinde_tip_detinere is True
    monkeypatch.setattr(posting.vehicule_repo, "get_default",
                        lambda s, u: SimpleNamespace(regim_utilizare="EXCLUSIV"))
    assert posting._resolve_auto_deductibility(None, 1, ins) == 50


def test_non_auto_identic_cu_get_deductibility_pct():
    # Non-auto: helper == get_deductibility_pct (comision 100, telecom 50 phone).
    for code in ("platform_commission", "registration", "telecom", "other_expense"):
        cat = _cat(code)
        assert cat.is_auto_mixt is False
        assert posting._resolve_auto_deductibility(None, 1, cat) == \
            RidesharingActivity.get_deductibility_pct(code)
