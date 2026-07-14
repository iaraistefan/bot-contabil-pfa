"""
Test IZOLAT pentru _resolve_auto_deductibility (regim auto, felia 5A ACTIVĂ).

Aprinderea 5A: vehicul EXCLUSIV business → 100% pentru categoriile auto pure
(fuel/car_service/car_wash/car_supplies). MIXT → 50 (default protejat, opt-in),
fără vehicul → 50 (fallback), non-auto → procent static (get_deductibility_pct).
Felia 5B: RCA/CASCO (car_insurance, depinde_tip_detinere) pe tip_detinere —
COMODAT → 0 (nedeductibil), proprietate/leasing/închiriere → regula de regim
(EXCLUSIV 100 / MIXT 50), tip nedeclarat (None) → conservator 50. Case-insensitive
(lowercase "comodat" din wizard web → tot 0). Comodat NU atinge fuel etc. (axe
independente).
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


# ──────────────────────────────────────────────────────────────
# 5B — car_insurance (RCA/CASCO) pe tip_detinere
# ──────────────────────────────────────────────────────────────
def _veh(tip=None, regim="MIXT"):
    return SimpleNamespace(tip_detinere=tip, regim_utilizare=regim)


def test_insurance_comodat_uppercase_zero(monkeypatch):
    # Comodat (mașină personală) → RCA/CASCO nedeductibile (0%), orice regim.
    ins = _cat("car_insurance")
    assert ins.depinde_tip_detinere is True
    for regim in ("MIXT", "EXCLUSIV"):
        monkeypatch.setattr(posting.vehicule_repo, "get_default",
                            lambda s, u, r=regim: _veh("COMODAT", r))
        assert posting._resolve_auto_deductibility(None, 1, ins) == 0


def test_insurance_comodat_lowercase_zero(monkeypatch):
    # ⚠️ case-insensitive: wizard-ul web salvează lowercase "comodat" → tot 0.
    ins = _cat("car_insurance")
    monkeypatch.setattr(posting.vehicule_repo, "get_default",
                        lambda s, u: _veh("comodat", "EXCLUSIV"))
    assert posting._resolve_auto_deductibility(None, 1, ins) == 0


def test_insurance_proprietate_mixt_50_exclusiv_100(monkeypatch):
    # Proprietate → deductibilă: MIXT 50 (base, default protejat) / EXCLUSIV 100.
    ins = _cat("car_insurance")
    monkeypatch.setattr(posting.vehicule_repo, "get_default",
                        lambda s, u: _veh("PROPRIETATE", "MIXT"))
    assert posting._resolve_auto_deductibility(None, 1, ins) == 50
    monkeypatch.setattr(posting.vehicule_repo, "get_default",
                        lambda s, u: _veh("PROPRIETATE", "EXCLUSIV"))
    assert posting._resolve_auto_deductibility(None, 1, ins) == 100


def test_insurance_leasing_exclusiv_100(monkeypatch):
    # Leasing = non-comodat declarat → regula de regim (EXCLUSIV 100).
    ins = _cat("car_insurance")
    monkeypatch.setattr(posting.vehicule_repo, "get_default",
                        lambda s, u: _veh("LEASING", "EXCLUSIV"))
    assert posting._resolve_auto_deductibility(None, 1, ins) == 100


def test_insurance_tip_none_conservator_50(monkeypatch):
    # Decizia luată: tip nedeclarat (None) → conservator base_pct (50), NU 100,
    # chiar pe EXCLUSIV (nu urcăm asigurarea fără deținere declarată).
    ins = _cat("car_insurance")
    monkeypatch.setattr(posting.vehicule_repo, "get_default",
                        lambda s, u: _veh(None, "EXCLUSIV"))
    assert posting._resolve_auto_deductibility(None, 1, ins) == 50


def test_fuel_comodat_exclusiv_ramane_100(monkeypatch):
    # ⚠️ REGRESIE 5A: comodat afectează DOAR insurance (depinde_tip_detinere).
    # fuel n-are flag-ul → comodat irelevant → EXCLUSIV tot 100 (foaia justifică).
    fuel = _cat("fuel")
    assert fuel.depinde_tip_detinere is False
    monkeypatch.setattr(posting.vehicule_repo, "get_default",
                        lambda s, u: _veh("COMODAT", "EXCLUSIV"))
    assert posting._resolve_auto_deductibility(None, 1, fuel) == 100


def test_non_auto_identic_cu_get_deductibility_pct():
    # Non-auto: helper == get_deductibility_pct (comision 100, telecom 50 phone).
    for code in ("platform_commission", "registration", "telecom", "other_expense"):
        cat = _cat(code)
        assert cat.is_auto_mixt is False
        assert posting._resolve_auto_deductibility(None, 1, cat) == \
            RidesharingActivity.get_deductibility_pct(code)
