"""
PAS 3 — casă de marcat (AMEF) LOGICĂ. Helper sursă unică necesita_amef (date OR declarat,
date au prioritate), flag profil incaseaza_numerar, endpoint /casa-marcat (income_cash din
tranzacții CASH), secțiune AMEF în ghid, card dashboard. Hardware EXCLUS.
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.casa_marcat import necesita_amef, AMEF_INFO
from app.models import User, Transaction
from app.repositories import users as users_repo

_HTML = (Path(__file__).resolve().parent.parent
         / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")


# ════════════ helper pur necesita_amef ════════════
def test_amef_cash_in_date():
    ok, motiv = necesita_amef(150.0, declarat=False)
    assert ok is True and "numerar" in motiv.lower()


def test_amef_declarat():
    ok, motiv = necesita_amef(0.0, declarat=True)
    assert ok is True and "declar" in motiv.lower()


def test_amef_niciunul_fals():
    ok, motiv = necesita_amef(0.0, declarat=False)
    assert ok is False and "nu" in motiv.lower()


def test_amef_override_date_peste_declaratie():
    # userul a declarat „nu" dar are cash în date → semnalăm oricum (date prioritare)
    ok, motiv = necesita_amef(80.0, declarat=False)
    assert ok is True and "date" in motiv.lower()


def test_amef_info_continut():
    assert AMEF_INFO["titlu"] and AMEF_INFO["ce_e"] and AMEF_INFO["cand"]
    assert "OUG 28/1999" in AMEF_INFO["de_ce"]            # sursă legală
    assert "Bolt" in AMEF_INFO["cum"] and "Uber" in AMEF_INFO["cum"]


# ════════════ endpoint + persistență ════════════
def _web(monkeypatch, tmp_path):
    from app.http import app as webapp
    eng = create_engine(f"sqlite:///{(tmp_path / 'cm.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=1); s.add(u); s.commit(); uid = u.id; s.close()
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    return webapp.flask_app.test_client(), S, uid


def _add_income(S, uid, brut, pm, year=2026):
    s = S()
    s.add(Transaction(user_id=uid, document_id=1, tx_type="INCOME", category="ride",
                      amount_brut=brut, payment_method=pm, period_year=year,
                      period_month=3, locked=False))
    s.commit(); s.close()


def test_casa_marcat_declarat(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path)
    s = S(); u = s.get(User, uid); users_repo.update_profile(s, u, incaseaza_numerar=True); s.commit(); s.close()
    d = client.get("/api/v1/casa-marcat?year=2026").get_json()
    assert d["necesita"] is True and d["declarat"] is True
    assert d["info"]["titlu"]


def test_casa_marcat_cash_din_date_override(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path)
    # NU declarat, dar are venit cash în date → semnal True (override)
    _add_income(S, uid, 200.0, "CASH")
    d = client.get("/api/v1/casa-marcat?year=2026").get_json()
    assert d["necesita"] is True and d["declarat"] is False
    assert d["income_cash"] == 200.0 and "date" in d["motiv"].lower()


def test_casa_marcat_doar_card_fals(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path)
    _add_income(S, uid, 500.0, "CARD")           # doar card → fără semnal
    d = client.get("/api/v1/casa-marcat?year=2026").get_json()
    assert d["necesita"] is False and d["income_cash"] == 0.0


def test_save_flag_si_status(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path)
    r = client.post("/api/v1/onboarding/save", json={"incaseaza_numerar": True, "step": 4})
    assert r.status_code == 200
    s = S(); u = s.get(User, uid); assert u.incaseaza_numerar is True; s.close()
    st = client.get("/api/v1/onboarding/status").get_json()
    assert st["data"]["incaseaza_numerar"] is True


def test_ghid_contine_amef(monkeypatch, tmp_path):
    client, _, _ = _web(monkeypatch, tmp_path)
    d = client.get("/api/v1/ghid").get_json()
    assert d.get("amef") and d["amef"]["titlu"]


# ════════════ gardieni template ════════════
def test_template_dashboard_amef():
    assert 'authFetch("/api/v1/casa-marcat' in _HTML       # card overview
    assert 'id="ov-amef"' in _HTML
    assert "casă de marcat (AMEF)" in _HTML.lower() or "casă de marcat" in _HTML
    assert "incaseaza_numerar" in _HTML                    # toggle onboarding
    assert "Încasez numerar" in _HTML
    assert "d.amef" in _HTML                               # secțiune ghid


# ════════════ regresie (fără cash/flag → niciun semnal) ════════════
def test_regresie_fara_semnal(monkeypatch, tmp_path):
    client, _, _ = _web(monkeypatch, tmp_path)
    d = client.get("/api/v1/casa-marcat?year=2026").get_json()
    assert d["necesita"] is False
