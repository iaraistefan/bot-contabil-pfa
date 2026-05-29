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
from app import monitoring  # Pas 13.1 - Sentry error tracking
from app.ai import client as ai_client
from app.ai import fiscal_monitor as fiscal_mon
from app.services import posting
from app.services import tax_engine
from app.services import scheduler as sched_service
from app.services import onboarding
from app.services import plata_fiscala  # Pas 11.4
from app.services import reminder_ui  # Pas 10.2
from app.services import vehicule  # Pas A.2
from app.services import foaie_parcurs  # Pas A.3
from app.services import combustibil  # Pas A+
from app.services import confirmare  # Pas R1 - confirmare date extrase
from app.ai.schemas import ExtractionItem
from app.activities import get_activity_for_user
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

DASHBOARD_URL = "https://bot-contabil-pfa.onrender.com/dashboard"

# === BUTOANE MENIU PRINCIPAL ===
BTN_RAPORT = "📊 Raport"
BTN_REGISTRU = "📂 Registru"
BTN_DASHBOARD = "🖥️ Dashboard"
BTN_CALENDAR = "📋 Calendar Fiscal"
BTN_PLATA = plata_fiscala.BTN_PLATA  # Pas 11.4: "💳 Plată Fiscală"
BTN_PARCURS = foaie_parcurs.BTN_PARCURS  # Pas A: "🛣️ Foaie parcurs"
BTN_SETARI = "⚙️ Setări"
BTN_AJUTOR = "🆘 Ajutor"

MAIN_MENU_BUTTONS = {
    BTN_RAPORT, BTN_REGISTRU, BTN_DASHBOARD,
    BTN_CALENDAR, BTN_PLATA, BTN_PARCURS, BTN_SETARI, BTN_AJUTOR,
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
            KeyboardButton(BTN_DASHBOARD),  # web_app mutat pe InlineKeyboardButton (init_data)
            KeyboardButton(BTN_CALENDAR),
        ],
        [KeyboardButton(BTN_PLATA), KeyboardButton(BTN_PARCURS)],  # Pas 11.4 + A
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
        [InlineKeyboardButton("🔔 Alerte fiscale (legislative)", callback_data="settings|alerts")],
        # Pas 10.2: Configurare reminder-uri obligații
        [InlineKeyboardButton(reminder_ui.BTN_LABEL, callback_data="reminder|menu")],
        # Pas A: Management vehicule
        [InlineKeyboardButton(vehicule.BTN_VEHICULE, callback_data="vehicul|menu")],
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
            # Pas 13.1 - context Sentry (ID-uri, fara date personale)
            monitoring.set_user_context(user_id=user_id, telegram_id=tg_user.id)
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
        # Pas R1.2: salvam numarul documentului direct pe obiect
        # (setat inainte de commit -> intra in INSERT/UPDATE).
        nr_doc = getattr(item, "numar_document", None)
        if nr_doc:
            doc.numar_document = str(nr_doc).strip()[:80]
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


def _tx_count_label(n: int) -> str:
    return "1 tranzacție" if n == 1 else f"{n} tranzacții"


def _resolve_expense_meta(activity, platforma, detalii):
    """Returneaza (icon, label, deductibility_pct, note) pentru o cheltuiala."""
    default_icon = "🛒"
    default_label = "Cheltuială"
    default_pct = 100
    default_note = ""

    if activity is None:
        return default_icon, default_label, default_pct, default_note

    text = f"{platforma or ''} {detalii or ''}".lower().strip()
    if not text:
        return default_icon, default_label, default_pct, default_note

    for cat in activity.expense_categories:
        if not cat.keywords:
            continue
        if any(kw.lower() in text for kw in cat.keywords):
            return (
                cat.icon or default_icon,
                cat.label or default_label,
                cat.get_effective_deductibility(),
                cat.deductibility_note or "",
            )

    other = activity.get_expense_category("other_expense")
    if other:
        return (
            other.icon or default_icon,
            other.label or default_label,
            other.get_effective_deductibility(),
            other.deductibility_note or "",
        )

    return default_icon, default_label, default_pct, default_note


# ============================================================
#                    GLOBAL ERROR HANDLER
# ============================================================

async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    tb_str = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    logger.error(f"Unhandled exception:\n{tb_str}")

    # Pas 13.1 - trimitem eroarea la Sentry cu context
    update_info = "n/a"
    try:
        if isinstance(update, Update):
            if update.effective_user:
                update_info = f"telegram_id={update.effective_user.id}"
            if update.callback_query:
                update_info += f" callback={update.callback_query.data}"
            elif update.effective_message and update.effective_message.text:
                update_info += f" text={update.effective_message.text[:80]}"
    except Exception:
        pass
    monitoring.capture_exception(error, update_info=update_info)

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
    """/start - verifica status onboarding."""
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
        "• 💳 *Plată Fiscală* — IBAN + sumă pre-calculate\n"
        "• 🛣️ *Foaie parcurs* — jurnal km auto\n"
        "• ⚙️ *Setări* — alerte, profil, mașini, export\n\n"
        "🚗 *Foaie de parcurs (comenzi text)*\n"
        "• `parcurs start 125430` — pornești tura\n"
        "• `parcurs stop 125680` — închizi tura\n"
        "• `parcurs 125430 125680` — tură completă\n"
        "• `parcurs` — vezi jurnalul lunii\n\n"
        "🔔 *Alerte automate (Setări)*\n"
        "• *Alerte fiscale* — modificări legislative ANAF\n"
        "• *Reminder-uri obligații* — termene proprii (D301, D100, etc.)\n\n"
        "💬 *Comenzi text*\n"
        "• `/start` — meniul principal\n"
        "• `/profil` — vezi profilul tău\n"
        "• `/reset_profil` — refă onboarding\n"
        "• `/plata_fiscala` — wizard plată ANAF\n"
        "• `/sterge_tura <ID>` — șterge o tură\n"
        "• `/status` — starea bot-ului\n"
        "• `/delete <ID>` — șterge un document"
    )
    await context.bot.send_message(
        chat_id=chat_id, text=msg, parse_mode="Markdown",
        reply_markup=build_main_menu(),
    )


async def handle_profil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/profil - afiseaza profilul curent."""
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
        else "Cod special intracom" if regim_tva == "SPECIAL_INTRACOM"
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
    """/reset_profil - relanseaza onboarding-ul."""
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


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pas 13.1 - /status: starea bot-ului (healthcheck rapid)."""
    user_id = ensure_user(update)

    # Verificam conexiunea DB
    db_ok = False
    doc_count = 0
    tx_count = 0
    try:
        session = get_session()
        try:
            from app.models import Document, Transaction
            if user_id:
                doc_count = (
                    session.query(Document)
                    .filter(Document.user_id == user_id,
                            Document.status != "rejected")
                    .count()
                )
                tx_count = (
                    session.query(Transaction)
                    .filter(Transaction.user_id == user_id)
                    .count()
                )
            db_ok = True
        finally:
            session.close()
    except Exception as e:
        logger.error(f"status DB check error: {e}")

    sentry_status = "✅ Activ" if monitoring.is_active() else "🔕 Inactiv"
    db_status = "✅ Conectat" if db_ok else "❌ Eroare"

    msg = (
        "🤖 *Status Bot Contabil*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚙️ Versiune: *v18* (Compliance + Alerts + Monitoring + Parcurs + Confirmare + Anti-duplicat pe nr. document)\n"
        f"🗄️ Bază de date: {db_status}\n"
        f"📡 Error tracking: {sentry_status}\n\n"
        f"📊 *Datele tale:*\n"
        f"• Documente: *{doc_count}*\n"
        f"• Tranzacții: *{tx_count}*\n\n"
        f"🕐 *Joburi automate:*\n"
        f"• Zilnic 08:00 — alerte obligații\n"
        f"• Luni 08:30 — dashboard conformitate\n"
        f"• Ziua 1 — monitorizare legislativă\n\n"
        f"_Sistemul funcționează normal._"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def handle_cont(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /cont - Diagnostic de izolare a datelor.

    Arata EXACT ce vede contul curent: ID intern, telegram_id, profil,
    si numarul de documente/tranzactii care apartin DOAR acestui cont.
    Folosit pentru a verifica ca doi utilizatori diferiti NU vad
    datele unul altuia.
    """
    user_id = ensure_user(update)
    tg_user = update.effective_user
    tg_id = tg_user.id if tg_user else "?"

    if not user_id:
        await update.message.reply_text("⚠️ Nu te pot identifica.")
        return

    session = get_session()
    try:
        from app.models import Document, Transaction, User
        from sqlalchemy import func

        profile = users_repo.get_profile_dict(session, user_id) or {}

        doc_count = (
            session.query(Document)
            .filter(Document.user_id == user_id,
                    Document.status != "rejected")
            .count()
        )
        tx_count = (
            session.query(Transaction)
            .filter(Transaction.user_id == user_id)
            .count()
        )
        venit_total = (
            session.query(func.coalesce(func.sum(Transaction.amount_brut), 0.0))
            .filter(
                Transaction.user_id == user_id,
                Transaction.tx_type == "INCOME",
            )
            .scalar()
        ) or 0.0

        total_users = session.query(User).count()

        firma = profile.get("firma_nume") or "—"
        cui = profile.get("firma_cui") or "—"
        activitate = profile.get("activity_code") or "—"
        nume = profile.get("name") or "—"
        onb = "✅ Da" if profile.get("onboarding_completed") else "❌ Nu"

        msg = (
            "🆔 *Contul tău*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Nume: {nume}\n"
            f"🔑 ID Telegram: `{tg_id}`\n"
            f"🗄️ ID intern bot: *#{user_id}*\n"
            f"📋 Onboarding complet: {onb}\n\n"
            f"🏢 *Firmă:*\n"
            f"• Denumire: {firma}\n"
            f"• CUI: {cui}\n"
            f"• Activitate: {activitate}\n\n"
            f"📂 *Datele TALE în bot:*\n"
            f"• Documente: *{doc_count}*\n"
            f"• Tranzacții: *{tx_count}*\n"
            f"• Venit total înregistrat: *{venit_total:.2f}* RON\n\n"
            f"👥 Utilizatori totali în sistem: {total_users}\n\n"
            f"_Fiecare cont vede DOAR datele lui. Dacă doi colegi "
            f"compară acest ecran, „ID intern bot” trebuie să difere, "
            f"iar fiecare vede doar propriile cifre._"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"handle_cont error: {e}")
        await update.message.reply_text("❌ Eroare la citirea contului.")
    finally:
        session.close()


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
    elif text == BTN_PLATA:
        await plata_fiscala.handle_menu_button(update, context)
    elif text == BTN_PARCURS:
        await foaie_parcurs.handle_menu_button(update, context)
    elif text == BTN_SETARI:
        await update.message.reply_text(
            "⚙️ *Setări*",
            parse_mode="Markdown",
            reply_markup=build_settings_menu(),
        )
    elif text == BTN_DASHBOARD:
        # Telegram NU injecteaza init_data pentru KeyboardButton cu web_app
        # (init_data e gol prin design Telegram). Trebuie deschis dintr-un
        # InlineKeyboardButton intr-un mesaj - acolo init_data e populat corect.
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "🖥️  Deschide Dashboard",
                web_app=WebAppInfo(url=DASHBOARD_URL),
            )
        ]])
        await update.message.reply_text(
            "🖥️ *Dashboard fiscal*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Apasa butonul de mai jos pentru a deschide dashboard-ul "
            "(carduri venituri si cheltuieli, grafice TVA, export CSV).",
            parse_mode="Markdown",
            reply_markup=markup,
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

    # Pas 13.1 - breadcrumb pentru Sentry
    monitoring.add_breadcrumb(f"callback: {data}", category="callback")

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
                    "🔔 *Alerte fiscale (legislative)*\n\n"
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
                        "Profilul firmei NU va fi șters.",
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

        # Pas 11.4: Plata Fiscala
        if namespace == "plata":
            await plata_fiscala.handle_callback(update, context, parts)
            return

        # Pas 10.2: Reminder UI (configurare alerte proactive)
        if namespace == "reminder":
            await reminder_ui.handle_callback(update, context, parts)
            return

        # Pas A.2: Management vehicule
        if namespace == "vehicul":
            await vehicule.handle_callback(update, context, parts)
            return

        # Pas A.3: Foaie de parcurs
        if namespace == "parcurs":
            await foaie_parcurs.handle_callback(update, context, parts)
            return

        # Pas R1: Confirmare date extrase de AI
        if namespace == "confirm":
            if len(parts) > 1 and parts[1] == "save":
                await execute_confirmed_save(update, context, user_id)
            else:
                await confirmare.handle_callback(update, context, parts)
            return

    except Exception as e:
        logger.error(f"Callback handler error data={data}: {e}")
        # Pas 13.1 - trimitem la Sentry
        monitoring.capture_exception(e, callback_data=data)
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
        else "Cod special intracom" if regim_tva == "SPECIAL_INTRACOM"
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

        # Pas A+ : sectiunea combustibil deductibil (mesaj separat)
        try:
            fuel_summary = combustibil.get_fuel_summary(user_id, year, month)
            fuel_msg = combustibil.format_fuel_section(fuel_summary)
            if fuel_msg:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=fuel_msg,
                    parse_mode="Markdown",
                )
        except Exception as fuel_err:
            logger.error(f"fuel section in raport error: {fuel_err}")
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
#                    /delete si /anafdebug
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
    """Test ANAF - debug."""
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
#                    PROCESARE INTRARI (poza/text)
# ============================================================

def find_duplicate_document(user_id, data_doc, brut, numar_document=None):
    """
    Pas R1.2: Cauta un document deja inregistrat care e duplicat.

    Strategie pe doua niveluri:
      1. PE NUMARUL DOCUMENTULUI (serie + nr) — match exact = DUPLICAT SIGUR.
         Doua bonuri reale nu pot avea acelasi numar de document.
      2. FALLBACK pe data + suma — cand numarul lipseste (bon vechi neclar).
         E doar POSIBIL duplicat (2 bonuri reale pot avea aceeasi suma/zi).

    Returneaza dict cu 'match_type' ("numar" | "data_suma") sau None.
    """
    session = get_session()
    try:
        from app.models import Document

        def _info(doc, match_type):
            created_str = ""
            try:
                created_str = doc.created_at.strftime("%d.%m.%Y")
            except Exception:
                pass
            return {
                "id": doc.id,
                "data_doc": doc.data_doc,
                "platforma": doc.platforma,
                "brut": doc.brut,
                "numar_document": doc.numar_document,
                "created_at_str": created_str,
                "match_type": match_type,
            }

        # --- Nivel 1: match exact pe numarul documentului ---
        nr = (numar_document or "").strip()
        if nr:
            doc = (
                session.query(Document)
                .filter(
                    Document.user_id == user_id,
                    Document.numar_document == nr,
                    Document.status != "rejected",
                )
                .first()
            )
            if doc:
                return _info(doc, "numar")

        # --- Nivel 2: fallback pe data + suma ---
        if data_doc and brut and brut > 0:
            candidates = (
                session.query(Document)
                .filter(
                    Document.user_id == user_id,
                    Document.data_doc == data_doc,
                    Document.status != "rejected",
                )
                .all()
            )
            for doc in candidates:
                if abs((doc.brut or 0) - (brut or 0)) < 0.01:
                    return _info(doc, "data_suma")

        return None
    except Exception as e:
        logger.error(f"find_duplicate_document error: {e}")
        return None
    finally:
        session.close()


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
        user_input=text_input,
        image_bytes=image_bytes,
        user_id=user_id,
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

    # === Pas R1.2: detectam duplicate (numarul documentului + fallback) ===
    duplicates = {}
    if user_id:
        for idx, it in enumerate(extraction["items"]):
            suma = it.brut
            if it.tip == DocType.FACTURA_COMISION:
                suma = it.comision
            elif it.tip == DocType.VENIT:
                suma = it.net
            dup = find_duplicate_document(
                user_id, it.data, suma,
                numar_document=getattr(it, "numar_document", None),
            )
            if dup:
                duplicates[idx] = dup

    # === Pas R1: NU mai salvam direct. Afisam confirmare. ===
    # Datele extrase devin "pending" in user_data. Salvarea efectiva
    # se face in execute_confirmed_save() doar dupa ce user-ul confirma.
    items_dicts = [it.model_dump() for it in extraction["items"]]
    confirmare.store_pending(
        context, items_dicts,
        source_file_id=source_file_id,
        raw_response=extraction["raw_response"],
        prompt_version=extraction["prompt_version"],
        duplicates=duplicates,
    )
    await confirmare.show_confirmation(update.effective_chat.id, context)


async def execute_confirmed_save(update, context, user_id):
    """
    Pas R1: Salveaza efectiv documentele DUPA ce user-ul a confirmat.
    Citeste datele 'pending' din user_data, le persista si afiseaza
    mesajul de confirmare cu deductibilitate.
    """
    query = update.callback_query
    chat_id = query.message.chat_id

    pending = confirmare.get_pending(context)
    if not pending:
        await query.edit_message_text(
            "⏳ Sesiunea de confirmare a expirat.\n"
            "Trimite documentul din nou."
        )
        return

    source_file_id = pending.get("source_file_id")
    raw_response = pending.get("raw_response", "")
    prompt_version = pending.get("prompt_version", "")

    # Reconstruim ExtractionItem din dict-urile validate
    try:
        items = [ExtractionItem(**d) for d in pending["items"]]
    except Exception as e:
        logger.error(f"execute_confirmed_save: rebuild items failed: {e}")
        await query.edit_message_text("❌ Eroare la citirea datelor confirmate.")
        confirmare.clear_pending(context)
        return

    activity = get_activity_for_user(user_id) if user_id else None

    try:
        await query.edit_message_text("💾 Salvez documentul...")

        msg_confirm = "✅ *Salvat:*\n"
        for item in items:
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
                    raw_response=raw_response,
                    prompt_version=prompt_version,
                )

            tx_ids = []
            if user_id and doc_id:
                tx_ids = persist_transactions(
                    user_id=user_id, doc_id=doc_id, item=item, banca=banca,
                )

            doc_tag = f" #{doc_id}" if doc_id else ""
            tx_tag = f" ({_tx_count_label(len(tx_ids))})" if tx_ids else ""

            try:
                d_obj = datetime.strptime(data_doc, "%d.%m.%Y")
                folder_label = f"{LUNI_LONG.get(d_obj.month, '?')} {d_obj.year}"
            except (ValueError, TypeError):
                folder_label = "—"

            if tip == DocType.FACTURA_COMISION:
                msg_confirm += (
                    f"📂 Dosar: {folder_label}{doc_tag}{tx_tag}\n"
                    f"📄 *FACTURA {item.platforma or 'comision'}*\n"
                    f"📅 Data: {data_doc}\n"
                    f"💵 Baza: {item.comision} RON\n"
                    f"🏛️ *TVA (21%): {tva:.2f} RON* (D301)\n"
                )
            elif tip == DocType.CHELTUIALA:
                cat_icon, cat_label, ded_pct, ded_note = _resolve_expense_meta(
                    activity, item.platforma, item.detalii
                )
                ded_amount = round(item.brut * ded_pct / 100.0, 2)

                lines = [
                    f"📂 Dosar: {folder_label}{doc_tag}{tx_tag}",
                    f"{cat_icon} *{item.detalii or cat_label}* — {item.brut:.2f} RON",
                    f"   📅 Data: {data_doc}",
                ]
                if ded_pct == 100:
                    lines.append(f"   💡 Deductibil: {ded_amount:.2f} RON (100%)")
                elif ded_pct == 0:
                    lines.append(f"   ⚠️ Nedeductibil fiscal (0%)")
                else:
                    lines.append(
                        f"   💡 Deductibil: {ded_amount:.2f} RON "
                        f"({ded_pct}% din {item.brut:.2f})"
                    )
                if ded_note:
                    note_short = ded_note if len(ded_note) <= 90 else ded_note[:87] + "..."
                    lines.append(f"   ℹ️ _{note_short}_")
                msg_confirm += "\n".join(lines) + "\n"
            else:
                net_display = item.net if item.net > 0 else item.brut
                card_display = round(net_display - item.cash, 2)
                platforma_tag = f" {item.platforma}" if item.platforma else ""
                income_icon = "💰"
                if activity and activity.income_categories:
                    income_icon = activity.income_categories[0].icon or "💰"
                msg_confirm += (
                    f"📂 Dosar: {folder_label}{doc_tag}{tx_tag}\n"
                    f"{income_icon} *Venit net{platforma_tag}: {net_display:.2f} RON*\n"
                    f"   💳 Card: {card_display:.2f} RON\n"
                    f"   💵 Cash: {item.cash:.2f} RON\n"
                    f"   📅 Data: {data_doc}\n"
                )

        confirmare.clear_pending(context)
        await context.bot.send_message(
            chat_id=chat_id,
            text=msg_confirm,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Error in execute_confirmed_save: {e}")
        monitoring.capture_exception(e, stage="execute_confirmed_save")
        confirmare.clear_pending(context)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Eroare la salvare: {str(e)}"
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

    if onboarding.user_is_in_onboarding(tg_id):
        handled = await onboarding.handle_onboarding_text(update, context)
        if handled:
            return

    # Butoanele de meniu au prioritate - anuleaza orice wizard activ
    if text in MAIN_MENU_BUTTONS:
        if vehicule.is_in_wizard(context):
            vehicule.cancel_wizard(context)
        if confirmare.is_editing(context):
            confirmare.cancel_edit(context)
        await handle_menu_button(update, context, text)
        return

    # Pas R1: Wizard editare camp (confirmare date extrase)
    if confirmare.is_editing(context):
        handled = await confirmare.handle_edit_text(update, context)
        if handled:
            return

    # Pas A.2: Wizard vehicule (adaugare/editare masina)
    if vehicule.is_in_wizard(context):
        handled = await vehicule.handle_wizard_text(update, context)
        if handled:
            return

    # Foaie parcurs v2: wizard cu butoane (asteapta numarul de km)
    if foaie_parcurs.is_in_wizard(context):
        handled = await foaie_parcurs.handle_wizard_text(update, context)
        if handled:
            return

    # Pas A.3: Comenzi foaie de parcurs (parcurs start/stop/...) - backup
    if foaie_parcurs.match_command(text):
        await foaie_parcurs.handle_command(update, context)
        return

    await process_entry(update, context, text_input=text)


# ============================================================
#                    MAIN
# ============================================================

if __name__ == '__main__':
    # Pas 13.1 - Sentry PRIMUL, ca sa capteze si erorile de pornire
    monitoring.init_sentry()

    try:
        init_db()
        logger.info("✅ DB init OK")
    except Exception as e:
        logger.error(f"❌ DB init FAILED: {e}")
        monitoring.capture_exception(e, stage="init_db")

    try:
        run_migrations()
    except Exception as e:
        logger.error(f"❌ Migrations FAILED: {e}")
        monitoring.capture_exception(e, stage="run_migrations")

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
        monitoring.capture_exception(e, stage="start_scheduler")

    app_bot = ApplicationBuilder().token(settings.telegram_token).build()

    # Comenzi
    app_bot.add_handler(CommandHandler("start", handle_start))
    app_bot.add_handler(CommandHandler("ajutor", handle_ajutor_command))
    app_bot.add_handler(CommandHandler("profil", handle_profil))
    app_bot.add_handler(CommandHandler("reset_profil", handle_reset_profil))
    app_bot.add_handler(CommandHandler("status", handle_status))  # Pas 13.1
    app_bot.add_handler(CommandHandler("cont", handle_cont))  # diagnostic izolare
    app_bot.add_handler(CommandHandler("delete", handle_delete))
    app_bot.add_handler(CommandHandler("anafdebug", handle_anafdebug))
    app_bot.add_handler(CommandHandler("plata_fiscala", plata_fiscala.handle_command))
    app_bot.add_handler(CommandHandler("sterge_tura", foaie_parcurs.handle_delete_command))  # Pas A.3

    # Callback queries (router pentru toate butoanele inline)
    app_bot.add_handler(CallbackQueryHandler(handle_callback_query))

    # Mesaje
    app_bot.add_handler(MessageHandler(filters.PHOTO, handle_photo_wrapper))
    app_bot.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_wrapper)
    )

    app_bot.add_error_handler(handle_error)

    print("🤖 Bot Contabil v18 — + Dashboard fix (InlineKeyboardButton) ONLINE (Pas 11 + 10 + 13 + A + B + R1 + R1.2)")
    app_bot.run_polling()
