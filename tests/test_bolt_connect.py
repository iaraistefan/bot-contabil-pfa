"""
#2-B — conectare Bolt per-user: BoltClient per-user, validare (mock token), connect/status.

Mock-uim `requests.post` pe endpoint-ul token Bolt (oidc.bolt.eu) — NU lovim API-ul real.
SECURITATE: connect stochează secretul CRIPTAT (nu plaintext în DB); status îl maschează.
"""

import requests as _requests
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config import settings
from app.integrations import bolt_sync
from app.domain import crypto
from app.models import User


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status; self._p = payload or {}
    def json(self): return self._p
    def raise_for_status(self):
        if self.status_code >= 400:
            raise _requests.HTTPError(str(self.status_code))


def _mock_token_ok(monkeypatch):
    monkeypatch.setattr(bolt_sync.requests, "post",
                        lambda *a, **k: _Resp(200, {"access_token": "tok", "expires_in": 600}))


def _mock_token_fail(monkeypatch):
    monkeypatch.setattr(bolt_sync.requests, "post", lambda *a, **k: _Resp(401))


# ════════════════════════════════════════════════════════
# 1. BoltClient — per-user vs env
# ════════════════════════════════════════════════════════

def test_boltclient_per_user_vs_env(monkeypatch):
    monkeypatch.delenv("BOLT_CLIENT_ID", raising=False)
    monkeypatch.delenv("BOLT_CLIENT_SECRET", raising=False)
    assert bolt_sync.BoltClient().available() is False          # fără env → indisponibil
    c = bolt_sync.BoltClient(client_id="ID", client_secret="SEC")
    assert c.client_id == "ID" and c.client_secret == "SEC" and c.available() is True


# ════════════════════════════════════════════════════════
# 2. validate_bolt_credentials — mock token (succes/eșec/gol/fără cheie)
# ════════════════════════════════════════════════════════

def test_validate_succes(monkeypatch):
    _mock_token_ok(monkeypatch)
    ok, err = bolt_sync.validate_bolt_credentials("ID", "SEC")
    assert ok is True and err is None


def test_validate_chei_invalide(monkeypatch):
    _mock_token_fail(monkeypatch)
    ok, err = bolt_sync.validate_bolt_credentials("ID", "SEC")
    assert ok is False and "invalide" in err.lower()


def test_validate_campuri_goale(monkeypatch):
    _mock_token_ok(monkeypatch)
    ok, err = bolt_sync.validate_bolt_credentials("", "SEC")
    assert ok is False and err


def test_validate_fara_cheie_cripto(monkeypatch):
    monkeypatch.setattr(settings, "contai_enc_key", None)
    ok, err = bolt_sync.validate_bolt_credentials("ID", "SEC")
    assert ok is False and "indisponibil" in err.lower()


# ════════════════════════════════════════════════════════
# 3. bolt_client_for_user — încărcare + decriptare
# ════════════════════════════════════════════════════════

def _db(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 'b2.db').as_posix()}")
    User.metadata.create_all(eng)
    return sessionmaker(bind=eng)


def test_bolt_client_for_user(tmp_path):
    S = _db(tmp_path); s = S()
    u = User(telegram_id=1, bolt_client_id="ID9", bolt_client_secret_enc=crypto.encrypt("SEC9"))
    s.add(u); s.commit(); uid = u.id
    c = bolt_sync.bolt_client_for_user(s, uid)
    assert c is not None and c.client_id == "ID9" and c.client_secret == "SEC9"   # decriptat
    # user neconectat → None
    u2 = User(telegram_id=2); s.add(u2); s.commit()
    assert bolt_sync.bolt_client_for_user(s, u2.id) is None
    s.close()


# ════════════════════════════════════════════════════════
# 4. /api/v1/bolt/connect + /status (web)
# ════════════════════════════════════════════════════════

def _web(monkeypatch, tmp_path):
    from app.http import app as webapp
    eng = create_engine(f"sqlite:///{(tmp_path / 'w.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=1); s.add(u); s.commit(); uid = u.id; s.close()
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    return webapp.flask_app.test_client(), S, uid


def test_connect_succes_stocheaza_criptat(monkeypatch, tmp_path):
    _mock_token_ok(monkeypatch)
    client, S, uid = _web(monkeypatch, tmp_path)
    r = client.post("/api/v1/bolt/connect", json={"client_id": "MYID", "client_secret": "MYSECRET"})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    # DB: secretul CRIPTAT (nu plaintext), connected_at setat
    s = S(); u = s.query(User).filter_by(id=uid).one()
    assert u.bolt_client_id == "MYID"
    assert u.bolt_client_secret_enc and "MYSECRET" not in u.bolt_client_secret_enc
    assert crypto.decrypt(u.bolt_client_secret_enc) == "MYSECRET"
    assert u.bolt_connected_at is not None
    s.close()


def test_connect_chei_invalide_nu_stocheaza(monkeypatch, tmp_path):
    _mock_token_fail(monkeypatch)
    client, S, uid = _web(monkeypatch, tmp_path)
    r = client.post("/api/v1/bolt/connect", json={"client_id": "X", "client_secret": "Y"})
    assert r.status_code == 400
    s = S(); u = s.query(User).filter_by(id=uid).one()
    assert u.bolt_client_id is None and u.bolt_client_secret_enc is None   # NU s-a stocat
    s.close()


def test_status_secret_mascat(monkeypatch, tmp_path):
    from app.http import app as webapp
    eng = create_engine(f"sqlite:///{(tmp_path / 's.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=1, bolt_client_id="PUBID",
                      bolt_client_secret_enc=crypto.encrypt("REALSECRET")); s.add(u); s.commit(); uid=u.id; s.close()
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    d = webapp.flask_app.test_client().get("/api/v1/bolt/status").get_json()
    assert d["connected"] is True
    assert d["client_id"] == "PUBID"
    assert d["secret_masked"] == "••••••"
    # secretul real NU apare nicăieri în răspuns
    import json as _json
    assert "REALSECRET" not in _json.dumps(d)
