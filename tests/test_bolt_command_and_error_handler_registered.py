"""
Regresie-lock (audit #4): /bolt ȘI error handler-ul global SUNT înregistrate.

Auditul a raportat (FALS) că /bolt e comandă moartă și că lipsește add_error_handler.
De fapt AMBELE există și funcționează:
  - /bolt e înregistrat la nivel de MODUL prin bolt_sync.register(app_bot) (NU în blocul
    principal de handlere din bot_contabil) → ușor de ratat (auditul însuși l-a ratat) și
    ușor de scos la un refactor.
  - add_error_handler(handle_error) e înregistrat în main().

Acest test le prinde în cuie + documentează că sunt intenționate și critice. ZERO cod de
producție modificat — doar lock. Dacă cineva scoate vreuna, testul cade.
"""

import inspect
import re
from pathlib import Path

from telegram.ext import ApplicationBuilder, CommandHandler

import bot_contabil
from app.integrations import bolt_sync

# sursa main()-ului, normalizată (fără spații) pentru lock robust la reformatări minore
_BOT_SRC_NOSPACE = re.sub(r"\s+", "", Path(bot_contabil.__file__).read_text(encoding="utf-8"))


def _build_app():
    # build() e offline (nu conectează) — token dummy valid ca format
    return ApplicationBuilder().token(
        "123456:TEST-DUMMY-abcdefghijklmnopqrstuvwxyz").build()


# ── (A) /bolt ────────────────────────────────────────────────

def test_bolt_sync_register_inregistreaza_comanda_bolt(monkeypatch):
    # nu pornim scheduler-ul Bolt real în test
    monkeypatch.setattr(bolt_sync, "_start_bolt_scheduler", lambda *a, **k: None)
    app = _build_app()
    bolt_sync.register(app)

    cmd_handlers = [h for hs in app.handlers.values() for h in hs
                    if isinstance(h, CommandHandler)]
    bolt = [h for h in cmd_handlers if "bolt" in h.commands]
    assert bolt, "CommandHandler('bolt') NU e înregistrat de bolt_sync.register()"
    # leagă comanda de logica reală, nu de un stub gol
    assert bolt[0].callback is bolt_sync.handle_bolt_command


def test_main_apeleaza_bolt_sync_register():
    # lock pe wiring: main() trebuie să cheme bolt_sync.register(app_bot)
    # (registrarea la nivel de modul = exact ce a ratat auditul)
    assert "bolt_sync.register(app_bot)" in _BOT_SRC_NOSPACE


# ── (B) error handler global ─────────────────────────────────

def test_handle_error_e_handler_valid_si_acceptat():
    # handle_error e o corutină (semnătura update/context) acceptată de PTB ca error handler
    assert inspect.iscoroutinefunction(bot_contabil.handle_error)
    app = _build_app()
    app.add_error_handler(bot_contabil.handle_error)
    assert bot_contabil.handle_error in app.error_handlers


def test_main_inregistreaza_error_handler_global():
    # lock pe wiring: main() înregistrează handle_error ca error handler global
    assert "add_error_handler(handle_error)" in _BOT_SRC_NOSPACE
