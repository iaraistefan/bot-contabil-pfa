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
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "TOKEN_AICI")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "CHEIE_AICI")
SHEET_NAME = "Contabilitate PFA 2025"
CREDENTIALS_FILE = "credentials.json"

# --- SERVER WEB (PENTRU RENDER) ---
app = Flask('')
@app.route('/')
def home():
    return "Botul Contabil Expert este ONLINE!"

def run_http():
    port_render = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port_render)

def keep_alive():
    t = Thread(target=run_http)
    t.start()

# --- INITIALIZARE ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
client_openai = OpenAI(api_key=OPENAI_API_KEY)

# --- SCRIERE IN EXCEL ---
def write_to_sheet(sheet_tab_name, row_data):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open(SHEET_NAME)
        
        tab_name_upper = str(sheet_tab_name).upper()
        
        # 1. Scrie in Tab-ul specific (BOLT / UBER / CHELTUIELI)
        try:
            worksheet = spreadsheet.worksheet(tab_name_upper)
            worksheet.append_row(row_data)
        except:
            pass 

        # 2. Scrie in GENERAL (Centralizator)
        if tab_name_upper != "GENERAL":
            try:
                general_sheet = spreadsheet.worksheet("GENERAL")
                general_sheet.append_row(row_data)
            except Exception as e:
                logging.error(f"Eroare scriere General: {e}")
            
    except Exception as e:
        logging.error(f"Eroare critica Excel: {e}")

# --- CREIERUL AI (LOGICA NOUA) ---
def ask_gpt_logic(user_input, image_base64=None):
    today = datetime.now().strftime("%d.%m.%Y")
    
    system_prompt = f"""
    Esti un contabil AI meticulos. Analizeaza documentul si extrage datele EXACTE.
    DATA CURENTA (de rezerva): {today}.

    TREBUIE SA DETECTEZI TIPUL DOCUMENTULUI SI SA APLICI REGULILE:

    SCENARIUL 1: RAPORT ZILNIC/SAPTAMANAL (Aplicatie Bolt/Uber - fundal negru)
    - Tip: "VENIT_ESTIMAT"
    - Platforma: Bolt sau Uber.
    - Brut = Venit Aplicatie + Numerar.
    - Comision = Taxa aplicatie (nr pozitiv).
    - TVA = 21% din Comision (Aceasta e o estimare zilnica).
    - Net = Brut - Comision.
    - Cash = Numerar/Colectat numerar.
    - Detalii: "Incasari aplicatie"

    SCENARIUL 2: FACTURA FISCALA DE COMISION (Document A4, Bolt Operations/Uber BV)
    - Tip: "FACTURA_COMISION" (Aceasta e baza pentru declaratia 301)
    - Platforma: Bolt sau Uber.
    - Brut = 0 (Nu e venit).
    - Comision = Valoarea TOTALA a facturii (ex: 346.81).
    - TVA = 21% din valoarea facturii (ACESTA ESTE DE PLATA LA ANAF).
    - Net = Valoarea facturii cu minus (ex: -346.81).
    - Cash = 0.
    - Detalii: "Factura Comision [Luna]"

    SCENARIUL 3: BON FISCAL / FACTURA CHELTUIELI (Combustibil, Piese, Consumabile)
    - Tip: "CHELTUIALA"
    - Platforma: "CHELTUIELI"
    - Brut = Totalul de pe bon.
    - Comision = 0.
    - TVA = 0 (Pe bon TVA-ul e deja platit, nu il mai declari separat la 301).
    - Net = 0.
    - Cash = 0 (Nu e venit cash).
    - DETALII CRITIC: Citeste lista de produse de pe bon! 
      Exemple corecte: "Motorina + Lichid Parbriz", "Ulei Motor + Filtru", "Spalatorie Auto".
      NU scrie generic "Bon".

    OUTPUT JSON STRICT (Fara ```json):
    [
      {{
        "data": "DD.MM.YYYY",
        "platforma": "...",
        "tip": "...",
        "brut": 0.00,
        "comision": 0.00,
        "tva": 0.00,
        "net": 0.00,
        "cash": 0.00,
        "detalii": "..."
      }}
    ]
    """

    messages = [{"role": "system", "content": system_prompt}]
    
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
        return response.choices[0].message.content
    except Exception as e:
        return "EROARE_AI"

# --- PROCESARE ---
async def process_entry(update, context, text_input=None, image_file=None):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="🔍 Analizez documentul...")

    try:
        image_base64 = None
        prompt_text = text_input
        
        if image_file:
            file_byte = await image_file.download_as_bytearray()
            image_base64 = base64.b64encode(file_byte).decode('utf-8')
            if not prompt_text: prompt_text = "Analizeaza detaliat"

        ai_response = ask_gpt_logic(prompt_text, image_base64)
        clean_json = ai_response.replace("```json", "").replace("```", "").strip()
        
        try:
            data_list = json.loads(clean_json)
        except:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Nu am putut citi documentul clar. Te rog trimite o poză mai clară.")
            return

        msg_confirm = "✅ **Salvat:**\n"

        for item in data_list:
            # Calcul Banca doar pentru Venituri din aplicatie
            net = float(item.get('net', 0))
            cash = float(item.get('cash', 0))
            tip = item.get('tip')
            
            banca = 0
            if tip == 'VENIT_ESTIMAT':
                banca = net - cash
            
            # Structura rândului pentru Excel
            row = [
                item.get('data'),
                item.get('platforma'),
                tip,
                item.get('brut', 0),
                item.get('comision', 0),
                item.get('tva', 0),
                net,
                cash,
                banca, 
                item.get('detalii')
            ]

            write_to_sheet(item.get('platforma'), row)

            # Mesaj personalizat in functie de tip
            if tip == 'FACTURA_COMISION':
                msg_confirm += (f"📄 **FACTURA COMISION {item['platforma']}**\n"
                                f"📅 Data: {item['data']}\n"
                                f"💵 Total Factura: {item['comision']} RON\n"
                                f"🏛️ **TVA DE PLATA (Declaratia 301): {item['tva']} RON**\n"
                                f"ℹ️ Aceasta suma bate aplicatia!")
            
            elif tip == 'CHELTUIALA':
                msg_confirm += (f"🛒 **{item['detalii']}**\n"
                                f"📅 {item['data']}\n"
                                f"💸 Total: {item['brut']} RON\n")
            
            else: # Venit Zilnic
                msg_confirm += (f"🚖 **{item['platforma']}** ({item['data']})\n"
                                f"💰 Net: {net} RON | 🏦 TVA Estimat: {item['tva']} RON\n")

        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg_confirm)

    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Eroare: {str(e)}")

# --- WRAPPERS ---
async def handle_photo_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_file = await update.message.photo[-1].get_file()
    caption = update.message.caption 
    await process_entry(update, context, text_input=caption, image_file=new_file)

async def handle_text_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_entry(update, context, text_input=update.message.text)

if __name__ == '__main__':
    keep_alive()
    app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_bot.add_handler(MessageHandler(filters.PHOTO, handle_photo_wrapper))
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_wrapper))
    print("🤖 Botul Contabil V2 este ONLINE!")
    app_bot.run_polling()