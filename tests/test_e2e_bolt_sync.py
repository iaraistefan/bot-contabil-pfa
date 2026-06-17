"""
E2E #2 — sync Bolt per-user cap-coadă: conectare → sync zilnic → ping+buton → tap → post.

Leagă A (criptare) + B (conectare) + C (sync zilnic + confirmare): un user își conectează
contul Bolt (token mock), sync-ul zilnic îl prinde (credențiale per-user decriptate), trimite
ping cu buton, iar tap-ul pe buton postează luna (atomic). API-ul Bolt e mock-uit.
"""

from types import SimpleNamespace

import requests as _requests
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from telegram.ext import ApplicationHandlerStop

from app.integrations import bolt_sync
from app.domain import crypto
from app.models import User


class _Resp:
    def __init__(self, status, payload=None): self.status_code=status; self._p=payload or {}
    def json(self): return self._p
    def raise_for_status(self):
        if self.status_code>=400: raise _requests.HTTPError(str(self.status_code))


@pytest.mark.asyncio
async def test_e2e_conectare_sync_ping_tap_post(monkeypatch, tmp_path):
    from app.http import app as webapp
    eng = create_engine(f"sqlite:///{(tmp_path / 'e2e.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=900); s.add(u); s.commit(); uid = u.id; s.close()

    # toate căile (web + bolt_sync) pe aceeași DB
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    monkeypatch.setattr(bolt_sync, "get_session", lambda: S())
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.delenv("BOLT_OWNER_TELEGRAM_ID", raising=False)

    # ── B: conectare (token de test OK) → creds CRIPTATE în DB ──
    monkeypatch.setattr(bolt_sync.requests, "post",
                        lambda *a, **k: _Resp(200, {"access_token": "tok", "expires_in": 600}))
    r = webapp.flask_app.test_client().post(
        "/api/v1/bolt/connect", json={"client_id": "CID", "client_secret": "MYSECRET"})
    assert r.status_code == 200
    # store+load+decrypt: clientul per-user se reconstruiește din DB
    ss = S(); c = bolt_sync.bolt_client_for_user(ss, uid); ss.close()
    assert c is not None and c.client_id == "CID" and c.client_secret == "MYSECRET"

    # ── C: sync zilnic îl prinde (credențiale per-user) → ping cu buton ──
    monkeypatch.setattr(bolt_sync, "collect_recent", lambda user_id, days=4, client=None: 5)
    monkeypatch.setattr(bolt_sync, "get_today_summary", lambda user_id: {"n": 5, "net": 240.0})
    pings = []
    monkeypatch.setattr(bolt_sync, "_send_with_button",
                        lambda tok, chat, txt, y, m: pings.append((chat, y, m, txt)))
    posted_at_sync = []
    monkeypatch.setattr(bolt_sync, "post_month", lambda *a, **k: posted_at_sync.append(a) or
                        {"replaced": False, "tx_count": 3, "doc_id": 1})

    bolt_sync.run_bolt_daily_sync("tok")
    assert len(pings) == 1 and pings[0][0] == 900           # ping trimis userului conectat
    assert "240" in pings[0][3]                             # „azi 240 lei net"
    assert posted_at_sync == []                             # CONFIRM-FIRST: nimic postat la sync
    _, py, pm, _ = pings[0]                                 # luna curentă din ping

    # ── tap pe buton → post_month (atomic) ──
    posted = []
    monkeypatch.setattr(bolt_sync, "_resolve_user_id", lambda tg: uid)
    monkeypatch.setattr(bolt_sync, "get_month_summary",
                        lambda user_id, y, m: {"n": 5, "brut": 300.0, "comision": 60.0})
    monkeypatch.setattr(bolt_sync, "post_month",
                        lambda user_id, s: posted.append((user_id, s)) or
                        {"replaced": False, "tx_count": 3, "doc_id": 7})

    class _Q:
        def __init__(self): self.data=f"boltsync|confirm|{py}|{pm}"; self.from_user=SimpleNamespace(id=900); self.edits=[]
        async def answer(self): pass
        async def edit_message_text(self, text, **kw): self.edits.append(text)
    q = _Q()
    with pytest.raises(ApplicationHandlerStop):
        await bolt_sync.handle_bolt_callback(SimpleNamespace(callback_query=q), SimpleNamespace())
    assert len(posted) == 1 and posted[0][0] == uid        # postare DOAR la tap (confirm-first)
    assert any("Adaugat in Registru" in e for e in q.edits)
