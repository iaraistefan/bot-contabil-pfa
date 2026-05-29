"""
Interfata (UI) pentru Declaratia Unica in bot.

Ofera doua moduri:
  - AUTOMAT: sumeaza venitul si cheltuielile deductibile din datele
    deja inregistrate in bot, pe anul ales.
  - MANUAL: utilizatorul introduce venitul brut si cheltuielile anuale.

Calculul efectiv (impozit + CAS + CASS) se face in
app/domain/declaratie_unica.py (modul testat separat).
"""

import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db import get_session
from app.services import tax_engine
from app.domain import declaratie_unica as du_calc
from app.repositories import users as users_repo

logger = logging.getLogger(__name__)

BTN_DU = "🧮 Declarația Unică"

# Cheia sub care tinem starea wizardului manual in user_data
_WIZ = "du_wizard"


# ============================================================
#                    HELPERS
# ============================================================

def _parse_suma(text: str):
    """
    Transforma un text introdus de utilizator intr-un numar.
    Accepta formate romanesti: 1.854,50 sau 1854,50 sau 50000.
    Regula: punctele sunt separatori de mii, virgula e separator zecimal.
    """
    if text is None:
        return None
    curat = text.strip().replace(" ", "").replace("lei", "").replace("RON", "")
    curat = curat.replace(".", "").replace(",", ".")
    try:
        val = float(curat)
        if val < 0:
            return None
        return val
    except ValueError:
        return None


def _ani_disponibili(user_id: int):
    """Anii pentru care exista date, plus anul curent si cel precedent."""
    ani = set()
    try:
        from app.models import Transaction
        session = get_session()
        try:
            rows = (
                session.query(Transaction.period_year)
                .filter(Transaction.user_id == user_id)
                .distinct()
                .all()
            )
            ani = set(r[0] for r in rows if r[0])
        finally:
            session.close()
    except Exception as e:
        logger.error(f"_ani_disponibili: {e}")
    acum = datetime.now().year
    ani.add(acum)
    ani.add(acum - 1)
    return sorted(ani, reverse=True)


def _sumar_anual_din_date(user_id: int, an: int):
    """
    Sumeaza venitul (brut incasat) si cheltuielile deductibile din datele
    inregistrate in bot, parcurgand cele 12 luni ale anului.
    Returneaza (venit_brut, cheltuieli_deductibile, nr_luni_cu_date).
    """
    venit_brut = 0.0
    chelt_ded = 0.0
    luni_cu_date = 0
    session = get_session()
    try:
        for luna in range(1, 13):
            try:
                totals = tax_engine.compute_period(
                    session, user_id=user_id, year=an, month=luna
                )
            except Exception:
                continue
            if not totals:
                continue
            inc = totals.get("income_total", 0) or 0
            exp = totals.get("expense_deductible_total", 0) or 0
            if totals.get("tx_count", 0):
                luni_cu_date += 1
            venit_brut += inc
            chelt_ded += exp
    finally:
        session.close()
    return round(venit_brut, 2), round(chelt_ded, 2), luni_cu_date


# ============================================================
#                    PORNIRE (comanda / buton)
# ============================================================

async def _arata_picker_an(send_func, user_id: int):
    ani = _ani_disponibili(user_id)
    rows = []
    rand = []
    for a in ani[:6]:
        rand.append(InlineKeyboardButton(str(a), callback_data=f"du|an|{a}"))
        if len(rand) == 3:
            rows.append(rand)
            rand = []
    if rand:
        rows.append(rand)
    rows.append([InlineKeyboardButton("❌ Închide", callback_data="nav|close")])
    await send_func(
        "🧮 *Declarația Unică (D212)*\n"
        "Calcul impozit + CAS + CASS pentru un an.\n\n"
        "Alege anul de realizare a venitului:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = _resolve_uid(update)
    await _arata_picker_an(update.message.reply_text, user_id)


async def handle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = _resolve_uid(update)
    await _arata_picker_an(update.message.reply_text, user_id)


def _resolve_uid(update: Update):
    """Rezolva user_id-ul intern din telegram_id."""
    tg = update.effective_user
    if not tg:
        return None
    session = get_session()
    try:
        user = users_repo.get_by_telegram_id(session, telegram_id=tg.id)
        return user.id if user else None
    finally:
        session.close()


# ============================================================
#                    CALLBACK (router du|...)
# ============================================================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          parts):
    query = update.callback_query
    user_id = _resolve_uid(update)
    actiune = parts[1] if len(parts) > 1 else ""

    if actiune == "an":
        an = int(parts[2])
        rows = [
            [InlineKeyboardButton("📊 Automat din datele mele",
                                  callback_data=f"du|auto|{an}")],
            [InlineKeyboardButton("✍️ Introduc eu cifrele",
                                  callback_data=f"du|manual|{an}")],
            [InlineKeyboardButton("❌ Închide", callback_data="nav|close")],
        ]
        await query.edit_message_text(
            f"🧮 *Declarația Unică {an}*\n\nCum vrei să calculăm?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if actiune == "auto":
        an = int(parts[2])
        await query.edit_message_text(f"🔄 Calculez din datele pe {an}...")
        venit_brut, chelt_ded, luni = _sumar_anual_din_date(user_id, an)
        if venit_brut <= 0 and chelt_ded <= 0:
            await query.edit_message_text(
                f"📭 Nu am date înregistrate pentru {an}.\n\n"
                f"Folosește varianta manuală (introduci tu cifrele).",
            )
            return
        rez = du_calc.calcul_declaratie_unica(venit_brut, chelt_ded, an=an)
        msg = du_calc.format_telegram(rez)
        msg += (f"\n\n_Calculat automat din {luni} luni cu date "
                f"inregistrate in bot pentru {an}._")
        await query.edit_message_text(msg, parse_mode="Markdown")
        return

    if actiune == "manual":
        an = int(parts[2])
        context.user_data[_WIZ] = {"step": "venit", "an": an}
        await query.edit_message_text(
            f"✍️ *Declarația Unică {an} - manual*\n\n"
            f"Scrie *venitul brut total* încasat în {an} (lei).\n"
            f"_Exemplu: 52300 sau 52.300,50_",
            parse_mode="Markdown",
        )
        return


# ============================================================
#                    WIZARD MANUAL (text)
# ============================================================

def is_in_wizard(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return _WIZ in context.user_data


def cancel_wizard(context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop(_WIZ, None)


async def handle_wizard_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    wiz = context.user_data.get(_WIZ)
    if not wiz:
        return False

    suma = _parse_suma(update.message.text)
    if suma is None:
        await update.message.reply_text(
            "⚠️ Nu am înțeles suma. Scrie doar un număr.\n"
            "_Exemplu: 52300 sau 52.300,50_",
            parse_mode="Markdown",
        )
        return True

    if wiz["step"] == "venit":
        wiz["venit_brut"] = suma
        wiz["step"] = "cheltuieli"
        await update.message.reply_text(
            f"✅ Venit brut: *{suma:.2f}* lei\n\n"
            f"Acum scrie *cheltuielile deductibile totale* din {wiz['an']} (lei).\n"
            f"_Dacă nu ai cheltuieli, scrie 0._",
            parse_mode="Markdown",
        )
        return True

    if wiz["step"] == "cheltuieli":
        venit_brut = wiz["venit_brut"]
        an = wiz["an"]
        cancel_wizard(context)
        rez = du_calc.calcul_declaratie_unica(venit_brut, suma, an=an)
        msg = du_calc.format_telegram(rez)
        await update.message.reply_text(msg, parse_mode="Markdown")
        return True

    return False
