"""
Pas 10.2 — UI Telegram pentru configurare Reminder-uri Obligații Fiscale.

Permite user-ului să:
  • Activeze / dezactiveze alertele proactive
  • Configureze ora la care primește alertele (default 08:00)
  • Configureze avansul de zile (default 7)
  • Testeze sistemul de alerte manual

Toate setările sunt salvate în coloanele User:
  • proactive_alerts_enabled (bool)
  • proactive_alerts_hour (int, 0-23)
  • proactive_alerts_advance_days (int, 1-30)

CHANGELOG:
- v1 (Pas 10.2): UI complet
"""

import logging
from typing import List

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


# ============================================================
#                    CONSTANTE
# ============================================================

BTN_LABEL = "⏰ Reminder-uri obligații"

# Orele disponibile pentru alerte (limităm la cele comune)
HOURS_AVAILABLE = [6, 7, 8, 9, 10, 12, 14, 18, 20]

# Avansul în zile (când să primească prima alertă)
ADVANCE_DAYS_AVAILABLE = [3, 5, 7, 10, 14, 21]


# ============================================================
#                    DB HELPERS
# ============================================================

def _get_user_settings(session, user_id: int) -> dict:
    """Returnează setări alerte pentru un user."""
    from app.models import User
    try:
        user = (
            session.query(User)
            .filter(User.id == user_id)
            .first()
        )
        if not user:
            return {"enabled": True, "hour": 8, "advance_days": 7}
        return {
            "enabled": getattr(user, "proactive_alerts_enabled", True),
            "hour": getattr(user, "proactive_alerts_hour", 8),
            "advance_days": getattr(user, "proactive_alerts_advance_days", 7),
        }
    except Exception as e:
        logger.error(f"_get_user_settings error: {e}")
        return {"enabled": True, "hour": 8, "advance_days": 7}


def _update_user_setting(session, user_id: int, field: str, value) -> bool:
    """Actualizează un singur câmp de setări."""
    from app.models import User
    try:
        user = (
            session.query(User)
            .filter(User.id == user_id)
            .first()
        )
        if not user:
            return False
        setattr(user, field, value)
        session.commit()
        logger.info(
            f"User {user_id} updated {field}={value}"
        )
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"_update_user_setting error: {e}")
        return False


# ============================================================
#                    UI BUILDERS
# ============================================================

def _build_main_menu(settings: dict) -> InlineKeyboardMarkup:
    """Meniul principal cu status și butoane."""
    enabled_emoji = "✅" if settings["enabled"] else "❌"
    enabled_label = (
        "DEZACTIVEAZĂ alertele" if settings["enabled"]
        else "ACTIVEAZĂ alertele"
    )

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{enabled_emoji} {enabled_label}",
            callback_data="reminder|toggle"
        )],
        [InlineKeyboardButton(
            f"⏰ Schimbă ora (acum {settings['hour']:02d}:00)",
            callback_data="reminder|hour"
        )],
        [InlineKeyboardButton(
            f"📅 Schimbă avansul (acum {settings['advance_days']} zile)",
            callback_data="reminder|advance"
        )],
        [InlineKeyboardButton(
            "🧪 Test acum (vezi ce obligații ai)",
            callback_data="reminder|test"
        )],
        [InlineKeyboardButton(
            "⬅️ Înapoi la Setări",
            callback_data="settings|menu"
        )],
    ])


def _format_status_message(settings: dict) -> str:
    """Construiește mesajul cu status curent."""
    enabled_label = (
        "✅ *ACTIVATE*" if settings["enabled"]
        else "❌ *DEZACTIVATE*"
    )

    return (
        f"⏰ *Reminder-uri pentru obligații*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*Status*: {enabled_label}\n"
        f"*Oră zilnică*: `{settings['hour']:02d}:00`\n"
        f"*Avans alertă*: `{settings['advance_days']} zile` "
        f"_(cu cât înainte de termen)_\n\n"
        f"_Îți trimit zilnic reminder-uri cu obligațiile "
        f"apropiate (D301, D100, D212, etc.):_\n\n"
        f"  • 🟡 *{settings['advance_days']} zile rămase* — din timp\n"
        f"  • 🟠 *3 zile rămase* — se apropie\n"
        f"  • 🔴 *Ziua termenului* — ultima zi\n"
        f"  • ❌ *Depășit* — zilnic 7 zile, apoi săptămânal\n\n"
        f"_Nu te sâcâi: primești o singură alertă pentru "
        f"fiecare obligație și tip._\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )


def _build_hour_picker() -> InlineKeyboardMarkup:
    """Picker pentru oră (3 butoane pe rând)."""
    rows = []
    for i in range(0, len(HOURS_AVAILABLE), 3):
        row = [
            InlineKeyboardButton(
                f"{h:02d}:00",
                callback_data=f"reminder|set_hour|{h}"
            )
            for h in HOURS_AVAILABLE[i:i + 3]
        ]
        rows.append(row)
    rows.append([
        InlineKeyboardButton("⬅️ Înapoi", callback_data="reminder|menu"),
    ])
    return InlineKeyboardMarkup(rows)


def _build_advance_picker() -> InlineKeyboardMarkup:
    """Picker pentru avans în zile (3 butoane pe rând)."""
    rows = []
    for i in range(0, len(ADVANCE_DAYS_AVAILABLE), 3):
        row = [
            InlineKeyboardButton(
                f"{d} zile",
                callback_data=f"reminder|set_advance|{d}"
            )
            for d in ADVANCE_DAYS_AVAILABLE[i:i + 3]
        ]
        rows.append(row)
    rows.append([
        InlineKeyboardButton("⬅️ Înapoi", callback_data="reminder|menu"),
    ])
    return InlineKeyboardMarkup(rows)


# ============================================================
#                    CALLBACK HANDLER
# ============================================================

async def handle_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parts: List[str],
) -> None:
    """
    Router pentru toate callback queries namespace=reminder.

    Formate callback_data:
      reminder|menu              → afișează meniul principal
      reminder|toggle            → toggle enable/disable
      reminder|hour              → afișează picker oră
      reminder|set_hour|H        → setează ora la H
      reminder|advance           → afișează picker avans
      reminder|set_advance|D     → setează avansul la D zile
      reminder|test              → rulează test manual
    """
    from db import get_session

    query = update.callback_query
    tg_id = update.effective_user.id

    session = get_session()
    try:
        from app.repositories import users as users_repo
        user = users_repo.get_by_telegram_id(session, telegram_id=tg_id)
        if not user:
            await query.edit_message_text(
                "⚠️ Nu te-am putut identifica. Deschide botul din nou din buton și încearcă iar."
            )
            return
        user_id = user.id

        if len(parts) < 2:
            return

        action = parts[1]

        # ─── MENIU PRINCIPAL ──────────────────────────────────
        if action == "menu":
            settings = _get_user_settings(session, user_id)
            await query.edit_message_text(
                _format_status_message(settings),
                parse_mode="Markdown",
                reply_markup=_build_main_menu(settings),
            )
            return

        # ─── TOGGLE ENABLE/DISABLE ────────────────────────────
        if action == "toggle":
            settings = _get_user_settings(session, user_id)
            new_value = not settings["enabled"]
            success = _update_user_setting(
                session, user_id,
                "proactive_alerts_enabled", new_value,
            )
            if success:
                settings["enabled"] = new_value
            await query.edit_message_text(
                _format_status_message(settings),
                parse_mode="Markdown",
                reply_markup=_build_main_menu(settings),
            )
            return

        # ─── PICKER ORĂ ───────────────────────────────────────
        if action == "hour":
            await query.edit_message_text(
                "⏰ *La ce oră vrei să-ți trimit reminder-urile?*\n\n"
                "_Atunci îți trimit alertele despre obligațiile "
                "apropiate._",
                parse_mode="Markdown",
                reply_markup=_build_hour_picker(),
            )
            return

        # ─── SETARE ORĂ ───────────────────────────────────────
        if action == "set_hour":
            try:
                new_hour = int(parts[2])
                if not (0 <= new_hour <= 23):
                    raise ValueError("Out of range")
            except (ValueError, IndexError):
                await query.edit_message_text("❌ Nu pare o oră validă.")
                return

            _update_user_setting(
                session, user_id,
                "proactive_alerts_hour", new_hour,
            )
            settings = _get_user_settings(session, user_id)
            await query.edit_message_text(
                _format_status_message(settings),
                parse_mode="Markdown",
                reply_markup=_build_main_menu(settings),
            )
            return

        # ─── PICKER AVANS ─────────────────────────────────────
        if action == "advance":
            await query.edit_message_text(
                "📅 *Cu câte zile înainte să te anunț prima dată?*\n\n"
                "_Ex: 7 zile = te anunț cu 7 zile înainte, "
                "apoi cu 3 zile, în ziua termenului, și după._",
                parse_mode="Markdown",
                reply_markup=_build_advance_picker(),
            )
            return

        # ─── SETARE AVANS ─────────────────────────────────────
        if action == "set_advance":
            try:
                new_days = int(parts[2])
                if not (1 <= new_days <= 30):
                    raise ValueError("Out of range")
            except (ValueError, IndexError):
                await query.edit_message_text("❌ Nu pare un număr de zile valid.")
                return

            _update_user_setting(
                session, user_id,
                "proactive_alerts_advance_days", new_days,
            )
            settings = _get_user_settings(session, user_id)
            await query.edit_message_text(
                _format_status_message(settings),
                parse_mode="Markdown",
                reply_markup=_build_main_menu(settings),
            )
            return

        # ─── TEST MANUAL ──────────────────────────────────────
        if action == "test":
            await query.edit_message_text(
                "🔄 _Verific alertele pentru luna asta..._",
                parse_mode="Markdown",
            )

            try:
                from app.services.proactive_alerts import test_alerts_for_user
                from config import settings as cfg

                result = test_alerts_for_user(
                    cfg.telegram_token, tg_id
                )

                if result.get("success"):
                    obligatii_count = result.get("obligatii_count", 0)
                    obligatii_list = result.get("obligatii", [])

                    if obligatii_count == 0:
                        msg = (
                            "✅ *Gata!*\n\n"
                            "N-ai nicio obligație de plătit "
                            "luna asta.\n\n"
                            "_Dacă ți se pare o greșeală, verifică-ți "
                            "profilul cu /profil._"
                        )
                    else:
                        obligatii_str = ", ".join(obligatii_list)
                        msg = (
                            f"✅ *Gata!*\n\n"
                            f"Ai *{obligatii_count}* obligații "
                            f"luna asta:\n"
                            f"`{obligatii_str}`\n\n"
                            f"Uite detaliile mai sus 📋\n\n"
                            f"_În mod normal, îți trimit alerte doar "
                            f"pentru cele cu termen apropiat._"
                        )
                else:
                    err = result.get("error", "necunoscut")
                    msg = (
                        f"❌ *N-a mers testul*\n\n"
                        f"Motiv: `{err}`\n\n"
                        f"_Detalii în log._"
                    )
            except Exception as e:
                logger.error(f"Test alerts error: {e}")
                msg = (
                    f"❌ *Ceva n-a mers la test*: `{str(e)[:200]}`"
                )

            settings = _get_user_settings(session, user_id)
            await query.edit_message_text(
                msg,
                parse_mode="Markdown",
                reply_markup=_build_main_menu(settings),
            )
            return

    except Exception as e:
        logger.error(f"reminder_ui callback error: {e}")
        try:
            await query.edit_message_text(
                f"❌ Ceva n-a mers cum trebuia: {str(e)[:200]}"
            )
        except Exception:
            pass
    finally:
        session.close()


# ============================================================
#                    ENTRY POINT (din settings menu)
# ============================================================

async def show_main_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Afișează meniul principal — apelat de bot_contabil.py când user
    apasă butonul '⏰ Reminder-uri obligații' din Setări.
    """
    from db import get_session

    query = update.callback_query
    tg_id = update.effective_user.id

    session = get_session()
    try:
        from app.repositories import users as users_repo
        user = users_repo.get_by_telegram_id(session, telegram_id=tg_id)
        if not user:
            await query.edit_message_text(
                "⚠️ Nu te-am putut identifica. Deschide botul din nou din buton și încearcă iar."
            )
            return

        settings = _get_user_settings(session, user.id)
        await query.edit_message_text(
            _format_status_message(settings),
            parse_mode="Markdown",
            reply_markup=_build_main_menu(settings),
        )
    finally:
        session.close()


__all__ = [
    "BTN_LABEL",
    "handle_callback",
    "show_main_menu",
]
