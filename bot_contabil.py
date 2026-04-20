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
from app.services import posting
from app.services import tax_engine
from app.integrations import sheets
from app.integrations.exports import csv_export
import logging
from datetime import datetime
from typing import Optional
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, ContextTypes,
    MessageHandler, CommandHandler, filters,
)
from flask import Flask
from threading import Thread

# --- CONFIGURARE ---
SHEET_NAME = "Contabilitate PFA 2025"
CREDENTIALS_FILE = "credentials.json"

# --- SERVER WEB ---
app = Flask('')
@app.route('/')
def home():
    return "Bot Fiscal (TVA 21% + Taburi Lunare) ONLINE"

def run_http():
    app.run(host='0.0.0.0', port=settings.port)

def keep_alive():
    t = Thread(target=run_http)
    t.start()

# --- INITIALIZARE ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


# --- HELPERS DB ---
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
                   "bytes_size": new_sf.bytes_size, "storage_path": new_sf.storage_path},
        )
        result = {
            "id": new_sf.id, "sha256": new_sf.sha256,
            "created_at": new_sf.created_at, "is_duplicate": False,
        }
        session.commit()
        logger.info(f"New SourceFile id={result['id']} sha={sha[:8]}...")
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
        logger.info(f"New Document id={doc_id} tip={item.tip} brut={item.brut}")
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
        if tx_ids:
            logger.info(f"Posted {len(tx_ids)} transaction(s) for doc_id={doc_id}: {tx_ids}")
        return tx_ids
    except Exception as e:
        session.rollback()
        logger.error(f"DB error in persist_transactions for doc_id={doc_id}: {e}")
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


def _parse_period_args(args, now: datetime):
    """
    Parsează argumentele lunii/anului dintr-o comandă Telegram.
    Returnează (year, month) sau ridică ValueError.
    Folosit de /raport și /export.
    """
    if len(args) == 0:
        return now.year, now.month
    elif len(args) == 1:
        month = int(args[0])
        if not 1 <= month <= 12:
            raise ValueError("luna invalida")
        return now.year, month
    else:
        month = int(args[0])
        year = int(args[1])
        if not 1 <= month <= 12:
            raise ValueError("luna invalida")
        if not 2020 <= year <= 2099:
            raise ValueError("an invalid")
        return year, month


def _tx_count_label(n: int) -> str:
    """'1 tranzacție', '2 tranzacții', etc."""
    if n == 1:
        return "1 tranzacție"
    return f"{n} tranzacții"


# --- COMMAND HANDLERS ---

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update)
    name = update.effective_user.first_name or "șofer"
    await update.message.reply_text(
        f"👋 Bun venit, {name}!\n\n"
        f"Trimite-mi:\n"
        f"📸 O poză cu bon/factură → o înregistrez automat\n"
        f"✍️ Text (ex: *am dat 50 lei bacsis cash*) → înregistrez manual\n\n"
        f"Comenzi:\n"
        f"/raport — raport luna curentă\n"
        f"/raport 04 2026 — raport specific\n"
        f"/export 04 2026 — export CSV pentru Excel\n"
        f"/ajutor — această listă",
        parse_mode="Markdown"
    )


async def handle_ajutor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Comenzi disponibile:*\n\n"
        "/raport — raport luna curentă\n"
        "/raport 04 — raport luna aprilie\n"
        "/raport 04 2026 — raport specific\n"
        "/export 04 2026 — CSV pentru Excel/contabil\n"
        "/ajutor — această listă\n\n"
        "📸 Trimite orice poză cu bon, factură sau screenshot din Bolt/Uber.",
        parse_mode="Markdown"
    )


async def handle_raport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = ensure_user(update)
    if not user_id:
        await update.message.reply_text("⚠️ Nu am putut identifica utilizatorul.")
        return

    now = datetime.now()
    try:
        year, month = _parse_period_args(context.args or [], now)
    except (ValueError, IndexError):
        await update.message.reply_text(
            "⚠️ Format incorect.\nExemple:\n  /raport\n  /raport 04\n  /raport 04 2026"
        )
        return

    await update.message.reply_text("🔄 Calculez raportul...")

    session = get_session()
    try:
        totals = tax_engine.compute_period(session, user_id=user_id, year=year, month=month)

        if totals["tx_count"] == 0:
            await update.message.reply_text(
                f"📭 Nu am găsit tranzacții pentru "
                f"{tax_engine.LUNI_RO.get(month, str(month))} {year}.\n\n"
                f"Trimite bonuri și facturi, apoi rulează din nou /raport."
            )
            return

        tp = tax_periods_repo.get_or_create(session, user_id=user_id, year=year, month=month)
        tax_periods_repo.save_totals(session, tp, totals)
        session.commit()

        msg = tax_engine.format_report_message(totals)
        # Fix gramatică inline în mesaj
        msg = msg.replace(
            f"_{totals['tx_count']} tranzacții procesate_",
            f"_{_tx_count_label(totals['tx_count'])} procesate_",
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
        logger.info(f"Raport {year}/{month:02d} generat pentru user_id={user_id}")

    except Exception as e:
        session.rollback()
        logger.error(f"Error computing period {year}/{month}: {e}")
        await update.message.reply_text("❌ Eroare la calculul raportului. Încearcă din nou.")
    finally:
        session.close()


async def handle_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /export [luna] [an]
    Generează și trimite 2 fișiere CSV:
    1. tranzactii_<an>_<luna>.csv — toate tranzacțiile cu detalii
    2. rezumat_fiscal_<an>_<luna>.csv — totaluri pentru contabil
    """
    user_id = ensure_user(update)
    if not user_id:
        await update.message.reply_text("⚠️ Nu am putut identifica utilizatorul.")
        return

    now = datetime.now()
    try:
        year, month = _parse_period_args(context.args or [], now)
    except (ValueError, IndexError):
        await update.message.reply_text(
            "⚠️ Format incorect.\nExemple:\n  /export\n  /export 04\n  /export 04 2026"
        )
        return

    month_name = tax_engine.LUNI_RO.get(month, str(month))
    await update.message.reply_text(f"🔄 Generez CSV pentru {month_name} {year}...")

    session = get_session()
    try:
        # Luăm tranzacțiile din DB
        txs = tx_repo.list_for_period(session, user_id=user_id, year=year, month=month)

        if not txs:
            await update.message.reply_text(
                f"📭 Nu am găsit tranzacții pentru {month_name} {year}.\n"
                f"Trimite documente mai întâi."
            )
            return

        # Generăm totalurile (pentru rezumat)
        totals = tax_engine.compute_period(session, user_id=user_id, year=year, month=month)

        # Generăm CSV-urile în memorie
        csv_tx = csv_export.generate_transactions_csv(txs, year, month)
        csv_rez = csv_export.generate_rezumat_csv(totals)

        fname_tx = csv_export.filename_transactions(year, month)
        fname_rez = csv_export.filename_rezumat(year, month)

        # Trimitem în Telegram ca fișiere
        import io as _io
        await update.message.reply_document(
            document=_io.BytesIO(csv_tx),
            filename=fname_tx,
            caption=f"📊 Tranzacții {month_name} {year} — {_tx_count_label(len(txs))}",
        )
        await update.message.reply_document(
            document=_io.BytesIO(csv_rez),
            filename=fname_rez,
            caption=f"📋 Rezumat fiscal {month_name} {year}",
        )

        # Log export în DB
        from app.models import ExportLog
        log_tx = ExportLog(
            target="csv",
            entity_type="period",
            entity_id=0,
            external_ref=fname_tx,
            status="ok",
            response_msg=f"{len(txs)} tranzacții",
        )
        log_rez = ExportLog(
            target="csv",
            entity_type="period",
            entity_id=0,
            external_ref=fname_rez,
            status="ok",
            response_msg=f"rezumat {month_name} {year}",
        )
        session.add(log_tx)
        session.add(log_rez)
        session.commit()

        logger.info(f"CSV export {year}/{month:02d} trimis user_id={user_id}: {len(txs)} tx")

    except Exception as e:
        session.rollback()
        logger.error(f"Error in handle_export {year}/{month}: {e}")
        await update.message.reply_text("❌ Eroare la generarea CSV. Încearcă din nou.")
    finally:
        session.close()


# --- PROCESARE MESAJ ---
async def process_entry(update, context, text_input=None, image_bytes=None, source_file_id=None):
    user_id = ensure_user(update)
    if user_id:
        logger.info(f"Processing entry for user_id={user_id} source_file_id={source_file_id}")

    await context.bot.send_message(chat_id=update.effective_chat.id, text="🔄 Analizez documentul (TVA 21%)...")

    extraction = ai_client.extract_document(
        user_input=text_input,
        image_bytes=image_bytes,
    )

    if not extraction["items"] and extraction["validation_errors"]:
        err_preview = "\n• ".join(extraction["validation_errors"][:3])
        logger.error(f"No valid items. Errors: {extraction['validation_errors']}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                f"⚠️ Documentul nu a putut fi înregistrat — datele extrase nu sunt valide:\n"
                f"• {err_preview}"
            ),
        )
        return

    if not extraction["items"]:
        logger.error(f"AI extraction failed: {extraction.get('error')}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Nu am putut citi datele. Incearca o poza mai clara.",
        )
        return

    try:
        msg_confirm = "✅ **Salvat:**\n"

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
            sheet_used = sync_to_sheets(doc_id=doc_id, row_data=row, date_str=data_doc) if doc_id else None

            doc_tag = f" #{doc_id}" if doc_id else ""
            tx_tag = f" ({_tx_count_label(len(tx_ids))})" if tx_ids else ""

            if tip == DocType.FACTURA_COMISION:
                msg_confirm += (f"📂 Dosar: {sheet_used}{doc_tag}{tx_tag}\n"
                                f"📄 **FACTURA {item.platforma}**\n"
                                f"📅 Data: {data_doc}\n"
                                f"💵 Baza: {item.comision} RON\n"
                                f"🏛️ **TVA (21%): {tva:.2f} RON** (D301)\n")
            elif tip == DocType.CHELTUIALA:
                msg_confirm += (f"📂 Dosar: {sheet_used}{doc_tag}{tx_tag}\n"
                                f"🛒 **{item.detalii}** ({item.brut} RON)\n")
            else:
                msg_confirm += (f"📂 Dosar: {sheet_used}{doc_tag}{tx_tag}\n"
                                f"💰 Incasare: {item.brut} RON\n")

        if extraction["validation_errors"]:
            msg_confirm += f"\n⚠️ {len(extraction['validation_errors'])} item(e) respinse la validare."

        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg_confirm)

    except Exception as e:
        logger.error(f"Error while processing items: {e}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Eroare sistem: {str(e)}")


# --- HANDLERS ---
async def handle_photo_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                created_at_str = sf_info["created_at"].strftime('%d.%m.%Y la %H:%M')
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=(
                        f"⚠️ Această imagine a fost deja înregistrată "
                        f"pe {created_at_str}. Nu o procesez din nou."
                    ),
                )
                return
            source_file_id = sf_info["id"]

    await process_entry(
        update, context,
        text_input=caption, image_bytes=file_bytes,
        source_file_id=source_file_id,
    )


async def handle_text_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_entry(update, context, text_input=update.message.text)


if __name__ == '__main__':
    try:
        init_db()
        logger.info("✅ DB init OK")
    except Exception as e:
        logger.error(f"❌ DB init FAILED: {e}")

    try:
        storage.ensure_storage_dir()
        logger.info("✅ Storage dir OK")
    except Exception as e:
        logger.error(f"❌ Storage dir FAILED: {e}")

    keep_alive()
    app_bot = ApplicationBuilder().token(settings.telegram_token).build()

    app_bot.add_handler(CommandHandler("start", handle_start))
    app_bot.add_handler(CommandHandler("ajutor", handle_ajutor))
    app_bot.add_handler(CommandHandler("raport", handle_raport))
    app_bot.add_handler(CommandHandler("export", handle_export))

    app_bot.add_handler(MessageHandler(filters.PHOTO, handle_photo_wrapper))
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_wrapper))

    print("🤖 Bot Contabil v5 (2026/TVA 21%) ONLINE!")
    app_bot.run_polling()
