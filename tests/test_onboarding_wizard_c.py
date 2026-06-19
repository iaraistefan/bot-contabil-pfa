"""
Onboarding wizard C — finalizare + complete + rehidratare.

- /api/v1/onboarding/status îmbogățit cu `data` (rehidratare: profil + vehicul + derivate
  is_ridesharing/_platforme/_boltConnected).
- /api/v1/onboarding/complete: validează minimele (nume, firma, regim, mașină) → marchează
  onboarding_completed. Bolt opțional. Lipsă → 400 + missing.
Mock DB — fără API real.
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.repositories import users as users_repo
from app.repositories import vehicule as vehicule_repo

_HTML = (Path(__file__).resolve().parent.parent
         / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")


def _web(monkeypatch, tmp_path):
    from app.http import app as webapp
    eng = create_engine(f"sqlite:///{(tmp_path / 'c.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=1); s.add(u); s.commit(); uid = u.id; s.close()
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    return webapp.flask_app.test_client(), S, uid


def _seteaza(S, uid, **fields):
    s = S(); u = s.get(User, uid)
    users_repo.update_profile(s, u, **fields)
    s.commit(); s.close()


def _adauga_masina(S, uid):
    s = S(); vehicule_repo.create(s, user_id=uid, nr_inmatriculare="BN01CAI"); s.commit(); s.close()


# ── /status îmbogățit (rehidratare) ──
def test_status_data_rehidratare(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path)
    _seteaza(S, uid, name="Ion", firma_cui="53067338", firma_nume="POPESCU ION PFA",
             regim_impunere="NORMA_VENIT", activity_code="ridesharing",
             regim_nerezident_bolt="BOLT_CU_CRF")
    _adauga_masina(S, uid)
    d = client.get("/api/v1/onboarding/status").get_json()
    assert d["data"]["name"] == "Ion"
    assert d["data"]["is_ridesharing"] is True          # derivat din activity_code
    assert d["data"]["_platforme"] == "BOLT"            # doar bolt setat → BOLT
    assert d["data"]["regim_nerezident_bolt"] == "BOLT_CU_CRF"
    assert d["data"]["veh_nr"] == "BN01CAI"             # vehicul rehidratat
    assert d["data"]["_boltConnected"] is False


def test_status_platforme_ambele(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path)
    _seteaza(S, uid, activity_code="ridesharing",
             regim_nerezident_bolt="BOLT_FARA_CRF", regim_nerezident_uber="UBER_CU_CRF")
    d = client.get("/api/v1/onboarding/status").get_json()
    assert d["data"]["_platforme"] == "AMBELE"


def test_status_non_ridesharing(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path)
    _seteaza(S, uid, activity_code="it_freelance")
    d = client.get("/api/v1/onboarding/status").get_json()
    assert d["data"]["is_ridesharing"] is False
    assert d["data"]["_platforme"] is None


# ── /complete: succes + onboarding_completed ──
def test_complete_succes(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path)
    _seteaza(S, uid, name="Ion", firma_cui="53067338", regim_impunere="NORMA_VENIT")
    _adauga_masina(S, uid)
    r = client.post("/api/v1/onboarding/complete", json={})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    s = S(); u = s.get(User, uid)
    assert u.onboarding_completed is True
    s.close()


def test_complete_manual_fara_cui(monkeypatch, tmp_path):
    # calea manuală: doar firma_nume (fără CUI) trebuie să fie acceptată
    client, S, uid = _web(monkeypatch, tmp_path)
    _seteaza(S, uid, name="Ion", firma_nume="POPESCU ION PFA", regim_impunere="SISTEM_REAL")
    _adauga_masina(S, uid)
    r = client.post("/api/v1/onboarding/complete", json={})
    assert r.status_code == 200 and r.get_json()["ok"] is True


def test_complete_bolt_optional(monkeypatch, tmp_path):
    # Bolt sărit (fără chei) → complete tot trece (Bolt e opțional)
    client, S, uid = _web(monkeypatch, tmp_path)
    _seteaza(S, uid, name="Ion", firma_cui="53067338", regim_impunere="NORMA_VENIT",
             activity_code="ridesharing", regim_nerezident_bolt="BOLT_CU_CRF")
    _adauga_masina(S, uid)
    r = client.post("/api/v1/onboarding/complete", json={})
    assert r.status_code == 200 and r.get_json()["ok"] is True


# ── /complete: blocat când lipsește obligatoriu ──
def test_complete_blocat_fara_masina(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path)
    _seteaza(S, uid, name="Ion", firma_cui="53067338", regim_impunere="NORMA_VENIT")
    # FĂRĂ mașină
    r = client.post("/api/v1/onboarding/complete", json={})
    assert r.status_code == 400
    d = r.get_json()
    assert d["ok"] is False and "masina" in d["missing"]
    s = S(); u = s.get(User, uid)
    assert not u.onboarding_completed                   # NU s-a finalizat
    s.close()


def test_complete_blocat_lista_lipsa(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path)
    # nimic setat → toate lipsesc
    r = client.post("/api/v1/onboarding/complete", json={})
    assert r.status_code == 400
    miss = set(r.get_json()["missing"])
    assert {"name", "firma", "regim_impunere", "masina"} <= miss


# ── gardieni template (finalizare + rehidratare + ieșire) ──
def test_template_finalizare_si_iesire():
    assert "function wizComplete()" in _HTML
    assert 'authFetch("/api/v1/onboarding/complete"' in _HTML
    assert "Gata! Contul tău e configurat" in _HTML     # ecran finalizare branded
    assert "Intră în Contai" in _HTML                   # buton final
    assert "function exitWizardToDashboard()" in _HTML  # tranziție → dashboard normal
    assert 'classList.remove("wizard-mode")' in _HTML
    assert "function wizGoto(" in _HTML                 # edge: mergi la pasul lipsă


def test_template_rehidratare():
    # enterWizard pre-populează WIZ.data din status.data
    assert "const d=(status&&status.data)||{};" in _HTML
    assert "if(WIZ.data.firma_cui||WIZ.data.firma_nume) WIZ.data._cuiConfirmat=true;" in _HTML
