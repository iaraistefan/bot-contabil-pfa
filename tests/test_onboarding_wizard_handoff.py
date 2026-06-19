"""
Onboarding wizard — sub-pas A: handoff /start → dashboard wizard.

User neonboarded dă /start → buton WebApp (NU pași în chat); dashboard se rutează la
wizard prin STARE (/api/v1/onboarding/status). User onboarded → meniu normal (gating).
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import bot_contabil
from app.models import User

_HTML = (Path(__file__).resolve().parent.parent
         / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")


# ── /start handoff (bot) ──
class _Msg:
    def __init__(self): self.text=None; self.kw=None
    async def reply_text(self, text, **kw): self.text=text; self.kw=kw


def _upd(first="Stefan"):
    return SimpleNamespace(message=_Msg(), effective_user=SimpleNamespace(id=7, first_name=first),
                           effective_chat=SimpleNamespace(id=7))


@pytest.mark.asyncio
async def test_start_neonboarded_buton_webapp(monkeypatch):
    monkeypatch.setattr(bot_contabil, "ensure_user", lambda update: 1)
    monkeypatch.setattr(bot_contabil.onboarding, "user_is_onboarded", lambda tg: False)
    upd = _upd()
    await bot_contabil.handle_start(upd, SimpleNamespace())
    # buton WebApp spre dashboard (nu pași chat)
    kb = upd.message.kw["reply_markup"].inline_keyboard
    btn = kb[0][0]
    assert btn.web_app is not None and btn.web_app.url == bot_contabil.DASHBOARD_URL
    assert "configur" in upd.message.text.lower()


@pytest.mark.asyncio
async def test_start_onboarded_meniu_normal(monkeypatch):
    monkeypatch.setattr(bot_contabil, "ensure_user", lambda update: 1)
    monkeypatch.setattr(bot_contabil.onboarding, "user_is_onboarded", lambda tg: True)
    upd = _upd()
    await bot_contabil.handle_start(upd, SimpleNamespace())
    assert "Bun venit înapoi" in upd.message.text
    # meniu reply (ReplyKeyboardMarkup), FĂRĂ buton web_app de wizard
    mk = upd.message.kw["reply_markup"]
    flat = [b for row in mk.keyboard for b in row]
    assert all(getattr(b, "web_app", None) is None for b in flat)


# ── /api/v1/onboarding/status (web) ──
def _web(monkeypatch, tmp_path, completed):
    from app.http import app as webapp
    eng = create_engine(f"sqlite:///{(tmp_path / 'o.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=1, onboarding_completed=completed, onboarding_step=3); s.add(u); s.commit(); uid=u.id; s.close()
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    return webapp.flask_app.test_client()


def test_status_neonboarded(monkeypatch, tmp_path):
    d = _web(monkeypatch, tmp_path, completed=False).get("/api/v1/onboarding/status").get_json()
    assert d["onboarding_completed"] is False and d["current_step"] == 3


def test_status_onboarded(monkeypatch, tmp_path):
    d = _web(monkeypatch, tmp_path, completed=True).get("/api/v1/onboarding/status").get_json()
    assert d["onboarding_completed"] is True


# ── dashboard: routing prin stare + mod wizard (gardian template) ──
def test_dashboard_routing_si_wizard_mode():
    assert 'authFetch("/api/v1/onboarding/status")' in _HTML
    assert "onboarding_completed" in _HTML and "enterWizard(" in _HTML
    assert 'id="wizard-root"' in _HTML
    assert "body.wizard-mode .app{display:none}" in _HTML   # chrome ascuns în wizard
