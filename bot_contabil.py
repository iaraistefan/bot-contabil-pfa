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

# --- CONFIGURARE CREDENTIALE RENDER (OBLIGATORIU) ---
CREDENTIALS_FILE = "credentials.json"
GOOGLE_JSON_CONTENT = os.getenv("GOOGLE_CREDENTIALS_JSON")

if GOOGLE_JSON_CONTENT:
    with open(CREDENTIALS_FILE, "w") as f:
        f.write(GOOGLE_JSON_CONTENT)
    print("✅ Credentialele Google au fost configurate pentru Render.")
else:
    print("⚠️ ATENTIE: Variabila GOOGLE_CREDENTIALS_JSON lipseste!")

SHEET_NAME = "Contabilitate PFA 2025"

# --- MAPARE LUNI ---
LUNI_RO = {
    1: "Ianuarie", 2: "Februarie", 3: "Martie", 4: "Aprilie",
    5: "Mai", 6: "Iunie", 7: "Iulie", 8: "August",
    9: "Septembrie", 10: "Octombrie", 11: "Noiembrie", 12: "Decembrie"
}

# --- SERVER WEB (PENTRU RENDER) ---
app = Flask('')
@app.route('/')
def home():
    return "Botul Contabil 2026 (TVA 21%) este ONLINE!"

def run_http():
    port_render = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port_render)

def keep_alive():
    t = Thread(target=run_http)
    t.start()

# --- INITIALIZARE ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
client_openai = OpenAI(api_key=OPENAI_API_KEY)

# --- FUNCTII EXCEL ---
def get_monthly_sheet_name():
    now = datetime.now()
    nume_luna = LUNI_RO[now.month]
    an = now.year
    return f"{nume_luna} {an}" # Ex: "Ianuarie 2026"

def ensure_sheet_exists(client, sheet_name):
    """Creeaza foaia lunara daca nu exista."""
    spreadsheet = client.open(SHEET_NAME)
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
        return worksheet
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=10)
        header = ['Data', 'Platforma', 'Tip', 'Brut', 'Comision', 'TVA (21%)', 'Net', 'Cash', 'Banca', 'Detalii']
        worksheet.append_row(header)
        return worksheet

def write_to_sheet(row_data):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        
        # 1. Scriere in Foaia Lunara (Siguranta maxima)
        nume_luna = get_monthly_sheet_name()
        ws_luna = ensure_sheet_exists(client, nume_luna)
        ws_luna.append_row(row_data)
        
        # 2. Scriere in GENERAL (Optional)
        try:
            spreadsheet = client.open(SHEET_NAME)
            ws_general = spreadsheet.worksheet("GENERAL")
            ws_general.append_row(row_data)
        except:
            pass 
            
    except Exception as e:
        logging.error(f"Eroare critica Excel: {e}")

# --- CREIERUL AI (LOGICA 2026 + TVA 21%) ---
def ask_gpt_logic(user_input, image_base64=None):
    today = datetime.now().strftime("%d.%m.%Y")
    
    system_prompt = f"""
    Esti contabil AI expert PFA 2026. DATA: {today}.

    REGULI 2026 (TVA 21%):
    1. FACTURA COMISION (Bolt/Uber):
       - Tip: "FACTURA_COMISION"
       - Comision: Valoarea TOTALA factura.
       - TVA: 21% din Comision.
       - Imp. Nerezidenti: 2% din Comision.
       - Net: -Valoarea facturii.

    2. RAPORT APLICATIE:
       - Tip: "VENIT_ESTIMAT"
       - Brut: Venit App + Numerar.
       - Comision: Taxa retinuta.
       - TVA: 21% din Comision.
       - Net: Brut - Comision.

    3. BON FISCAL:
       - Tip: "CHELTUIALA"
       - Brut: Total bon.

    OUTPUT JSON STRICT (Format Array):
    [
      {{
        "data": "DD.MM.YYYY",
        "platforma": "Bolt",
        "tip": "VENIT_ESTIMAT",
        "brut": 100.0,
        "comision": 20.0,
        "tva": 4.2,
        "net": 80.0,
        "cash": 0.0,
        "detalii": "Raport"
      }}
    ]
    DOAR JSON. Fara ```json.
    """

    messages = [{"role": "system", "content": system_prompt}]
    
    # REPARATIE: Initializare lista goala
    content_payload = [] 
    content_payload.append({"type": "text", "text": user_input if user_input else "Analizeaza documentul"})
    
    if image_base64:
        content_payload.append({
            "type": "image_url", 
            "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
        })
        
    messages.append({"role": "user", "content": content_payload})

    try:
        response = client_openai.chat.completions.create(
            model="gpt-4o", 
            messages=messages, 
            max_tokens=800,
            temperature=0.1
        )
        return response.choices.message.content
    except Exception as e:
        return "EROARE_AI"

# --- PROCESARE ---
async def process_entry(update, context, text_input=None, image_file=None):
    loading_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="📊 Analizez (TVA 21%)...")

    try:
        image_base64 = None
        prompt_text = text_input
        
        if image_file:
            file_byte = await image_file.download_as_bytearray()
            image_base64 = base64.b64encode(file_byte).decode('utf-8')

        ai_response = ask_gpt_logic(prompt_text, image_base64)
        clean_json = ai_response.replace("```json", "").replace("```", "").strip()
        
        try:
            data_list = json.loads(clean_json)
        except:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=loading_msg.message_id, text="⚠️ Eroare: Nu am inteles documentul.")
            return

        msg_confirm = "✅ **Inregistrat (2026):**\n"

        for item in data_list:
            net = float(item.get('net', 0))
            cash = float(item.get('cash', 0))
            tva = float(item.get('tva', 0))
            tip = item.get('tip')
            
            banca = 0
            if tip == 'VENIT_ESTIMAT':
                banca = net - cash
            
            row = [
                item.get('data'),
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

            write_to_sheet(row)

            if tip == 'FACTURA_COMISION':
                impozit_nerezidenti = float(item.get('comision', 0)) * 0.02
                msg_confirm += (f"📄 **FACTURA {item['platforma']}**\n"
                                f"💵 Baza: {item['comision']} RON\n"
                                f"🇷🇴 TVA (21%): {tva:.2f} RON\n"
                                f"🇪🇪 Imp. Nerezidenti (2%): {impozit_nerezidenti:.2f} RON\n")
            
            elif tip == 'CHELTUIALA':
                msg_confirm += (f"🛒 **{item['detalii']}**\n"
                                f"💸 Total: {item['brut']} RON\n")
            
            else:
                msg_confirm += (f"🚖 **{item['platforma']}**\n"
                                f"💰 Net: {net} RON | 🏦 TVA (21%): {tva:.2f} RON\n")

        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=loading_msg.message_id, text=msg_confirm)

    except Exception as e:
        logging.error(f"Eroare: {e}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ A aparut o eroare interna.")

# --- WRAPPERS ---
async def handle_photo_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_file = await update.message.photo[-1].get_file()
    caption = update.message.caption 
    await process_entry(update, context, text_input=caption, image_file=new_file)

async def handle_document_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # SUPORT PENTRU IMAGINI CLARE TRIMISE CA FILE
    doc = update.message.document
    if 'image' in doc.mime_type or 'pdf' in doc.mime_type:
        new_file = await doc.get_file()
        caption = update.message.caption
        await process_entry(update, context, text_input=caption, image_file=new_file)
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Trimite doar imagini sau PDF.")

async def handle_text_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_entry(update, context, text_input=update.message.text)

if __name__ == '__main__':
    keep_alive()
    app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_bot.add_handler(MessageHandler(filters.PHOTO, handle_photo_wrapper))
    app_bot.add_handler(MessageHandler(filters.Document.ALL, handle_document_wrapper)) # IMPORTANT PENTRU POZE CLARE
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_wrapper))
    print("🤖 Botul Contabil 2026 este ONLINE!")
    app_bot.run_polling()