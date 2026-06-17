"""
#2-D — nudge „fără API → manual" pentru userii neconectați (web + Telegram).

Onest: manual = ALTERNATIVA pentru cei fără acces API, NU echivalentul (API = automat).
CSV amânat (format Bolt incert). Calea manuală în sine e neschimbată (există deja).
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import bot_contabil
from app.domain import crypto
from app.models import User

_HTML = (Path(__file__).resolve().parent.parent
         / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")


def test_nudge_web_neconectat():
    # nudge-ul e în formularul Bolt-connect (ramura neconectat)
    assert "Nu poți conecta API-ul Bolt" in _HTML
    assert "manual" in _HTML and "screenshot" in _HTML
    assert "venit bolt" in _HTML.lower()       # formatul din /ajutor


class _Msg:
    def __init__(self): self.text = None; self.kw = None
    async def reply_text(self, text, **kw): self.text = text; self.kw = kw


def _setup(monkeypatch, tmp_path, **user_kw):
    eng = create_engine(f"sqlite:///{(tmp_path / 'n.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=5, **user_kw); s.add(u); s.commit(); uid = u.id; s.close()
    monkeypatch.setattr(bot_contabil, "get_session", lambda: S())
    monkeypatch.setattr(bot_contabil, "ensure_user", lambda update: uid)
    msg = _Msg()
    upd = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=5),
                          effective_chat=SimpleNamespace(id=5))
    return upd, msg


@pytest.mark.asyncio
async def test_nudge_telegram_neconectat(monkeypatch, tmp_path):
    upd, msg = _setup(monkeypatch, tmp_path)        # user fără credențiale Bolt
    await bot_contabil.handle_bolt_conectare(upd, SimpleNamespace())
    assert "Nu poți conecta API-ul" in msg.text
    assert "manual" in msg.text and "screenshot" in msg.text.lower()


@pytest.mark.asyncio
async def test_conectat_fara_nudge(monkeypatch, tmp_path):
    # user CONECTAT → mesaj de status, FĂRĂ nudge-ul „nu poți conecta"
    upd, msg = _setup(monkeypatch, tmp_path,
                      bolt_client_id="ID", bolt_client_secret_enc=crypto.encrypt("SEC"))
    await bot_contabil.handle_bolt_conectare(upd, SimpleNamespace())
    assert "conectat" in msg.text.lower()
    assert "Nu poți conecta API-ul" not in msg.text
