from config import settings
from app.enums import DocType
from db import init_db, get_session
from app.repositories import users as users_repo
from app.repositories import source_files as source_files_repo
from app.repositories import audit as audit_repo
from app import storage
from app.ai import client as ai_client
import logging
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from flask import Flask
from threading import Thread

# --- CONFIGURARE ---
SHEET_NAME = "Contabilitate PFA 2025"
CREDENTIALS_FILE = "credentials.json"

# --- SERVER WEB (PENTRU RENDER) ---
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


# --- HELPER: înregistrează user-ul din Telegram în DB ---
def ensure_user(update: Update):
    """
    Garantează că user-ul din Telegram există în DB.
    Întoarce user.id (int) sau None dacă operația DB eșuează.
    """
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
                    session,
                    entity_type="user",
                    entity_id=user.id,
                    action="create",
                    user_id=user.id,
                    source="user",
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


# --- HELPER: dedup + salvare fișier sursă ---
def register_source_file(
    user_id: int,
    file_bytes: bytes,
    telegram_file_id: str,
    kind: str = "photo",
    mime: str = "image/jpeg",
):
    """
    Verifică dedup prin SHA256.
    Întoarce un dict: {"id", "sha256", "created_at", "is_duplicate"} sau None în caz de eroare.
    """
    sha = storage.compute_sha256(file_bytes)
    session = get_session()
    try:
        existing = source_files_repo.get_by_sha256(session, user_id, sha)
        if existing is not None:
            logger.info(f"Dedup HIT sha={sha[:8]}... sf_id={existing.id}")
            result = {
                "id": existing.id,
                "sha256": existing.sha256,
                "created_at": existing.created_at,
                "is_duplicate": True,
            }
            audit_repo.write(
                session,
                entity_type="source_file",
                entity_id=existing.id,
                action="dedup_hit",
                user_id=user_id,
                source="system",
                note=f"duplicate upload; original created at {existing.created_at.isoformat()}",
            )
            session.commit()
            return result

        ext = "jpg" if kind == "photo" else "bin"
        path = storage.save_bytes(file_bytes, sha, ext=ext)
        new_sf = source_files_repo.create(
            session,
            user_id=user_id,
            kind=kind,
            sha256=sha,
            telegram_file_id=telegram_file_id,
            mime=mime,
            bytes_size=len(file_bytes),
            storage_path=path,
        )
        audit_repo.write(
            session,
            entity_type="source_file",
            entity_id=new_sf.id,
            action="create",
            user_id=user_id,
            source="user",
            after={
                "kind": new_sf.kind,
                "sha256": new_sf.sha256,
                "bytes_size": new_sf.bytes_size,
                "storage_path": new_sf.storage_path,
            },
        )
        result = {
            "id": new_sf.id,
            "sha256": new_sf.sha256,
            "created_at": new_sf.created_at,
            "is_duplicate": False,
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


# --- MAPARE LUNI (RO) ---
LUNI_RO = {
    "01": "Ianuarie", "02": "Februarie", "03": "Martie", "04": "Aprilie",
    "05": "Mai", "06": "Iunie", "07": "Iulie", "08": "August",
    "09": "Septembrie", "10": "Octombrie", "11": "Noiembrie", "12": "Decembrie"
}


def write_to_sheet(row_data, date_str):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open(SHEET_NAME)

        try:
            parts = date_str.split('.')
            luna_cifra = parts[1]
            anul = parts[2]
            nume_luna = LUNI_RO.get(luna_cifra, "General")
            tab_name = f"{nume_luna} {anul}"
        except:
            tab_name = "General"

        try:
            worksheet = spreadsheet.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title=tab_name, rows=100, cols=10)
            header = ["Data", "Platforma", "Tip", "Brut", "Comision", "TVA (21%)", "Net", "Cash", "Banca", "Detalii"]
            worksheet.append_row(header)

        worksheet.append_row(row_data)
        return tab_name

    except Exception as e:
        logger.error(f"Eroare scriere Excel: {e}")
        return None


# --- PROCESARE MESAJ ---
async def process_entry(update, context, text_input=None, image_bytes=None):
    user_id = ensure_user(update)
    if user_id:
        logger.info(f"Processing entry for user_id={user_id}")

    await context.bot.send_message(chat_id=update.effective_chat.id, text="🔄 Analizez documentul (TVA 21%)...")

    # --- Chemare AI (include validare Pydantic) ---
    extraction = ai_client.extract_document(
        user_input=text_input,
        image_bytes=image_bytes,
    )

    # Caz 1: AI a răspuns, dar Pydantic a respins toate item-urile.
    # Verificat ÎNAINTEA erorii globale — altfel mesajul generic ar înghiți feedback-ul util.
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

    # Caz 2: eroare globală (OpenAI down, JSON corrupt, nimic extras).
    if not extraction["items"]:
        logger.error(f"AI extraction failed: {extraction.get('error')}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Nu am putut citi datele. Incearca o poza mai clara.",
        )
        return

    # Caz 3 (happy): avem item-uri valide; poate ne-au scăpat câteva pe drum.
    try:
        msg_confirm = "✅ **Salvat:**\n"

        for item in extraction["items"]:
            data_doc = item.data or datetime.now().strftime("%d.%m.%Y")
            tip = item.tip
            tva = item.tva

            banca = 0.0
            if tip == DocType.VENIT:
                banca = item.net - item.cash

            row = [
                data_doc,
                item.platforma or "",
                tip,
                item.brut,
                item.comision,
                tva,
                item.net,
                item.cash,
                banca,
                item.detalii or "",
            ]

            sheet_used = write_to_sheet(row, data_doc)

            if tip == DocType.FACTURA_COMISION:
                msg_confirm += (f"📂 Dosar: {sheet_used}\n"
                                f"📄 **FACTURA {item.platforma}**\n"
                                f"📅 Data: {data_doc}\n"
                                f"💵 Baza: {item.comision} RON\n"
                                f"🏛️ **TVA (21%): {tva:.2f} RON** (D301)\n")
            elif tip == DocType.CHELTUIALA:
                msg_confirm += (f"📂 Dosar: {sheet_used}\n"
                                f"🛒 **{item.detalii}** ({item.brut} RON)\n")
            else:
                msg_confirm += (f"📂 Dosar: {sheet_used}\n"
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

    if user_id:
        sf_info = register_source_file(
            user_id=user_id,
            file_bytes=file_bytes,
            telegram_file_id=tg_file.file_id,
            kind="photo",
            mime="image/jpeg",
        )
        if sf_info and sf_info["is_duplicate"]:
            created_at_str = sf_info["created_at"].strftime('%d.%m.%Y la %H:%M')
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=(
                    f"⚠️ Această imagine a fost deja înregistrată "
                    f"pe {created_at_str}. Nu o procesez din nou."
                ),
            )
            return

    await process_entry(update, context, text_input=caption, image_bytes=file_bytes)


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
    app_bot.add_handler(MessageHandler(filters.PHOTO, handle_photo_wrapper))
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_wrapper))
    print("🤖 Bot Contabil v4 (2026/TVA 21%) ONLINE!")
    app_bot.run_polling()
