"""
C1 — deltă month-over-month (compute_mom): luna vs luna PRECEDENTĂ pe metricile LUNARE.

Opțiunea (b) confirmată: comparăm două luni COMPLETE (apelantul pasează ultima lună
completă). Math testat în backend; frontend doar afișează. prev≤0 → comparabil:false
(fără +∞%). Expus în /api/v1/period DOAR la ?mom=1 (aditiv, regresie 0).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import tax_engine
from app.models import User, Transaction

Y = 2026
METRICI = ("income_total", "expense_deductible_total", "vat_out_total")


def _db(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=7, activity_code="ridesharing")
    s.add(u); s.commit(); uid = u.id; s.close()
    return S, uid


def _income(uid, year, month, amount):
    return Transaction(
        user_id=uid, document_id=1, tx_type="INCOME", category="ride_revenue",
        amount_brut=amount, amount_vat=0.0, amount_net=amount, currency="RON",
        payment_method="CARD", counterparty="Bolt",
        period_year=year, period_month=month, locked=False,
    )


def _mom(S, uid, year, month):
    s = S()
    r = tax_engine.compute_mom(s, user_id=uid, year=year, month=month)
    s.close()
    return r


# ════════════════════════════════════════════════════════════
#   Deltă + semn
# ════════════════════════════════════════════════════════════

def test_delta_up(tmp_path):
    # aprilie 1000 → mai 1200 = +20% up
    S, uid = _db(tmp_path)
    s = S()
    s.add_all([_income(uid, Y, 4, 1000.0), _income(uid, Y, 5, 1200.0)])
    s.commit(); s.close()
    m = _mom(S, uid, Y, 5)["income_total"]
    assert m["comparabil"] is True
    assert m["curr"] == 1200.0 and m["prev"] == 1000.0
    assert m["delta_pct"] == 20.0 and m["dir"] == "up"


def test_delta_down(tmp_path):
    S, uid = _db(tmp_path)
    s = S()
    s.add_all([_income(uid, Y, 4, 1000.0), _income(uid, Y, 5, 750.0)])
    s.commit(); s.close()
    m = _mom(S, uid, Y, 5)["income_total"]
    assert m["delta_pct"] == -25.0 and m["dir"] == "down"


def test_delta_flat(tmp_path):
    S, uid = _db(tmp_path)
    s = S()
    s.add_all([_income(uid, Y, 4, 800.0), _income(uid, Y, 5, 800.0)])
    s.commit(); s.close()
    m = _mom(S, uid, Y, 5)["income_total"]
    assert m["delta_pct"] == 0.0 and m["dir"] == "flat" and m["comparabil"] is True


# ════════════════════════════════════════════════════════════
#   Edge: prev≤0 / prima lună → comparabil:false (fără +∞%)
# ════════════════════════════════════════════════════════════

def test_prev_zero_necomparabil(tmp_path):
    # mai are venit, aprilie = 0 → necomparabil (nu inventăm %)
    S, uid = _db(tmp_path)
    s = S(); s.add(_income(uid, Y, 5, 1200.0)); s.commit(); s.close()
    m = _mom(S, uid, Y, 5)["income_total"]
    assert m["comparabil"] is False
    assert m["delta_pct"] is None and m["dir"] is None
    assert m["curr"] == 1200.0 and m["prev"] == 0.0


def test_prima_luna_fara_date_necomparabil(tmp_path):
    # nicio tranzacție → ambele 0 → necomparabil pe toate metricile
    S, uid = _db(tmp_path)
    r = _mom(S, uid, Y, 5)
    for k in METRICI:
        assert r[k]["comparabil"] is False and r[k]["delta_pct"] is None


# ════════════════════════════════════════════════════════════
#   Ianuarie → comparat cu decembrie an precedent
# ════════════════════════════════════════════════════════════

def test_ianuarie_vs_decembrie_an_precedent(tmp_path):
    S, uid = _db(tmp_path)
    s = S()
    s.add_all([_income(uid, Y - 1, 12, 500.0), _income(uid, Y, 1, 600.0)])
    s.commit(); s.close()
    m = _mom(S, uid, Y, 1)["income_total"]
    assert m["prev"] == 500.0 and m["curr"] == 600.0     # ian comparat cu dec an precedent
    assert m["delta_pct"] == 20.0 and m["dir"] == "up"


# ════════════════════════════════════════════════════════════
#   Endpoint /api/v1/period — opt-in ?mom=1 (aditiv, regresie 0)
# ════════════════════════════════════════════════════════════

def _web(monkeypatch, tmp_path):
    from app.http import app as webapp
    S, uid = _db(tmp_path)
    s = S()
    s.add_all([_income(uid, Y, 4, 1000.0), _income(uid, Y, 5, 1200.0)])
    s.commit(); s.close()
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    return webapp.flask_app.test_client()


def test_period_fara_mom_nu_include_blocul(monkeypatch, tmp_path):
    client = _web(monkeypatch, tmp_path)
    d = client.get(f"/api/v1/period/{Y}/5").get_json()
    assert "mom" not in d                                  # regresie 0 pe apelurile existente


def test_period_cu_mom_include_blocul(monkeypatch, tmp_path):
    client = _web(monkeypatch, tmp_path)
    d = client.get(f"/api/v1/period/{Y}/5?mom=1").get_json()
    assert "mom" in d
    assert d["mom"]["income_total"]["delta_pct"] == 20.0
    assert d["mom"]["income_total"]["dir"] == "up"
