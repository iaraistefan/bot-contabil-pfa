"""
Ghid de obligații — surfața Telegram (sub-pas Ghid 2 + 3).

/ghid: listă (grupată pe frecvență) → tap → card pedagogic. Sub-pas 3 = PERSONALIZARE:
default afișează DOAR obligațiile userului (filtrat pe profil), cu toggle „vezi toate".

SURSĂ UNICĂ: textul vine din `DEFINITII_OBLIGATII` (registru, sub-pas 1) via
`fiscal_calendar.ghid_grupuri`; lista de coduri via `ghid_codes_for_user` (același
helper folosit și de web /api/v1/ghid). ZERO duplicare.

Anti-omisiune (ca fiscal #4): un profil INCOMPLET (onboarding neterminat) → afișăm
TOATE (NU lista filtrată, care ar ascunde D100/D301/D390/D700 unui profil „generic"
→ userul ar crede fals că n-are acele obligații) + nudge de completare profil.
"""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from app.domain.fiscal_calendar import DEFINITII_OBLIGATII, ghid_grupuri, ghid_obligation_codes

logger = logging.getLogger(__name__)

# Cheia internă a registrului per cod ANAF (codul din definiție e „D100 poz. 634").
_KEY_BY_COD = {d.cod: key for key, d in DEFINITII_OBLIGATII.items()}


def ghid_codes_for_user(session, user_id, *, force_all=False):
    """
    Codurile de afișat în ghid pentru un user → (codes, personalizat, nudge).

    - `force_all=True` → TOATE (userul a cerut explicit „vezi toate").
    - profil INCOMPLET (`onboarding_completed` False) → TOATE + nudge. ANTI-OMISIUNE:
      un profil „generic" filtrat ar ascunde D100/D301/D390/D700 (sunt pe
      activitati=ridesharing) → NU ascundem nimic până nu e profilul complet.
    - altfel → FILTRAT pe profil (`ghid_obligation_codes(profile, ctx)`) = ghidul TĂU.

    SURSĂ UNICĂ pentru ambele surfețe (Telegram + web /api/v1/ghid).
    """
    if force_all:
        return ghid_obligation_codes(), False, False

    from app.repositories import users as users_repo
    user = users_repo.get_by_id(session, user_id)
    if user is None or not getattr(user, "onboarding_completed", False):
        return ghid_obligation_codes(), False, True   # toate + nudge (anti-omisiune)

    from app.domain.fiscal_profile import from_user_id
    from app.services import plata_fiscala
    fiscal_profile = from_user_id(session, user_id)
    profile_dict = users_repo.get_profile_dict(session, user_id) or {}
    ctx = plata_fiscala._profile_to_guardian_context(fiscal_profile, profile_dict)
    return ghid_obligation_codes(fiscal_profile, ctx), True, False


def _scurt(nume: str) -> str:
    s = nume.split("(")[0].strip()
    return s if len(s) <= 38 else s[:37] + "…"


def _kb_lista(codes, personalizat: bool) -> InlineKeyboardMarkup:
    """Listă grupată pe frecvență pentru `codes` + toggle personalizat/toate."""
    rows = []
    for grup in ghid_grupuri(codes):
        rows.append([InlineKeyboardButton(f"── {grup['label']} ──", callback_data="nav|noop")])
        for d in grup["obligatii"]:
            key = _KEY_BY_COD.get(d.cod, d.cod)
            rows.append([InlineKeyboardButton(
                f"{d.cod.split(' poz')[0]} — {_scurt(d.nume)}",
                callback_data=f"ghid|view|{key}")])
    # Toggle: din personalizat → vezi toate; din toate → doar ale mele.
    if personalizat:
        rows.append([InlineKeyboardButton("👁️ Vezi toate declarațiile", callback_data="ghid|all")])
    else:
        rows.append([InlineKeyboardButton("📋 Doar ale mele", callback_data="ghid|list")])
    rows.append([InlineKeyboardButton("❌ Închide", callback_data="nav|close")])
    return InlineKeyboardMarkup(rows)


def _kb_card() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Înapoi la listă", callback_data="ghid|list"),
        InlineKeyboardButton("❌ Închide", callback_data="nav|close"),
    ]])


def _intro(personalizat: bool, nudge: bool) -> str:
    if personalizat:
        cap = ("📖 *Ghidul TĂU fiscal*\n━━━━━━━━━━━━━━━━━━━━\n\n"
               "Doar obligațiile TALE, explicate pe înțeles — *ce e*, *cine*, *când*, "
               "*cum* și mai ales *de ce e obligația TA*.")
    else:
        cap = ("📖 *Ghidul fiscal — toate declarațiile*\n━━━━━━━━━━━━━━━━━━━━\n\n"
               "Toate obligațiile, explicate pe înțeles.")
    if nudge:
        cap += ("\n\n📝 _Profilul tău nu e complet — îți arăt TOT (nu ascundem nimic). "
                "Completează-l cu /start ca să vezi doar ce te privește pe tine._")
    cap += "\n\nApasă o declarație (grupate după cât de des le ai):"
    return cap


def _card(key: str) -> str:
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


def _lista_pentru(user_id, *, force_all=False):
    """(text, keyboard) pentru lista de ghid a unui user — SURSĂ UNICĂ ghid_codes_for_user."""
    from db import get_session
    session = get_session()
    try:
        codes, personalizat, nudge = ghid_codes_for_user(session, user_id, force_all=force_all)
    finally:
        session.close()
    return _intro(personalizat, nudge), _kb_lista(codes, personalizat)


def _user_id(update: Update):
    from db import get_session
    from app.repositories import users as users_repo
    session = get_session()
    try:
        user = users_repo.get_by_telegram_id(session, telegram_id=update.effective_user.id)
        return user.id if user else None
    finally:
        session.close()


async def handle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ghid — listă PERSONALIZATĂ (obligațiile userului) + toggle „vezi toate"."""
    user_id = _user_id(update)
    if user_id is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="⚠️ Nu te-am putut identifica. Deschide din /start.")
        return
    text, kb = _lista_pentru(user_id)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=text, parse_mode="Markdown", reply_markup=kb)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts):
    """ghid|view|<key> (card) · ghid|list (personalizat) · ghid|all (toate)."""
    query = update.callback_query
    action = parts[1] if len(parts) > 1 else ""

    if action == "view":
        key = parts[2] if len(parts) > 2 else ""
        await query.edit_message_text(_card(key), parse_mode="Markdown", reply_markup=_kb_card())
        return

    # list (personalizat) / all (toate) — re-randează lista
    user = update.effective_user
    from db import get_session
    from app.repositories import users as users_repo
    session = get_session()
    try:
        u = users_repo.get_by_telegram_id(session, telegram_id=user.id)
        uid = u.id if u else None
    finally:
        session.close()
    if uid is None:
        await query.edit_message_text("⚠️ Nu te-am putut identifica. Deschide din /start.")
        return
    text, kb = _lista_pentru(uid, force_all=(action == "all"))
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
