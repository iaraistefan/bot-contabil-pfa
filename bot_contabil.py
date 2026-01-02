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
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "PUNE_TOKEN_DACA_TESTEZI_LOCAL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "PUNE_CHEIE_DACA_TESTEZI_LOCAL")
SHEET_NAME = "Contabilitate PFA 2025"
CREDENTIALS_FILE = "credentials.json"

# --- KEEP ALIVE (PENTRU RENDER) ---
app = Flask('')

@app.route('/')
def home():
    return "Botul este ACTIV!"

def run_http():
    port_render = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port_render)

def keep_alive():
    t = Thread(target=run_http)
    t.start()

# --- LOGGING ---
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
        
        # Incercam sa scriem in Tab-ul specific
        try:
            worksheet = spreadsheet.worksheet(tab_name_upper)
            worksheet.append_row(row_data)
        except:
            pass # Daca nu exista tab-ul, nu e panica

        # Scriem OBLIGATORIU in GENERAL
        if tab_name_upper != "GENERAL":
            try:
                general_sheet = spreadsheet.worksheet("GENERAL")
                general_sheet.append_row(row_data)
            except Exception as e:
                logging.error(f"Eroare scriere General: {e}")
            
    except Exception as e:
        logging.error(f"Eroare critica Excel: {e}")

# --- ANALIZA AI ---
def ask_gpt_logic(user_input, image_base64=None):
    today = datetime.now().strftime("%d.%m.%Y")
    
    system_prompt = f"""
    Esti un contabil AI expert. Sarcina ta este sa extragi date structurate din text sau imagini (bonuri fiscale, rapoarte Bolt/Uber).
    
    DATA CURENTA DE REZERVA: {today}.

    REGULI CRITICE:
    1. **DATA:** Cauta cu disperare data PE BON/IMAGINE. Doar daca este ilizibila sau lipseste complet, foloseste data curenta de rezerva.
    2. **PLATFORMA:** Identifica daca e Bolt, Uber sau "Cheltuieli" (bonuri combustibil, spalatorie, piese).
    3. **SUME:**
       - Daca e Raport Bolt/Uber: Brut = Venit Aplicatie + Numerar. Comision = Taxa aplicatie (pozitiv). TVA = 21% din comision. Net = Brut - Comision.
       - Daca e BON FISCAL (Cheltuieli): Brut = Totalul de pe bon. Comision=0. TVA=0. Net=0.
    4. **OUTPUT:** Returneaza DOAR un JSON valid, fara ```json in fata sau spate. Fara alte comentarii.

    FORMAT JSON ASTEPTAT:
    [
      {{
        "data": "DD.MM.YYYY",
        "platforma": "Bolt" sau "Uber" sau "CHELTUIELI",
        "tip": "VENIT" sau "CHELTUIALA",
        "brut": 100.50,
        "comision": 20.00,
        "tva": 4.20,
        "net": 76.30,
        "cash": 50.00,
        "detalii": "Bon Motorina OMV"
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
            model="gpt-4o", 
            messages=messages, 
            max_tokens=600,
            temperature=0.2 # Mai strict, mai putin creativ
        )
        return response.choices[0].message.content
    except Exception as e:
        return "EROARE_AI"

# --- PROCESARE ---
async def process_entry(update, context, text_input=None, image_file=None):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="⏳ Analizez imaginea...")

    try:
        image_base64 = None
        
        # Daca e poza, o pregatim
        if image_file:
            file_byte = await image_file.download_as_bytearray()
            image_base64 = base64.b64encode(file_byte).decode('utf-8')
            prompt_text = text_input if text_input else "Analizeaza bonul/raportul"
        else:
            prompt_text = text_input

        # Trimitem la AI
        ai_response = ask_gpt_logic(prompt_text, image_base64)
        
        # Curatam raspunsul (scoatem ```json daca exista)
        clean_json = ai_response.replace("```json", "").replace("```", "").strip()
        
        # --- FIXUL PENTRU EROAREA TA ---
        try:
            data_list = json.loads(clean_json)
        except json.JSONDecodeError:
            # Daca AI-ul nu a dat JSON corect (bon neclar)
            await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ **Nu am putut citi bonul.**\nEste posibil să fie neclar, șifonat sau rotit.\nTe rog fă o poză mai clară, verticală.")
            return

        msg_confirm = "✅ **Salvat:**\n"

        for item in data_list:
            # Calculam Banca doar daca e Venit
            net = float(item.get('net', 0))
            cash = float(item.get('cash', 0))
            banca = 0
            if item.get('tip') == 'VENIT':
                banca = net - cash

            row = [
                item.get('data'),
                item.get('platforma'),
                item.get('tip'),
                item.get('brut', 0),
                item.get('comision', 0),
                item.get('tva', 0),
                net,
                cash,
                banca, 
                item.get('detalii')
            ]

            write_to_sheet(item.get('platforma'), row)

            if item['tip'] == 'VENIT':
                msg_confirm += (f"🚖 {item['platforma']} ({item['data']})\n"
                                f"💰 Net: {net} RON | 🏦 TVA: {item['tva']} RON\n")
            else:
                 msg_confirm += f"⛽ {item['platforma']} ({item['data']})\n💸 Total: {item.get('brut')} RON\n📝 {item.get('detalii')}\n"

        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg_confirm)

    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Eroare tehnică: {str(e)}")

# --- WRAPPERS ---
async def handle_photo_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Luam poza la rezolutie maxima
    new_file = await update.message.photo[-1].get_file()
    # Verificam daca userul a scris si text sub poza (Caption)
    caption = update.message.caption 
    await process_entry(update, context, text_input=caption, image_file=new_file)

async def handle_text_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_entry(update, context, text_input=update.message.text)

if __name__ == '__main__':
    keep_alive()
    app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_bot.add_handler(MessageHandler(filters.PHOTO, handle_photo_wrapper))
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_wrapper))
    print("🤖 Botul este UPGRADE-AT si ONLINE!")
    app_bot.run_polling()