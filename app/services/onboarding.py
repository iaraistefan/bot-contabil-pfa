"""
Sistem de onboarding interactiv pentru utilizatorii noi.

Flow conversational pas cu pas:
  Step 1: Numele personal (text)
  Step 2: Formă juridică (butoane)
  Step 3: CUI (text → ANAF lookup → confirmare)
  Step 4: Activitate (cele 10 + Altul)
  Step 5: Regim TVA (auto din ANAF sau butoane)
  Step 6: Regim impunere (depinde de formă juridică)
  Step 7: Confirmare finală
  Step 99: COMPLETED
"""

import logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import ContextTypes

from db import get_session
from app.repositories import users as users_repo
from app.integrations.anaf_lookup import lookup_cui

logger = logging.getLogger(__name__)


# === Pași onboarding ===
STEP_NOT_STARTED = 0
STEP_NUME_PERSONAL = 1
STEP_FORMA_JURIDICA = 2
STEP_CUI = 3
STEP_ACTIVITATE = 4
STEP_REGIM_TVA = 5
STEP_REGIM_IMPUNERE = 6
STEP_CONFIRMARE = 7
STEP_COMPLETED = 99


# === Cele 10 activități ===
ACTIVITIES = [
    {"code": "ridesharing", "label": "🚗 Ridesharing (Bolt/Uber)", "caen": "4932"},
    {"code": "it_freelance", "label": "💻 IT / Programare", "caen": "6201"},
    {"code": "ecommerce", "label": "🛒 E-commerce / Comerț online", "caen": "4791"},
    {"code": "consulting", "label": "📊 Consultanță / Servicii business", "caen": "7022"},
    {"code": "construction", "label": "🔨 Construcții / Meserii", "caen": "4399"},
    {"code": "medical", "label": "⚕️ Cabinet medical / Stomatologic", "caen": "8621"},
    {"code": "transport", "label": "🚛 Transport marfă", "caen": "4941"},
    {"code": "real_estate", "label": "🏠 Imobiliare (chirii)", "caen": "6820"},
    {"code": "education", "label": "🎓 Educație / Cursuri", "caen": "8559"},
    {"code": "generic", "label": "📌 Alte servicii", "caen": ""},
]
ACTIVITIES_BY_CODE = {a["code"]: a for a in ACTIVITIES}


# === Forme juridice ===
FORME_JURIDICE = [
    {"code": "PFA", "label": "🧑‍💼 PFA — Persoană Fizică Autorizată"},
    {"code": "II", "label": "🏪 Întreprindere Individuală (II)"},
    {"code": "IF", "label": "👨‍👩‍👧 Întreprindere Familială (IF)"},
    {"code": "SRL_MICRO", "label": "🏢 SRL — Microîntreprindere"},
    {"code": "SRL_NORMAL", "label": "🏛️ SRL/SA — Impozit profit"},
    {"code": "PROFESIE_LIBERALA", "label": "⚕️ Profesie liberală"},
]
FORME_BY_CODE = {f["code"]: f for f in FORME_JURIDICE}


# === Regim TVA ===
REGIMURI_TVA = [
    {"code": "NEPLATITOR", "label": "❌ Neplătitor TVA"},
    {"code": "PLATITOR_21", "label": "✅ Plătitor TVA (21%)"},
]
REGIM_TVA_BY_CODE = {r["code"]: r for r in REGIMURI_TVA}


# === Regim impunere — depinde de forma juridică ===
REGIM_IMPUNERE_PFA = [
    {"code": "SISTEM_REAL", "label": "📊 Sistem real (cheltuieli reale)"},
    {"code": "NORMA_VENIT", "label": "📋 Normă de venit (sumă fixă)"},
]
REGIM_IMPUNERE_SRL_MICRO = [
    {"code": "MICRO_1", "label": "🟢 Micro 1% (cu salariat)"},
    {"code": "MICRO_3", "label": "🟡 Micro 3% (fără salariat)"},
    {"code": "SISTEM_REAL", "label": "🔵 Impozit profit (16%)"},
]
REGIM_IMPUNERE_SRL_NORMAL = [
    {"code": "SISTEM_REAL", "label": "🔵 Impozit profit (16%)"},
]


def get_regimuri_for_forma(forma_juridica: str):
    if forma_juridica in ("PFA", "II", "IF", "PROFESIE_LIBERALA"):
        return REGIM_IMPUNERE_PFA
    if forma_juridica == "SRL_MICRO":
        return REGIM_IMPUNERE_SRL_MICRO
    if forma_juridica == "SRL_NORMAL":
        return REGIM_IMPUNERE_SRL_NORMAL
    return REGIM_IMPUNERE_PFA


def regim_impunere_label(code: str) -> str:
    return {
        "SISTEM_REAL": "Sistem real",
        "NORMA_VENIT": "Normă de venit",
        "MICRO_1": "Micro 1%",
        "MICRO_3": "Micro 3%",
    }.get(code, code or "—")


# ============================================================
#                    KEYBOARD BUILDERS
# ============================================================

def _kb_skip(skip_target: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭️ Skip", callback_data=f"onb|skip|{skip_target}")],
        [InlineKeyboardButton("❌ Anulează", callback_data="onb|cancel")],
    ])


def _kb_forma_juridica():
    rows = []
    for f in FORME_JURIDICE:
        rows.append([InlineKeyboardButton(
            f["label"], callback_data=f"onb|forma|{f['code']}"
        )])
    rows.append([InlineKeyboardButton("⏭️ Skip", callback_data="onb|skip|forma")])
    return InlineKeyboardMarkup(rows)


def _kb_activity():
    rows = []
    for a in ACTIVITIES:
        rows.append([InlineKeyboardButton(
            a["label"], callback_data=f"onb|activity|{a['code']}"
        )])
    return InlineKeyboardMarkup(rows)


def _kb_regim_tva():
    rows = []
    for r in REGIMURI_TVA:
        rows.append([InlineKeyboardButton(
            r["label"], callback_data=f"onb|tva|{r['code']}"
        )])
    return InlineKeyboardMarkup(rows)


def _kb_regim_tva_confirm():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Da, e corect", callback_data="onb|tva_confirm|yes")],
        [InlineKeyboardButton("✏️ Vreau să schimb", callback_data="onb|tva_confirm|change")],
    ])


def _kb_regim_impunere(forma: str):
    regimuri = get_regimuri_for_forma(forma)
    rows = []
    for r in regimuri:
        rows.append([InlineKeyboardButton(
            r["label"], callback_data=f"onb|impunere|{r['code']}"
        )])
    return InlineKeyboardMarkup(rows)


def _kb_anaf_confirm():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Da, datele sunt corecte", callback_data="onb|cui_confirm|yes")],
        [InlineKeyboardButton("✏️ Vreau să introduc manual", callback_data="onb|cui_confirm|manual")],
        [InlineKeyboardButton("⏭️ Skip CUI", callback_data="onb|skip|cui")],
    ])


def _kb_cui_not_found():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Încearcă alt CUI", callback_data="onb|cui_retry")],
        [InlineKeyboardButton("✏️ Salvează CUI fără verificare", callback_data="onb|cui_save_raw")],
        [InlineKeyboardButton("⏭️ Skip", callback_data="onb|skip|cui")],
    ])


def _kb_final_confirm():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirmă și Salvează", callback_data="onb|finalize|yes")],
        [InlineKeyboardButton("🔄 Reia de la început", callback_data="onb|finalize|restart")],
    ])


# ============================================================
#                    START ONBOARDING
# ============================================================

async def start_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Punct de start pentru onboarding. Trimite mesaj welcome și primul pas."""
    chat_id = update.effective_chat.id
    tg_user = update.effective_user

    session = get_session()
    try:
        user = users_repo.get_or_create_by_telegram_id(
            session, telegram_id=tg_user.id,
            name=tg_user.full_name or tg_user.username or None
        )
        users_repo.set_onboarding_step(session, user, STEP_NUME_PERSONAL)
        session.commit()
        user_id = user.id
    except Exception as e:
        session.rollback()
        logger.error(f"start_onboarding error: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Eroare la inițializare. Încearcă din nou cu /start."
        )
        return
    finally:
        session.close()

    welcome = (
        "👋 *Bun venit la Bot Contabil!*\n\n"
        "Sunt asistentul tău contabil automat. Te ajut să:\n"
        "• Înregistrezi automat bonuri/facturi din poze 📸\n"
        "• Generezi Registrul de Încasări și Plăți 📂\n"
        "• Calculezi profitul, TVA, contribuțiile 💰\n"
        "• Primești alerte pentru termenele ANAF ⏰\n\n"
        "Pentru început am nevoie să te cunosc — durează ~2 minute.\n"
        "Poți sări orice pas cu *Skip* și completa ulterior.\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    await context.bot.send_message(
        chat_id=chat_id, text=welcome, parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )

    await send_step_question(update, context, STEP_NUME_PERSONAL, user_id)


# ============================================================
#                    SEND STEP QUESTION
# ============================================================

async def send_step_question(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    step: int, user_id: int,
):
    """Trimite întrebarea pentru pasul dat."""
    chat_id = update.effective_chat.id

    session = get_session()
    try:
        profile = users_repo.get_profile_dict(session, user_id) or {}
    finally:
        session.close()

    if step == STEP_NUME_PERSONAL:
        msg = (
            "*Pasul 1/6: Numele tău*\n\n"
            "Cum te numești? (prenume + nume)\n"
            "_Pentru personalizarea mesajelor — nu apare pe documente._\n\n"
            "📝 Trimite-mi numele ca mesaj text."
        )
        await context.bot.send_message(
            chat_id=chat_id, text=msg, parse_mode="Markdown",
            reply_markup=_kb_skip("nume"),
        )

    elif step == STEP_FORMA_JURIDICA:
        nume = profile.get("name") or "salut"
        msg = (
            f"*Pasul 2/6: Forma juridică*\n\n"
            f"Bun, *{nume}*! Ce formă juridică ai?\n"
            f"_Această informație determină regulile contabile aplicate._"
        )
        await context.bot.send_message(
            chat_id=chat_id, text=msg, parse_mode="Markdown",
            reply_markup=_kb_forma_juridica(),
        )

    elif step == STEP_CUI:
        forma = profile.get("firma_forma_juridica") or ""
        forma_label = FORME_BY_CODE.get(forma, {}).get("label", "—")
        msg = (
            f"*Pasul 3/6: CUI-ul firmei*\n\n"
            f"Formă juridică: {forma_label}\n\n"
            f"Trimite-mi *CUI-ul* (codul fiscal).\n\n"
            f"📝 Exemple acceptate:\n"
            f"• `53067338`\n"
            f"• `RO53067338`\n\n"
            f"🔍 Voi căuta automat în registrul ANAF datele firmei "
            f"(denumire, adresă, CAEN, status TVA)."
        )
        await context.bot.send_message(
            chat_id=chat_id, text=msg, parse_mode="Markdown",
            reply_markup=_kb_skip("cui"),
        )

    elif step == STEP_ACTIVITATE:
        msg = (
            "*Pasul 4/6: Activitate principală*\n\n"
            "Care e domeniul tău principal?\n"
            "_Asta determină ce categorii de cheltuieli/venituri "
            "sunt auto-recunoscute._"
        )
        await context.bot.send_message(
            chat_id=chat_id, text=msg, parse_mode="Markdown",
            reply_markup=_kb_activity(),
        )

    elif step == STEP_REGIM_TVA:
        regim = profile.get("regim_tva")
        if regim:
            label = "Plătitor (21%)" if regim == "PLATITOR_21" else "Neplătitor"
            msg = (
                f"*Pasul 5/6: Regim TVA*\n\n"
                f"📋 Conform ANAF, regimul tău e: *{label}*\n\n"
                f"E corect?"
            )
            await context.bot.send_message(
                chat_id=chat_id, text=msg, parse_mode="Markdown",
                reply_markup=_kb_regim_tva_confirm(),
            )
        else:
            msg = (
                "*Pasul 5/6: Regim TVA*\n\n"
                "Ești plătitor de TVA?\n"
                "_PFA-urile sub 300.000 lei venit/an sunt de obicei neplătitoare._"
            )
            await context.bot.send_message(
                chat_id=chat_id, text=msg, parse_mode="Markdown",
                reply_markup=_kb_regim_tva(),
            )

    elif step == STEP_REGIM_IMPUNERE:
        forma = profile.get("firma_forma_juridica") or "PFA"
        forma_label = FORME_BY_CODE.get(forma, {}).get("label", "—")
        msg = (
            f"*Pasul 6/6: Regim de impunere*\n\n"
            f"Formă juridică: {forma_label}\n\n"
            f"Ce regim fiscal aplici?"
        )
        await context.bot.send_message(
            chat_id=chat_id, text=msg, parse_mode="Markdown",
            reply_markup=_kb_regim_impunere(forma),
        )

    elif step == STEP_CONFIRMARE:
        await _show_summary(update, context, user_id)


# ============================================================
#                    SUMMARY (final review)
# ============================================================

async def _show_summary(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int,
):
    chat_id = update.effective_chat.id

    session = get_session()
    try:
        profile = users_repo.get_profile_dict(session, user_id) or {}
    finally:
        session.close()

    forma_label = FORME_BY_CODE.get(
        profile.get("firma_forma_juridica") or "", {}
    ).get("label", "—")

    activitate_label = ACTIVITIES_BY_CODE.get(
        profile.get("activity_code") or "", {}
    ).get("label", "—")

    regim_tva_label = (
        "Plătitor (21%)" if profile.get("regim_tva") == "PLATITOR_21"
        else "Neplătitor"
    )
    if not profile.get("regim_tva"):
        regim_tva_label = "—"

    regim_imp = regim_impunere_label(profile.get("regim_impunere") or "")

    msg = (
        "*📋 Rezumat profil*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 *Nume:* {profile.get('name') or '—'}\n"
        f"🏢 *Firmă:* {profile.get('firma_nume') or '—'}\n"
        f"📋 *CUI:* `{profile.get('firma_cui') or '—'}`\n"
        f"🧾 *Formă juridică:* {forma_label}\n"
        f"🏷️ *CAEN:* `{profile.get('caen_principal') or '—'}`\n"
        f"📊 *Activitate:* {activitate_label}\n"
        f"💰 *Regim TVA:* {regim_tva_label}\n"
        f"📈 *Regim impunere:* {regim_imp}\n"
        f"📍 *Județ:* {profile.get('judet') or '—'}\n"
        f"🏘️ *Localitate:* {profile.get('localitate') or '—'}\n\n"
        "Confirmi datele?"
    )

    await context.bot.send_message(
        chat_id=chat_id, text=msg, parse_mode="Markdown",
        reply_markup=_kb_final_confirm(),
    )


# ============================================================
#                    HANDLE TEXT INPUT
# ============================================================

async def handle_onboarding_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """
    Procesează input text DACĂ user-ul e în onboarding.
    Returnează True dacă a fost procesat, False altfel.
    """
    chat_id = update.effective_chat.id
    tg_user = update.effective_user
    text = (update.message.text or "").strip()

    session = get_session()
    try:
        user = users_repo.get_by_telegram_id(session, telegram_id=tg_user.id)
        if not user:
            return False

        step = user.onboarding_step or 0
        if step in (STEP_NOT_STARTED, STEP_COMPLETED):
            return False

        user_id = user.id

        # Step 1 — primește numele
        if step == STEP_NUME_PERSONAL:
            if len(text) < 2:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Numele e prea scurt. Trimite minim 2 caractere.",
                )
                return True
            users_repo.advance_onboarding_step(
                session, user, next_step=STEP_FORMA_JURIDICA,
                profile_updates={"name": text[:200]},
            )
            session.commit()
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Bun, *{text}*!", parse_mode="Markdown",
            )
            await send_step_question(update, context, STEP_FORMA_JURIDICA, user_id)
            return True

        # Step 3 — primește CUI și caută în ANAF
        if step == STEP_CUI:
            cui_text = text
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔍 Caut CUI `{cui_text}` în ANAF...",
                parse_mode="Markdown",
            )

            try:
                anaf = lookup_cui(cui_text)
            except Exception as e:
                logger.error(f"ANAF lookup error in onboarding: {e}")
                anaf = {"found": False, "error": str(e)[:100]}

            if anaf.get("found"):
                # Auto-completare
                updates = {
                    "firma_cui": anaf.get("cui"),
                    "firma_nume": anaf.get("denumire"),
                    "judet": anaf.get("judet"),
                    "localitate": anaf.get("localitate"),
                    "regim_tva": anaf.get("regim_tva"),
                    "caen_principal": anaf.get("cod_caen"),
                }
                users_repo.update_profile(session, user, **updates)
                session.commit()

                msg = (
                    f"✅ *Firma găsită în ANAF:*\n\n"
                    f"🏢 *{anaf.get('denumire')}*\n"
                    f"📋 CUI: `{anaf.get('cui')}`\n"
                    f"💰 TVA: *"
                    f"{('Plătitor (21%)' if anaf.get('is_platitor_tva') else 'Neplătitor')}"
                    f"*\n"
                )
                if anaf.get('cod_caen'):
                    msg += f"🏷️ CAEN: `{anaf.get('cod_caen')}`\n"
                if anaf.get('adresa_completa'):
                    msg += f"📍 {anaf.get('adresa_completa')}\n"
                msg += "\n*Datele sunt corecte?*"

                await context.bot.send_message(
                    chat_id=chat_id, text=msg, parse_mode="Markdown",
                    reply_markup=_kb_anaf_confirm(),
                )
                return True
            else:
                err = anaf.get("error", "necunoscută")
                msg = (
                    f"⚠️ Nu am găsit CUI `{cui_text}` în ANAF.\n"
                    f"_Motiv: {err}_\n\n"
                    f"Ce vrei să fac?"
                )
                context.user_data["pending_cui"] = cui_text
                await context.bot.send_message(
                    chat_id=chat_id, text=msg, parse_mode="Markdown",
                    reply_markup=_kb_cui_not_found(),
                )
                return True

        # Pentru alți pași (forma, activitate, etc.) — nu acceptăm text
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "⚠️ Te rog folosește butoanele de mai sus pentru "
                "a răspunde la întrebarea curentă."
            ),
        )
        return True

    except Exception as e:
        session.rollback()
        logger.error(f"handle_onboarding_text error: {e}")
        return True
    finally:
        session.close()


# ============================================================
#                    HANDLE CALLBACK
# ============================================================

async def handle_onboarding_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list,
):
    """Procesează callback-uri de onboarding (parts[0] == 'onb')."""
    query = update.callback_query
    chat_id = query.message.chat_id
    tg_user = update.effective_user

    session = get_session()
    try:
        user = users_repo.get_by_telegram_id(session, telegram_id=tg_user.id)
        if not user:
            await query.edit_message_text("⚠️ Eroare identificare utilizator.")
            return
        user_id = user.id
        action = parts[1] if len(parts) > 1 else ""
        sub = parts[2] if len(parts) > 2 else ""

        # === Cancel ===
        if action == "cancel":
            users_repo.reset_onboarding(session, user)
            session.commit()
            await query.edit_message_text(
                "❌ Onboarding anulat.\nPoți relua oricând cu /start."
            )
            return

        # === Skip ===
        if action == "skip":
            if sub == "nume":
                users_repo.set_onboarding_step(session, user, STEP_FORMA_JURIDICA)
                session.commit()
                await query.edit_message_text("⏭️ Sărit pasul nume.")
                await send_step_question(update, context, STEP_FORMA_JURIDICA, user_id)
            elif sub == "forma":
                users_repo.set_onboarding_step(session, user, STEP_CUI)
                session.commit()
                await query.edit_message_text("⏭️ Sărit forma juridică.")
                await send_step_question(update, context, STEP_CUI, user_id)
            elif sub == "cui":
                users_repo.set_onboarding_step(session, user, STEP_ACTIVITATE)
                session.commit()
                await query.edit_message_text("⏭️ Sărit CUI.")
                await send_step_question(update, context, STEP_ACTIVITATE, user_id)
            return

        # === FORMA JURIDICĂ ===
        if action == "forma" and sub in FORME_BY_CODE:
            users_repo.advance_onboarding_step(
                session, user, next_step=STEP_CUI,
                profile_updates={"firma_forma_juridica": sub},
            )
            session.commit()
            label = FORME_BY_CODE[sub]["label"]
            await query.edit_message_text(
                f"✅ Formă juridică: *{label}*", parse_mode="Markdown",
            )
            await send_step_question(update, context, STEP_CUI, user_id)
            return

        # === CUI confirmare ANAF ===
        if action == "cui_confirm":
            if sub == "yes":
                users_repo.set_onboarding_step(session, user, STEP_ACTIVITATE)
                session.commit()
                await query.edit_message_text("✅ Date ANAF confirmate.")
                await send_step_question(update, context, STEP_ACTIVITATE, user_id)
            elif sub == "manual":
                users_repo.set_onboarding_step(session, user, STEP_ACTIVITATE)
                session.commit()
                await query.edit_message_text(
                    "✏️ OK. Poți edita ulterior din /profil."
                )
                await send_step_question(update, context, STEP_ACTIVITATE, user_id)
            return

        if action == "cui_retry":
            await query.edit_message_text(
                "🔄 OK, trimite-mi alt CUI ca mesaj text.",
            )
            return

        if action == "cui_save_raw":
            pending = context.user_data.get("pending_cui", "")
            if pending:
                users_repo.update_profile(session, user, firma_cui=pending)
            users_repo.set_onboarding_step(session, user, STEP_ACTIVITATE)
            session.commit()
            await query.edit_message_text(
                "✅ CUI salvat (fără verificare ANAF)."
            )
            context.user_data.pop("pending_cui", None)
            await send_step_question(update, context, STEP_ACTIVITATE, user_id)
            return

        # === ACTIVITY ===
        if action == "activity" and sub in ACTIVITIES_BY_CODE:
            act = ACTIVITIES_BY_CODE[sub]
            updates = {"activity_code": sub}
            profile = users_repo.get_profile_dict(session, user_id) or {}
            if not profile.get("caen_principal") and act.get("caen"):
                updates["caen_principal"] = act["caen"]
            users_repo.advance_onboarding_step(
                session, user, next_step=STEP_REGIM_TVA,
                profile_updates=updates,
            )
            session.commit()
            await query.edit_message_text(f"✅ Activitate: {act['label']}")
            await send_step_question(update, context, STEP_REGIM_TVA, user_id)
            return

        # === Regim TVA confirmare (auto din ANAF) ===
        if action == "tva_confirm":
            if sub == "yes":
                users_repo.set_onboarding_step(session, user, STEP_REGIM_IMPUNERE)
                session.commit()
                await query.edit_message_text("✅ Regim TVA confirmat.")
                await send_step_question(update, context, STEP_REGIM_IMPUNERE, user_id)
            elif sub == "change":
                await query.edit_message_text(
                    "✏️ Alege regim TVA dorit:",
                    reply_markup=_kb_regim_tva(),
                )
            return

        # === Regim TVA selectare ===
        if action == "tva" and sub in REGIM_TVA_BY_CODE:
            users_repo.advance_onboarding_step(
                session, user, next_step=STEP_REGIM_IMPUNERE,
                profile_updates={"regim_tva": sub},
            )
            session.commit()
            label = REGIM_TVA_BY_CODE[sub]["label"]
            await query.edit_message_text(f"✅ Regim TVA: {label}")
            await send_step_question(update, context, STEP_REGIM_IMPUNERE, user_id)
            return

        # === Regim impunere ===
        if action == "impunere" and sub in (
            "SISTEM_REAL", "NORMA_VENIT", "MICRO_1", "MICRO_3"
        ):
            users_repo.advance_onboarding_step(
                session, user, next_step=STEP_CONFIRMARE,
                profile_updates={"regim_impunere": sub},
            )
            session.commit()
            await query.edit_message_text(
                f"✅ Regim impunere: {regim_impunere_label(sub)}"
            )
            await send_step_question(update, context, STEP_CONFIRMARE, user_id)
            return

        # === Finalize ===
        if action == "finalize":
            if sub == "yes":
                users_repo.complete_onboarding(session, user)
                session.commit()
                await query.edit_message_text(
                    "🎉 *Profil completat cu succes!*\n\n"
                    "Acum poți începe să trimiți poze cu bonuri/facturi sau "
                    "screenshot-uri Bolt — botul te ajută cu restul.\n\n"
                    "Folosește meniul de jos pentru rapoarte, registru, etc.",
                    parse_mode="Markdown",
                )
                # Restaurăm meniul principal (lazy import ca să evităm circular)
                from bot_contabil import build_main_menu
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="📋 Meniu principal:",
                    reply_markup=build_main_menu(),
                )
            elif sub == "restart":
                users_repo.reset_onboarding(session, user)
                session.commit()
                await query.edit_message_text("🔄 Reluăm de la început...")
                await start_onboarding(update, context)
            return

    except Exception as e:
        session.rollback()
        logger.error(f"handle_onboarding_callback error: {e}")
        try:
            await query.edit_message_text(f"❌ Eroare: {str(e)[:200]}")
        except Exception:
            pass
    finally:
        session.close()


# ============================================================
#                    UTILITY: este în onboarding?
# ============================================================

def user_is_in_onboarding(telegram_id: int) -> bool:
    """Returnează True dacă user e în mijlocul onboarding-ului."""
    session = get_session()
    try:
        user = users_repo.get_by_telegram_id(session, telegram_id=telegram_id)
        if not user:
            return False
        step = user.onboarding_step or 0
        return step != STEP_NOT_STARTED and step != STEP_COMPLETED
    except Exception:
        return False
    finally:
        session.close()


def user_is_onboarded(telegram_id: int) -> bool:
    """Returnează True dacă user a terminat onboarding-ul."""
    session = get_session()
    try:
        user = users_repo.get_by_telegram_id(session, telegram_id=telegram_id)
        if not user:
            return False
        return bool(user.onboarding_completed)
    except Exception:
        return False
    finally:
        session.close()
