"""
Onboarding wizard — E2E cap-coadă (verificare finală branch feat/onboarding-wizard).

Parcurge endpoint-urile REALE în secvență, ca un user nou care trece prin wizard:
status(neonboarded) → save nume → cui-lookup(ANAF) → save firma → save regim → vehicul
→ [ridesharing] save platforme → save regim nerezident → complete → status(completed).
Singurul mock = ANAF lookup_cui (fără rețea) + auth. DB SQLite temporar real.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.integrations import anaf_lookup
from app.models import User


def _web(monkeypatch, tmp_path):
    from app.http import app as webapp
    eng = create_engine(f"sqlite:///{(tmp_path / 'e2e.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=1); s.add(u); s.commit(); uid = u.id; s.close()
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    return webapp.flask_app.test_client(), S, uid


def test_e2e_ridesharing_cap_coada(monkeypatch, tmp_path):
    # ANAF întoarce un PFA ridesharing (CAEN 4933) — fără rețea
    monkeypatch.setattr(anaf_lookup, "lookup_cui", lambda cui: {
        "found": True, "cui": cui, "denumire": "POPESCU ION PFA", "cod_caen": "4933",
        "forma_juridica_detectata": "PFA", "regim_tva": "NEPLATITOR", "is_platitor_tva": False,
        "is_inactiv": False, "stare_inregistrare": "INREGISTRAT", "judet": "BN",
        "localitate": "Bistrița", "adresa_completa": "...",
    })
    client, S, uid = _web(monkeypatch, tmp_path)

    # 1. user nou → neonboarded
    st = client.get("/api/v1/onboarding/status").get_json()
    assert st["onboarding_completed"] is False

    # 2. pas NUME
    assert client.post("/api/v1/onboarding/save", json={"name": "Ion", "step": 1}).status_code == 200

    # 3. pas CUI — cercetare ANAF + salvare date firmă
    d = client.get("/api/v1/cui-lookup?cui=53067338").get_json()
    assert d["found"] and d["is_ridesharing"] is True
    client.post("/api/v1/onboarding/save", json={
        "firma_cui": d["cui"], "firma_nume": d["denumire"], "caen_principal": d["cod_caen"],
        "activity_code": d["activity_code"], "regim_tva": d["regim_tva"],
        "judet": d["judet"], "localitate": d["localitate"], "step": 2})

    # 4. pas REGIM impunere
    client.post("/api/v1/onboarding/save", json={"regim_impunere": "NORMA_VENIT", "step": 3})

    # 5. pas MAȘINĂ
    assert client.post("/api/v1/vehicul", json={"nr_inmatriculare": "BN01CAI",
                       "marca_model": "Dacia Logan", "norma_consum": 7.5}).status_code == 200

    # 6. pas REGIM NEREZIDENT (ridesharing — Ambele)
    client.post("/api/v1/onboarding/save", json={
        "regim_nerezident_bolt": "BOLT_CU_CRF", "regim_nerezident_uber": "UBER_CU_CRF", "step": 6})

    # 7. (Bolt API sărit — opțional) → FINALIZARE
    r = client.post("/api/v1/onboarding/complete", json={})
    assert r.status_code == 200 and r.get_json()["ok"] is True

    # 8. status final = onboarding complet + rehidratare coerentă
    st = client.get("/api/v1/onboarding/status").get_json()
    assert st["onboarding_completed"] is True
    data = st["data"]
    assert data["name"] == "Ion"
    assert data["is_ridesharing"] is True and data["_platforme"] == "AMBELE"
    assert data["veh_nr"] == "BN01CAI"
    assert data["regim_impunere"] == "NORMA_VENIT"

    # 9. persistat corect în DB
    s = S(); u = s.get(User, uid)
    assert u.onboarding_completed is True
    assert u.name == "Ion" and u.firma_cui == "53067338"
    assert u.regim_nerezident_bolt == "BOLT_CU_CRF" and u.regim_nerezident_uber == "UBER_CU_CRF"
    s.close()


def test_e2e_non_ridesharing_fara_pasi_bolt(monkeypatch, tmp_path):
    # user IT (non-ridesharing) → complete fără pași platforme/Bolt
    monkeypatch.setattr(anaf_lookup, "lookup_cui", lambda cui: {
        "found": True, "cui": cui, "denumire": "IT SRL", "cod_caen": "6201",
        "forma_juridica_detectata": "SRL_MICRO", "regim_tva": "PLATITOR_21",
        "is_platitor_tva": True, "is_inactiv": False, "stare_inregistrare": "OK",
    })
    client, S, uid = _web(monkeypatch, tmp_path)
    d = client.get("/api/v1/cui-lookup?cui=123").get_json()
    assert d["is_ridesharing"] is False
    client.post("/api/v1/onboarding/save", json={"name": "Ana", "step": 1})
    client.post("/api/v1/onboarding/save", json={"firma_cui": "123", "firma_nume": "IT SRL",
                "activity_code": "it_freelance", "regim_impunere": "SISTEM_REAL", "step": 3})
    client.post("/api/v1/vehicul", json={"nr_inmatriculare": "B100IT"})
    r = client.post("/api/v1/onboarding/complete", json={})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    st = client.get("/api/v1/onboarding/status").get_json()
    assert st["onboarding_completed"] is True
    assert st["data"]["is_ridesharing"] is False and st["data"]["_platforme"] is None
