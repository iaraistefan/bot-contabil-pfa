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
from app.services import bank_import_ui  # Felia 3 - UI postare cheltuieli extras
from app.services import bank_tax_ui  # Felia 5c-c - UI marcare taxe achitate
from app.services import banner_send  # Faza UI - trimitere bannere (wrapper comun)
from app.ro_dates import luna_ro  # Faza UI - luni RO pentru bannere (caption Raport)
from app.services import declaratie_unica_ui as du_ui  # Faza 1: Declaratia Unica
from app.services import ghid_ui  # sub-pas Ghid 2: ghid de obligații (Telegram)
from app.services import certificat  # Certificat rezidență Bolt (PDF comun + ghid)
from app.ai.schemas import ExtractionItem
from app.activities import get_activity_for_user
from app.integrations.imports.classify import (
    classify_bt,
    VENIT_BOLT, PLATA_TAXA, RETURNARE_TAXA,
    COMISION_BANCAR, CHELTUIALA_BUSINESS, DE_VERIFICAT,
)
from app.integrations.imports import bolt_reconcile  # Felia 4 - reconciliere prezenta Bolt
from app.integrations.exports import csv_export
from app.integrations.exports.registru import (
    generate_registru_xlsx, filename_registru, registru_totals
)
from app.integrations import bolt_sync  # Bolt API - venituri automate (/bolt)
from app.http.app import start_http_server
from app.domain import fiscal_calendar
from app.domain import declaratii_spv  # Faza 1.3: fisa completare D301 (PDF vechi)
from app.integrations.anaf import declaratii_service as decl_nou  # noile generatoare (XML + ghid)
from app.migrations import run_migrations
from app.migrare_coduri import ensure_coduri_fiscale_columns
import io as _io
import logging
import traceback
from datetime import datetime, date
from app.domain.tax_rules import cota_tva  # sursă unică cotă TVA pe dată (fiscal #1)
from typing import List
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup, WebAppInfo,
    BotCommand, MenuButtonCommands, MenuButtonWebApp,
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
BTN_DU = du_ui.BTN_DU  # Faza 1: "🧮 Declaratia Unica"
BTN_CHELTUIELI = "💸 Cheltuieli"  # Faza UI: ecran cheltuieli pe categorii + banner
BTN_SETARI = "⚙️ Setări"
BTN_AJUTOR = "🆘 Ajutor"
BTN_GHID = "📖 Ghid"  # sub-pas Ghid 2: ghid de obligații fiscale

MAIN_MENU_BUTTONS = {
    BTN_RAPORT, BTN_REGISTRU, BTN_DASHBOARD,
    BTN_CALENDAR, BTN_PLATA, BTN_PARCURS, BTN_DU, BTN_CHELTUIELI,
    BTN_SETARI, BTN_GHID, BTN_AJUTOR,
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
        [KeyboardButton(BTN_DU), KeyboardButton(BTN_CHELTUIELI)],  # Faza 1 + ecran cheltuieli
        [KeyboardButton(BTN_GHID), KeyboardButton(BTN_SETARI), KeyboardButton(BTN_AJUTOR)],
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
            InlineKeyboardButton("✅ Da, șterge tot", callback_data="settings|reset|do"),
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
        ext = {"photo": "jpg", "bank_statement": "pdf"}.get(kind, "bin")
        # Arhivare R2 (dacă e configurat): cheie user_<id>/<an>/<lună>/<sha>.<ext>
        # pe data upload-ului. R2 dezactivat -> fallback disk (neschimbat).
        path = storage.save_bytes(
            file_bytes, sha, ext=ext, user_id=user_id, dt=datetime.utcnow()
        )
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


def persist_document(session, user_id, source_file_id, item, banca, raw_response, prompt_version):
    """
    Crează documentul + audit ÎN SESIUNEA DATĂ. NU comite și NU înghite excepția
    — apelantul deține tranzacția (atomicitate per batch; coada-bugs #1).
    Întoarce doc_id (după flush, în aceeași tranzacție).
    """
    doc = documents_repo.create(
        session, user_id=user_id, source_file_id=source_file_id,
        data_doc=item.data, platforma=item.platforma, tip=item.tip,
        brut=item.brut, comision=item.comision, tva=item.tva,
        net=item.net, cash=item.cash, banca=banca,
        detalii=item.detalii or "",
        raw_json=raw_response[:10000] if raw_response else "",
        prompt_version=prompt_version, status="posted", confidence=1.0,
    )
    # Pas R1.2: salvam numarul documentului direct pe obiect.
    nr_doc = getattr(item, "numar_document", None)
    if nr_doc:
        doc.numar_document = str(nr_doc).strip()[:80]
    session.flush()  # populează doc.id în aceeași tranzacție (FĂRĂ commit)
    doc_id = doc.id
    audit_repo.write(
        session, entity_type="document", entity_id=doc_id,
        action="create", user_id=user_id, source="ai",
        after=documents_repo.to_dict(doc),
        note=f"posted via AI extraction (prompt={prompt_version})",
    )
    return doc_id


def persist_transactions(session, user_id, doc_id, item, banca):
    """
    Postează tranzacțiile ÎN SESIUNEA DATĂ. NU comite, NU înghite excepția
    (apelantul deține tranzacția; coada-bugs #1). Întoarce tx_ids.
    """
    return posting.post_document(
        session, user_id=user_id, document_id=doc_id,
        tip=item.tip, platforma=item.platforma, detalii=item.detalii,
        brut=item.brut, comision=item.comision, tva=item.tva,
        net=item.net, cash=item.cash, banca=banca, data_doc=item.data,
    )


def _persist_all_items(session, *, items, user_id, source_file_id,
                       raw_response, prompt_version):
    """
    Persistă TOȚI itemii ÎN ACEEAȘI sesiune (NU comite). Întoarce lista de
    (item, doc_id, tx_ids) pentru construirea mesajului DUPĂ commit.

    Apelantul face commit O SINGURĂ DATĂ (atomic) sau rollback la orice excepție
    → ori toți itemii intră, ori niciunul. coada-bugs #1.
    """
    results = []
    for item in items:
        banca = 0.0
        if item.tip == DocType.VENIT:
            banca = item.net - item.cash

        doc_id = None
        if user_id:
            doc_id = persist_document(
                session, user_id=user_id, source_file_id=source_file_id,
                item=item, banca=banca, raw_response=raw_response,
                prompt_version=prompt_version,
            )
        tx_ids = []
        if user_id and doc_id:
            tx_ids = persist_transactions(
                session, user_id=user_id, doc_id=doc_id, item=item, banca=banca,
            )
        results.append((item, doc_id, tx_ids))
    return results


def _build_confirm_message(results, activity) -> str:
    """
    Construiește mesajul „✅ Salvat" din (item, doc_id, tx_ids) — DUPĂ commit.
    Doar formatare (zero I/O): un eșec aici nu poate pierde date deja salvate.
    """
    msg_confirm = "✅ *Salvat:*\n"
    for item, doc_id, tx_ids in results:
        data_doc = item.data or datetime.now().strftime("%d.%m.%Y")
        tip = item.tip
        tva = item.tva
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
    return msg_confirm


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
        # Onboarding nou (wizard în dashboard, sub-pas A): user neonboarded → buton WebApp.
        # Dashboard-ul se auto-rutează la wizard via /api/v1/onboarding/status (routing prin
        # stare, nu URL). ensure_user a creat deja rândul. Fallback chat = /setup_text (sub-pas D).
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("🚀 Începe configurarea",
                                 web_app=WebAppInfo(url=DASHBOARD_URL))
        ]])
        await update.message.reply_text(
            "👋 *Bun venit la Contai!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Hai să-ți configurăm contul — apasă butonul de mai jos. Durează *sub un "
            "minut*: îți caut datele firmei automat în registrul ANAF (denumire, CAEN, TVA), "
            "tu doar confirmi.\n\n"
            "_Configurarea se face în Dashboard (mai clar decât în chat)._",
            parse_mode="Markdown",
            reply_markup=markup,
        )


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
        "• `/bolt <lună>` — venituri Bolt automat din API (ex: `/bolt 2026 4`)\n"
        "• `/sterge_tura <ID>` — șterge o tură\n"
        "• `/status` — starea bot-ului\n"
        "• `/delete <ID>` — șterge un document"
    )
    await context.bot.send_message(
        chat_id=chat_id, text=msg, parse_mode="Markdown",
        reply_markup=build_main_menu(),
    )


async def handle_certificat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/certificat — trimite ghidul de obținere + PDF-ul comun Bolt (dacă e încărcat).

    Document COMUN Bolt (același pentru toți), NU personalizat — onest. Sursă unică:
    app.services.certificat (text + nume fișier dinamic pe an).
    """
    chat_id = update.effective_chat.id
    an = certificat.current_year()
    text = (
        f"📄 *Certificat de rezidență fiscală Bolt {an}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{certificat.INTRO}\n\n{certificat.GHID_OBTINERE}"
    )
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    if certificat.exists(an):
        try:
            with open(certificat.file_path(an), "rb") as f:
                await context.bot.send_document(
                    chat_id=chat_id, document=f, filename=certificat.filename(an),
                    caption=(f"📎 Certificat Bolt {an} — document COMUN Bolt "
                             f"(Romania.pdf), nu personal. Verifică anul înainte de depunere."),
                )
        except Exception as e:
            logger.error(f"handle_certificat send_document error: {e}")


async def handle_bolt_conectare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/bolt_conectare — status conectare Bolt + link spre Setări web (#2-B).

    SECURITATE: conectarea (lipit Client ID + Secret) se face DOAR în Setări web —
    cheile NU se primesc în chat (ar rămâne în istoricul Telegram). Aici doar status + link.
    """
    user_id = ensure_user(update)
    if not user_id:
        await update.message.reply_text("⚠️ Nu te-am putut identifica. Deschide din nou din butonul bot-ului.")
        return
    session = get_session()
    try:
        profile = users_repo.get_profile_dict(session, user_id) or {}
    finally:
        session.close()
    connected = bool(profile.get("bolt_client_id") and profile.get("bolt_client_secret_enc"))
    if connected:
        dt = (profile.get("bolt_connected_at") or "")[:10]
        text = (
            f"✅ *Cont Bolt conectat*" + (f" (din {dt})" if dt else "") + "\n\n"
            "Sincronizăm automat cursele tale Bolt la închiderea zilei și îți propunem "
            "să le adaugi în Registru. Poți schimba cheile în *Dashboard → Setări*."
        )
    else:
        text = (
            "🔌 *Conectare cont Bolt (sync automat)*\n\n"
            "Ca să sincronizăm automat cursele, conectează-ți contul Bolt Fleet în "
            "*Dashboard → Setări → Conectare cont Bolt* (lipești Client ID + Secret, "
            "le generezi în fleets.bolt.eu → Settings → API).\n\n"
            "🔒 Din motive de securitate, conectarea se face DOAR în Dashboard (web), "
            "NU lipi cheile aici în chat — ar rămâne în istoricul conversației.\n\n"
            "🛟 *Nu poți conecta API-ul?* (ex. cont gestionat de altă flotă) — API-ul "
            "sincronizează automat, dar dacă nu-l poți folosi, introdu venitul *manual*: "
            "trimite-mi *screenshotul raportului Bolt* sau text "
            "(`venit bolt aprilie: net 1878, cash 1081`). Manual e alternativa pentru "
            "cine n-are acces API."
        )
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("🖥️ Deschide Dashboard", web_app=WebAppInfo(url=DASHBOARD_URL))
    ]])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)


async def handle_profil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/profil - afiseaza profilul curent."""
    user_id = ensure_user(update)
    if not user_id:
        await update.message.reply_text("⚠️ Nu te-am putut identifica. Deschide din nou din butonul bot-ului.")
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
        await update.message.reply_text("⚠️ N-am putut reseta profilul. Încearcă din nou.")
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
        "🤖 *Status Contai*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚙️ Versiune: *v30* (Compliance + Alerts + Monitoring + Parcurs + Confirmare + Anti-duplicat + Bolt API)\n"
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
        await update.message.reply_text("⚠️ N-am putut citi contul. Încearcă din nou.")
    finally:
        session.close()


# ============================================================
#                    MENU BUTTON HANDLERS
# ============================================================

async def handle_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = ensure_user(update)
    if not user_id:
        await update.message.reply_text("⚠️ Nu te-am putut identifica. Deschide din nou din butonul bot-ului.")
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
    elif text == BTN_DU:
        await du_ui.handle_menu_button(update, context)
    elif text == BTN_CHELTUIELI:
        await handle_cheltuieli_command(update, context)   # aceeași cale ca /cheltuieli
    elif text == BTN_GHID:
        await ghid_ui.handle_command(update, context)
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
        await query.edit_message_text("⚠️ Nu te-am putut identifica. Deschide din nou din butonul bot-ului.")
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

    # === CODURI FISCALE (Faza 1) ===
    if namespace == "coduri":
        await handle_coduri_callback(update, context, parts, user_id)
        return

    # === IMPORT EXTRAS — postare cheltuieli (Felia 3) ===
    if namespace == "bankpost":
        await bank_import_ui.handle_callback(update, context)
        return

    # === IMPORT EXTRAS — marcare taxe achitate (Felia 5c-c) ===
    if namespace == "banktax":
        await bank_tax_ui.handle_callback(update, context)
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
        if namespace == "ghid":
            await ghid_ui.handle_callback(update, context, parts)
            return

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

        # Faza 1.3: Fisa completare D301
        if namespace == "d301":
            year = int(parts[1])
            month = int(parts[2])
            await execute_fisa_d301(query, context, user_id, year, month)
            return

        # Faza 1: Fisa D390 (VIES) - perechea D301
        if namespace == "d390":
            year = int(parts[1])
            month = int(parts[2])
            await execute_fisa_d390(query, context, user_id, year, month)
            return

        # Faza 1: Fisa D100 (impozit nerezident - comision Bolt)
        if namespace == "d100":
            year = int(parts[1])
            month = int(parts[2])
            await execute_fisa_d100(query, context, user_id, year, month)
            return

        # Buton-poartă: ecran TVA & Declarații (banner + fisele D301/D390/D100)
        if namespace == "tvadecl":
            year = int(parts[1])
            month = int(parts[2])
            await execute_tva_declaratii(query, context, user_id, year, month)
            return

        # Faza 1: Declaratia Unica
        if namespace == "du":
            await du_ui.handle_callback(update, context, parts)
            return

        # Pas R1: Confirmare date extrase de AI
        if namespace == "confirm":
            if len(parts) > 1 and parts[1] == "save":
                await execute_confirmed_save(update, context, user_id)
            else:
                await confirmare.handle_callback(update, context, parts)
            return

    except Exception as e:
        logger.exception(f"Callback handler error data={data}")
        # Pas 13.1 - trimitem la Sentry
        monitoring.capture_exception(e, callback_data=data)
        try:
            await query.edit_message_text(
                "⚠️ N-am putut deschide asta. Încearcă din nou — dacă ține, apasă /start."
            )
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


def _deduct_label(pct) -> str:
    """Procent deductibilitate → label scurt: 50 → '50%' (fără zecimale)."""
    try:
        return f"{int(pct)}%"
    except (TypeError, ValueError):
        return "—"


def _cheltuieli_banner_data(totals, year, month):
    """Data dict `cheltuieli` — total/deductibil + TOP 3 categorii (expense_breakdown
    e deja sortat desc pe amount_brut). `deduct` din pct REAL. Pe lună goală:
    total 0 + categorii [] (render are gardă, nu crapă). Luni RO.
    """
    return {
        "total":      totals["expense_total_brut"],
        "deductibil": totals["expense_deductible_total"],
        "categories": [
            {"name": e["label"], "amount": e["amount_brut"],
             "deduct": _deduct_label(e["deductibility_pct"])}
            for e in totals.get("expense_breakdown", [])[:3]
        ],
        "period":   f"{luna_ro(month)} {year}",
        "subtitle": "Deductibilitate pe categorii",
    }


def _format_cheltuieli_text(totals, year, month) -> str:
    """Textul de sub banner: cheltuieli per-categorie + total + deductibil.
    `total`/`deductibil` = EXACT cifrele de pe banner (aceeași `compute_period`).
    """
    lines = [
        f"💸 *Cheltuieli — {luna_ro(month)} {year}*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    for e in totals["expense_breakdown"]:
        lines.append(
            f"{e['icon']} {e['label']}: `{e['amount_brut']:.2f} RON` "
            f"_({_deduct_label(e['deductibility_pct'])} deductibil)_"
        )
    lines.append("")
    lines.append(f"*Total cheltuieli: {totals['expense_total_brut']:.2f} RON*")
    lines.append(f"💡 *Din care deductibil: {totals['expense_deductible_total']:.2f} RON*")
    return "\n".join(lines)


async def handle_cheltuieli_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ecran Cheltuieli (cale-comandă) — buton 💸 Cheltuieli SAU /cheltuieli [lună].

    O singură cale (butonul deleagă aici). Luna implicită = curentă; `/cheltuieli 4`
    sau `/cheltuieli 2026 4` pentru altă perioadă. Banner hero + text dedesubt
    (reply_banner_or_text). Lună goală → banner total 0 + mesaj, fără crash.
    """
    user_id = ensure_user(update)
    if not user_id:
        await update.message.reply_text("⚠️ Nu te-am putut identifica. Deschide din nou din butonul bot-ului.")
        return

    now = datetime.now()
    year, month = now.year, now.month
    args = context.args or []
    try:
        if len(args) >= 2:
            year, month = int(args[0]), int(args[1])
        elif len(args) == 1:
            month = int(args[0])
    except ValueError:
        await update.message.reply_text("Foloseste: /cheltuieli 4 sau /cheltuieli 2026 4")
        return

    session = get_session()
    try:
        totals = tax_engine.compute_period(session, user_id=user_id, year=year, month=month)
    except Exception as e:
        logger.error(f"cheltuieli compute error {year}/{month} user={user_id}: {e}")
        await update.message.reply_text("⚠️ N-am putut calcula cheltuielile. Încearcă din nou.")
        return
    finally:
        session.close()

    # Gardă lună goală: niciun breakdown → banner total 0 + mesaj (nu listă goală).
    if not totals.get("expense_breakdown"):
        text = (
            f"💸 *Cheltuieli — {luna_ro(month)} {year}*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📭 Fără cheltuieli înregistrate în {luna_ro(month)} {year}."
        )
    else:
        text = _format_cheltuieli_text(totals, year, month)

    await banner_send.reply_banner_or_text(
        update.message, context,
        screen="cheltuieli", data=_cheltuieli_banner_data(totals, year, month),
        text=text,
        caption=f"💸 Cheltuieli · {luna_ro(month)} {year}",
    )


def _raport_banner_data(d212, year):
    """Data dict pentru banner-ul `raport` — orizont ANUAL YTD (vezi CONTRACT.md).

    Tot din `d212` (compute_d212_anual) → profit + taxe pe ACELAȘI orizont (anual),
    aritmetic consistent (`venit_net = venit_brut − cheltuieli`, garantat de motor).
    Bannerul DOAR afișează; plafoanele (salariu minim, TVA) sunt în motor, nu aici.
    """
    return {
        "period":     f"{year} · la zi",
        "profit":     d212.venit_net,       # hero — ANUAL YTD
        "venituri":   d212.venit_brut,      # ANUAL YTD brut
        "cheltuieli": d212.cheltuieli,      # ANUAL YTD deductibil → venituri−cheltuieli=profit
        "impozit":    d212.impozit,
        "cas":        d212.cas,
        "cass":       d212.cass,
        "total_taxe": d212.total_plata,     # cheia = total_taxe; valoarea din motor
        "taxe_label": "ESTIMARE D212 ANUALĂ · LA ZI",
    }


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
        # estimare fiscala anuala pe realizat YTD (sursa unica, ca dashboard-ul)
        d212 = tax_engine.compute_d212_anual(session, user_id=user_id, an=year)
        msg = tax_engine.format_report_message(totals, d212=d212)
        # Buton-poartă TVA & Declarații: pe lunile cu factură Bolt (vat_out>0),
        # deschide ecranul dedicat (banner render_declaratii + fisele D301/D390/D100).
        # Garda vat_out>0 e PĂSTRATĂ → lunile fără factură n-au butonul deloc.
        tva_d301 = totals.get("vat_out_total", 0) or 0
        rm = None
        if tva_d301 > 0:
            rm = InlineKeyboardMarkup([[InlineKeyboardButton(
                "🧾 TVA & Declarații",
                callback_data=f"tvadecl|{year}|{month}",
            )]])

        # Banner hero premium (estimare D212 anuală) + textul lunar dedesubt.
        # Wrapper comun: build → delete → foto → text, fallback 3 niveluri cu
        # logger.exception. Butoanele D301/D390/D100 rămân pe mesajul TEXT (jos).
        await banner_send.send_banner_or_text(
            query, context,
            screen="raport", data=_raport_banner_data(d212, year),
            text=msg, reply_markup=rm,
            caption=f"📊 Raport · {luna_ro(month)} {year}",
        )

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
        await query.edit_message_text("⚠️ N-am putut calcula raportul. Încearcă din nou.")
    finally:
        session.close()


async def execute_tva_declaratii(query, context, user_id, year, month):
    """Ecran TVA & Declarații (buton-poartă din Raport).

    Banner premium `render_declaratii` + fisele D301/D390/D100 ca reply_markup.
    SURSĂ UNICĂ: `compute_period(...).vat_out_total` — EXACT pragul folosit de
    `_trimite_declaratie_noua` (vat_out<=0 → 'nu se depune'). Deci 'De depus' pe
    banner ⇔ fisa chiar se generează la apăsare (coerență prag garantată, >0 vs <=0).
    `baza` și cota din payload (cota_tva pe dată), NU hardcodat 21%.

    vat_out==0 (cale defensivă; butonul-poartă oricum nu apare atunci): banner
    'Nimic de depus' FĂRĂ butoane — nu oferim fise care ar răspunde 'nu se depune'.
    """
    session = get_session()
    d100_plan = None
    try:
        totals = tax_engine.compute_period(
            session, user_id=user_id, year=year, month=month
        )
        # D100 split per-platformă (Uber sub-pas B): planul = sursă unică status +
        # defalcare. Aceeași folosită de fișă/web → coerență prag garantată.
        from app.domain.fiscal_profile import from_user_dict
        profile = users_repo.get_profile_dict(session, user_id) or {}
        cota_p = totals.get("cota_tva") or cota_tva(date(year, month, 1))
        d100_plan = tax_engine.compute_d100_plan(
            tax_engine.vat_out_by_brand(session, user_id=user_id, year=year, month=month),
            cota_p, from_user_dict(profile),
        )
    except Exception as e:
        logger.error(f"execute_tva_declaratii error: {e}")
        await query.edit_message_text("⚠️ N-am putut calcula TVA & Declarații. Încearcă din nou.")
        return
    finally:
        session.close()

    vat_out = totals.get("vat_out_total", 0) or 0
    cota = totals.get("cota_tva") or cota_tva(date(year, month, 1))  # sursă unică, fără 0.21
    tva_pct = round(cota * 100)

    if vat_out > 0:
        baza = vat_out / cota
        # format RO (oglindă fmt_ron din contai_banners; evită importul PIL în bot)
        baza_ro = f"{baza:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")

        # D100 — rând + buton + notă după PLANUL split per-platformă. D301/D390
        # depind doar de vat_out (neschimbate); doar D100 variază cu brand+cotă.
        rows = [
            {"code": "D301", "name": "Decont special TVA"},
            {"code": "D390", "name": "Declarație recapitulativă VIES"},
        ]
        buttons = [
            [InlineKeyboardButton(
                "📋 Fisa completare D301", callback_data=f"d301|{year}|{month}")],
            [InlineKeyboardButton(
                "🇪🇺 Fisa D390 (VIES)", callback_data=f"d390|{year}|{month}")],
        ]
        # Defalcare informativă „din care Bolt X · Uber Y" (CU BANI).
        defalcare_txt = (
            " · ".join(f"{s.eticheta} {s.suma:.2f}" for s in d100_plan.segmente)
            if d100_plan.segmente else ""
        )
        st = d100_plan.status
        if st == "neconfigurat":
            nume = " și ".join(s.title() for s in d100_plan.neconfig_brands) or "platformă"
            rows.append({"code": "D100", "name": f"Nerezident · setează regim {nume}", "warn": True})
            buttons.append([InlineKeyboardButton(
                f"⚙️ D100 — setează regim {nume}", callback_data=f"d100|{year}|{month}")])
            d100_nota = (f"⚙️ *D100*: ai facturi *{nume}* dar regimul nerezident nu e setat "
                         f"— apasă fișa D100 ca să-l configurezi. Nu emitem D100 (parțial) "
                         f"până nu alegi.")
        elif st == "scutit":
            rows.append({"code": "D100", "name": "Scutit (CRF) · declari D207"})
            d100_nota = ("✅ *D100*: scutit (CRF, 0%) — nu se depune lunar. "
                         "Venitul scutit se declară anual în *D207*.")
        elif st == "de_depus":
            pcte = " · ".join(f"{round(s.cota*100)}%" for s in d100_plan.segmente)
            rows.append({"code": "D100",
                         "name": f"Impozit nerezident · {int(d100_plan.suma_declarata)} lei",
                         "warn": True})
            buttons.append([InlineKeyboardButton(
                "🌍 Fisa D100 (nerezident)", callback_data=f"d100|{year}|{month}")])
            d100_nota = (f"🌍 *D100*: {int(d100_plan.suma_declarata)} lei (impozit nerezident, {pcte})"
                         + (f"\nDin care: {defalcare_txt}" if d100_plan.segmente and len(d100_plan.segmente) > 1 else ""))
        else:  # fara_baza (vat_out neatribuit unei platforme rideshare)
            rows.append({"code": "D100", "name": "Nerezident · verifică furnizorul"})
            d100_nota = ("ℹ️ *D100*: facturile nu-s atribuite unei platforme rideshare "
                         "(Bolt/Uber). Verifică furnizorul — D100 nu se depune până nu o identificăm.")
        # Nudge neatribuit (orthogonal — poate coexista cu orice status).
        if d100_plan.neatribuit_lei > 0 and st != "fara_baza":
            d100_nota = (d100_nota or "") + (
                f"\n⚠️ {d100_plan.neatribuit_lei:.2f} lei TVA neatribuit unei platforme "
                f"— verifică furnizorul (exclus din D100).")

        data = {
            "title": "De depus",
            "subtitle": f"BAZĂ {baza_ro} LEI · TVA {tva_pct}%",
            "rows": rows,
            "status": "de depus în SPV",
        }
        rm = InlineKeyboardMarkup(buttons)
        text = (
            f"🧾 *TVA & Declarații · {luna_ro(month)} {year}*\n"
            f"Bază facturi: *{baza:.2f} RON* · TVA {tva_pct}%\n"
            f"TVA colectat D301: *{vat_out:.2f} RON*\n\n"
            f"Apasă o fișă pentru ghid de completare + XML (DUKIntegrator)."
            + (f"\n\n{d100_nota}" if d100_nota else "")
        )
    else:
        data = {
            "title": "Nimic de depus",
            "subtitle": f"FĂRĂ FACTURĂ BOLT ÎN {month:02d}/{year} · NIMIC DE DECLARAT",
            "rows": [],
            "status": "nimic de depus",
        }
        rm = None
        text = (
            f"🧾 *TVA & Declarații · {luna_ro(month)} {year}*\n\n"
            f"Nu există factură Bolt (comision) în {month:02d}/{year} → "
            f"D301/D390/D100 nu se depun pentru această lună."
        )

    await banner_send.send_banner_or_text(
        query, context,
        screen="declaratii", data=data,
        text=text, reply_markup=rm,
        caption=f"🧾 TVA & Declarații · {luna_ro(month)} {year}",
    )


async def execute_fisa_d301(query, context, user_id, year, month):
    """Genereaza fisa D301 (ghid completare + XML) cu noul serviciu unificat."""
    await _trimite_declaratie_noua(query, context, user_id, year, month, "D301")


async def _trimite_declaratie_noua(query, context, user_id, year, month, tip):
    """
    Generator unificat pentru D301/D390/D100 (acelasi 'creier' ca dashboard-ul).

    Trimite ghidul de completare ca mesaj + fisierul XML ca document atasat.
    """
    chat_id = query.message.chat_id
    session = get_session()
    try:
        totals = tax_engine.compute_period(
            session, user_id=user_id, year=year, month=month
        )
        tva = totals.get("vat_out_total", 0) or 0
        if tva <= 0:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"ℹ️ Nu exista factura Bolt (comision) in {month:02d}/{year}, "
                     f"deci {tip} nu se depune pentru aceasta luna.",
            )
            return
        # Cotă din sursa unică (cota_tva pe data lunii), NU /0.21 hardcodat. Pe luni
        # cu cotă ≠21% (ex. 19% înainte de 01.08.2025) baza ieșea prea mică → XML
        # subdeclarat. cota_tva e deja în totals (compute_period); fallback defensiv.
        cota = totals.get("cota_tva") or cota_tva(date(year, month, 1))
        baza = round(tva / cota, 2)
        profile = users_repo.get_profile_dict(session, user_id) or {}
        # D100 multi-brand (Uber sub-pas B): planul split per-platformă (vat_out_by_brand
        # are nevoie de DB → îl calculăm aici, în sesiune). Ignorat pentru D301/D390.
        from app.domain.fiscal_profile import from_user_dict
        d100_plan = tax_engine.compute_d100_plan(
            tax_engine.vat_out_by_brand(session, user_id=user_id, year=year, month=month),
            cota, from_user_dict(profile),
        ) if tip == "D100" else None
    except Exception as e:
        logger.error(f"_trimite_declaratie_noua compute error {tip}: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ N-am putut calcula {tip}. Încearcă din nou.")
        return
    finally:
        session.close()

    try:
        firma = decl_nou.date_firma_din_profil(profile)
        # D100 → planul multi-brand (sursă unică); D301/D390 → baza (total).
        # Cota nerezident legacy păstrată ca fallback dacă planul lipsește.
        cota_nerez = from_user_dict(profile).cota_nerezident
        rez = decl_nou.genereaza(tip, year, month, baza, firma=firma,
                                 cota_nerezident=cota_nerez, d100_plan=d100_plan)
    except Exception as e:
        logger.error(f"_trimite_declaratie_noua gen error {tip}: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ N-am putut genera {tip}. Încearcă din nou.")
        return

    # 1. Ghidul de completare (mesaj text)
    try:
        await context.bot.send_message(
            chat_id=chat_id, text=rez.ghid_telegram, parse_mode="Markdown",
        )
    except Exception:
        # fallback fara markdown daca ceva din continut strica parsarea
        await context.bot.send_message(chat_id=chat_id, text=rez.ghid_plain)

    # 2. Avertismente (daca exista)
    warns = []
    if rez.namespace_de_confirmat:
        warns.append(
            f"⚠️ XML-ul pentru {tip} e gata, dar formatul nu e inca confirmat "
            f"100%. Foloseste deocamdata ghidul de completare (sigur)."
        )
    for a in (rez.avertismente or []):
        warns.append(f"ℹ️ {a}")
    if warns:
        await context.bot.send_message(chat_id=chat_id, text="\n\n".join(warns))

    # 3. Fisierul XML (document atasat) — DOAR daca s-a generat.
    # La D100 cu cota 0 (scutit) / None (neconfigurat) rez.generat=False:
    # NU trimitem niciun fisier (ghidul de la pasul 1 explica de ce). Astfel e
    # imposibil sa iasa un XML D100 cu suma 0 / cota presupusa (date la ANAF).
    if not rez.generat:
        return
    try:
        await context.bot.send_document(
            chat_id=chat_id,
            document=_io.BytesIO(rez.xml.encode("utf-8")),
            filename=rez.nume_fisier_xml,
            caption=(
                f"📄 *{tip} — {month:02d}/{year}* (XML pentru DUKIntegrator)"
                + (f"\nDe plata: *{rez.suma_plata:.2f} lei*" if rez.are_plata else "")
            ),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"_trimite_declaratie_noua xml error {tip}: {e}")


async def execute_fisa_d390(query, context, user_id, year, month):
    """Genereaza fisa D390 (VIES) cu noul serviciu unificat."""
    await _trimite_declaratie_noua(query, context, user_id, year, month, "D390")


async def execute_fisa_d100(query, context, user_id, year, month):
    """Genereaza fisa D100 (impozit nerezident) cu noul serviciu unificat."""
    await _trimite_declaratie_noua(query, context, user_id, year, month, "D100")


async def execute_registru(query, context, user_id, year, month=None):
    period_label = (
        f"{LUNI_LONG[month]} {year}" if month else f"anul {year}"
    )
    period_banner = f"{luna_ro(month)} {year}" if month else str(year)  # lunar / anual
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

        # Banner hero ÎNTÂI (incasari/plati/sold) — sursă unică `registru_totals` (= Excel).
        # Aditiv/defensiv: eșec → sare bannerul, Excel-ul tot pleacă. Lună goală → 0/0/0.
        t = registru_totals(txs, year, month)
        banner_data = {
            "incasari": t["incasari"], "plati": t["plati"], "sold": t["sold"],
            "period": period_banner,
        }
        if t["last"]:
            banner_data["last"] = t["last"]
        await banner_send.send_banner_photo(
            context, query.message.chat_id,
            screen="registru", data=banner_data,
            caption=f"📂 Registru · {period_banner}",
        )

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
        await query.edit_message_text("⚠️ N-am putut genera registrul. Încearcă din nou.")
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
        await query.edit_message_text("⚠️ N-am putut exporta. Încearcă din nou.")
    finally:
        session.close()


def _calendar_banner_data(alerts, year, month):
    """Data dict `calendar` — TOP-4 obligații după URGENȚĂ (days_left crescător →
    overdue/critical întâi), NU ordinea de definiție. `warn` = status urgent (accent
    auriu); restul teal. Subset al textului (aceeași sursă get_monthly+get_annual).
    """
    ordered = sorted(alerts, key=lambda a: a["days_left"])   # overdue (<0) → apropiate
    return {
        "obligations": [
            {"code": a["code"], "name": a["name"], "date": a["deadline"],
             "days_left": a["days_left"],
             "warn": a["status"] in ("overdue", "critical", "warning")}
            for a in ordered[:4]
        ],
        "period": f"{luna_ro(month)} {year}",
        "subtitle": "Termene și obligații",
    }


async def execute_fiscal(query, context, user_id, year, month):
    session = get_session()
    cota_nerez = None
    try:
        # Fiscal #4: semnalul „are factură Bolt taxabilă" = vat_out_total>0
        # (sursă unică, ca web/banner), NU vechiul filtru (EXPENSE+REVERSE_CHARGE)
        # care era relicvă de model vechi → mereu False → calendar „nu se depun".
        has_bolt = tax_engine.has_taxable_bolt_invoice(
            session, user_id=user_id, year=year, month=month)
        # Cota nerezident D100 din profil (None = neconfigurat). #3.
        from app.domain.fiscal_profile import from_user_dict
        profile = users_repo.get_profile_dict(session, user_id) or {}
        cota_nerez = from_user_dict(profile).cota_nerezident
        # D100 split per-platformă (Uber sub-pas D): planul → status + label multi-brand
        # în calendar („Bolt 2% · Uber 16%"), nu „(X% Bolt)" legacy.
        d100_status = d100_label = None
        if has_bolt:
            _plan = tax_engine.d100_plan_for(session, user_id=user_id, year=year, month=month)
            d100_status = _plan.status
            d100_label = (" · ".join(f"{s.eticheta} {round(s.cota*100)}%" for s in _plan.segmente)
                          or None)
    except Exception:
        has_bolt = False
        d100_status = d100_label = None
    finally:
        session.close()

    msg = fiscal_calendar.format_fiscal_message(year, month, has_bolt_invoice=has_bolt,
                                                cota_nerezident=cota_nerez,
                                                d100_status=d100_status, d100_pct_label=d100_label)
    # Banner hero TOP-4 obligații urgente + textul complet dedesubt. Sursă = aceeași
    # ca textul (get_monthly_alerts + get_annual_alerts filtrate -30..60, ca format_*).
    alerts = fiscal_calendar.get_monthly_alerts(year, month, has_bolt_invoice=has_bolt,
                                                cota_nerezident=cota_nerez,
                                                d100_status=d100_status, d100_pct_label=d100_label) + [
        a for a in fiscal_calendar.get_annual_alerts(year) if -30 <= a["days_left"] <= 60
    ]
    if alerts:
        await banner_send.send_banner_or_text(
            query, context,
            screen="calendar", data=_calendar_banner_data(alerts, year, month),
            text=msg, caption=f"📋 Calendar fiscal · {luna_ro(month)} {year}",
        )
    else:
        # Caz gol: nicio obligație în fereastră → DOAR textul (explică situația), fără banner gol.
        await query.edit_message_text(msg, parse_mode="Markdown")


async def execute_reminder(query, context):
    await query.edit_message_text("🔄 Trimit reminder...")
    try:
        sched_service.check_and_remind(settings.telegram_token)
        await query.edit_message_text("✅ Reminder trimis. Verifică mesajele.")
    except Exception as e:
        logger.error(f"reminder error: {e}")
        await query.edit_message_text("⚠️ N-am putut trimite reminderul. Încearcă din nou.")


async def handle_sumar_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /sumar_test — preview OWNER-ONLY al sumarului lunar (luna incheiata).

    Trimite DOAR owner-ului, NU atinge summary_sent (repetabil oricand, nu
    interfereaza cu jobul automat). Gardat pe OWNER_TELEGRAM_ID: nesetat sau
    alt user -> comanda inerta. Foloseste build_summary_for_user = EXACT
    acelasi mesaj ca jobul automat.
    """
    owner_id = settings.owner_telegram_id
    if not owner_id or update.effective_user.id != owner_id:
        await update.message.reply_text("Comandă indisponibilă.")
        return

    year, month = sched_service.luna_precedenta(
        datetime.now(sched_service.ROMANIA_TZ)
    )
    session = get_session()
    try:
        user = users_repo.get_by_telegram_id(
            session, telegram_id=update.effective_user.id
        )
        if not user:
            await update.message.reply_text(
                "Nu te găsesc în baza de date. Folosește /start întâi."
            )
            return
        msg = sched_service.build_summary_for_user(session, user, year, month)
        if msg is None:
            await update.message.reply_text(
                f"📭 Nu ai tranzacții pe {LUNI_LONG.get(month, month)} {year} "
                f"— nimic de sumarizat."
            )
            return
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=msg, parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"sumar_test error: {e}")
        await update.message.reply_text("⚠️ N-am putut genera sumarul. Încearcă din nou.")
    finally:
        session.close()


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
        await query.edit_message_text("⚠️ N-am putut porni monitorizarea. Încearcă din nou.")


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
        await query.edit_message_text("⚠️ N-am putut citi istoricul. Încearcă din nou.")
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
        logger.exception("execute_reset error")
        await query.edit_message_text(
            "⚠️ N-am putut șterge datele acum. Nimic nu s-a modificat — încearcă din nou."
        )
    finally:
        session.close()


# ============================================================
#                    /delete si /anafdebug
# ============================================================

async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = ensure_user(update)
    if not user_id:
        await update.message.reply_text("⚠️ Nu te-am putut identifica. Deschide din nou din butonul bot-ului.")
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
        await update.message.reply_text("⚠️ N-am putut anula documentul. Încearcă din nou.")
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
        logger.exception("anafdebug error")
        # Comandă de debug (owner) — păstrăm detaliul tehnic intenționat.
        await update.message.reply_text(
            f"❌ Lookup ANAF a eșuat (debug):\n`{str(e)[:300]}`", parse_mode="Markdown",
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
        await query.edit_message_text("⚠️ N-am putut citi datele confirmate. Trimite documentul din nou.")
        confirmare.clear_pending(context)
        return

    activity = get_activity_for_user(user_id) if user_id else None

    await query.edit_message_text("💾 Salvez documentul...")

    # === SALVARE ATOMICĂ (coada-bugs #1): o sesiune, UN commit, rollback TOTAL la
    # orice eșec → ori toți itemii intră, ori niciunul. Înainte: commit per item →
    # eșec mid-loop lăsa date parțiale + documente orfane raportate ca succes. ===
    session = get_session()
    committed = False
    results = []
    try:
        results = _persist_all_items(
            session, items=items, user_id=user_id,
            source_file_id=source_file_id, raw_response=raw_response,
            prompt_version=prompt_version,
        )
        session.commit()
        committed = True
    except Exception as e:
        session.rollback()
        logger.exception("execute_confirmed_save: eșec la salvare → rollback TOTAL")
        monitoring.capture_exception(e, stage="execute_confirmed_save")
    finally:
        session.close()

    if not committed:
        confirmare.clear_pending(context)
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "⚠️ N-am salvat nimic — *ori toate, ori niciuna*. "
                "Nicio modificare în registru. Reîncearcă liniștit."
            ),
            parse_mode="Markdown",
        )
        return

    # === Commit reușit → efecte DOAR acum. Un eșec de MESAJ ≠ pierdere de date
    # (datele sunt deja comise), deci nu raportăm fals „n-am salvat". ===
    confirmare.clear_pending(context)
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=_build_confirm_message(results, activity),
            parse_mode="Markdown",
        )
    except Exception:
        logger.exception(
            "execute_confirmed_save: mesaj confirmare eșuat (datele SUNT salvate)"
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


def _fmt_ron(x: float) -> str:
    """1019.45 -> '1.019,45' (format RO: punct mii, virgulă zecimale)."""
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# Ordinea grupurilor în preview (relevanță fiscală) + emoji + etichetă + hint scurt.
# Hint-ul e la nivel de GRUP (preview = sumar; detaliul fin vine la postare, felia 3).
_BUCKET_DISPLAY = [
    (VENIT_BOLT,          "📥", "Venituri Bolt",              None),
    (PLATA_TAXA,          "📤", "Plăți obligații fiscale",    "decontare, nu cheltuială"),
    (RETURNARE_TAXA,      "↩️", "Returnări (plăți respinse)", "anulează plăți, nu venit nou"),
    (COMISION_BANCAR,     "💳", "Comisioane bancare",         "deductibile"),
    (CHELTUIALA_BUSINESS, "🧾", "Cheltuieli business",        None),
    (DE_VERIFICAT,        "🟡", "De verificat",               "tu decizi la confirmare"),
]
_EMOJI_BY_BUCKET = {b: e for b, e, _l, _h in _BUCKET_DISPLAY}


def _format_bank_preview(clasificate) -> str:
    """Preview felia 2: clasificare grupată pe buckete. ZERO scriere în registru.

    Primește deja `list[BankTxnClasificat]` (handler-ul orchestrează activity +
    clasificare). Funcția e PURĂ — doar formatează mesajul.
    """
    total = len(clasificate)
    n_verif = sum(1 for r in clasificate if r.bucket == DE_VERIFICAT)
    n_clasif = total - n_verif

    by_bucket = {}
    for r in clasificate:
        by_bucket.setdefault(r.bucket, []).append(r)

    lines = [
        f"✅ *{total} tranzacții* în extras — {n_clasif} clasificate, {n_verif} de verificat",
        "✓ verificat cu RULAJ TOTAL CONT",
        "",
    ]

    # Grupuri în ordinea relevanței fiscale (sărim grupurile goale)
    for bucket, emoji, label, hint in _BUCKET_DISPLAY:
        grup = by_bucket.get(bucket)
        if not grup:
            continue
        suma = sum(r.txn.suma for r in grup)
        sufix = f" — {hint}" if hint else ""
        lines.append(f"{emoji} *{label}:* {len(grup)}  ({_fmt_ron(suma)} lei){sufix}")

    # Linie fiscală: returnările sunt plăți respinse reîntoarse (NU venit nou).
    # Dacă sumele plăți/returnări se potrivesc exact → se anulează net 0.
    retur = by_bucket.get(RETURNARE_TAXA)
    if retur:
        s_plata = sum(r.txn.suma for r in by_bucket.get(PLATA_TAXA, []))
        s_retur = sum(r.txn.suma for r in retur)
        lines.append("")
        if by_bucket.get(PLATA_TAXA) and round(s_plata, 2) == round(s_retur, 2):
            lines.append(
                "ℹ️ _Plățile și returnările se anulează (net 0) — "
                "au fost respinse și reîntoarse._"
            )
        else:
            lines.append(
                "ℹ️ _Returnările sunt plăți respinse reîntoarse (nu venit nou)._"
            )

    # Exemple concrete (primele tranzacții, cu etichetă)
    lines.append("")
    lines.append("_Primele tranzacții:_")
    for r in clasificate[:6]:
        t = r.txn
        d = t.data.strftime("%d.%m") if t.data else "??.??"
        et = r.eticheta or ""
        if len(et) > 32:
            et = et[:32] + "…"
        lines.append(f"{_EMOJI_BY_BUCKET.get(r.bucket, '•')} {d}  {_fmt_ron(t.suma)}  _{et}_")

    lines.append("")
    lines.append("_Deocamdată doar afișare — nu am adăugat nimic în registru._")
    return "\n".join(lines)


async def handle_bank_statement_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Import extras bancar (PDF) — felia 1: parsare + preview, ZERO scriere registru.

    Handler izolat pe filters.Document (calea foto/text neatinsă).
    """
    tg_id = update.effective_user.id
    if onboarding.user_is_in_onboarding(tg_id):
        await update.message.reply_text(
            "⚠️ Te rog termină mai întâi configurarea profilului (/start)."
        )
        return

    doc = update.message.document
    fname = (doc.file_name or "").lower()
    is_pdf = fname.endswith(".pdf") or doc.mime_type == "application/pdf"
    if not is_pdf:
        await update.message.reply_text(
            "📄 Trimite extrasul ca fișier *PDF* (deocamdată doar Banca Transilvania).",
            parse_mode="Markdown",
        )
        return
    if doc.file_size and doc.file_size > 10 * 1024 * 1024:
        await update.message.reply_text("⚠️ Fișier prea mare (max 10 MB).")
        return

    user_id = ensure_user(update)
    if not user_id:
        return

    tg_file = await doc.get_file()
    file_bytes = bytes(await tg_file.download_as_bytearray())
    # arhivare + dedup la nivel fișier (nu blocăm la duplicat — felia 1 e doar preview)
    sf_info = register_source_file(
        user_id=user_id, file_bytes=file_bytes,
        telegram_file_id=tg_file.file_id,
        kind="bank_statement", mime="application/pdf",
    )
    source_file_id = sf_info["id"] if sf_info else None

    await update.message.reply_text("📄 Procesez extrasul…")
    from app.integrations.imports.bt_parser import parse_bt_pdf
    from app.integrations.imports.bank_statement import BankStatementError
    try:
        txns = parse_bt_pdf(file_bytes)
    except BankStatementError as e:
        await update.message.reply_text(
            f"⚠️ Nu pot citi sigur extrasul: {e}\n\n"
            "Deocamdată suport doar extrase *Banca Transilvania* (PDF).",
            parse_mode="Markdown",
        )
        return
    except Exception as e:
        logger.error(f"bank_statement parse error user={user_id}: {e}")
        await update.message.reply_text(
            "⚠️ Nu am putut procesa fișierul. Verifică să fie un extras BT în format PDF."
        )
        return

    # Clasificare deterministă (felia 2): activity din profilul user-ului,
    # ACEEAȘI sursă ca post_document (get_activity_for_user -> get_activity).
    activity = get_activity_for_user(user_id)
    clasificate = [classify_bt(t, activity) for t in txns]

    # Felia 3 + 5c-c: butoane condiționate sub preview (cheltuieli + taxe achitate).
    # Preview-ul (_format_bank_preview) rămâne NEATINS — doar se adaugă reply_markup.
    postable = bank_import_ui.has_postable(clasificate)
    if postable:
        state = bank_import_ui.init_state(clasificate, source_file_id)
        state["user_id"] = user_id
        bank_import_ui.store_state(context, state)
    reale_tax = bank_tax_ui.real_tax_payments(clasificate)   # = compensate, o singură dată
    if reale_tax:
        bank_tax_ui.store_tax_state(context, clasificate, source_file_id, user_id)
    reply_markup = bank_tax_ui.build_preview_keyboard(
        postable, bool(reale_tax), len(reale_tax)
    )

    # Felia 4: reconciliere de prezență Bolt — BONUS, adăugat la preview defensiv
    # (o eroare la reconciliere NU strică preview-ul: append_nudge prinde și întoarce
    # textul neschimbat). `_format_bank_preview` rămâne NEATINS.
    preview_text = _format_bank_preview(clasificate)
    session = get_session()
    try:
        preview_text = bolt_reconcile.append_nudge(
            preview_text, session, user_id, clasificate
        )
    finally:
        session.close()

    await update.message.reply_text(
        preview_text,
        parse_mode="Markdown",
        reply_markup=reply_markup,
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
        if du_ui.is_in_wizard(context):
            du_ui.cancel_wizard(context)
        await handle_menu_button(update, context, text)
        return

    # Faza 1: Wizard coduri fiscale (asteapta cod TVA / CNP)
    if context.user_data.get("coduri_wizard"):
        await handle_coduri_wizard_text(update, context)
        return

    # Pas R1: Wizard editare camp (confirmare date extrase)
    if confirmare.is_editing(context):
        handled = await confirmare.handle_edit_text(update, context)
        if handled:
            return

    # Faza 1: Wizard manual Declaratia Unica
    if du_ui.is_in_wizard(context):
        handled = await du_ui.handle_wizard_text(update, context)
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

# ============================================================
#          POST INIT - meniu comenzi (/) vizibil mereu
# ============================================================


# ============================================================
#          COMENZI - CODURI FISCALE (Faza 1)
# ============================================================

async def _coduri_text(profile: dict) -> str:
    cui = profile.get("firma_cui") or "—"
    cod_tva = profile.get("cod_special_tva")
    cnp = profile.get("cnp")
    cod_tva_txt = f"RO {cod_tva}" if cod_tva else "— nesetat"
    cnp_txt = "setat (ascuns)" if cnp else "— nesetat"
    return (
        "*🔑 Coduri fiscale*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🏢 *CUI normal:* `{cui}`\n"
        "_folosit pe D100 si registre_\n\n"
        f"🇪🇺 *Cod special TVA (art. 317):* {cod_tva_txt}\n"
        "_folosit pe D301 si D390_\n\n"
        f"🆔 *CNP:* {cnp_txt}\n"
        "_folosit pe Declaratia Unica D212_\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "_Apasa un buton ca sa setezi._"
    )


def _kb_coduri(profile: dict):
    cod_tva = profile.get("cod_special_tva")
    cnp = profile.get("cnp")
    rows = []
    if cod_tva:
        rows.append([
            InlineKeyboardButton("✏️ Schimbă cod TVA", callback_data="coduri|set_tva"),
            InlineKeyboardButton("🗑️ Șterge", callback_data="coduri|del_tva"),
        ])
    else:
        rows.append([InlineKeyboardButton(
            "🇪🇺 Setează cod special TVA", callback_data="coduri|set_tva")])
    if cnp:
        rows.append([
            InlineKeyboardButton("✏️ Schimbă CNP", callback_data="coduri|set_cnp"),
            InlineKeyboardButton("🗑️ Șterge", callback_data="coduri|del_cnp"),
        ])
    else:
        rows.append([InlineKeyboardButton(
            "🆔 Setează CNP", callback_data="coduri|set_cnp")])
    return InlineKeyboardMarkup(rows)


async def handle_coduri_fiscale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/coduri_fiscale - afiseaza codurile cu butoane de setare."""
    user_id = ensure_user(update)
    if not user_id:
        await update.message.reply_text("⚠️ Nu te-am putut identifica. Deschide din nou din butonul bot-ului.")
        return
    session = get_session()
    try:
        profile = users_repo.get_profile_dict(session, user_id) or {}
    finally:
        session.close()
    await update.message.reply_text(
        await _coduri_text(profile),
        parse_mode="Markdown",
        reply_markup=_kb_coduri(profile),
    )


async def _reafiseaza_coduri(update, context, user_id, via_query=None):
    """Reincarca profilul si afiseaza codurile cu butoane (mesaj nou)."""
    session = get_session()
    try:
        profile = users_repo.get_profile_dict(session, user_id) or {}
    finally:
        session.close()
    chat_id = (via_query.message.chat_id if via_query
               else update.effective_chat.id)
    await context.bot.send_message(
        chat_id=chat_id,
        text=await _coduri_text(profile),
        parse_mode="Markdown",
        reply_markup=_kb_coduri(profile),
    )


async def handle_coduri_callback(update, context, parts, user_id):
    """Router pentru butoanele coduri|... (apelat din handle_callback_query)."""
    query = update.callback_query
    action = parts[1] if len(parts) > 1 else ""

    if action == "set_tva":
        context.user_data["coduri_wizard"] = "cod_tva"
        await query.edit_message_text(
            "🇪🇺 *Cod special TVA (art. 317)*\n\n"
            "Trimite-mi codul ca mesaj — doar cifrele.\n"
            "_Exemplu: 53148882_\n\n"
            "Apasa `/coduri_fiscale` ca sa renunti.",
            parse_mode="Markdown",
        )
        return
    if action == "set_cnp":
        context.user_data["coduri_wizard"] = "cnp"
        await query.edit_message_text(
            "🆔 *CNP*\n\n"
            "Trimite-mi CNP-ul (13 cifre).\n"
            "_Dato sensibila — se foloseste doar la Declaratia Unica D212._\n\n"
            "Apasa `/coduri_fiscale` ca sa renunti.",
            parse_mode="Markdown",
        )
        return
    if action == "del_tva":
        session = get_session()
        try:
            users_repo.update_profile_by_id(session, user_id, cod_special_tva="")
            session.commit()
        finally:
            session.close()
        await query.edit_message_text("🗑️ Cod special TVA sters.")
        await _reafiseaza_coduri(update, context, user_id, via_query=query)
        return
    if action == "del_cnp":
        session = get_session()
        try:
            users_repo.update_profile_by_id(session, user_id, cnp="")
            session.commit()
        finally:
            session.close()
        await query.edit_message_text("🗑️ CNP sters.")
        await _reafiseaza_coduri(update, context, user_id, via_query=query)
        return
    if action == "skip":
        # folosit la onboarding - utilizatorul amana setarea codurilor
        await query.edit_message_text(
            "👍 OK. Poti seta codurile oricand din /coduri_fiscale."
        )
        return


async def handle_coduri_wizard_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Proceseaza valoarea trimisa dupa apasarea unui buton de setare cod."""
    kind = context.user_data.get("coduri_wizard")
    text = update.message.text or ""
    cifre = "".join(c for c in text if c.isdigit())
    user_id = ensure_user(update)
    if not user_id:
        context.user_data.pop("coduri_wizard", None)
        return

    if kind == "cod_tva":
        if len(cifre) < 2:
            await update.message.reply_text(
                "Cod invalid. Trimite doar cifrele. Exemplu: 53148882"
            )
            return
        session = get_session()
        try:
            users_repo.update_profile_by_id(session, user_id, cod_special_tva=cifre)
            session.commit()
        finally:
            session.close()
        context.user_data.pop("coduri_wizard", None)
        await update.message.reply_text(
            f"✅ Cod special TVA salvat: *RO {cifre}*\n"
            "Se foloseste automat pe *D301* si *D390*.",
            parse_mode="Markdown",
        )
        await _reafiseaza_coduri(update, context, user_id)
        return

    if kind == "cnp":
        if len(cifre) != 13:
            await update.message.reply_text(
                "CNP-ul trebuie sa aiba exact 13 cifre. Reincearca."
            )
            return
        session = get_session()
        try:
            users_repo.update_profile_by_id(session, user_id, cnp=cifre)
            session.commit()
        finally:
            session.close()
        context.user_data.pop("coduri_wizard", None)
        await update.message.reply_text(
            "✅ CNP salvat (ascuns).\n"
            "Se foloseste pe *Declaratia Unica D212*.",
            parse_mode="Markdown",
        )
        await _reafiseaza_coduri(update, context, user_id)
        return

    # stare necunoscuta - curata
    context.user_data.pop("coduri_wizard", None)


async def handle_set_cod_tva(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cod_tva NNNNNNNN - seteaza codul special TVA art. 317."""
    user_id = ensure_user(update)
    if not user_id:
        await update.message.reply_text("⚠️ Nu te-am putut identifica. Deschide din nou din butonul bot-ului.")
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Scrie codul dupa comanda. Exemplu:\n`/cod_tva 53148882`",
            parse_mode="Markdown",
        )
        return
    cod = "".join(c for c in args[0] if c.isdigit())
    if len(cod) < 2:
        await update.message.reply_text(
            "Cod invalid. Exemplu: /cod_tva 53148882"
        )
        return
    session = get_session()
    try:
        users_repo.update_profile_by_id(session, user_id, cod_special_tva=cod)
        session.commit()
    finally:
        session.close()
    await update.message.reply_text(
        f"✅ Cod special TVA salvat: *RO {cod}*\n"
        "Se va folosi automat pe *D301* si *D390*.",
        parse_mode="Markdown",
    )


async def handle_set_cnp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cnp NNNNNNNNNNNNN - seteaza CNP-ul (pentru Declaratia Unica)."""
    user_id = ensure_user(update)
    if not user_id:
        await update.message.reply_text("⚠️ Nu te-am putut identifica. Deschide din nou din butonul bot-ului.")
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Scrie CNP-ul dupa comanda. Exemplu:\n`/cnp 1234567890123`\n\n"
            "_Dato sensibila - se pastreaza doar pentru a completa "
            "Declaratia Unica D212._",
            parse_mode="Markdown",
        )
        return
    cnp = "".join(c for c in args[0] if c.isdigit())
    if len(cnp) != 13:
        await update.message.reply_text(
            "CNP-ul trebuie sa aiba 13 cifre. Verifica si reincearca."
        )
        return
    session = get_session()
    try:
        users_repo.update_profile_by_id(session, user_id, cnp=cnp)
        session.commit()
    finally:
        session.close()
    await update.message.reply_text(
        "✅ CNP salvat (ascuns).\n"
        "Se va folosi pe *Declaratia Unica D212*.",
        parse_mode="Markdown",
    )


async def post_init(application):
    """
    Seteaza lista de comenzi care apare la apasarea butonului de meniu
    (sau a tastei /). Asa, orice utilizator vede usor /start si restul.
    """
    comenzi = [
        BotCommand("start", "Pornire / meniul principal"),
        BotCommand("ghid", "Ghid de obligatii fiscale"),
        BotCommand("certificat", "Certificat rezidenta Bolt (2% D100)"),
        BotCommand("ajutor", "Ghid de utilizare"),
        BotCommand("profil", "Vezi profilul tau"),
        BotCommand("bolt", "Venituri Bolt automat din API (luna)"),
        BotCommand("bolt_conectare", "Conecteaza contul Bolt (sync automat)"),
        BotCommand("plata_fiscala", "Calcul si IBAN pentru plata ANAF"),
        BotCommand("coduri_fiscale", "Coduri fiscale (CUI, TVA art.317, CNP)"),
        BotCommand("status", "Starea bot-ului"),
        BotCommand("cont", "Verifica datele contului tau"),
        BotCommand("reset_profil", "Reia configurarea profilului"),
    ]
    try:
        await application.bot.set_my_commands(comenzi)
        # C9-D: butonul de meniu (lângă input) deschide Mini App-ul într-un tap, pentru
        # toți userii. Înlocuiește MenuButtonCommands — comenzile rămân accesibile tastând
        # "/" (set_my_commands neschimbat). Butonul de MENIU WebApp primește init_data
        # (≠ KeyboardButton) → auth funcționează. Fallback: dacă set eșuează (except mai
        # jos), butonul inline 🖥️ Dashboard + /start rămân → accesul nu se rupe.
        await application.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="📊 Contai",
                web_app=WebAppInfo(url=DASHBOARD_URL),
            )
        )
        logger.info("Meniu setat (set_my_commands + buton meniu → Mini App)")
    except Exception as e:
        logger.error(f"Nu am putut seta meniul de comenzi: {e}")


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
        ensure_coduri_fiscale_columns()
    except Exception as e:
        logger.error(f"❌ Migrare coduri fiscale FAILED: {e}")
        monitoring.capture_exception(e, stage="migrare_coduri")

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

    app_bot = ApplicationBuilder().token(settings.telegram_token).post_init(post_init).build()

    # Comenzi
    app_bot.add_handler(CommandHandler("start", handle_start))
    app_bot.add_handler(CommandHandler("ajutor", handle_ajutor_command))
    app_bot.add_handler(CommandHandler("ghid", ghid_ui.handle_command))  # sub-pas Ghid 2
    app_bot.add_handler(CommandHandler("certificat", handle_certificat))  # Certificat Bolt
    app_bot.add_handler(CommandHandler("bolt_conectare", handle_bolt_conectare))  # #2-B status+link
    app_bot.add_handler(CommandHandler("profil", handle_profil))
    app_bot.add_handler(CommandHandler("reset_profil", handle_reset_profil))
    app_bot.add_handler(CommandHandler("status", handle_status))  # Pas 13.1
    app_bot.add_handler(CommandHandler("cont", handle_cont))  # diagnostic izolare
    app_bot.add_handler(CommandHandler("delete", handle_delete))
    app_bot.add_handler(CommandHandler("anafdebug", handle_anafdebug))
    app_bot.add_handler(CommandHandler("plata_fiscala", plata_fiscala.handle_command))
    app_bot.add_handler(CommandHandler("sterge_tura", foaie_parcurs.handle_delete_command))  # Pas A.3
    app_bot.add_handler(CommandHandler("declaratie_unica", du_ui.handle_command))  # Faza 1
    app_bot.add_handler(CommandHandler("cheltuieli", handle_cheltuieli_command))  # Faza UI - ecran cheltuieli
    app_bot.add_handler(CommandHandler("coduri_fiscale", handle_coduri_fiscale))  # Faza 1
    app_bot.add_handler(CommandHandler("cod_tva", handle_set_cod_tva))  # Faza 1
    app_bot.add_handler(CommandHandler("cnp", handle_set_cnp))  # Faza 1
    app_bot.add_handler(CommandHandler("sumar_test", handle_sumar_test))  # Faza 3 (owner-only)

    # Callback queries (router pentru toate butoanele inline)
    app_bot.add_handler(CallbackQueryHandler(handle_callback_query))

    # Mesaje
    # Extras bancar PDF (felia 1) — handler izolat, ÎNAINTE de foto/text
    app_bot.add_handler(
        MessageHandler(filters.Document.PDF, handle_bank_statement_wrapper)
    )
    app_bot.add_handler(MessageHandler(filters.PHOTO, handle_photo_wrapper))
    app_bot.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_wrapper)
    )

    app_bot.add_error_handler(handle_error)

    # === Bolt API — venituri automate (/bolt) ===
    bolt_sync.register(app_bot)

    print("🤖 Bot Contabil v30 — + Bolt API venituri (/bolt) ONLINE (Pas 11 + 10 + 13 + A + B + R1 + R1.2 + F1 + F1.3 + Bolt)")
    app_bot.run_polling()
