"""
A2 — endpoint /api/v1/simulare-regim/<year>: conectează funcția pură A1 la profilul real.

Citește venit_brut/cheltuieli YTD (compute_d212_anual, sursă unică) + profilul user
(normă stocată, regim, activitate, pensionar/salariat) → cheamă simulare_regim → JSON.
Funcția pură A1 NEatinsă; endpointul doar o alimentează + adaugă flag-ul de prezentare
`fara_venituri`.
"""

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User

AN = 2026


def _web(monkeypatch, tmp_path, **user_kw):
    from app.http import app as webapp
    eng = create_engine(f"sqlite:///{(tmp_path / 'sim.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=1, **user_kw); s.add(u); s.commit(); uid = u.id; s.close()
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    return webapp, webapp.flask_app.test_client(), uid


def _mock_ytd(monkeypatch, webapp, venit_brut, cheltuieli):
    """Controlează venitul/cheltuielile YTD (sursa unică) fără a popula tranzacții."""
    monkeypatch.setattr(
        webapp.tax_engine, "compute_d212_anual",
        lambda s, *, user_id, an: SimpleNamespace(venit_brut=venit_brut, cheltuieli=cheltuieli),
    )


# ════════════════════════════════════════════════════════════
#   User pe normă cu venituri → comparație completă
# ════════════════════════════════════════════════════════════

def test_user_norma_comparatie(monkeypatch, tmp_path):
    webapp, client, uid = _web(monkeypatch, tmp_path, regim_impunere="NORMA_VENIT",
                               norma_venit_anuala=50_000.0, activity_code="ridesharing")
    _mock_ytd(monkeypatch, webapp, 200_000, 20_000)   # real scump → normă mai ieftină
    r = client.get(f"/api/v1/simulare-regim/{AN}")
    assert r.status_code == 200
    d = r.get_json()
    assert d["regim_curent"] == "NORMA_VENIT"
    assert d["fara_venituri"] is False
    assert d["real"] is not None and d["norma"] is not None
    assert d["recomandat"] == "NORMA_VENIT"
    assert d["diferenta"] > 0
    # structura cheilor
    assert set(d["real"]) == {"total_taxe", "impozit", "cas", "cass", "venit_net"}


# ════════════════════════════════════════════════════════════
#   User pe real fără normă → indisponibilă (NU inventăm), fără crash
# ════════════════════════════════════════════════════════════

def test_user_real_norma_indisponibila(monkeypatch, tmp_path):
    webapp, client, uid = _web(monkeypatch, tmp_path, regim_impunere="SISTEM_REAL",
                               norma_venit_anuala=None, activity_code="ridesharing")
    _mock_ytd(monkeypatch, webapp, 90_000, 30_000)
    r = client.get(f"/api/v1/simulare-regim/{AN}")
    assert r.status_code == 200
    d = r.get_json()
    assert d["norma"] is None
    assert d["recomandat"] is None
    assert "NORMA_INDISPONIBILA" in d["avertismente_legale"]
    assert d["real"] is not None                       # real calculat oricum


# ════════════════════════════════════════════════════════════
#   Fără venituri → flag elegant, NU 500
# ════════════════════════════════════════════════════════════

def test_fara_venituri_flag_nu_500(monkeypatch, tmp_path):
    webapp, client, uid = _web(monkeypatch, tmp_path, regim_impunere="NORMA_VENIT",
                               norma_venit_anuala=50_000.0, activity_code="ridesharing")
    _mock_ytd(monkeypatch, webapp, 0, 0)
    r = client.get(f"/api/v1/simulare-regim/{AN}")
    assert r.status_code == 200                         # nu 500
    d = r.get_json()
    assert d["fara_venituri"] is True
    assert d["real"]["total_taxe"] == 0.0               # real pe 0 venituri


# ════════════════════════════════════════════════════════════
#   Auth + validare an
# ════════════════════════════════════════════════════════════

def test_neautentificat_401(monkeypatch):
    from app.http import app as webapp
    monkeypatch.setattr(webapp, "_require_user", lambda: (None, ("unauth", 401)))
    r = webapp.flask_app.test_client().get(f"/api/v1/simulare-regim/{AN}")
    assert r.status_code == 401


def test_an_invalid_400(monkeypatch, tmp_path):
    webapp, client, uid = _web(monkeypatch, tmp_path, regim_impunere="SISTEM_REAL")
    r = client.get("/api/v1/simulare-regim/1999")
    assert r.status_code == 400


# ════════════════════════════════════════════════════════════
#   A3.2 — override ?norma= (ipoteză) + judet în răspuns
# ════════════════════════════════════════════════════════════

def test_judet_in_raspuns(monkeypatch, tmp_path):
    webapp, client, uid = _web(monkeypatch, tmp_path, regim_impunere="SISTEM_REAL",
                               norma_venit_anuala=None, activity_code="ridesharing", judet="SJ")
    _mock_ytd(monkeypatch, webapp, 90_000, 30_000)
    d = client.get(f"/api/v1/simulare-regim/{AN}").get_json()
    assert d["judet"] == "SJ"                              # pentru norma-lookup live


def test_override_norma_deblocheaza_comparatia(monkeypatch, tmp_path):
    # user pe real FĂRĂ normă stocată → fără param = indisponibilă; cu ?norma= → comparație
    webapp, client, uid = _web(monkeypatch, tmp_path, regim_impunere="SISTEM_REAL",
                               norma_venit_anuala=None, activity_code="ridesharing", judet="SJ")
    _mock_ytd(monkeypatch, webapp, 200_000, 20_000)
    fara = client.get(f"/api/v1/simulare-regim/{AN}").get_json()
    assert fara["norma"] is None and "NORMA_INDISPONIBILA" in fara["avertismente_legale"]
    cu = client.get(f"/api/v1/simulare-regim/{AN}?norma=50000").get_json()
    assert cu["norma"] is not None                        # override (ipoteză) → comparație
    assert cu["recomandat"] is not None
    assert "NORMA_INDISPONIBILA" not in cu["avertismente_legale"]


def test_override_nu_scrie_in_profil(monkeypatch, tmp_path):
    # IPOTEZĂ: ?norma NU modifică profilul userului
    webapp, client, uid = _web(monkeypatch, tmp_path, regim_impunere="SISTEM_REAL",
                               norma_venit_anuala=None, activity_code="ridesharing", judet="SJ")
    _mock_ytd(monkeypatch, webapp, 200_000, 20_000)
    client.get(f"/api/v1/simulare-regim/{AN}?norma=50000")
    from app.http import app as webapp2
    s = webapp.get_session(); u = s.get(User, uid)
    assert u.norma_venit_anuala is None                   # profilul NEatins
    s.close()


def test_norma_invalida_400(monkeypatch, tmp_path):
    webapp, client, uid = _web(monkeypatch, tmp_path, regim_impunere="SISTEM_REAL",
                               norma_venit_anuala=None, activity_code="ridesharing")
    _mock_ytd(monkeypatch, webapp, 90_000, 30_000)
    assert client.get(f"/api/v1/simulare-regim/{AN}?norma=abc").status_code == 400   # non-numeric
    assert client.get(f"/api/v1/simulare-regim/{AN}?norma=-5").status_code == 400    # ≤0
    assert client.get(f"/api/v1/simulare-regim/{AN}?norma=").status_code == 200      # gol → stocata
