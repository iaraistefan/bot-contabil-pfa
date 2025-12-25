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

# --- CONFIGURARE ---
TELEGRAM_TOKEN = "8557712194:AAHEmAPAVRr_qG_xnKlTUNeb6t_OS_3rJB0"
OPENAI_API_KEY = "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"
SHEET_NAME = "Contabilitate PFA 2025" 
CREDENTIALS_FILE = "credentials.json"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
client_openai = OpenAI(api_key=OPENAI_API_KEY)

# --- SCRIERE IN EXCEL (Reparat pentru MAJUSCULE) ---
def write_to_sheet(sheet_tab_name, row_data):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open(SHEET_NAME)
        
        # Fortam numele tab-ului sa fie cu LITERE MARI (ex: "Bolt" devine "BOLT")
        tab_name_upper = str(sheet_tab_name).upper()
        
        # 1. Scrie in tab-ul specific (BOLT/UBER/CHELTUIELI)
        try:
            worksheet = spreadsheet.worksheet(tab_name_upper)
            worksheet.append_row(row_data)
        except gspread.exceptions.WorksheetNotFound:
            logging.warning(f"Nu am gasit tab-ul {tab_name_upper}, sar peste el.")
        except Exception as e:
            logging.error(f"Eroare la scrierea in tab-ul specific: {e}")

        # 2. Scrie SI in GENERAL (Tot cu litere mari)
        if tab_name_upper != "GENERAL":
            try:
                general_sheet = spreadsheet.worksheet("GENERAL")
                general_sheet.append_row(row_data)
            except Exception as e:
                logging.error(f"Eroare la scrierea in GENERAL: {e}")
            
    except Exception as e:
        # Aici prindem eroarea principala de acces
        logging.error(f"EROARE CRITICA EXCEL (Verifica SHARE la email): {e}")

# --- ANALIZA AI ---
def ask_gpt_logic(user_input, image_base64=None):
    today = datetime.now().strftime("%d.%m.%Y")
    
    system_prompt = f"""
    Esti contabil PFA Ridesharing. Analizeaza imaginea si extrage datele.
    Data: {today}.

    REGULI DE CALCUL:
    1. PLATFORMA: Bolt, Uber sau Cheltuieli.
    2. SUME:
       - BRUT = Venituri aplicatie + Venituri numerar.
       - COMISION = Taxa retinuta de aplicatie (transforma in numar pozitiv).
       - TVA = 21% din Comision.
       - NET = Castigurile tale (suma finala ramasa).
       - CASH = Cauta "Numerar in mana" sau "Colectat numerar". Daca nu exista, foloseste "Venituri numerar".
    
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

            # Trimitem numele platformei, functia il va face UPPERCASE automat
            write_to_sheet(item.get('platforma'), row)

            if item['tip'] == 'VENIT':
                msg_confirm += (f"🚖 {item['platforma']}\n"
                                f"💰 Net Total: {net} RON\n"
                                f"💵 Cash (Mana): {cash} RON\n"
                                f"💳 Banca (Card): {banca:.2f} RON\n"
                                f"🏛️ TVA: {item['tva']} RON\n\n")
            else:
                 msg_confirm += f"⛽ Cheltuiala: {item.get('brut')} RON\n"

        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg_confirm)

    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Eroare: {str(e)}")

# --- HANDLERS ---
async def handle_photo_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_file = await update.message.photo[-1].get_file()
    await process_entry(update, context, image_file=new_file)

async def handle_text_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_entry(update, context, text_input=update.message.text)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_wrapper))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_wrapper))
    
    print("🤖 Botul este ACTIV. Verificati SHARE la email inainte de utilizare!")
    app.run_polling()