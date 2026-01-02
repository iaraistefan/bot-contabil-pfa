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

# --- CONFIGURARE (Citim din Environment sau folosim fallback) ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "PUNE_TOKENUL_AICI_DACA_RULEZI_LOCAL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "PUNE_CHEIA_OPENAI_AICI_DACA_RULEZI_LOCAL")
SHEET_NAME = "Contabilitate PFA 2025"
CREDENTIALS_FILE = "credentials.json"

# --- KEEP ALIVE (SERVER WEB PENTRU RENDER) ---
# Aceasta este partea care repara eroarea "Port scan timeout"
app = Flask('')

@app.route('/')
def home():
    return "Botul Contabil este ONLINE si Sanatos!"

def run_http():
    # TRUCUL: Citim portul pe care il vrea Render. Daca nu zice nimic, folosim 8080.
    port_render = int(os.environ.get("PORT", 8080))
    # Ascultam pe toate interfetele (0.0.0.0) la portul corect
    app.run(host='0.0.0.0', port=port_render)

def keep_alive():
    t = Thread(target=run_http)
    t.start()

# --- LOGICA BOTULUI ---
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
        
        try:
            worksheet = spreadsheet.worksheet(tab_name_upper)
            worksheet.append_row(row_data)
        except:
            pass

        if tab_name_upper != "GENERAL":
            try:
                general_sheet = spreadsheet.worksheet("GENERAL")
                general_sheet.append_row(row_data)
            except:
                pass
            
    except Exception as e:
        logging.error(f"Eroare critica Excel: {e}")

# --- ANALIZA AI (TVA 21%) ---
def ask_gpt_logic(user_input, image_base64=None):
    today = datetime.now().strftime("%d.%m.%Y")
    
    system_prompt = f"""
    Esti contabil PFA Ridesharing. Analizeaza imaginea si extrage datele.
    Data: {today}.

    REGULI DE CALCUL:
    1. PLATFORMA: Bolt, Uber sau Cheltuieli.
    2. SUME:
       - BRUT = Venituri aplicatie + Venituri numerar.
       - COMISION = Taxa retinuta de aplicatie.
       - TVA = 21% din Comision. (Conform legislatiei noi).
       - NET = Castigurile tale.
       - CASH = Cauta "Numerar in mana" sau "Colectat numerar".
    
    OUTPUT JSON:
    [
      {{
        "data": "DD.MM.YYYY",
        "platforma": "Bolt", 
        "tip": "VENIT",
        "brut": 0.00,
        "comision": 0.00,
        "tva": 0.00,
        "net": 0.00,
        "cash": 0.00,
        "detalii": "Text scurt"
      }}
    ]
    """

    messages = [{"role": "system", "content": system_prompt}]
    if image_base64:
        messages.append({
            "role": "user", 
            "content": [
                {"type": "text", "text": "Analizeaza raportul."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
            ]
        })
    else:
        messages.append({"role": "user", "content": user_input})

    response = client_openai.chat.completions.create(model="gpt-4o", messages=messages, max_tokens=600)
    return response.choices[0].message.content

# --- PROCESARE ---
async def process_entry(update, context, text_input=None, image_file=None):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="🧮 Calculez...")
    try:
        image_base64 = None
        user_msg = text_input if text_input else "Analizeaza"

        if image_file:
            file_byte = await image_file.download_as_bytearray()
            image_base64 = base64.b64encode(file_byte).decode('utf-8')

        json_str = ask_gpt_logic(user_msg, image_base64)
        clean_json = json_str.replace("```json", "").replace("```", "").strip()
        data_list = json.loads(clean_json)

        msg_confirm = "✅ **Inregistrat:**\n"
        for item in data_list:
            net = float(item.get('net', 0))
            cash = float(item.get('cash', 0))
            banca = net - cash 

            row = [item.get('data'), item.get('platforma'), item.get('tip'), item.get('brut', 0), item.get('comision', 0), item.get('tva', 0), net, cash, banca, item.get('detalii')]
            write_to_sheet(item.get('platforma'), row)

            if item['tip'] == 'VENIT':
                msg_confirm += (f"🚖 {item['platforma']}\n💰 Net: {net} RON\n💵 Cash: {cash} RON\n💳 Banca: {banca:.2f} RON\n🏛️ TVA (21%): {item['tva']} RON\n\n")
            else:
                 msg_confirm += f"⛽ Cheltuiala: {item.get('brut')} RON\n"

        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg_confirm)
    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Eroare: {str(e)}")

async def handle_photo_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_file = await update.message.photo[-1].get_file()
    await process_entry(update, context, image_file=new_file)

async def handle_text_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_entry(update, context, text_input=update.message.text)

if __name__ == '__main__':
    # 1. Pornim serverul web pentru Render
    keep_alive()
    
    # 2. Pornim botul
    app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_bot.add_handler(MessageHandler(filters.PHOTO, handle_photo_wrapper))
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_wrapper))
    
    print("🤖 Botul este ONLINE si asculta pe portul cerut de Render!")
    app_bot.run_polling()