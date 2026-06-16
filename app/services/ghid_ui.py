"""
Ghid de obligații — surfața Telegram (sub-pas Ghid 2).

Comanda /ghid: listă grupată pe frecvență (lunar / anual / o dată) → tap pe o
declarație → card pedagogic (ce e / cui / când / cum / de ce TU / penalty).

SURSĂ UNICĂ: tot textul vine din `DEFINITII_OBLIGATII` (registrul pedagogic,
sub-pas 1) via `fiscal_calendar.ghid_grupuri`. ZERO duplicare de conținut —
aceeași definiție alimentează și web (/api/v1/ghid).

Oglindă structurală a `plata_fiscala` (command → picker → callback list/view).
Sub-pas 2 afișează TOATE declarațiile; personalizarea pe profil = sub-pas 3
(prin `ghid_obligation_codes(profile, ctx)`, fără rescrierea acestui modul).
"""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from app.domain.fiscal_calendar import DEFINITII_OBLIGATII, ghid_grupuri

logger = logging.getLogger(__name__)

# Cheia internă a registrului per cod ANAF (codul din definiție e „D100 poz. 634").
_KEY_BY_COD = {d.cod: key for key, d in DEFINITII_OBLIGATII.items()}


def _scurt(nume: str) -> str:
    """Etichetă scurtă de buton din nume (taie la prima paranteză / lungime)."""
    s = nume.split("(")[0].strip()
    return s if len(s) <= 38 else s[:37] + "…"


def _kb_lista() -> InlineKeyboardMarkup:
    """Listă grupată pe frecvență: antet de grup (noop) + buton per declarație."""
    rows = []
    for grup in ghid_grupuri():            # TOATE (sub-pas 2)
        rows.append([InlineKeyboardButton(f"── {grup['label']} ──",
                                          callback_data="nav|noop")])
        for d in grup["obligatii"]:
            key = _KEY_BY_COD.get(d.cod, d.cod)
            rows.append([InlineKeyboardButton(
                f"{d.cod.split(' poz')[0]} — {_scurt(d.nume)}",
                callback_data=f"ghid|view|{key}")])
    rows.append([InlineKeyboardButton("❌ Închide", callback_data="nav|close")])
    return InlineKeyboardMarkup(rows)


def _kb_card() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Înapoi la listă", callback_data="ghid|list"),
        InlineKeyboardButton("❌ Închide", callback_data="nav|close"),
    ]])


_INTRO = (
    "📖 *Ghidul tău fiscal*\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "Fiecare declarație, explicată pe înțeles — *ce e*, *cine*, *când*, *cum* și "
    "mai ales *de ce e obligația TA*.\n\n"
    "Apasă o declarație (grupate după cât de des le ai):"
)


def _card(key: str) -> str:
    """Cardul pedagogic complet al unei declarații — DIN registru, nu hardcodat."""
    d = DEFINITII_OBLIGATII.get(key)
    if d is None:
        return "⚠️ Declarație necunoscută."
    linii = [f"📖 *{d.cod} — {d.nume}*", "━━━━━━━━━━━━━━━━━━━━", ""]
    if d.ce_e:
        linii += [f"🔹 *Ce e?*\n{d.ce_e}", ""]
    if d.cui_se_aplica:
        linii += [f"👤 *Cui se aplică?*\n{d.cui_se_aplica}", ""]
    if d.cand:
        linii += [f"📅 *Când?*\n{d.cand}", ""]
    if d.cum_depun:
        linii += [f"📝 *Cum depun?*\n{d.cum_depun}", ""]
    if d.de_ce:
        linii += [f"💡 *De ce?*\n{d.de_ce}", ""]
    if d.penalty_info:
        linii += [f"⚠️ *Dacă nu depui:*\n{d.penalty_info}"]
    return "\n".join(linii).strip()


async def handle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ghid — afișează lista grupată a declarațiilor."""
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=_INTRO,
        parse_mode="Markdown", reply_markup=_kb_lista(),
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts):
    """Callback-uri namespace 'ghid': ghid|list (re-listă) · ghid|view|<key> (card)."""
    query = update.callback_query
    action = parts[1] if len(parts) > 1 else ""

    if action == "view":
        key = parts[2] if len(parts) > 2 else ""
        await query.edit_message_text(
            _card(key), parse_mode="Markdown", reply_markup=_kb_card())
        return

    # action == "list" (sau orice altceva) → înapoi la listă
    await query.edit_message_text(
        _INTRO, parse_mode="Markdown", reply_markup=_kb_lista())
