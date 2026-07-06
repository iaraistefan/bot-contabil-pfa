"""
Sistem de onboarding interactiv pentru utilizatorii noi.

PAS B - Onboarding ANAF Smart (auto-complet maxim):
  Flux scurt: nume -> CUI -> cercetare ANAF -> un ecran de confirmare.

  Step 1: Numele personal (text)
  Step 2: CUI (text -> ANAF lookup)
  Step 7: Confirmare - ANAF a completat tot, user confirma sau corecteaza

  FALLBACK MANUAL (daca ANAF nu gaseste firma):
  Step 3: Forma juridica -> Step 4: Activitate -> Step 5: Regim TVA
  -> Step 6: Regim impunere -> Step 7: Confirmare

Datele auto-completate din ANAF: denumire, CUI, forma juridica, CAEN,
activitate (derivata din CAEN), regim TVA, judet, localitate.
Regimul de impunere nu exista in ANAF -> se pune un default rezonabil
pe care user-ul il poate corecta.
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
from app.domain.fiscal_profile import VAT_THRESHOLD_RON  # sursă unică prag TVA (B8)

logger = logging.getLogger(__name__)


# === Pasi onboarding ===
STEP_NOT_STARTED = 0
STEP_NUME_PERSONAL = 1
STEP_FORMA_JURIDICA = 2
STEP_CUI = 3
STEP_ACTIVITATE = 4
STEP_REGIM_TVA = 5
STEP_REGIM_IMPUNERE = 6
STEP_CONFIRMARE = 7
# Pași CONDIȚIONAȚI (doar ridesharing) — inserați între IMPUNERE și CONFIRMARE.
# Tranzițiile sunt explicite (set_onboarding_step), nu secvențiale → CONFIRMARE
# rămâne 7. Vezi fiscal #3 + Uber sub-pas C.
#   8  = GATE platforme [Bolt / Uber / Ambele] — ce platforme folosește șoferul.
#   9  = întrebarea Bolt (2%/16%) → scrie regim_nerezident_bolt.
#   10 = întrebarea Uber (0%/16%) → scrie regim_nerezident_uber.
# „Ambele" → 9 apoi 10. „Bolt"/„Uber" → doar pasul lui („nu întrebăm irelevant").
STEP_REGIM_NEREZIDENT = 8          # GATE platforme (numele păstrat: e pasul de intrare)
STEP_REGIM_NEREZIDENT_BOLT = 9
STEP_REGIM_NEREZIDENT_UBER = 10
STEP_COMPLETED = 99


# Regim impozit nerezident PER-PLATFORMĂ (fiscal #3 + Uber sub-pas C). Cotele
# diferă fundamental — Bolt și Uber au convenții DIFERITE, deci seturi separate,
# fără cross (validatorii VALID_REGIMURI_NEREZIDENT_BOLT/_UBER resping codul
# celeilalte platforme). NICIUNA preselectată.
#
# Bolt (Bolt Operations OÜ, Estonia) — Art. 12 „Comisioane": 2% cu CRF / 16% fără.
# NU există 0% pentru Bolt.
REGIMURI_NEREZIDENT = [
    {"code": "BOLT_CU_CRF",   "label": "✅ Am certificatul Bolt — 2% (D100 + D207)"},
    {"code": "BOLT_FARA_CRF", "label": "⚠️ Nu am certificatul — 16% (stopaj)"},
]
# Uber (Uber B.V., Olanda) — art. 7 „profituri": 0% cu CRF (doar D207, fără D100)
# / 16% fără. NU există 2% pentru Uber (acela e exclusiv Bolt).
REGIMURI_NEREZIDENT_UBER = [
    {"code": "UBER_CU_CRF",   "label": "✅ Am certificatul Uber — 0% (doar D207)"},
    {"code": "UBER_FARA_CRF", "label": "⚠️ Nu am certificatul — 16% (stopaj)"},
]
# Hartă combinată DOAR pentru etichete + rutarea handler-ului (sub ∈ BY_CODE).
# REGIMURI_NEREZIDENT rămâne lista Bolt (subsetul activ legacy = VALID_..._BOLT).
REGIM_NEREZIDENT_BY_CODE = {
    r["code"]: r for r in (REGIMURI_NEREZIDENT + REGIMURI_NEREZIDENT_UBER)
}

# Gate-ul de platforme (sub-pas C). „Ambele" → Bolt apoi Uber.
PLATFORME_NEREZIDENT = [
    {"code": "BOLT",   "label": "🟢 Doar Bolt"},
    {"code": "UBER",   "label": "⚫ Doar Uber"},
    {"code": "AMBELE", "label": "🔵 Ambele (Bolt + Uber)"},
]


def nerezident_label(code: str) -> str:
    return REGIM_NEREZIDENT_BY_CODE.get(code or "", {}).get("label", "—")


def next_step_after_impunere(activity_code: str) -> int:
    """
    Pasul de după REGIM_IMPUNERE: doar ridesharing primește întrebările despre
    regimul nerezident D100 (gate-ul de platforme); ceilalți merg direct la
    confirmare (nu-i întrebăm irelevant — comisionul nerezident e specific Bolt/Uber).
    """
    if (activity_code or "") == "ridesharing":
        return STEP_REGIM_NEREZIDENT
    return STEP_CONFIRMARE


# === Cele 10 activitati ===
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


# === Mapare cod CAEN -> activitate (pentru auto-detectie din ANAF) ===
CAEN_TO_ACTIVITY = {
    # Ridesharing / transport persoane (4933 = transport rutier de pasageri cu taxiul/
    # alternativ — eligibil normă de venit 2026, OMF 1960/2025)
    "4932": "ridesharing", "4931": "ridesharing", "4933": "ridesharing", "4939": "ridesharing",
    # IT
    "6201": "it_freelance", "6202": "it_freelance", "6209": "it_freelance",
    "6311": "it_freelance", "6312": "it_freelance",
    # E-commerce / comert
    "4791": "ecommerce", "4719": "ecommerce", "4799": "ecommerce",
    # Consultanta
    "7022": "consulting", "7021": "consulting", "7320": "consulting",
    "8211": "consulting", "7010": "consulting",
    # Constructii
    "4399": "construction", "4321": "construction", "4322": "construction",
    "4329": "construction", "4331": "construction", "4332": "construction",
    "4333": "construction", "4334": "construction", "4391": "construction",
    "4120": "construction", "4110": "construction",
    # Medical
    "8621": "medical", "8622": "medical", "8623": "medical", "8690": "medical",
    # Transport marfa
    "4941": "transport", "4942": "transport",
    # Imobiliare
    "6820": "real_estate", "6810": "real_estate", "6831": "real_estate",
    "6832": "real_estate",
    # Educatie
    "8559": "education", "8551": "education", "8552": "education",
    "8553": "education", "8541": "education", "8542": "education",
}


def activity_from_caen(caen: str):
    """Deriva codul de activitate din codul CAEN. None daca nu se poate."""
    if not caen:
        return None
    return CAEN_TO_ACTIVITY.get(caen.strip())


def default_regim_impunere(forma: str) -> str:
    """
    Returneaza un regim de impunere implicit rezonabil pentru o forma.
    ANAF nu expune regimul de impunere, asa ca punem un default pe care
    user-ul il poate corecta.
    """
    if forma in ("PFA", "II", "IF", "PROFESIE_LIBERALA"):
        return "SISTEM_REAL"   # cel mai comun pentru persoane fizice
    if forma == "SRL_MICRO":
        return "MICRO_1"       # micro 1% (cu salariat) - regimul uzual
    if forma == "SRL_NORMAL":
        return "SISTEM_REAL"
    return "SISTEM_REAL"


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


# === Regim impunere — depinde de forma juridica ===
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
        [InlineKeyboardButton("⏭️ Sari", callback_data=f"onb|skip|{skip_target}")],
        [InlineKeyboardButton("❌ Anulează", callback_data="onb|cancel")],
    ])


def _kb_forma_juridica():
    rows = []
    for f in FORME_JURIDICE:
        rows.append([InlineKeyboardButton(
            f["label"], callback_data=f"onb|forma|{f['code']}"
        )])
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


def _kb_regim_impunere(forma: str):
    regimuri = get_regimuri_for_forma(forma)
    rows = []
    for r in regimuri:
        rows.append([InlineKeyboardButton(
            r["label"], callback_data=f"onb|impunere|{r['code']}"
        )])
    return InlineKeyboardMarkup(rows)


def _kb_platforme_nerezident():
    """Gate: ce platforme folosește șoferul — Bolt / Uber / Ambele (sub-pas C)."""
    rows = [
        [InlineKeyboardButton(p["label"], callback_data=f"onb|platforme|{p['code']}")]
        for p in PLATFORME_NEREZIDENT
    ]
    return InlineKeyboardMarkup(rows)


def _kb_regim_nerezident():
    """2 opțiuni regim nerezident Bolt (2%/16%) — NICIUNA preselectată."""
    rows = [
        [InlineKeyboardButton(r["label"], callback_data=f"onb|nerezident|{r['code']}")]
        for r in REGIMURI_NEREZIDENT
    ]
    return InlineKeyboardMarkup(rows)


def _kb_regim_nerezident_uber():
    """2 opțiuni regim nerezident Uber (0%/16%) — NICIUNA preselectată."""
    rows = [
        [InlineKeyboardButton(r["label"], callback_data=f"onb|nerezident|{r['code']}")]
        for r in REGIMURI_NEREZIDENT_UBER
    ]
    return InlineKeyboardMarkup(rows)


def _kb_cui_not_found():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Încearcă alt CUI", callback_data="onb|cui_retry")],
        [InlineKeyboardButton("✏️ Continuă manual (fără ANAF)", callback_data="onb|cui_save_raw")],
    ])


def _kb_anaf_summary(forma_lipsa: bool = False):
    """Ecranul de confirmare dupa cercetarea ANAF."""
    if forma_lipsa:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Completează datele lipsă", callback_data="onb|fix|menu")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirmă tot", callback_data="onb|confirm_all")],
        [InlineKeyboardButton("✏️ Vreau să corectez ceva", callback_data="onb|fix|menu")],
    ])


def _kb_fix_menu():
    """Meniul de corectare a campurilor."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧾 Formă juridică", callback_data="onb|fix|forma")],
        [InlineKeyboardButton("📊 Activitate", callback_data="onb|fix|activity")],
        [InlineKeyboardButton("💰 Regim TVA", callback_data="onb|fix|tva")],
        [InlineKeyboardButton("📈 Regim impunere", callback_data="onb|fix|impunere")],
        [InlineKeyboardButton("⬅️ Înapoi la confirmare", callback_data="onb|fix|back")],
    ])


def _kb_final_confirm():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirmă și salvează", callback_data="onb|finalize|yes")],
        [InlineKeyboardButton("🔄 Reia de la început", callback_data="onb|finalize|restart")],
    ])


def _kb_coduri_onboarding():
    """Oferta de coduri fiscale la finalul onboarding-ului."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇪🇺 Adaugă cod special TVA", callback_data="coduri|set_tva")],
        [InlineKeyboardButton("🆔 Adaugă CNP", callback_data="coduri|set_cnp")],
        [InlineKeyboardButton("⏭️ Mai târziu", callback_data="coduri|skip")],
    ])


# ============================================================
#                    START ONBOARDING
# ============================================================

async def start_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Punct de start pentru onboarding."""
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
        "👋 *Bun venit la Coniar!*\n\n"
        "Sunt asistentul tău fiscal automat. Te ajut să:\n"
        "• Îți înregistrez bonurile și facturile din poze 📸\n"
        "• Îți țin Registrul de Încasări și Plăți 📂\n"
        "• Îți calculez profitul, TVA-ul, contribuțiile 💰\n"
        "• Te anunț de termenele ANAF ⏰\n\n"
        "Hai să te configurez — durează *sub un minut*. Îți caut "
        "singur datele firmei în registrul ANAF.\n"
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
    """Trimite intrebarea pentru pasul dat."""
    chat_id = update.effective_chat.id

    session = get_session()
    try:
        profile = users_repo.get_profile_dict(session, user_id) or {}
    finally:
        session.close()

    if step == STEP_NUME_PERSONAL:
        msg = (
            "*👤 Cum te cheamă?*\n\n"
            "Scrie-mi prenumele și numele tău.\n"
            "_Doar ca să știu cum să-ți spun — nu apare pe niciun document._"
        )
        await context.bot.send_message(
            chat_id=chat_id, text=msg, parse_mode="Markdown",
            reply_markup=_kb_skip("nume"),
        )

    elif step == STEP_CUI:
        nume = profile.get("name") or "salut"
        msg = (
            f"*🔍 Care e CUI-ul firmei tale?*\n\n"
            f"Bun, *{nume}*! Scrie-mi *CUI-ul* (codul fiscal) al "
            f"PFA-ului / firmei tale.\n\n"
            f"📝 Exemple acceptate:\n"
            f"• `53067338`\n"
            f"• `RO53067338`\n\n"
            f"🔎 Caut singur în ANAF *toate* datele: denumire, formă "
            f"juridică, activitate, regim TVA, adresă. Tu doar confirmi."
        )
        await context.bot.send_message(
            chat_id=chat_id, text=msg, parse_mode="Markdown",
            reply_markup=_kb_skip("cui"),
        )

    elif step == STEP_FORMA_JURIDICA:
        msg = (
            "*🧾 Forma juridică*\n\n"
            "Ce formă juridică ai?\n"
            "_De asta depind regulile contabile pe care le aplic._"
        )
        await context.bot.send_message(
            chat_id=chat_id, text=msg, parse_mode="Markdown",
            reply_markup=_kb_forma_juridica(),
        )

    elif step == STEP_ACTIVITATE:
        msg = (
            "*📊 Activitate principală*\n\n"
            "Care e domeniul tău principal?\n"
            "_După asta știu ce cheltuieli și venituri să-ți "
            "recunosc automat._"
        )
        await context.bot.send_message(
            chat_id=chat_id, text=msg, parse_mode="Markdown",
            reply_markup=_kb_activity(),
        )

    elif step == STEP_REGIM_TVA:
        # Pragul vine din VAT_THRESHOLD_RON (sursă unică, B8) — nu hardcodat.
        prag_tva = f"{VAT_THRESHOLD_RON:,.0f}".replace(",", ".")
        msg = (
            "*💰 Regim TVA*\n\n"
            "Ești plătitor de TVA?\n"
            f"_De obicei, PFA-urile sub {prag_tva} lei cifră de afaceri pe an nu sunt plătitoare._"
        )
        await context.bot.send_message(
            chat_id=chat_id, text=msg, parse_mode="Markdown",
            reply_markup=_kb_regim_tva(),
        )

    elif step == STEP_REGIM_IMPUNERE:
        forma = profile.get("firma_forma_juridica") or "PFA"
        forma_label = FORME_BY_CODE.get(forma, {}).get("label", "—")
        msg = (
            f"*📈 Regim de impunere*\n\n"
            f"Formă juridică: {forma_label}\n\n"
            f"Ce regim fiscal aplici?"
        )
        await context.bot.send_message(
            chat_id=chat_id, text=msg, parse_mode="Markdown",
            reply_markup=_kb_regim_impunere(forma),
        )

    elif step == STEP_REGIM_NEREZIDENT:
        # GATE: ce platforme folosește (sub-pas C). Întrebăm regimul DOAR pentru
        # platformele alese — nu pe cele irelevante.
        msg = (
            "*🌍 Impozit nerezident — platforme*\n\n"
            "Comisionul reținut de platformele de ridesharing (firme din afara "
            "României) se impozitează în România prin D100. Cota depinde de "
            "platformă și de certificatul de rezidență fiscală.\n\n"
            "*Ce platforme folosești?*\n\n"
            "_Poți schimba oricând în Setări. Dacă apare o factură de la o "
            "platformă pe care n-ai configurat-o, te anunțăm înainte de D100._"
        )
        await context.bot.send_message(
            chat_id=chat_id, text=msg, parse_mode="Markdown",
            reply_markup=_kb_platforme_nerezident(),
        )

    elif step == STEP_REGIM_NEREZIDENT_BOLT:
        msg = (
            "*🌍 Impozit nerezident — comision Bolt*\n\n"
            "Comisionul reținut de Bolt (Bolt Operations OÜ, Estonia) se "
            "impozitează în România. Conform Convenției RO-Estonia (Art. 12 "
            "„Comisioane”), cota depinde de certificatul de rezidență fiscală "
            "al Bolt.\n\n"
            "*Ai certificatul de rezidență fiscală al Bolt (Estonia)?*\n\n"
            "• *Da, am certificatul* → impozit *2%* (D100 lunar + D207 anual)\n"
            "• *Nu am certificatul* → impozit *16%* (stopaj la sursă)\n\n"
            "_Certificatul e al firmei Bolt (Bolt Operations OÜ), valabil pe an. "
            "Nu îl ai? Îl ceri de la suportul Bolt. Verifică anul înainte de "
            "depunere. Alegerea îți aparține — nu alegem noi._"
        )
        await context.bot.send_message(
            chat_id=chat_id, text=msg, parse_mode="Markdown",
            reply_markup=_kb_regim_nerezident(),
        )

    elif step == STEP_REGIM_NEREZIDENT_UBER:
        msg = (
            "*🌍 Impozit nerezident — comision Uber*\n\n"
            "Comisionul reținut de Uber (Uber B.V., Olanda) se impozitează în "
            "România. Convenția RO-Olanda NU are articol de comisioane → se "
            "aplică art. 7 „profituri”, cu tratament DIFERIT de Bolt.\n\n"
            "*Ai certificatul de rezidență fiscală al Uber B.V. (Olanda)?*\n\n"
            "• *Da, am certificatul* → *0%* (scutire; doar D207, fără D100)\n"
            "• *Nu am certificatul* → *16%* (stopaj la sursă)\n\n"
            "_Certificatul e al firmei Uber (Uber B.V.), valabil pe an. Nu există "
            "cota de 2% pentru Uber (aceea e doar pentru Bolt). Alegerea îți "
            "aparține — nu alegem noi._"
        )
        await context.bot.send_message(
            chat_id=chat_id, text=msg, parse_mode="Markdown",
            reply_markup=_kb_regim_nerezident_uber(),
        )

    elif step == STEP_CONFIRMARE:
        await _show_summary(update, context, user_id)


# ============================================================
#                    ANAF SUMMARY (auto-complet maxim)
# ============================================================

async def _show_anaf_summary(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int,
    via_callback: bool = False,
):
    """
    Ecranul cheie al PAS B: dupa cercetarea ANAF, arata TOT profilul
    completat automat. User-ul confirma sau corecteaza.
    """
    chat_id = update.effective_chat.id

    session = get_session()
    try:
        profile = users_repo.get_profile_dict(session, user_id) or {}
    finally:
        session.close()

    forma = profile.get("firma_forma_juridica") or ""
    forma_label = FORME_BY_CODE.get(forma, {}).get("label", "⚠️ nedetectată")
    activity = profile.get("activity_code") or ""
    activity_label = ACTIVITIES_BY_CODE.get(activity, {}).get("label", "—")
    caen = profile.get("caen_principal") or "—"
    regim_tva = profile.get("regim_tva")
    regim_tva_label = (
        "Plătitor (21%)" if regim_tva == "PLATITOR_21"
        else "Neplătitor" if regim_tva == "NEPLATITOR" else "—"
    )
    regim_imp = regim_impunere_label(profile.get("regim_impunere") or "")

    forma_lipsa = not forma

    lines = [
        "✅ *Am găsit firma în ANAF!*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"🏢 *{profile.get('firma_nume') or '—'}*",
        f"📋 CUI: `{profile.get('firma_cui') or '—'}`",
        f"🧾 Formă: *{forma_label}*",
    ]

    # CAEN + activitate derivata
    if activity:
        lines.append(f"🏷️ CAEN `{caen}` → *{activity_label}*")
    else:
        lines.append(f"🏷️ CAEN: `{caen}` → _activitate nedetectată_")

    lines.append(f"💰 TVA: *{regim_tva_label}*")
    lines.append(f"📈 Impunere: *{regim_imp}* _(presupus)_")

    # Regim nerezident D100 PER-PLATFORMĂ — afișat doar dacă e setat (ridesharing).
    # Bolt cu fallback la deprecatul `regim_nerezident` (useri pre-migrare). #3 + sub-pas C.
    regim_bolt = profile.get("regim_nerezident_bolt") or profile.get("regim_nerezident")
    regim_uber = profile.get("regim_nerezident_uber")
    if regim_bolt:
        lines.append(f"🌍 Nerezident Bolt: *{nerezident_label(regim_bolt)}*")
    if regim_uber:
        lines.append(f"🌍 Nerezident Uber: *{nerezident_label(regim_uber)}*")

    judet = profile.get("judet") or ""
    localitate = profile.get("localitate") or ""
    if judet or localitate:
        loc = ", ".join(p for p in [localitate, judet] if p)
        lines.append(f"📍 {loc}")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    if forma_lipsa:
        lines.append(
            "⚠️ Nu am putut detecta forma juridică. "
            "Apasă mai jos ca să o completezi."
        )
    else:
        lines.append(
            "_Regimul de impunere e o presupunere — verifică-l dacă nu e corect._\n\n"
            "*Totul e corect?*"
        )

    text = "\n".join(lines)
    markup = _kb_anaf_summary(forma_lipsa=forma_lipsa)

    if via_callback and update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=markup
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id, text=text, parse_mode="Markdown",
            reply_markup=markup,
        )


# ============================================================
#                    SUMMARY MANUAL (fallback)
# ============================================================

async def _show_summary(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int,
):
    """Rezumat final pentru fluxul manual (ANAF not found)."""
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
        else "Neplătitor" if profile.get("regim_tva") else "—"
    )
    regim_imp = regim_impunere_label(profile.get("regim_impunere") or "")

    # Regim nerezident D100 PER-PLATFORMĂ — Bolt cu fallback la deprecat. #3 + sub-pas C.
    regim_bolt = profile.get("regim_nerezident_bolt") or profile.get("regim_nerezident")
    regim_uber = profile.get("regim_nerezident_uber")
    nerez_line = ""
    if regim_bolt:
        nerez_line += f"🌍 *Nerezident Bolt:* {nerezident_label(regim_bolt)}\n"
    if regim_uber:
        nerez_line += f"🌍 *Nerezident Uber:* {nerezident_label(regim_uber)}\n"

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
        f"{nerez_line}"
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
    """Proceseaza input text DACA user-ul e in onboarding."""
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

        # Step 1 - numele personal
        if step == STEP_NUME_PERSONAL:
            if len(text) < 2:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Numele e prea scurt. Trimite minim 2 caractere.",
                )
                return True
            users_repo.advance_onboarding_step(
                session, user, next_step=STEP_CUI,
                profile_updates={"name": text[:200]},
            )
            session.commit()
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Îmi pare bine, *{text}*!", parse_mode="Markdown",
            )
            await send_step_question(update, context, STEP_CUI, user_id)
            return True

        # Step 2 - CUI + cercetare ANAF
        if step == STEP_CUI:
            cui_text = text
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔎 Caut `{cui_text}` în registrul ANAF...",
                parse_mode="Markdown",
            )

            try:
                anaf = lookup_cui(cui_text)
            except Exception as e:
                logger.error(f"ANAF lookup error in onboarding: {e}")
                anaf = {"found": False, "error": str(e)[:100]}

            if anaf.get("found"):
                # === AUTO-COMPLET MAXIM ===
                caen = anaf.get("cod_caen") or ""
                forma = anaf.get("forma_juridica_detectata") or ""
                activity = activity_from_caen(caen)
                regim_imp = default_regim_impunere(forma) if forma else "SISTEM_REAL"

                updates = {
                    "firma_cui": anaf.get("cui"),
                    "firma_nume": anaf.get("denumire"),
                    "judet": anaf.get("judet"),
                    "localitate": anaf.get("localitate"),
                    "regim_tva": anaf.get("regim_tva"),
                    "caen_principal": caen,
                    "firma_forma_juridica": forma,
                    "regim_impunere": regim_imp,
                }
                if activity:
                    updates["activity_code"] = activity

                users_repo.update_profile(session, user, **updates)
                users_repo.set_onboarding_step(session, user, STEP_CONFIRMARE)
                session.commit()

                # Avertisment daca firma e inactiva
                if anaf.get("is_inactiv"):
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "⚠️ Firma apare ca inactivă în ANAF. Merită să "
                            "verifici situația, dar putem continua oricum."
                        ),
                        parse_mode="Markdown",
                    )

                await _show_anaf_summary(update, context, user_id)
                return True
            else:
                # ANAF nu a gasit -> fallback manual
                err = anaf.get("error", "necunoscută")
                msg = (
                    f"⚠️ Nu am găsit `{cui_text}` în ANAF.\n"
                    f"_Motiv: {err}_\n\n"
                    f"Nicio grijă — continuăm manual, te întreb eu datele."
                )
                context.user_data["pending_cui"] = cui_text
                await context.bot.send_message(
                    chat_id=chat_id, text=msg, parse_mode="Markdown",
                    reply_markup=_kb_cui_not_found(),
                )
                return True

        # Pentru alti pasi - nu acceptam text
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
    """Proceseaza callback-uri de onboarding (parts[0] == 'onb')."""
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

        # === Done (a sarit adaugarea masinii) ===
        if action == "done":
            await query.edit_message_text(
                "👍 OK! Poți adăuga mașina oricând din "
                "*⚙️ Setări → 🚗 Mașinile mele*.",
                parse_mode="Markdown",
            )
            from bot_contabil import build_main_menu
            await context.bot.send_message(
                chat_id=chat_id,
                text="📋 Meniu principal:",
                reply_markup=build_main_menu(),
            )
            return

        # === Skip ===
        if action == "skip":
            if sub == "nume":
                users_repo.set_onboarding_step(session, user, STEP_CUI)
                session.commit()
                await query.edit_message_text("⏭️ Sărit pasul nume.")
                await send_step_question(update, context, STEP_CUI, user_id)
            elif sub == "cui":
                # Fara CUI -> flux manual complet
                users_repo.set_onboarding_step(session, user, STEP_FORMA_JURIDICA)
                session.commit()
                await query.edit_message_text("⏭️ Sărit CUI. Continuăm manual.")
                await send_step_question(update, context, STEP_FORMA_JURIDICA, user_id)
            return

        # === CUI not found -> flux manual ===
        if action == "cui_retry":
            users_repo.set_onboarding_step(session, user, STEP_CUI)
            session.commit()
            await query.edit_message_text(
                "🔄 Trimite-mi alt CUI, ca mesaj.",
            )
            return

        if action == "cui_save_raw":
            pending = context.user_data.get("pending_cui", "")
            if pending:
                users_repo.update_profile(session, user, firma_cui=pending)
            users_repo.set_onboarding_step(session, user, STEP_FORMA_JURIDICA)
            session.commit()
            context.user_data.pop("pending_cui", None)
            await query.edit_message_text(
                "✅ Am notat CUI-ul. Continuăm manual."
            )
            await send_step_question(update, context, STEP_FORMA_JURIDICA, user_id)
            return

        # === Confirm all (dupa ANAF) -> finalizare directa ===
        if action == "confirm_all":
            await _finalize(update, context, session, user, user_id)
            return

        # === FIX (corectare campuri dupa ANAF) ===
        if action == "fix":
            if sub == "menu":
                await query.edit_message_text(
                    "✏️ *Ce vrei să corectezi?*",
                    parse_mode="Markdown",
                    reply_markup=_kb_fix_menu(),
                )
            elif sub == "back":
                await _show_anaf_summary(update, context, user_id, via_callback=True)
            elif sub == "forma":
                context.user_data["onb_fixing"] = True
                await query.edit_message_text(
                    "🧾 *Alege forma juridică:*",
                    parse_mode="Markdown",
                    reply_markup=_kb_forma_juridica(),
                )
            elif sub == "activity":
                context.user_data["onb_fixing"] = True
                await query.edit_message_text(
                    "📊 *Alege activitatea:*",
                    parse_mode="Markdown",
                    reply_markup=_kb_activity(),
                )
            elif sub == "tva":
                context.user_data["onb_fixing"] = True
                await query.edit_message_text(
                    "💰 *Alege regimul TVA:*",
                    parse_mode="Markdown",
                    reply_markup=_kb_regim_tva(),
                )
            elif sub == "impunere":
                context.user_data["onb_fixing"] = True
                session2 = get_session()
                try:
                    profile = users_repo.get_profile_dict(session2, user_id) or {}
                finally:
                    session2.close()
                forma = profile.get("firma_forma_juridica") or "PFA"
                await query.edit_message_text(
                    "📈 *Alege regimul de impunere:*",
                    parse_mode="Markdown",
                    reply_markup=_kb_regim_impunere(forma),
                )
            return

        # === FORMA JURIDICA ===
        if action == "forma" and sub in FORME_BY_CODE:
            users_repo.update_profile(session, user, firma_forma_juridica=sub)
            session.commit()
            if context.user_data.pop("onb_fixing", None):
                # Corectare -> revine la summary ANAF
                await _show_anaf_summary(update, context, user_id, via_callback=True)
            else:
                # Flux manual -> avanseaza
                users_repo.set_onboarding_step(session, user, STEP_ACTIVITATE)
                session.commit()
                label = FORME_BY_CODE[sub]["label"]
                await query.edit_message_text(
                    f"✅ Bun — Formă juridică: *{label}*", parse_mode="Markdown",
                )
                await send_step_question(update, context, STEP_ACTIVITATE, user_id)
            return

        # === ACTIVITY ===
        if action == "activity" and sub in ACTIVITIES_BY_CODE:
            act = ACTIVITIES_BY_CODE[sub]
            updates = {"activity_code": sub}
            profile = users_repo.get_profile_dict(session, user_id) or {}
            if not profile.get("caen_principal") and act.get("caen"):
                updates["caen_principal"] = act["caen"]
            users_repo.update_profile(session, user, **updates)
            session.commit()
            if context.user_data.pop("onb_fixing", None):
                await _show_anaf_summary(update, context, user_id, via_callback=True)
            else:
                users_repo.set_onboarding_step(session, user, STEP_REGIM_TVA)
                session.commit()
                await query.edit_message_text(f"✅ Bun — Activitate: {act['label']}")
                await send_step_question(update, context, STEP_REGIM_TVA, user_id)
            return

        # === REGIM TVA ===
        if action == "tva" and sub in REGIM_TVA_BY_CODE:
            users_repo.update_profile(session, user, regim_tva=sub)
            session.commit()
            if context.user_data.pop("onb_fixing", None):
                await _show_anaf_summary(update, context, user_id, via_callback=True)
            else:
                users_repo.set_onboarding_step(session, user, STEP_REGIM_IMPUNERE)
                session.commit()
                label = REGIM_TVA_BY_CODE[sub]["label"]
                await query.edit_message_text(f"✅ Bun — Regim TVA: {label}")
                await send_step_question(update, context, STEP_REGIM_IMPUNERE, user_id)
            return

        # === REGIM IMPUNERE ===
        if action == "impunere" and sub in (
            "SISTEM_REAL", "NORMA_VENIT", "MICRO_1", "MICRO_3"
        ):
            users_repo.update_profile(session, user, regim_impunere=sub)
            session.commit()
            if context.user_data.pop("onb_fixing", None):
                await _show_anaf_summary(update, context, user_id, via_callback=True)
            else:
                # Ridesharing → întrebăm regimul nerezident D100; altfel confirmare.
                profile = users_repo.get_profile_dict(session, user_id) or {}
                next_step = next_step_after_impunere(profile.get("activity_code"))
                users_repo.set_onboarding_step(session, user, next_step)
                session.commit()
                await query.edit_message_text(
                    f"✅ Bun — Regim impunere: {regim_impunere_label(sub)}"
                )
                await send_step_question(update, context, next_step, user_id)
            return

        # === GATE PLATFORME (sub-pas C — ce platforme folosește, doar ridesharing) ===
        if action == "platforme" and sub in ("BOLT", "UBER", "AMBELE"):
            # Reținem alegerea ca să știm dacă după Bolt mai urmează Uber („Ambele").
            context.user_data["onb_platforme"] = sub
            first = STEP_REGIM_NEREZIDENT_UBER if sub == "UBER" else STEP_REGIM_NEREZIDENT_BOLT
            users_repo.set_onboarding_step(session, user, first)
            session.commit()
            await query.edit_message_text(
                "✅ Platforme: " + {
                    "BOLT": "Bolt", "UBER": "Uber", "AMBELE": "Bolt + Uber",
                }[sub]
            )
            await send_step_question(update, context, first, user_id)
            return

        # === REGIM NEREZIDENT (D100 — per-platformă, doar ridesharing) ===
        # Rutare după codul ales: BOLT_* → regim_nerezident_bolt; UBER_* →
        # regim_nerezident_uber. Scriem câmpul NOU (per-platformă, sub-pas A);
        # citirea păstrează fallback la deprecatul `regim_nerezident`.
        if action == "nerezident" and sub in REGIM_NEREZIDENT_BY_CODE:
            if sub in users_repo.VALID_REGIMURI_NEREZIDENT_BOLT:
                users_repo.update_profile(session, user, regim_nerezident_bolt=sub)
                e_bolt = True
            else:  # sub ∈ VALID_REGIMURI_NEREZIDENT_UBER (seturi separate, fără cross)
                users_repo.update_profile(session, user, regim_nerezident_uber=sub)
                e_bolt = False
            session.commit()
            if context.user_data.pop("onb_fixing", None):
                await _show_anaf_summary(update, context, user_id, via_callback=True)
            else:
                # „Ambele": după Bolt urmează Uber; altfel → confirmare.
                if e_bolt and context.user_data.get("onb_platforme") == "AMBELE":
                    next_step = STEP_REGIM_NEREZIDENT_UBER
                else:
                    context.user_data.pop("onb_platforme", None)
                    next_step = STEP_CONFIRMARE
                users_repo.set_onboarding_step(session, user, next_step)
                session.commit()
                await query.edit_message_text(
                    f"✅ Regim nerezident: {nerezident_label(sub)}"
                )
                await send_step_question(update, context, next_step, user_id)
            return

        # === Finalize (din fluxul manual) ===
        if action == "finalize":
            if sub == "yes":
                await _finalize(update, context, session, user, user_id)
            elif sub == "restart":
                users_repo.reset_onboarding(session, user)
                session.commit()
                await query.edit_message_text("🔄 Reluăm de la început...")
                await start_onboarding(update, context)
            return

    except Exception as e:
        session.rollback()
        logger.exception("handle_onboarding_callback error")
        try:
            await query.edit_message_text(
                "⚠️ N-am putut continua configurarea. Încearcă din nou cu /start."
            )
        except Exception:
            pass
    finally:
        session.close()


# ============================================================
#                    FINALIZARE
# ============================================================

async def _finalize(update, context, session, user, user_id):
    """Finalizeaza onboarding-ul si afiseaza mesajul de bun venit."""
    query = update.callback_query
    chat_id = query.message.chat_id

    users_repo.complete_onboarding(session, user)
    session.commit()

    # Verificam activitatea pentru pasul urmator
    profile = users_repo.get_profile_dict(session, user_id) or {}
    activity = profile.get("activity_code") or ""
    nume = profile.get("name") or "șofer"

    await query.edit_message_text(
        "🎉 *Profil completat cu succes!*\n\n"
        "Acum poți trimite poze cu bonuri/facturi sau screenshot-uri "
        "Bolt — botul te ajută cu restul.",
        parse_mode="Markdown",
    )

    # === Faza 1: oferta coduri fiscale speciale (optional) ===
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "🔑 *Coduri fiscale (opțional)*\n\n"
            "Dacă ai *cod special de TVA* (art. 317 — pentru tranzacții cu "
            "firme din UE) sau vrei să salvezi *CNP-ul* pentru Declarația "
            "Unică, le poți adăuga acum. Le poți seta oricând și din "
            "`/coduri_fiscale`."
        ),
        parse_mode="Markdown",
        reply_markup=_kb_coduri_onboarding(),
    )

    # Daca e ridesharing -> sugeram adaugarea masinii direct
    if activity == "ridesharing":
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"🚗 *{nume}, hai să-ți configurăm mașina!*\n\n"
                "Pentru foaia de parcurs și deductibilitatea combustibilului, "
                "adaugă mașina cu care lucrezi."
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚗 Adaugă mașina acum", callback_data="vehicul|add")],
                [InlineKeyboardButton("⏭️ Mai târziu", callback_data="onb|done")],
            ]),
        )
    else:
        from bot_contabil import build_main_menu
        await context.bot.send_message(
            chat_id=chat_id,
            text="📋 Meniu principal:",
            reply_markup=build_main_menu(),
        )


# ============================================================
#                    UTILITY
# ============================================================

def user_is_in_onboarding(telegram_id: int) -> bool:
    """True daca user e in mijlocul onboarding-ului."""
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
    """True daca user a terminat onboarding-ul."""
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
