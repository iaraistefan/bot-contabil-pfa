"""
C9-D — butonul de meniu permanent deschide Mini App-ul (set_chat_menu_button).

Test comportamental: post_init setează un MenuButtonWebApp („📊 Contai" → DASHBOARD_URL),
NU MenuButtonCommands. Comenzile rămân (set_my_commands apelat). Auth: butonul de meniu
WebApp primește init_data (≠ KeyboardButton).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram import MenuButtonWebApp

import bot_contabil


@pytest.mark.asyncio
async def test_post_init_seteaza_miniapp_ca_buton_meniu():
    bot = SimpleNamespace(set_my_commands=AsyncMock(), set_chat_menu_button=AsyncMock())
    await bot_contabil.post_init(SimpleNamespace(bot=bot))

    # comenzile „/" rămân populate
    bot.set_my_commands.assert_awaited_once()

    # butonul de meniu = Mini App (nu lista de comenzi)
    bot.set_chat_menu_button.assert_awaited_once()
    mb = bot.set_chat_menu_button.call_args.kwargs["menu_button"]
    assert isinstance(mb, MenuButtonWebApp)
    assert mb.text == "📊 Contai"
    assert mb.web_app.url == bot_contabil.DASHBOARD_URL


@pytest.mark.asyncio
async def test_post_init_fallback_la_eroare():
    # dacă set_chat_menu_button crapă (API down) → post_init NU aruncă (try/except) →
    # accesul rămâne pe butonul inline Dashboard + /start.
    bot = SimpleNamespace(
        set_my_commands=AsyncMock(),
        set_chat_menu_button=AsyncMock(side_effect=RuntimeError("API down")),
    )
    await bot_contabil.post_init(SimpleNamespace(bot=bot))   # nu trebuie să arunce
