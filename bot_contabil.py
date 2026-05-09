from config import settings
from app.enums import DocType
from db import init_db, get_session
from app.repositories import users as users_repo
from app.repositories import source_files as source_files_repo
from app.repositories import documents as documents_repo
from app.repositories import transactions as tx_repo
from app.repositories import audit as audit_repo
from app.repositories import tax_periods as tax_periods_repo
from app import storage
from app.ai import client as ai_client
from app.ai import fiscal_monitor as fiscal_mon
from app.services import posting
from app.services import tax_engine
from app.services import scheduler as sched_service
from app.services import onboarding
from app.integrations import sheets
from app.integrations.exports import csv_export
from app.integrations.exports.registru import (
    generate_registru_xlsx, filename_registru
)
from app.http.app import start_http_server
from app.domain import fiscal_calendar
from app.migrations import run_migrations
import io as _io
import logging
import traceback
from datetime import datetime
from typing import List
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup, WebAppInfo,
)
from telegram.ext import (
    ApplicationBuilder, ContextTypes,
    MessageHandler, CommandHandler, CallbackQueryHandler, filters,
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

SHEET_NAME = "Contabilitate PFA 2025"
CREDENTIALS_FILE = "credentials.json"
DASHBOARD_URL = "https://bot-contabil-pfa.onrender.com/dashboard"

# === BUTOANE MENIU PRINCIPAL ===
BTN_RAPORT = "📊 Raport"
BTN_REGISTRU = "📂 Registru"
BTN_DASHBOARD = "🖥️ Dashboard"
BTN_CALENDAR = "📋 Calendar Fiscal"
BTN_SETARI = "⚙️ Setări"
BTN_AJUTOR = "🆘 Ajutor"

MAIN_MENU_BUTTONS = {
    BTN_RAPORT, BTN_REGISTRU, BTN_DASHBOARD,
    BTN_CALENDAR, BTN_SETARI, BTN_AJUTOR,
}

LUNI_SHORT = {
    1: "Ian", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Mai", 6: "Iun",
    7: "Iul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"
}
LUNI_LONG = {
    1: "Ianuarie", 2: "Februarie", 3: "Martie", 4: "Aprilie",
    5: "Mai", 6: "Iunie", 7: "Iulie", 8: "August",
    9: "Septembrie", 10: "Octombrie", 11: "Noiembrie", 12: "Decembrie"
}


# ============================================================
#                    KEYBOARD BUILDERS
# ============================================================

def build_main_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton(BTN_RAPORT), KeyboardButton(BTN_REGISTRU)],
        [
            KeyboardButton(BTN_DASHBOARD, web_app=WebAppInfo(url=DASHBOARD_URL)),
            KeyboardButton(BTN_CALENDAR),
        ],
        [KeyboardButton(BTN_SETARI), KeyboardButton(BTN_AJUTOR)],
    ], resize_keyboard=True, is_persistent=True)


def build_year_picker(action: str, years: List[int]):
    if not years:
        years = [datetime.now().year]
    rows = []
    for i in range(0, len(years), 3):
        row = [
            InlineKeyboardButton(
                str(y), callback_data=f"{action}|year|{y}"
            )
            for y in years[i:i+3]
        ]
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ Închide", callback_data="nav|close")])
    return InlineKeyboardMarkup(rows)


def build_month_picker(action: str, year: int, available_months: List[int] = None):
    rows = []
    for i in range(0, 12, 3):
        row = []
        for j in range(i, i + 3):
            month = j + 1
            if available_months is None or month in available_months:
                row.append(InlineKeyboardButton(
                    LUNI_SHORT[month],
                    callback_data=f"{action}|month|{year}|{month}"
                ))
            else:
                row.append(InlineKeyboardButton(
                    f"·{LUNI_SHORT[month]}·",
                    callback_data="nav|noop"
                ))
        rows.append(row)
    rows.append([
        InlineKeyboardButton("⬅️ Înapoi", callback_data=f"{action}|back"),
        InlineKeyboardButton("❌ Închide", callback_data="nav|close"),
    ])
    return InlineKeyboardMarkup(rows)


def build_registru_type_picker():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 Lunar", callback_data="registru|type|monthly"),
            InlineKeyboardButton("📆 Anual", callback_data="registru|type|annual"),
        ],
        [InlineKeyboardButton("❌ Închide", callback_data="nav|close")],
    ])


def build_settings_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Vezi profilul meu", callback_data="settings|profil")],
        [InlineKeyboardButton("🔔 Alerte fiscale", callback_data="settings|alerts")],
        [InlineKeyboardButton("⏰ Trimite reminder manual", callback_data="settings|reminder")],
        [InlineKeyboardButton("📥 Export CSV", callback_data="settings|export")],
        [InlineKeyboardButton("🗑️ Reset (șterge toate datele)", callback_data="settings|reset|ask")],
        [InlineKeyboardButton("❌ Închide", callback_data="nav|close")],
    ])


def build_alerts_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Verifică modificări acum", callback_data="alerts|run")],
        [InlineKeyboardButton("📋 Vezi istoric alerte", callback_data="alerts|history")],
        [InlineKeyboardButton("⬅️ Înapoi", callback_data="settings|menu")],
    ])


def build_reset_confirm():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ DA, șterge tot", callback_data="settings|reset|do"),
            InlineKeyboardButton("❌ Nu, anulează", callback_data="settings|menu"),
        ],
    ])


# ============================================================
#                    DB HELPERS
# ============================================================

def ensure_user(update: Update):
    try:
        tg_user = update.effective_user
        if tg_user is None:
            return None
        display_name = tg_user.full_name or tg_user.username or None
        session = get_session()
        try:
            existing = users_repo.get_by_telegram_id(session, telegram_id=tg_user.id)
            is_new = existing is None
            user = users_repo.get_or_create_by_telegram_id(
                session, telegram_id=tg_user.id, name=display_name
            )
            if is_new:
                audit_repo.write(
                    session, entity_type="user", entity_id=user.id,
                    action="create", user_id=user.id, source="user",
                    after={"telegram_id": user.telegram_id, "name": user.name},
                    note="auto-created from first Telegram message",
                )
            user_id = user.id
            session.commit()
            return user_id
        except Exception as e:
            session.rollback()
            logger.error(f"DB error in ensure_user: {e}")
            return None
        finally:
            session.close()
    except Exception as e:
        logger.error(f"Unexpected error in ensure_user: {e}")
        return None


def get_available_years(user_id: int) -> List[int]:
    session = get_session()
    try:
        from app.models import Transaction
        rows = (
            session.query(Transaction.period_year)
            .filter(
                Transaction.user_id == user_id,
                Transaction.locked == False,
            )
            .distinct()
            .all()
        )
        years = sorted(set(r[0] for r in rows if r[0]), reverse=True)
        if not years:
            years = [datetime.now().year]
        return years
    except Exception as e:
        logger.error(f"get_available_years error: {e}")
        return [datetime.now().year]
    finally:
        session.close()


def get_available_months(user_id: int, year: int) -> List[int]:
    session = get_session()
    try:
        from app.models import Transaction
        rows = (
            session.query(Transaction.period_month)
            .filter(
                Transaction.user_id == user_id,
                Transaction.period_year == year,
                Transaction.locked == False,
            )
            .distinct()
            .all()
        )
        months = sorted(set(r[0] for r in rows if r[0]))
        return months
    except Exception:
        return list(range(1, 13))
    finally:
        session.close()


def register_source_file(user_id, file_bytes, telegram_file_id, kind="photo", mime="image/jpeg"):
    sha = storage.compute_sha256(file_bytes)
    session = get_session()
    try:
        existing = source_files_repo.get_by_sha256(session, user_id, sha)
        if existing is not None:
            logger.info(f"Dedup HIT sha={sha[:8]}... sf_id={existing.id}")
            result = {
                "id": existing.id, "sha256": existing.sha256,
                "created_at": existing.created_at, "is_duplicate": True,
            }
            audit_repo.write(
                session, entity_type="source_file", entity_id=existing.id,
                action="dedup_hit", user_id=user_id, source="system",
                note=f"duplicate upload; original created at {existing.created_at.isoformat()}",
            )
            session.commit()
            return result
        ext = "jpg" if kind == "photo" else "bin"
        path = storage.save_bytes(file_bytes, sha, ext=ext)
        new_sf = source_files_repo.create(
            session, user_id=user_id, kind=kind, sha256=sha,
            telegram_file_id=telegram_file_id, mime=mime,
            bytes_size=len(file_bytes), storage_path=path,
        )
        audit_repo.write(
            session, entity_type="source_file", entity_id=new_sf.id,
            action="create", user_id=user_id, source="user",
            after={"kind": new_sf.kind, "sha256": new_sf.sha256,
                   "bytes_size": new_sf.bytes_size,
                   "storage_path": new_sf.storage_path},
        )
        result = {
            "id": new_sf.id, "sha256": new_sf.sha256,
            "created_at": new_sf.created_at, "is_duplicate": False,
        }
        session.commit()
        return result
    except Exception as e:
        session.rollback()
        logger.error(f"DB error in register_source_file: {e}")
        return None
    finally:
        session.close()


def persist_document(user_id, source_file_id, item, banca, raw_response, prompt_version):
    session = get_session()
    try:
        doc = documents_repo.create(
            session, user_id=user_id, source_file_id=source_file_id,
            data_doc=item.data, platforma=item.platforma, tip=item.tip,
            brut=item.brut, comision=item.comision, tva=item.tva,
            net=item.net, cash=item.cash, banca=banca,
            detalii=item.detalii or "",
            raw_json=raw_response[:10000] if raw_response else "",
            prompt_version=prompt_version, status="posted", confidence=1.0,
        )
        doc_id = doc.id
        audit_repo.write(
            session, entity_type="document", entity_id=doc_id,
            action="create", user_id=user_id, source="ai",
            after=documents_repo.to_dict(doc),
            note=f"posted via AI extraction (prompt={prompt_version})",
        )
        session.commit()
        return doc_id
    except Exception as e:
        session.rollback()
        logger.error(f"DB error in persist_document: {e}")
        return None
    finally:
        session.close()


def persist_transactions(user_id, doc_id, item, banca):
    session = get_session()
    try:
        tx_ids = posting.post_document(
            session, user_id=user_id, document_id=doc_id,
            tip=item.tip, platforma=item.platforma, detalii=item.detalii,
            brut=item.brut, comision=item.comision, tva=item.tva,
            net=item.net, cash=item.cash, banca=banca, data_doc=item.data,
        )
        session.commit()
        return tx_ids
    except Exception as e:
        session.rollback()
        logger.error(f"persist_transactions error: {e}")
        return []
    finally:
        session.close()


def sync_to_sheets(doc_id, row_data, date_str):
    session = get_session()
    try:
        tab_name = sheets.upsert_document(
            session, doc_id=doc_id, row_data=row_data,
            date_str=date_str, sheet_name=SHEET_NAME,
            credentials_file=CREDENTIALS_FILE,
        )
        session.commit()
        return tab_name
    except Exception as e:
        session.rollback()
        logger.error(f"sync_to_sheets failed for doc_id={doc_id}: {e}")
        return None
    finally:
        session.close()


def _tx_count_label(n: int) -> str:
    return "1 tranzacție" if n == 1 else f"{n} tranzacții"


# ============================================================
#                    GLOBAL ERROR HANDLER
# ============================================================

async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    tb_str = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    logger.error(f"Unhandled exception:\n{tb_str}")
    try:
        user_id = None
        if isinstance(update, Update) and update.effective_user:
            user_id = update.effective_user.id
        session = get_session()
        try:
            db_user_id = None
            if user_id:
                db_user = users_repo.get_by_telegram_id(session, telegram_id=user_id)
                db_user_id = db_user.id if db_user else None
            audit_repo.write(
                session, entity_type="system", entity_id=0,
                action="error", user_id=db_user_id, source="system",
                note=f"{type(error).__name__}: {str(error)[:400]}",
            )
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()
    except Exception as audit_err:
        logger.error(f"Failed to write error to audit: {audit_err}")
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ A apărut o eroare neașteptată.\nÎncearcă din nou."
            )
        except Exception:
            pass


# ============================================================
#                    /start, /ajutor, /profil, /reset_profil
# ============================================================

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start — verifică status onboarding:
    - Dacă user e onboarded → afișează meniul principal
    - Altfel → începe/continuă onboarding-ul
    """
    ensure_user(update)
    tg_id = update.effective_user.id

    if onboarding.user_is_onboarded(tg_id):
        name = update.effective_user.first_name or "șofer"
        await update.message.reply_text(
            f"👋 Bun venit înapoi, *{name}*!\n\n"
            f"Folosește meniul de mai jos pentru navigare rapidă.\n\n"
            f"📸 *Cum încarci documente:*\n"
            f"• Trimite poze cu bonuri/facturi → procesate automat\n"
            f"• Sau text: `bon 05.04.2026 Lukoil 300 lei motorina`",
            parse_mode="Markdown",
            reply_markup=build_main_menu(),
        )
    else:
        await onboarding.start_onboarding(update, context)


async def handle_ajutor_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_ajutor(update.effective_chat.id, context)


async def send_ajutor(chat_id, context):
    msg = (
        "🆘 *Ghid de utilizare*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📸 *Încărcare documente*\n"
        "• Poză bon/factură → AI extrage automat\n"
        "• Screenshot raport Bolt → înregistrare lunară\n\n"
        "✍️ *Format text*\n"
        "• `bon 05.04.2026 Lukoil 300 lei motorina`\n"
        "• `cheltuiala 15.03.2026 service auto 800 lei`\n"
        "• `venit bolt aprilie: net 1878 lei, cash 1081 lei`\n\n"
        "📋 *Meniul principal*\n"
        "• 📊 *Raport* — sumar lunar cu profit\n"
        "• 📂 *Registru* — Excel pentru bancă/ANAF\n"
        "• 🖥️ *Dashboard* — interfață vizuală\n"
        "• 📋 *Calendar* — termene fiscale\n"
        "• ⚙️ *Setări* — alerte, profil, export, reset\n\n"
        "💬 *Comenzi text*\n"
        "• `/start` — meniul principal\n"
        "• `/profil` — vezi profilul tău\n"
        "• `/reset_profil` — refă onboarding\n"
        "• `/delete <ID>` — șterge un document"
    )
    await context.bot.send_message(
        chat_id=chat_id, text=msg, parse_mode="Markdown",
        reply_markup=build_main_menu(),
    )


async def handle_profil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/profil — afișează profilul curent al utilizatorului."""
    user_id = ensure_user(update)
    if not user_id:
        await update.message.reply_text("⚠️ Eroare identificare utilizator.")
        return

    session = get_session()
    try:
        profile = users_repo.get_profile_dict(session, user_id) or {}
    finally:
        session.close()

    forma_label = onboarding.FORME_BY_CODE.get(
        profile.get("firma_forma_juridica") or "", {}
    ).get("label", "—")
    activitate_label = onboarding.ACTIVITIES_BY_CODE.get(
        profile.get("activity_code") or "", {}
    ).get("label", "—")
    regim_tva = profile.get("regim_tva")
    regim_tva_label = (
        "Plătitor (21%)" if regim_tva == "PLATITOR_21"
        else "Neplătitor" if regim_tva == "NEPLATITOR"
        else "—"
    )
    regim_imp_label = onboarding.regim_impunere_label(profile.get("regim_impunere") or "")
    onb_status = "✅ Completat" if profile.get("onboarding_completed") else "⏳ Incomplet"

    msg = (
        "*👤 Profilul tău*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 *Nume:* {profile.get('name') or '—'}\n"
        f"🏢 *Firmă:* {profile.get('firma_nume') or '—'}\n"
        f"📋 *CUI:* `{profile.get('firma_cui') or '—'}`\n"
        f"🧾 *Formă juridică:* {forma_label}\n"
        f"🏷️ *CAEN:* `{profile.get('caen_principal') or '—'}`\n"
        f"📊 *Activitate:* {activitate_label}\n"
        f"💰 *Regim TVA:* {regim_tva_label}\n"
        f"📈 *Regim impunere:* {regim_imp_label}\n"
        f"📍 *Județ:* {profile.get('judet') or '—'}\n"
        f"🏘️ *Localitate:* {profile.get('localitate') or '—'}\n\n"
        f"*Status onboarding:* {onb_status}\n\n"
        f"_Pentru editare folosește_ `/reset_profil`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def handle_reset_profil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/reset_profil — relansează onboarding-ul (pentru editare profil)."""
    ensure_user(update)
    tg_id = update.effective_user.id

    session = get_session()
    try:
        user = users_repo.get_by_telegram_id(session, telegram_id=tg_id)
        if not user:
            await update.message.reply_text("⚠️ Utilizator inexistent.")
            return
        users_repo.reset_onboarding(session, user)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"reset_profil error: {e}")
        await update.message.reply_text("❌ Eroare la reset profil.")
        return
    finally:
        session.close()

    await update.message.reply_text(
        "🔄 *Reluăm configurarea profilului...*\n\n"
        "_Datele existente vor fi suprascrise pe măsură ce completezi din nou._",
        parse_mode="Markdown",
    )
    await onboarding.start_onboarding(update, context)


# ============================================================
#                    MENU BUTTON HANDLERS
# ============================================================

async def handle_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = ensure_user(update)
    if not user_id:
        await update.message.reply_text("⚠️ Eroare identificare utilizator.")
        return

    if text == BTN_RAPORT:
        years = get_available_years(user_id)
        if not years or (len(years) == 1 and not get_available_months(user_id, years[0])):
            await update.message.reply_text(
                "📭 Nu ai tranzacții încă.\n"
                "Trimite poze sau text cu bonuri pentru a începe.",
                reply_markup=build_main_menu(),
            )
            return
        await update.message.reply_text(
            "📊 *Raport Fiscal*\nAlege anul:",
            parse_mode="Markdown",
            reply_markup=build_year_picker("report", years),
        )
    elif text == BTN_REGISTRU:
        await update.message.reply_text(
            "📂 *Registru de Încasări și Plăți*\n"
            "Excel formatat pentru bancă și ANAF.\n\nAlege tipul:",
            parse_mode="Markdown",
            reply_markup=build_registru_type_picker(),
        )
    elif text == BTN_CALENDAR:
        years = [datetime.now().year, datetime.now().year - 1, datetime.now().year + 1]
        years = sorted(set(years), reverse=True)
        await update.message.reply_text(
            "📋 *Calendar Fiscal ANAF*\nAlege anul:",
            parse_mode="Markdown",
            reply_markup=build_year_picker("fiscal", years),
        )
    elif text == BTN_SETARI:
        await update.message.reply_text(
            "⚙️ *Setări*",
            parse_mode="Markdown",
            reply_markup=build_settings_menu(),
        )
    elif text == BTN_AJUTOR:
        await send_ajutor(update.effective_chat.id, context)


# ============================================================
#                    CALLBACK QUERY HANDLER (router)
# ============================================================

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = ensure_user(update)
    if not user_id:
        await query.edit_message_text("⚠️ Eroare identificare utilizator.")
        return

    data = query.data
    parts = data.split("|")
    namespace = parts[0]

    # === ONBOARDING ===
    if namespace == "onb":
        await onboarding.handle_onboarding_callback(update, context, parts)
        return

    try:
        if namespace == "nav":
            if parts[1] == "close":
                await query.edit_message_text("✅ Meniu închis.")
            elif parts[1] == "noop":
                pass
            return

        if namespace == "report":
            if parts[1] == "year":
                year = int(parts[2])
                months = get_available_months(user_id, year)
                await query.edit_message_text(
                    f"📊 *Raport {year}*\nAlege luna:",
                    parse_mode="Markdown",
                    reply_markup=build_month_picker("report", year, months),
                )
            elif parts[1] == "month":
                year = int(parts[2])
                month = int(parts[3])
                await execute_raport(query, context, user_id, year, month)
            elif parts[1] == "back":
                years = get_available_years(user_id)
                await query.edit_message_text(
                    "📊 *Raport Fiscal*\nAlege anul:",
                    parse_mode="Markdown",
                    reply_markup=build_year_picker("report", years),
                )
            return

        if namespace == "registru":
            if parts[1] == "type":
                kind = parts[2]
                years = get_available_years(user_id)
                if kind == "annual":
                    await query.edit_message_text(
                        "📆 *Registru ANUAL*\nAlege anul:",
                        parse_mode="Markdown",
                        reply_markup=build_year_picker("registru_annual", years),
                    )
                elif kind == "monthly":
                    await query.edit_message_text(
                        "📅 *Registru LUNAR*\nAlege anul:",
                        parse_mode="Markdown",
                        reply_markup=build_year_picker("registru_monthly", years),
                    )
            return

        if namespace == "registru_annual":
            if parts[1] == "year":
                year = int(parts[2])
                await execute_registru(query, context, user_id, year, month=None)
            return

        if namespace == "registru_monthly":
            if parts[1] == "year":
                year = int(parts[2])
                months = get_available_months(user_id, year)
                await query.edit_message_text(
                    f"📅 *Registru LUNAR {year}*\nAlege luna:",
                    parse_mode="Markdown",
                    reply_markup=build_month_picker("registru_monthly", year, months),
                )
            elif parts[1] == "month":
                year = int(parts[2])
                month = int(parts[3])
                await execute_registru(query, context, user_id, year, month=month)
            elif parts[1] == "back":
                years = get_available_years(user_id)
                await query.edit_message_text(
                    "📅 *Registru LUNAR*\nAlege anul:",
                    parse_mode="Markdown",
                    reply_markup=build_year_picker("registru_monthly", years),
                )
            return

        if namespace == "fiscal":
            if parts[1] == "year":
                year = int(parts[2])
                await query.edit_message_text(
                    f"📋 *Calendar Fiscal {year}*\nAlege luna:",
                    parse_mode="Markdown",
                    reply_markup=build_month_picker("fiscal", year),
                )
            elif parts[1] == "month":
                year = int(parts[2])
                month = int(parts[3])
                await execute_fiscal(query, context, user_id, year, month)
            elif parts[1] == "back":
                years = [datetime.now().year, datetime.now().year - 1, datetime.now().year + 1]
                years = sorted(set(years), reverse=True)
                await query.edit_message_text(
                    "📋 *Calendar Fiscal*\nAlege anul:",
                    parse_mode="Markdown",
                    reply_markup=build_year_picker("fiscal", years),
                )
            return

        if namespace == "settings":
            if parts[1] == "menu":
                await query.edit_message_text(
                    "⚙️ *Setări*",
                    parse_mode="Markdown",
                    reply_markup=build_settings_menu(),
                )
            elif parts[1] == "profil":
                await execute_show_profil(query, context, user_id)
            elif parts[1] == "alerts":
                await query.edit_message_text(
                    "🔔 *Alerte fiscale*\n\n"
                    "Monitorizare automată ANAF/Monitorul Oficial pentru "
                    "modificări legislative.",
                    parse_mode="Markdown",
                    reply_markup=build_alerts_menu(),
                )
            elif parts[1] == "reminder":
                await execute_reminder(query, context)
            elif parts[1] == "export":
                years = get_available_years(user_id)
                await query.edit_message_text(
                    "📥 *Export CSV*\nAlege anul:",
                    parse_mode="Markdown",
                    reply_markup=build_year_picker("export", years),
                )
            elif parts[1] == "reset":
                if parts[2] == "ask":
                    await query.edit_message_text(
                        "⚠️ *Atenție — Operațiune ireversibilă!*\n\n"
                        "Vor fi șterse:\n"
                        "• Toate documentele\n"
                        "• Toate tranzacțiile\n"
                        "• Toate fișierele sursă\n"
                        "• Toate rapoartele salvate\n\n"
                        "Profilul firmei NU va fi șters.\n"
                        "Google Sheets NU va fi modificat.",
                        parse_mode="Markdown",
                        reply_markup=build_reset_confirm(),
                    )
                elif parts[2] == "do":
                    await execute_reset(query, context, user_id)
            return

        if namespace == "alerts":
            if parts[1] == "run":
                await execute_alerts_run(query, context, user_id)
            elif parts[1] == "history":
                await execute_alerts_history(query, context, user_id)
            return

        if namespace == "export":
            if parts[1] == "year":
                year = int(parts[2])
                months = get_available_months(user_id, year)
                await query.edit_message_text(
                    f"📥 *Export CSV {year}*\nAlege luna:",
                    parse_mode="Markdown",
                    reply_markup=build_month_picker("export", year, months),
                )
            elif parts[1] == "month":
                year = int(parts[2])
                month = int(parts[3])
                await execute_export(query, context, user_id, year, month)
            elif parts[1] == "back":
                await query.edit_message_text(
                    "⚙️ *Setări*",
                    parse_mode="Markdown",
                    reply_markup=build_settings_menu(),
                )
            return

    except Exception as e:
        logger.error(f"Callback handler error data={data}: {e}")
        try:
            await query.edit_message_text(f"❌ Eroare: {str(e)[:200]}")
        except Exception:
            pass


# ============================================================
#                    EXECUTORS
# ============================================================

async def execute_show_profil(query, context, user_id):
    session = get_session()
    try:
        profile = users_repo.get_profile_dict(session, user_id) or {}
    finally:
        session.close()

    forma_label = onboarding.FORME_BY_CODE.get(
        profile.get("firma_forma_juridica") or "", {}
    ).get("label", "—")
    activitate_label = onboarding.ACTIVITIES_BY_CODE.get(
        profile.get("activity_code") or "", {}
    ).get("label", "—")
    regim_tva = profile.get("regim_tva")
    regim_tva_label = (
        "Plătitor (21%)" if regim_tva == "PLATITOR_21"
        else "Neplătitor" if regim_tva == "NEPLATITOR"
        else "—"
    )
    regim_imp_label = onboarding.regim_impunere_label(profile.get("regim_impunere") or "")

    msg = (
        "*👤 Profilul tău*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 *Nume:* {profile.get('name') or '—'}\n"
        f"🏢 *Firmă:* {profile.get('firma_nume') or '—'}\n"
        f"📋 *CUI:* `{profile.get('firma_cui') or '—'}`\n"
        f"🧾 *Formă:* {forma_label}\n"
        f"🏷️ *CAEN:* `{profile.get('caen_principal') or '—'}`\n"
        f"📊 *Activitate:* {activitate_label}\n"
        f"💰 *Regim TVA:* {regim_tva_label}\n"
        f"📈 *Regim impunere:* {regim_imp_label}\n"
        f"📍 *Județ:* {profile.get('judet') or '—'}\n"
        f"🏘️ *Localitate:* {profile.get('localitate') or '—'}\n\n"
        f"_Pentru editare:_ `/reset_profil`"
    )
    await query.edit_message_text(msg, parse_mode="Markdown")


async def execute_raport(query, context, user_id, year, month):
    await query.edit_message_text(
        f"🔄 Calculez raportul {LUNI_LONG[month]} {year}...",
    )
    session = get_session()
    try:
        totals = tax_engine.compute_period(
            session, user_id=user_id, year=year, month=month
        )
        if totals["tx_count"] == 0:
            await query.edit_message_text(
                f"📭 Nu am găsit tranzacții pentru {LUNI_LONG[month]} {year}."
            )
            return
        tp = tax_periods_repo.get_or_create(
            session, user_id=user_id, year=year, month=month
        )
        tax_periods_repo.save_totals(session, tp, totals)
        session.commit()
        msg = tax_engine.format_report_message(totals)
        await query.edit_message_text(msg, parse_mode="Markdown")
    except Exception as e:
        session.rollback()
        logger.error(f"execute_raport error: {e}")
        await query.edit_message_text("❌ Eroare la calculul raportului.")
    finally:
        session.close()


async def execute_registru(query, context, user_id, year, month=None):
    period_label = (
        f"{LUNI_LONG[month]} {year}" if month else f"anul {year}"
    )
    await query.edit_message_text(
        f"🔄 Generez Registrul de Încasări și Plăți pentru {period_label}...\n"
        f"_(Excel formatat, gata de tipărit)_",
        parse_mode="Markdown",
    )

    session = get_session()
    try:
        profile = users_repo.get_profile_dict(session, user_id) or {}
        pfa_name = profile.get("firma_nume") or "PFA"
        pfa_cui = profile.get("firma_cui") or ""

        from app.models import Transaction as TxModel
        q = session.query(TxModel).filter(
            TxModel.user_id == user_id,
            TxModel.period_year == year,
            TxModel.locked == False,
        )
        if month:
            q = q.filter(TxModel.period_month == month)
        txs = q.order_by(TxModel.occurred_on).all()

        if not txs:
            await query.edit_message_text(
                f"📭 Nu am găsit tranzacții pentru {period_label}."
            )
            return

        xlsx_bytes = generate_registru_xlsx(
            txs, year, pfa_name=pfa_name, pfa_cui=pfa_cui, month=month,
        )
        fname = filename_registru(year, month=month)

        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=_io.BytesIO(xlsx_bytes),
            filename=fname,
            caption=(
                f"📊 *Registru Încasări și Plăți — {period_label}*\n\n"
                f"✅ Format Excel — bancă și ANAF\n"
                f"🖨️ Tipărește: File → Print → Landscape A4\n\n"
                f"_Verificați cu contabilul înainte de depunere._"
            ),
            parse_mode="Markdown",
        )
        await query.edit_message_text(f"✅ Registru generat pentru {period_label}.")
    except Exception as e:
        session.rollback()
        logger.error(f"execute_registru error: {e}")
        await query.edit_message_text("❌ Eroare la generarea registrului.")
    finally:
        session.close()


async def execute_export(query, context, user_id, year, month):
    period_label = f"{LUNI_LONG[month]} {year}"
    await query.edit_message_text(f"🔄 Generez CSV pentru {period_label}...")

    session = get_session()
    try:
        txs = tx_repo.list_for_period(session, user_id=user_id, year=year, month=month)
        if not txs:
            await query.edit_message_text(
                f"📭 Nu am găsit tranzacții pentru {period_label}."
            )
            return
        totals = tax_engine.compute_period(session, user_id=user_id, year=year, month=month)
        csv_tx = csv_export.generate_transactions_csv(txs, year, month)
        csv_rez = csv_export.generate_rezumat_csv(totals)
        fname_tx = csv_export.filename_transactions(year, month)
        fname_rez = csv_export.filename_rezumat(year, month)

        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=_io.BytesIO(csv_tx), filename=fname_tx,
            caption=f"📊 Tranzacții {period_label}",
        )
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=_io.BytesIO(csv_rez), filename=fname_rez,
            caption=f"📋 Rezumat fiscal {period_label}",
        )
        session.commit()
        await query.edit_message_text(f"✅ Export CSV generat pentru {period_label}.")
    except Exception as e:
        session.rollback()
        logger.error(f"execute_export error: {e}")
        await query.edit_message_text("❌ Eroare la export.")
    finally:
        session.close()


async def execute_fiscal(query, context, user_id, year, month):
    session = get_session()
    try:
        from app.models import Transaction
        has_bolt = (
            session.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.period_year == year,
                Transaction.period_month == month,
                Transaction.vat_treatment == "REVERSE_CHARGE",
                Transaction.tx_type == "EXPENSE",
            )
            .count()
        ) > 0
    except Exception:
        has_bolt = False
    finally:
        session.close()

    msg = fiscal_calendar.format_fiscal_message(year, month, has_bolt_invoice=has_bolt)
    await query.edit_message_text(msg, parse_mode="Markdown")


async def execute_reminder(query, context):
    await query.edit_message_text("🔄 Trimit reminder...")
    try:
        sched_service.check_and_remind(settings.telegram_token)
        await query.edit_message_text("✅ Reminder trimis. Verifică mesajele.")
    except Exception as e:
        logger.error(f"reminder error: {e}")
        await query.edit_message_text("❌ Eroare la trimitere reminder.")


async def execute_alerts_run(query, context, user_id):
    await query.edit_message_text(
        "🔄 Rulez monitorizarea fiscală...\n"
        "_(30-60 secunde, caut pe ANAF.ro și Monitorul Oficial)_",
        parse_mode="Markdown",
    )
    try:
        now = datetime.now()
        result = fiscal_mon.run_fiscal_research(now.year, now.month)

        session = get_session()
        try:
            from app.models import FiscalAlert
            alert = FiscalAlert(
                user_id=user_id, research_year=now.year, research_month=now.month,
                title=result.get("title", "Research manual"),
                summary=result.get("summary", ""),
                full_response=result.get("raw_response", "")[:5000],
                sources_json=[
                    {"url": c.get("source_url", ""), "name": c.get("source_name", "")}
                    for c in result.get("changes", []) if c.get("source_url")
                ],
                urgency=result.get("urgency", "none"),
                has_changes=result.get("has_changes", False),
                seen=True,
            )
            session.add(alert)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Error saving fiscal alert: {e}")
        finally:
            session.close()

        msg = fiscal_mon.format_alert_telegram(result)
        if msg:
            await query.edit_message_text(msg, parse_mode="Markdown")
        else:
            await query.edit_message_text(
                "✅ *Monitorizare finalizată*\n\n"
                "Nu am găsit modificări legislative relevante pentru luna curentă.\n\n"
                "_Surse: ANAF.ro, Monitorul Oficial, legislatie.just.ro_",
                parse_mode="Markdown",
            )
    except Exception as e:
        logger.error(f"alerts run error: {e}")
        await query.edit_message_text("❌ Eroare la monitorizare.")


async def execute_alerts_history(query, context, user_id):
    session = get_session()
    try:
        from app.models import FiscalAlert
        alerts = (
            session.query(FiscalAlert)
            .filter(FiscalAlert.user_id == user_id)
            .order_by(FiscalAlert.created_at.desc())
            .limit(5)
            .all()
        )
        if not alerts:
            await query.edit_message_text(
                "📭 Nu există alerte fiscale înregistrate.\n\n"
                "Monitorizarea rulează automat în ziua 1 a fiecărei luni.",
            )
            return

        urgency_icon = {"critical": "🔴", "warning": "🟡", "info": "🟢", "none": "✅"}
        msg = "📋 *Istoric alerte fiscale:*\n\n"
        for a in alerts:
            icon = urgency_icon.get(a.urgency, "ℹ️")
            period = f"{LUNI_SHORT.get(a.research_month, '?')} {a.research_year}"
            status = "" if a.seen else " 🆕"
            msg += f"{icon} *{period}*{status} — {a.title}\n"
            msg += f"   _{a.summary[:100]}..._\n\n"
            a.seen = True
        session.commit()
        await query.edit_message_text(msg, parse_mode="Markdown")
    except Exception as e:
        session.rollback()
        logger.error(f"alerts history error: {e}")
        await query.edit_message_text("❌ Eroare la citirea istoricului.")
    finally:
        session.close()


async def execute_reset(query, context, user_id):
    await query.edit_message_text("🔄 Șterg toate datele tale...")
    session = get_session()
    try:
        from app.models import (
            Document, Transaction, SourceFile,
            TaxPeriod, ExportLog, FiscalAlert,
        )

        doc_ids = [
            row[0] for row in
            session.query(Document.id).filter(Document.user_id == user_id).all()
        ]
        if doc_ids:
            exp_logs = (
                session.query(ExportLog)
                .filter(ExportLog.document_id.in_(doc_ids))
                .all()
            )
            for el in exp_logs:
                session.delete(el)
            session.flush()

        tx_count = (
            session.query(Transaction)
            .filter(Transaction.user_id == user_id)
            .delete(synchronize_session=False)
        )
        session.flush()

        doc_count = (
            session.query(Document)
            .filter(Document.user_id == user_id)
            .delete(synchronize_session=False)
        )
        session.flush()

        sf_count = (
            session.query(SourceFile)
            .filter(SourceFile.user_id == user_id)
            .delete(synchronize_session=False)
        )
        session.flush()

        session.query(TaxPeriod).filter(
            TaxPeriod.user_id == user_id
        ).delete(synchronize_session=False)
        session.flush()

        session.query(FiscalAlert).filter(
            FiscalAlert.user_id == user_id
        ).delete(synchronize_session=False)
        session.flush()

        audit_repo.write(
            session, entity_type="user", entity_id=user_id,
            action="reset", user_id=user_id, source="user",
            note=f"full reset: {doc_count} docs, {tx_count} txs deleted",
        )
        session.commit()

        await query.edit_message_text(
            f"✅ *Date șterse cu succes.*\n\n"
            f"• {doc_count} documente eliminate\n"
            f"• {tx_count} tranzacții eliminate\n"
            f"• {sf_count} fișiere sursă eliminate\n\n"
            f"Profilul firmei e păstrat. Poți încărca documente de la zero.",
            parse_mode="Markdown",
        )
    except Exception as e:
        session.rollback()
        logger.error(f"execute_reset error: {e}")
        await query.edit_message_text(f"❌ Eroare la ștergere: {str(e)[:200]}")
    finally:
        session.close()


# ============================================================
#                    /delete și /anafdebug
# ============================================================

async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = ensure_user(update)
    if not user_id:
        await update.message.reply_text("⚠️ Eroare identificare utilizator.")
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "⚠️ Specifică ID-ul documentului.\nExemplu: /delete 5"
        )
        return

    try:
        doc_id = int(args[0])
    except ValueError:
        await update.message.reply_text("⚠️ ID invalid.")
        return

    session = get_session()
    try:
        doc = documents_repo.get_by_id(session, doc_id=doc_id, user_id=user_id)
        if doc is None:
            await update.message.reply_text(f"⚠️ Documentul #{doc_id} nu a fost găsit.")
            return
        if doc.status == "rejected":
            await update.message.reply_text(f"ℹ️ Documentul #{doc_id} este deja anulat.")
            return
        if doc.status == "exported":
            await update.message.reply_text(f"⚠️ Documentul #{doc_id} a fost deja exportat.")
            return

        before_snapshot = documents_repo.to_dict(doc)
        tx_count = tx_repo.delete_for_document(session, document_id=doc_id)
        documents_repo.set_status(session, doc, "rejected")

        audit_repo.write(
            session, entity_type="document", entity_id=doc_id,
            action="delete", user_id=user_id, source="user",
            before=before_snapshot, after={"status": "rejected"},
            note=f"deleted by user; {tx_count} transactions removed",
        )
        session.commit()

        details = f"{doc.platforma or '?'} · {doc.data_doc or '?'} · {doc.brut:.2f} RON"
        await update.message.reply_text(
            f"🗑️ Document #{doc_id} anulat.\n_{details}_\n\n"
            f"✅ {_tx_count_label(tx_count)} eliminate.",
            parse_mode="Markdown",
        )
    except Exception as e:
        session.rollback()
        logger.error(f"delete error: {e}")
        await update.message.reply_text("❌ Eroare la anularea documentului.")
    finally:
        session.close()


async def handle_anafdebug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test ANAF — îl păstrăm pentru debug. Va fi eliminat ulterior."""
    args = context.args or []
    cui = args[0] if args else "53067338"
    await update.message.reply_text(f"🔄 Caut CUI `{cui}` în ANAF...", parse_mode="Markdown")

    try:
        from app.integrations.anaf_lookup import lookup_cui, format_lookup_result
        result = lookup_cui(cui)
        msg = format_lookup_result(result)
        if result.get("found"):
            msg += "\n\n*🔧 Date detaliate (debug):*"
            msg += f"\n• Formă detectată: `{result.get('forma_juridica_detectata')}`"
            msg += f"\n• Plătitor TVA: `{result.get('is_platitor_tva')}`"
            msg += f"\n• Inactiv: `{result.get('is_inactiv')}`"
            msg += f"\n• Județ: `{result.get('judet')}`"
            msg += f"\n• Localitate: `{result.get('localitate')}`"
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"anafdebug error: {e}")
        await update.message.reply_text(
            f"❌ Eroare ANAF: `{str(e)[:300]}`", parse_mode="Markdown",
        )


# ============================================================
#                    PROCESARE INTRARI (poză/text)
# ============================================================

async def process_entry(
    update, context,
    text_input=None, image_bytes=None, source_file_id=None
):
    user_id = ensure_user(update)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🔄 Analizez documentul (TVA 21%)..."
    )
    extraction = ai_client.extract_document(
        user_input=text_input, image_bytes=image_bytes,
    )

    if not extraction["items"] and extraction["validation_errors"]:
        err_preview = "\n• ".join(extraction["validation_errors"][:3])
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"⚠️ Datele extrase nu sunt valide:\n• {err_preview}",
        )
        return

    if not extraction["items"]:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                "⚠️ Nu am putut citi datele.\n\n"
                "Pentru cheltuieli încearcă formatul text:\n"
                "`bon 05.04.2026 Lukoil 300 lei motorina`"
            ),
            parse_mode="Markdown",
        )
        return

    try:
        msg_confirm = "✅ *Salvat:*\n"
        for item in extraction["items"]:
            data_doc = item.data or datetime.now().strftime("%d.%m.%Y")
            tip = item.tip
            tva = item.tva
            banca = 0.0
            if tip == DocType.VENIT:
                banca = item.net - item.cash

            doc_id = None
            if user_id:
                doc_id = persist_document(
                    user_id=user_id, source_file_id=source_file_id,
                    item=item, banca=banca,
                    raw_response=extraction["raw_response"],
                    prompt_version=extraction["prompt_version"],
                )

            tx_ids = []
            if user_id and doc_id:
                tx_ids = persist_transactions(
                    user_id=user_id, doc_id=doc_id, item=item, banca=banca,
                )

            row = [
                data_doc, item.platforma or "", tip,
                item.brut, item.comision, tva,
                item.net, item.cash, banca, item.detalii or "",
            ]
            sheet_used = sync_to_sheets(
                doc_id=doc_id, row_data=row, date_str=data_doc
            ) if doc_id else None

            doc_tag = f" #{doc_id}" if doc_id else ""
            tx_tag = f" ({_tx_count_label(len(tx_ids))})" if tx_ids else ""

            if tip == DocType.FACTURA_COMISION:
                msg_confirm += (
                    f"📂 Dosar: {sheet_used}{doc_tag}{tx_tag}\n"
                    f"📄 *FACTURA {item.platforma}*\n"
                    f"📅 Data: {data_doc}\n"
                    f"💵 Baza: {item.comision} RON\n"
                    f"🏛️ *TVA (21%): {tva:.2f} RON* (D301)\n"
                )
            elif tip == DocType.CHELTUIALA:
                msg_confirm += (
                    f"📂 Dosar: {sheet_used}{doc_tag}{tx_tag}\n"
                    f"🛒 *{item.detalii}* ({item.brut} RON)\n"
                    f"   📅 Data: {data_doc}\n"
                )
            else:
                net_display = item.net if item.net > 0 else item.brut
                card_display = round(net_display - item.cash, 2)
                platforma_tag = f" {item.platforma}" if item.platforma else ""
                msg_confirm += (
                    f"📂 Dosar: {sheet_used}{doc_tag}{tx_tag}\n"
                    f"💰 *Venit net{platforma_tag}: {net_display:.2f} RON*\n"
                    f"   💳 Card: {card_display:.2f} RON\n"
                    f"   💵 Cash: {item.cash:.2f} RON\n"
                    f"   📅 Data: {data_doc}\n"
                )

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=msg_confirm,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Error processing items: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Eroare sistem: {str(e)}"
        )


# ============================================================
#                    HANDLERS PRINCIPALE
# ============================================================

async def handle_photo_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id

    if onboarding.user_is_in_onboarding(tg_id):
        await update.message.reply_text(
            "⚠️ Te rog termină mai întâi configurarea profilului.\n"
            "Folosește butoanele de mai sus, sau /start pentru a relua."
        )
        return

    tg_file = await update.message.photo[-1].get_file()
    file_bytes = bytes(await tg_file.download_as_bytearray())
    caption = update.message.caption
    user_id = ensure_user(update)
    source_file_id = None

    if user_id:
        sf_info = register_source_file(
            user_id=user_id, file_bytes=file_bytes,
            telegram_file_id=tg_file.file_id,
        )
        if sf_info:
            if sf_info["is_duplicate"]:
                session = get_session()
                try:
                    from app.models import Document
                    has_docs = (
                        session.query(Document)
                        .filter(
                            Document.source_file_id == sf_info["id"],
                            Document.status != "rejected",
                        )
                        .count()
                    ) > 0
                finally:
                    session.close()

                if has_docs:
                    created_at_str = sf_info["created_at"].strftime(
                        '%d.%m.%Y la %H:%M'
                    )
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=f"⚠️ Imagine deja înregistrată pe {created_at_str}.",
                    )
                    return
                else:
                    source_file_id = sf_info["id"]
            else:
                source_file_id = sf_info["id"]

    await process_entry(
        update, context,
        text_input=caption, image_bytes=file_bytes,
        source_file_id=source_file_id,
    )


async def handle_text_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    tg_id = update.effective_user.id

    # 1. Verificăm dacă user e în onboarding și așteaptă text
    if onboarding.user_is_in_onboarding(tg_id):
        handled = await onboarding.handle_onboarding_text(update, context)
        if handled:
            return

    # 2. Buton meniu principal?
    if text in MAIN_MENU_BUTTONS:
        await handle_menu_button(update, context, text)
        return

    # 3. Altfel — procesăm ca document
    await process_entry(update, context, text_input=text)


# ============================================================
#                    MAIN
# ============================================================

if __name__ == '__main__':
    try:
        init_db()
        logger.info("✅ DB init OK")
    except Exception as e:
        logger.error(f"❌ DB init FAILED: {e}")

    try:
        run_migrations()
    except Exception as e:
        logger.error(f"❌ Migrations FAILED: {e}")

    try:
        storage.ensure_storage_dir()
        logger.info("✅ Storage dir OK")
    except Exception as e:
        logger.error(f"❌ Storage dir FAILED: {e}")

    start_http_server()

    try:
        sched_service.start_scheduler(settings.telegram_token)
    except Exception as e:
        logger.error(f"❌ Scheduler FAILED: {e}")

    app_bot = ApplicationBuilder().token(settings.telegram_token).build()

    # Comenzi
    app_bot.add_handler(CommandHandler("start", handle_start))
    app_bot.add_handler(CommandHandler("ajutor", handle_ajutor_command))
    app_bot.add_handler(CommandHandler("profil", handle_profil))
    app_bot.add_handler(CommandHandler("reset_profil", handle_reset_profil))
    app_bot.add_handler(CommandHandler("delete", handle_delete))
    app_bot.add_handler(CommandHandler("anafdebug", handle_anafdebug))

    # Callback queries (router pentru toate butoanele inline)
    app_bot.add_handler(CallbackQueryHandler(handle_callback_query))

    # Mesaje
    app_bot.add_handler(MessageHandler(filters.PHOTO, handle_photo_wrapper))
    app_bot.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_wrapper)
    )

    app_bot.add_error_handler(handle_error)

    print("🤖 Bot Contabil v7 — Multi-Tenant + Onboarding ONLINE!")
    app_bot.run_polling()
