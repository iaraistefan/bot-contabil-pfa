"""
Onboarding wizard B2 — pași ridesharing (platforme → regim nerezident → API Bolt).
Condiționați STRICT pe is_ridesharing (din pasul CUI). Pasul API Bolt apare doar dacă
Bolt e selectat (Uber n-are sync). Zero endpoint nou — regimurile folosesc /onboarding/save
(allowlist existent), conectarea folosește /bolt/connect (#2-B). Mock DB — fără API real.
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User

_HTML = (Path(__file__).resolve().parent.parent
         / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")


def _web(monkeypatch, tmp_path):
    from app.http import app as webapp
    eng = create_engine(f"sqlite:///{(tmp_path / 'b2.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=1); s.add(u); s.commit(); uid = u.id; s.close()
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    return webapp.flask_app.test_client(), S, uid


# ── pașii ridesharing condiționați pe is_ridesharing ──
def test_wizsteps_dinamic_ridesharing():
    # lista de pași se extinde DOAR dacă is_ridesharing; apibolt apare doar cu Bolt
    assert 'if(WIZ.data.is_ridesharing){' in _HTML
    # masina e acum în blocul ridesharing (I2 — condiționată de is_ridesharing)
    assert 's.push("masina","platforme","nerezident");' in _HTML
    assert 'if(wizHasBolt()) s.push("apibolt");' in _HTML       # Uber n-are pas API


def test_wizsteps_gating_uber_fara_apibolt():
    # Uber-only → fără pas apibolt (helperele decid)
    assert 'function wizHasBolt(){ return WIZ.data._platforme==="BOLT" || WIZ.data._platforme==="AMBELE"; }' in _HTML
    assert 'function wizHasUber(){ return WIZ.data._platforme==="UBER" || WIZ.data._platforme==="AMBELE"; }' in _HTML


# ── pas PLATFORME ──
def test_pas_platforme_carduri():
    for fn in ("function wizPlatforme()", "wizPickPlatforme"):
        assert fn in _HTML, f"lipsește {fn}"
    assert "Doar Bolt" in _HTML and "Doar Uber" in _HTML and "Ambele" in _HTML
    assert "Pe ce platforme lucrezi?" in _HTML


# ── pas REGIM NEREZIDENT (cote exacte, per platformă) ──
def test_pas_nerezident_cote():
    assert "function wizNerezident()" in _HTML
    # Bolt: 2% / 16% — codurile exacte din onboarding.py
    assert "BOLT_CU_CRF" in _HTML and "BOLT_FARA_CRF" in _HTML
    assert "Am certificatul Bolt — 2%" in _HTML
    # Uber: 0% / 16% — fără 2% (acela e doar Bolt)
    assert "UBER_CU_CRF" in _HTML and "UBER_FARA_CRF" in _HTML
    assert "Am certificatul Uber — 0%" in _HTML
    assert "Uber nu are cota de 2%" in _HTML
    # notă spre certificat (#3)
    assert "secțiunea <b>Certificat</b>" in _HTML


def test_pas_nerezident_salveaza_regimuri():
    # regimurile se salvează prin /onboarding/save (allowlist), nu endpoint nou
    assert "f.regim_nerezident_bolt=WIZ.data.regim_nerezident_bolt" in _HTML
    assert "f.regim_nerezident_uber=WIZ.data.regim_nerezident_uber" in _HTML


# ── pas API BOLT (opțional, refolosește #2-B) ──
def test_pas_apibolt_optional():
    assert "function wizApiBolt()" in _HTML
    assert 'authFetch("/api/v1/bolt/connect"' in _HTML          # refolosește endpoint #2-B
    assert "wizApiBoltSkip" in _HTML                            # se poate sări
    assert "Sări peste" in _HTML
    assert "venit bolt [lună]" in _HTML                         # nudge manual (#2-D)
    assert "fleets.bolt.eu" in _HTML                            # ghid chei


# ── behavioral: /onboarding/save persistă AMBELE regimuri (Ambele) ──
def test_save_ambele_regimuri(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path)
    r = client.post("/api/v1/onboarding/save", json={
        "regim_nerezident_bolt": "BOLT_CU_CRF",
        "regim_nerezident_uber": "UBER_CU_CRF", "step": 6})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    s = S(); u = s.get(User, uid)
    assert u.regim_nerezident_bolt == "BOLT_CU_CRF"
    assert u.regim_nerezident_uber == "UBER_CU_CRF"
    s.close()


# ── validare: fiecare platformă aleasă cere regim înainte de avansare ──
def test_validare_regim_per_platforma():
    assert 'if(wizHasBolt() && !WIZ.data.regim_nerezident_bolt){ wizMsg("Alege regimul pentru Bolt.",true); return; }' in _HTML
    assert 'if(wizHasUber() && !WIZ.data.regim_nerezident_uber){ wizMsg("Alege regimul pentru Uber.",true); return; }' in _HTML
