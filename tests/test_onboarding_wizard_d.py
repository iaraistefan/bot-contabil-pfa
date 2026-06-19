"""
Onboarding wizard — sub-pas D: redirect chat vechi → /setup_text (ULTIMUL sub-pas).

Wizardul (dashboard) = calea PRIMARĂ; chat-ul (step-engine vechi) = fallback ne-promovat
pentru userul care nu poate deschide dashboard-ul. /setup_text intră în același
start_onboarding (sursă unică). start_onboarding NU e orfan (și /reset_profil îl apelează).
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

import bot_contabil

_BOT_SRC = (Path(__file__).resolve().parent.parent / "bot_contabil.py").read_text(encoding="utf-8")


class _Msg:
    def __init__(self): self.text=None; self.kw=None
    async def reply_text(self, text, **kw): self.text=text; self.kw=kw


def _upd():
    return SimpleNamespace(message=_Msg(), effective_user=SimpleNamespace(id=7, first_name="Stefan", full_name="Stefan I", username="stefan"),
                           effective_chat=SimpleNamespace(id=7))


# ── /setup_text pornește chat-ul vechi (start_onboarding) ──
@pytest.mark.asyncio
async def test_setup_text_porneste_chat(monkeypatch):
    monkeypatch.setattr(bot_contabil, "ensure_user", lambda update: 1)
    called = {"n": 0}
    async def _fake_start(update, context): called["n"] += 1
    monkeypatch.setattr(bot_contabil.onboarding, "start_onboarding", _fake_start)
    upd = _upd()
    await bot_contabil.handle_setup_text(upd, SimpleNamespace())
    assert called["n"] == 1                                  # intră în chat step-engine
    assert "chat" in upd.message.text.lower()                # mesaj: calea text alternativă
    assert "/start" in upd.message.text                      # trimite spre dashboard ca preferință


# ── /start neonboarded indică /setup_text ca fallback (discret) ──
@pytest.mark.asyncio
async def test_start_neonboarded_mentioneaza_setup_text(monkeypatch):
    monkeypatch.setattr(bot_contabil, "ensure_user", lambda update: 1)
    monkeypatch.setattr(bot_contabil.onboarding, "user_is_onboarded", lambda tg: False)
    upd = _upd()
    await bot_contabil.handle_start(upd, SimpleNamespace())
    # butonul WebApp rămâne calea primară
    assert upd.message.kw["reply_markup"].inline_keyboard[0][0].web_app is not None
    # fallback discret menționat
    assert "/setup_text" in upd.message.text


# ── comanda e înregistrată ──
def test_setup_text_inregistrat():
    assert 'CommandHandler("setup_text", handle_setup_text)' in _BOT_SRC


# ── start_onboarding NU e orfan: și /reset_profil îl apelează (curățenie) ──
def test_start_onboarding_neorfan():
    # două căi spre chat-ul vechi: reset_profil + setup_text; handle_start NU-l mai apelează
    assert "await onboarding.start_onboarding(update, context)" in _BOT_SRC
    # handle_start (neonboarded) folosește buton WebApp, nu start_onboarding direct
    start_fn = _BOT_SRC.split("async def handle_start")[1].split("async def ")[0]
    assert "start_onboarding" not in start_fn                # /start nu mai pornește chat-ul
