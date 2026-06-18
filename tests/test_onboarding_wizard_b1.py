"""
Onboarding wizard B1 — structură + pași de bază (nume, CUI+ANAF, normă/real, mașină).

Endpoint-uri noi: /api/v1/cui-lookup (wrap ANAF + ridesharing flag), /api/v1/onboarding/save
(allowlist + avansare pas), /api/v1/vehicul (vehicule_repo). Mock ANAF — fără API real.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.integrations import anaf_lookup
from app.services.onboarding import activity_from_caen
from app.models import User, Vehicul

_HTML = (Path(__file__).resolve().parent.parent
         / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")


def _web(monkeypatch, tmp_path):
    from app.http import app as webapp
    eng = create_engine(f"sqlite:///{(tmp_path / 'b1.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=1); s.add(u); s.commit(); uid = u.id; s.close()
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    return webapp.flask_app.test_client(), S, uid


# ── CAEN 4933 = ridesharing (adăugat la B1) ──
def test_caen_4933_ridesharing():
    assert activity_from_caen("4933") == "ridesharing"
    assert activity_from_caen("4931") == "ridesharing"
    assert activity_from_caen("6201") == "it_freelance"


# ── /api/v1/cui-lookup ──
def test_cui_lookup_ridesharing(monkeypatch, tmp_path):
    monkeypatch.setattr(anaf_lookup, "lookup_cui", lambda cui: {
        "found": True, "cui": cui, "denumire": "POPESCU ION PFA", "cod_caen": "4933",
        "forma_juridica_detectata": "PFA", "regim_tva": "NEPLATITOR", "is_platitor_tva": False,
        "is_inactiv": False, "stare_inregistrare": "INREGISTRAT", "judet": "BN", "localitate": "Bistrița",
        "adresa_completa": "...",
    })
    client, _, _ = _web(monkeypatch, tmp_path)
    d = client.get("/api/v1/cui-lookup?cui=53067338").get_json()
    assert d["found"] is True and d["cod_caen"] == "4933"
    assert d["is_ridesharing"] is True and d["activity_code"] == "ridesharing"
    assert "POPESCU" in d["denumire"]


def test_cui_lookup_non_ridesharing(monkeypatch, tmp_path):
    monkeypatch.setattr(anaf_lookup, "lookup_cui", lambda cui: {
        "found": True, "cui": cui, "denumire": "IT SRL", "cod_caen": "6201",
        "forma_juridica_detectata": "SRL_MICRO", "regim_tva": "PLATITOR_21", "is_platitor_tva": True,
        "is_inactiv": False, "stare_inregistrare": "OK",
    })
    client, _, _ = _web(monkeypatch, tmp_path)
    d = client.get("/api/v1/cui-lookup?cui=123").get_json()
    assert d["is_ridesharing"] is False and d["activity_code"] == "it_freelance"


def test_cui_lookup_negasit(monkeypatch, tmp_path):
    monkeypatch.setattr(anaf_lookup, "lookup_cui", lambda cui: {"found": False, "error": "Firmă negăsită"})
    client, _, _ = _web(monkeypatch, tmp_path)
    d = client.get("/api/v1/cui-lookup?cui=000").get_json()
    assert d["found"] is False


# ── /api/v1/onboarding/save (allowlist + avansare pas) ──
def test_onboarding_save_fields_si_pas(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path)
    r = client.post("/api/v1/onboarding/save", json={"name": "Ion", "regim_impunere": "NORMA_VENIT",
                                                     "evil_field": "x", "step": 3})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    s = S(); u = s.get(User, uid)
    assert u.name == "Ion" and u.regim_impunere == "NORMA_VENIT"
    assert u.onboarding_step == 3
    assert not hasattr(u, "evil_field")          # allowlist a ignorat câmpul necunoscut
    s.close()


# ── /api/v1/vehicul ──
def test_vehicul_create(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path)
    r = client.post("/api/v1/vehicul", json={"nr_inmatriculare": "bn12abc", "marca_model": "Dacia Logan",
                                             "norma_consum": 6.5, "tip_detinere": "proprietate"})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    s = S(); v = s.query(Vehicul).filter_by(user_id=uid).one()
    assert v.nr_inmatriculare == "BN12ABC" and v.norma_consum == 6.5 and v.tip_detinere == "proprietate"
    s.close()


def test_vehicul_nr_obligatoriu(monkeypatch, tmp_path):
    client, _, _ = _web(monkeypatch, tmp_path)
    r = client.post("/api/v1/vehicul", json={"marca_model": "X"})
    assert r.status_code == 400


# ── gardieni template wizard ──
def test_wizard_template_pasi():
    for fn in ("function wizCui()", "function wizRegim()", "function wizMasina()", "wizCuiCauta", "wizCuiManual"):
        assert fn in _HTML, f"lipsește {fn}"
    assert 'authFetch("/api/v1/cui-lookup' in _HTML
    assert 'authFetch("/api/v1/onboarding/save"' in _HTML
    assert 'authFetch("/api/v1/vehicul"' in _HTML
    assert "Am găsit firma" in _HTML            # cardul ANAF
    assert "INACTIVĂ la ANAF" in _HTML          # edge: firmă inactivă
    assert "Pasul ${x} din ${n}" in _HTML       # progres
