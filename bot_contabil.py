import logging
import base64
import json
import gspread
import asyncio
import os
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from openai import OpenAI
from flask import Flask
from threading import Thread

# --- CONFIGURARE ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# --- CREDENTIALE RENDER ---
CREDENTIALS_FILE = "credentials.json"
GOOGLE_JSON_CONTENT = os.getenv("GOOGLE_CREDENTIALS_JSON")

if GOOGLE_JSON_CONTENT:
    with open(CREDENTIALS_FILE, "w") as f:
        f.write(GOOGLE_JSON_CONTENT)
else:
    print("⚠️ ATENTIE: Variabila GOOGLE_CREDENTIALS_JSON lipseste!")

SHEET_NAME = "Contabilitate PFA 2025"

# --- MAPARE LUNI ---
LUNI_RO = {
    1: "Ianuarie", 2: "Februarie", 3: "Martie", 4: "Aprilie",
    5: "Mai", 6: "Iunie", 7: "Iulie", 8: "August",
    9: "Septembrie", 10: "Octombrie", 11: "Noiembrie", 12: "Decembrie"
}

# --- SERVER WEB ---
app = Flask('')
@app.route('/')
def home():
    return "Botul Contabil este ONLINE (Mode: JSON Strict)"

def run_http():
    port_render = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port_render)

def keep_alive():
    t = Thread(target=run_http)
    t.start()

# --- INITIALIZARE ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
client_openai = OpenAI(api_key=OPENAI_API_KEY)

# --- EXCEL ---
def get_monthly_sheet_name():
    now = datetime.now()
    return f"{LUNI_RO[now.month]} {now.year}"

def ensure_sheet_exists(client, sheet_name):
    spreadsheet = client.open(SHEET_NAME)
    try:
        return spreadsheet.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=10)
        ws.append_row(['Data', 'Platforma', 'Tip', 'Brut', 'Comision', 'TVA (21%)', 'Net', 'Cash', 'Banca', 'Detalii'])
        return ws

def write_to_sheet(row_data):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        
        ws_luna = ensure_sheet_exists(client, get_monthly_sheet_name())
        ws_luna.append_row(row_data)
        
        try:
            client.open(SHEET_NAME).worksheet("GENERAL").append_row(row_data)
        except:
            pass
            
    except Exception as e:
        logging.error(f"Eroare Excel: {e}")

# --- AI LOGIC (STRICT MODE) ---
def ask_gpt_logic(user_input, image_base64=None):
    today = datetime.now().strftime("%d.%m.%Y")
    
    # Prompt optimizat pentru structura {"inregistrari": [...]}
    system_prompt = f"""
    Esti un sistem OCR contabil. Data: {today}.
    Analizeaza imaginea si extrage datele pentru PFA (TVA 21%).
    
    REGULI:
    1. Bolt/Uber (Raport Activitate):
       - Tip: VENIT_ESTIMAT
       - Brut = Venit Brut (Total).
       - Comision = Taxa Bolt/Uber.
       - TVA = 21% din Comision.
       - Net = Brut - Comision.
       
    2. Factura Comision (PDF/Poza factura):
       - Tip: FACTURA_COMISION
       - Comision = Total Factura.
       - TVA = 21% din Comision.
    
    Raspunde STRICT in format JSON care contine o cheie "inregistrari".
    Exemplu:
    {{
      "inregistrari": [
        {{
            "data": "DD.MM.YYYY",
            "platforma": "Bolt",
            "tip": "VENIT_ESTIMAT",
            "brut": 100.0,
            "comision": 20.0,
            "tva": 4.2,
            "net": 80.0,
            "cash": 10.0,
            "detalii": "Saptamana curenta"
        }}
      ]
    }}
    """

    content_payload = [{"type": "text", "text": user_input if user_input else "Extrage datele"}]
    
    if image_base64:
        content_payload.append({
            "type": "image_url", 
            "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
        })

    try:
        response = client_openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content_payload}
            ],
            response_format={"type": "json_object"}, # <--- CHEIA SUCCESULUI
            max_tokens=800,
            temperature=0.1
        )
        return response.choices.message.content
    except Exception as e:
        logging.error(f"Eroare OpenAI: {e}")
        return None

# --- PROCESARE ---
async def process_entry(update, context, text_input=None, image_file=None):
    msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="🔄 Procesez (Mod Strict)...")

    try:
        image_base64 = None
        if image_file:
            file_byte = await image_file.download_as_bytearray()
            image_base64 = base64.b64encode(file_byte).decode('utf-8')

        json_str = ask_gpt_logic(text_input, image_base64)
        
        if not json_str:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="⚠️ Eroare conexiune AI.")
            return

        try:
            data = json.loads(json_str)
            lista_inregistrari = data.get("inregistrari", [])
        except Exception as e:
            logging.error(f"Eroare JSON Raw: {json_str}") # Vedem in loguri ce a gresit
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text=f"⚠️ Format necunoscut. AI a raspuns: {json_str[:50]}...")
            return

        if not lista_inregistrari:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="⚠️ Nu am gasit date financiare clare in imagine.")
            return

        report_msg = "✅ **Salvat:**\n"
        for item in lista_inregistrari:
            # Calcul preventiv daca AI-ul a omis campuri
            brut = float(item.get('brut', 0))
            comision = float(item.get('comision', 0))
            # Recalculam TVA local pentru siguranta
            tva = comision * 0.21
            net = brut - comision
            cash = float(item.get('cash', 0))
            banca = net - cash
            
            row = [
                item.get('data', datetime.now().strftime("%d.%m.%Y")),
                item.get('platforma', 'Necunoscut'),
                item.get('tip', 'GENERIC'),
                brut, comision, tva, net, cash, banca,
                item.get('detalii', '-')
            ]
            
            write_to_sheet(row)
            
            report_msg += f"📌 {item.get('platforma')}: Net {net:.2f} RON | TVA {tva:.2f} RON\n"

        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text=report_msg)

    except Exception as e:
        logging.error(f"Eroare generala: {e}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Eroare interna. Verifica logurile Render.")

# --- HANDLERS ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.photo[-1].get_file()
    await process_entry(update, context, update.message.caption, file)

async def handle_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if 'image' in doc.mime_type or 'pdf' in doc.mime_type:
        file = await doc.get_file()
        await process_entry(update, context, update.message.caption, file)
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Trimite o poza sau PDF.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_entry(update, context, text_input=update.message.text)

if __name__ == '__main__':
    keep_alive()
    app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_bot.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app_bot.add_handler(MessageHandler(filters.Document.ALL, handle_doc))
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    app_bot.run_polling()