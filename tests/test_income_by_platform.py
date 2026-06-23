"""
B1 — defalcare venit pe platformă (Bolt/Uber/Altele) în compute_period.

Agregare în aceeași buclă + filtru ca income_by_cat → INVARIANT prin construcție:
Σ income_by_platform == income_total. Brand din counterparty via _d100_brand_key
(sursă unică, ca vat_out_by_brand). None → „Altele". Câmp aditiv (regresie 0).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import tax_engine
from app.models import User, Transaction

Y, M = 2026, 5


def _db(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S()
    u = User(telegram_id=42, activity_code="ridesharing")
    s.add(u); s.commit(); uid = u.id; s.close()
    return S, uid


def _income(uid, counterparty, amount):
    return Transaction(
        user_id=uid, document_id=1, tx_type="INCOME", category="ride_revenue",
        amount_brut=amount, amount_vat=0.0, amount_net=amount, currency="RON",
        payment_method="CARD", counterparty=counterparty,
        period_year=Y, period_month=M, locked=False,
    )


def _platforme(S, uid):
    s = S()
    t = tax_engine.compute_period(s, user_id=uid, year=Y, month=M)
    s.close()
    return t


# ════════════════════════════════════════════════════════════
#   Invariant + atribuire
# ════════════════════════════════════════════════════════════

def test_invariant_suma_egal_income_total(tmp_path):
    S, uid = _db(tmp_path)
    s = S()
    s.add_all([_income(uid, "Bolt", 1000.0), _income(uid, "Uber", 600.0),
               _income(uid, "APP", 400.0)])
    s.commit(); s.close()
    t = _platforme(S, uid)
    plat = t["income_by_platform"]
    assert round(sum(p["amount_brut"] for p in plat), 2) == t["income_total"]  # INVARIANT
    assert t["income_total"] == 2000.0


def test_atribuire_bolt_uber(tmp_path):
    S, uid = _db(tmp_path)
    s = S()
    s.add_all([_income(uid, "Bolt", 1000.0), _income(uid, "Uber", 600.0)])
    s.commit(); s.close()
    by = {p["brand"]: p for p in _platforme(S, uid)["income_by_platform"]}
    assert by["bolt"]["label"] == "Bolt" and by["bolt"]["amount_brut"] == 1000.0
    assert by["uber"]["label"] == "Uber" and by["uber"]["amount_brut"] == 600.0


def test_neatribuit_altele(tmp_path):
    # counterparty nerecunoscut (cash/bancă/APP) → brand None → eticheta „Altele"
    S, uid = _db(tmp_path)
    s = S()
    s.add_all([_income(uid, "Bolt", 800.0), _income(uid, "Banca Transilvania", 300.0)])
    s.commit(); s.close()
    by = {p["brand"]: p for p in _platforme(S, uid)["income_by_platform"]}
    assert by[None]["label"] == "Altele" and by[None]["amount_brut"] == 300.0


def test_sortare_desc_si_fara_zero(tmp_path):
    S, uid = _db(tmp_path)
    s = S()
    s.add_all([_income(uid, "Uber", 600.0), _income(uid, "Bolt", 1500.0)])
    s.commit(); s.close()
    plat = _platforme(S, uid)["income_by_platform"]
    assert [p["brand"] for p in plat] == ["bolt", "uber"]          # sortat desc după sumă
    assert all(p["amount_brut"] != 0 for p in plat)               # fără felii zero


def test_fara_venituri_lista_goala(tmp_path):
    S, uid = _db(tmp_path)
    plat = _platforme(S, uid)["income_by_platform"]
    assert plat == []                                              # nimic → listă goală


# ════════════════════════════════════════════════════════════
#   Endpoint /api/v1/period întoarce income_by_platform
# ════════════════════════════════════════════════════════════

def test_endpoint_period_include_platforme(tmp_path, monkeypatch):
    from app.http import app as webapp
    S, uid = _db(tmp_path)
    s = S()
    s.add_all([_income(uid, "Bolt", 1000.0), _income(uid, "Uber", 600.0)])
    s.commit(); s.close()
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    d = webapp.flask_app.test_client().get(f"/api/v1/period/{Y}/{M}").get_json()
    assert "income_by_platform" in d
    brands = {p["brand"] for p in d["income_by_platform"]}
    assert brands == {"bolt", "uber"}
