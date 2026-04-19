from config import settings
from app.enums import DocType
from db import init_db, get_session
from app.repositories import users as users_repo
import logging
import base64
import json
import gspread
import asyncio
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from openai import OpenAI
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
client_openai = OpenAI(api_key=settings.openai_api_key)

# --- HELPER: înregistrează user-ul din Telegram în DB ---
def ensure_user(update: Update):
    """
    Garantează că user-ul din Telegram există în DB.
    Întoarce user.id (int) sau None dacă operația DB eșuează (nu blocăm bot-ul).
    """
    try:
        tg_user = update.effective_user
        if tg_user is None:
            return None
        display_name = tg_user.full_name or tg_user.username or None
        session = get_session()
        try:
            user = users_repo.get_or_create_by_telegram_id(
                session, telegram_id=tg_user.id, name=display_name
            )
            session.commit()
            return user.id
        except Exception as e:
            session.rollback()
            logger.error(f"DB error in ensure_user: {e}")
            return None
        finally:
            session.close()
    except Exception as e:
        logger.error(f"Unexpected error in ensure_user: {e}")
        return None

# --- MAPARE LUNI (RO) ---
LUNI_RO = {
    "01": "Ianuarie", "02": "Februarie", "03": "Martie", "04": "Aprilie",
    "05": "Mai", "06": "Iunie", "07": "Iulie", "08": "August",
    "09": "Septembrie", "10": "Octombrie", "11": "Noiembrie", "12": "Decembrie"
}

# --- FUNCTIE SCRIERE EXCEL (DINAMIC PE LUNI) ---
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

# --- CREIERUL AI (LOGICA 2026 - TVA 21%) ---
def ask_gpt_logic(user_input, image_base64=None):
    today = datetime.now().strftime("%d.%m.%Y")

    system_prompt = f"""
    Esti contabil AI expert pentru PFA Ridesharing in Romania.
    DATA CURENTA: {today}.
    COTA TVA STANDARD: 21% (Actualizat 2026).

    REGULI ANALIZA:
    1. FACTURA COMISION (Bolt/Uber):
       - Cauta data pe factura.
       - Comision = Total Factura.
       - TVA Datorat = Comision * 0.21 (Taxare Inversa).
       - Impozit Nerezidenti = Comision * 0.02 (Calcul informativ).

    2. BON FISCAL (Combustibil/Piese):
       - Cauta data bonului.
       - Brut = Total Bon.

    3. RAPORT VENITURI (Screenshot aplicatie):
       - Brut = Venit Total (App + Cash).
       - Comision = Taxa aplicatiei.
       - Net = Brut - Comision.

    OUTPUT JSON OBLIGATORIU:
    [
      {{
        "data": "DD.MM.YYYY", (Data de pe document sau data curenta daca nu e vizibila)
        "platforma": "Bolt/Uber/Petrom...",
        "tip": "FACTURA_COMISION" sau "CHELTUIALA" sau "VENIT",
        "brut": 0.00,
        "comision": 0.00,
        "tva": 0.00, (Doar pt comision, calculat cu 21%)
        "net": 0.00,
        "cash": 0.00,
        "detalii": "Scurta descriere"
      }}
    ]
    """

    messages = [{"role": "system", "content": system_prompt}]

    content_payload = []
    content_payload.append({"type": "text", "text": user_input if user_input else "Analizeaza imaginea"})

    if image_base64:
        content_payload.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
        })

    messages.append({"role": "user", "content": content_payload})

    try:
        response = client_openai.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            max_tokens=800,
            temperature=0.1
        )
        return response.choices[0].message.content
    except Exception as e:
        return "EROARE_AI"

# --- PROCESARE MESAJ ---
async def process_entry(update, context, text_input=None, image_file=None):
    # Înregistrăm user-ul în DB (silent fail dacă DB e indisponibil)
    user_id = ensure_user(update)
    if user_id:
        logger.info(f"Processing entry for user_id={user_id}")

    await context.bot.send_message(chat_id=update.effective_chat.id, text="🔄 Analizez documentul (TVA 21%)...")

    try:
        image_base64 = None
        if image_file:
            file_byte = await image_file.download_as_bytearray()
            image_base64 = base64.b64encode(file_byte).decode('utf-8')

        ai_response = ask_gpt_logic(text_input, image_base64)
        clean_json = ai_response.replace("```json", "").replace("```", "").strip()

        try:
            data_list = json.loads(clean_json)
        except:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Nu am putut citi datele. Incearca o poza mai clara.")
            return

        msg_confirm = "✅ **Salvat:**\n"

        for item in data_list:
            data_doc = item.get('data', datetime.now().strftime("%d.%m.%Y"))
            net = float(item.get('net', 0))
            cash = float(item.get('cash', 0))
            tip = item.get('tip')
            tva = float(item.get('tva', 0))

            banca = 0
            if tip == DocType.VENIT:
                banca = net - cash

            row = [
                data_doc,
                item.get('platforma'),
                tip,
                item.get('brut', 0),
                item.get('comision', 0),
                tva,
                net,
                cash,
                banca,
                item.get('detalii')
            ]

            sheet_used = write_to_sheet(row, data_doc)

            if tip == DocType.FACTURA_COMISION:
                msg_confirm += (f"📂 Dosar: {sheet_used}\n"
                                f"📄 **FACTURA {item['platforma']}**\n"
                                f"📅 Data: {data_doc}\n"
                                f"💵 Baza: {item['comision']} RON\n"
                                f"🏛️ **TVA (21%): {tva:.2f} RON** (D301)\n")
            elif tip == DocType.CHELTUIALA:
                msg_confirm += (f"📂 Dosar: {sheet_used}\n"
                                f"🛒 **{item['detalii']}** ({item['brut']} RON)\n")
            else:
                msg_confirm += (f"📂 Dosar: {sheet_used}\n"
                                f"💰 Incasare: {item['brut']} RON\n")

        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg_confirm)

    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Eroare sistem: {str(e)}")

# --- HANDLERS ---
async def handle_photo_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_file = await update.message.photo[-1].get_file()
    caption = update.message.caption
    await process_entry(update, context, text_input=caption, image_file=new_file)

async def handle_text_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_entry(update, context, text_input=update.message.text)

if __name__ == '__main__':
    # Crează tabelele (idempotent — safe la fiecare pornire)
    try:
        init_db()
        logger.info("✅ DB init OK")
    except Exception as e:
        logger.error(f"❌ DB init FAILED: {e}")
        # Nu oprim bot-ul — continuă fără DB; user-urile nu se vor salva.

    keep_alive()
    app_bot = ApplicationBuilder().token(settings.telegram_token).build()
    app_bot.add_handler(MessageHandler(filters.PHOTO, handle_photo_wrapper))
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_wrapper))
    print("🤖 Bot Contabil v4 (2026/TVA 21%) ONLINE!")
    app_bot.run_polling()
