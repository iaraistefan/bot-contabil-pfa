"""
PAS 1-UI — wiring normă în wizard + dashboard. Endpoint norma-lookup (nomenclator),
allowlist norma_venit_anuala, status _an_fiscal (gardian selecție), setari regim+normă,
gardieni template (tip localitate + fallback manual + dezactivare normă <2026).
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.repositories import users as users_repo

_HTML = (Path(__file__).resolve().parent.parent
         / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")


def _web(monkeypatch, tmp_path):
    from app.http import app as webapp
    eng = create_engine(f"sqlite:///{(tmp_path / 'ui.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=1); s.add(u); s.commit(); uid = u.id; s.close()
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    return webapp.flask_app.test_client(), S, uid


# ── /api/v1/norma-lookup (nomenclator) ──
def test_norma_lookup_salaj_gasit(monkeypatch, tmp_path):
    client, _, _ = _web(monkeypatch, tmp_path)
    d = client.get("/api/v1/norma-lookup?judet=SJ&tip=municipiu&an=2026").get_json()
    assert d["found"] is True and d["norma"] == 54_300.0
    assert d["sursa"] and "Sălaj" in d["sursa"]


def test_norma_lookup_judet_necunoscut_fallback(monkeypatch, tmp_path):
    client, _, _ = _web(monkeypatch, tmp_path)
    d = client.get("/api/v1/norma-lookup?judet=BN&tip=municipiu&an=2026").get_json()
    assert d["found"] is False and d["norma"] is None     # BN → fallback manual, fără cifră inventată


# ── allowlist: norma_venit_anuala se salvează ──
def test_onboarding_save_norma(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path)
    r = client.post("/api/v1/onboarding/save",
                    json={"regim_impunere": "NORMA_VENIT", "norma_venit_anuala": 54300, "step": 3})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    s = S(); u = s.get(User, uid)
    assert u.regim_impunere == "NORMA_VENIT" and u.norma_venit_anuala == 54300.0
    s.close()


# ── status: _an_fiscal pentru gardianul de selecție ──
def test_status_an_fiscal(monkeypatch, tmp_path):
    client, _, _ = _web(monkeypatch, tmp_path)
    d = client.get("/api/v1/onboarding/status").get_json()
    assert isinstance(d["data"]["_an_fiscal"], int) and d["data"]["_an_fiscal"] >= 2026


# ── setari: regim + normă (afișaj dinamic) ──
def test_setari_expune_regim_si_norma(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path)
    s = S(); u = s.get(User, uid)
    users_repo.update_profile(s, u, firma_forma_juridica="PFA",
                              regim_impunere="NORMA_VENIT", norma_venit_anuala=54300)
    s.commit(); s.close()
    d = client.get("/api/v1/setari").get_json()
    assert d["regim_impunere"] == "NORMA_VENIT"
    assert d["norma_venit_anuala"] == 54300.0
    assert d["firma_forma_juridica"] == "PFA"


# ── gardieni template (wizard normă UI) ──
def test_template_wizard_norma_ui():
    for fn in ("function wizNormaTip()", "function wizPickTipLoc(", "function wizNormaInput(",
               "function wizRegimBtn()"):
        assert fn in _HTML, f"lipsește {fn}"
    assert 'authFetch("/api/v1/norma-lookup' in _HTML       # lookup nomenclator
    assert "Municipiu" in _HTML and "Comună" in _HTML       # tip localitate
    assert "Decizia AJFP" in _HTML                          # fallback manual + sursă
    assert "norma_venit_anuala:WIZ.data.norma_venit_anuala" in _HTML  # save normă
    # gardian selecție: ridesharing pe normă doar din 2026
    assert "_an_fiscal" in _HTML and "normaPermisa" in _HTML


def test_template_setari_regim_dinamic():
    assert 'id="set-forma"' in _HTML
    assert 'setTxt("set-forma"' in _HTML
    assert "PFA · sistem real" not in _HTML                 # textul static a dispărut
