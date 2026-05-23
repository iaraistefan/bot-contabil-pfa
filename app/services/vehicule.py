"""
Pas A.2 - Modul UI pentru managementul vehiculelor.

Permite user-ului sa adauge, editeze si stearga masini, cu un wizard
conversational. Limita de masini se aplica automat pe baza formei
juridice (PFA = 1 masina, SRL/I.I. = flota).

INTEGRARE in bot_contabil.py:
  - Buton meniu: vehicule.BTN_VEHICULE
  - In handle_text_wrapper, INAINTE de procesarea documentelor:
        if vehicule.is_in_wizard(context):
            handled = await vehicule.handle_wizard_text(update, context)
            if handled:
                return
  - In callback router, namespace "vehicul":
        if namespace == "vehicul":
            await vehicule.handle_callback(update, context, parts)
            return

CALLBACK namespace "vehicul":
  vehicul|menu                  - meniul masinilor
  vehicul|add                   - porneste wizard adaugare
  vehicul|view|<id>             - detalii masina
  vehicul|edit|<id>             - meniu editare (alege campul)
  vehicul|ef|<id>|<field>       - editeaza un camp (nr/marca/consum)
  vehicul|setc|<val>            - in wizard: seteaza consum din buton
  vehicul|tip|<TIP>             - in wizard: seteaza tip detinere (finalizeaza)
  vehicul|del|<id>              - cere confirmare stergere
  vehicul|delok|<id>            - executa stergerea (soft)
  vehicul|cancel                - anuleaza wizard-ul curent

CHANGELOG:
  - v1 (Pas A.2): Versiune initiala
"""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db import get_session
from app.repositories import users as users_repo
from app.repositories import vehicule as vehicule_repo
from app.repositories import audit as audit_repo
from app.models import (
    TIP_DETINERE_LABELS,
    TIP_DETINERE_PROPRIETATE, TIP_DETINERE_COMODAT,
    TIP_DETINERE_LEASING, TIP_DETINERE_INCHIRIERE,
)

logger = logging.getLogger(__name__)

BTN_VEHICULE = "🚗 Mașinile mele"

# Cheia sub care tinem starea wizard-ului in context.user_data
_WIZARD_KEY = "vehicul_wizard"

# Valori rapide pentru norma de consum (butoane)
CONSUM_PRESETS = [6.5, 7.0, 7.5, 8.0, 9.0]

# Ordinea tipurilor de detinere in meniu
TIP_ORDER = [
    TIP_DETINERE_COMODAT,
    TIP_DETINERE_PROPRIETATE,
    TIP_DETINERE_LEASING,
    TIP_DETINERE_INCHIRIERE,
]


# ============================================================
#       HELPERS
# ============================================================

def is_in_wizard(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """True daca user-ul e in mijlocul unui wizard de vehicul."""
    return bool(context.user_data.get(_WIZARD_KEY))


def _clear_wizard(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(_WIZARD_KEY, None)


def _get_user_id(update: Update) -> int:
    """Rezolva user_id-ul DB-intern din update."""
    session = get_session()
    try:
        tg_user = update.effective_user
        user = users_repo.get_by_telegram_id(session, telegram_id=tg_user.id)
        return user.id if user else None
    finally:
        session.close()


def _get_forma_juridica(user_id: int) -> str:
    session = get_session()
    try:
        profile = users_repo.get_profile_dict(session, user_id) or {}
        return profile.get("firma_forma_juridica") or ""
    finally:
        session.close()


def _vehicul_line(v) -> str:
    """Formateaza o linie descriptiva pentru un vehicul."""
    nume = v.marca_model or "fără model"
    tip = TIP_DETINERE_LABELS.get(v.tip_detinere or "", "tip nedefinit")
    km = f" · {v.km_curent:,} km".replace(",", ".") if v.km_curent else ""
    return (
        f"🚗 *{v.nr_inmatriculare}* — {nume}\n"
        f"   ⛽ {v.norma_consum:g} L/100km · {tip}{km}"
    )


# ============================================================
#       MENIU PRINCIPAL VEHICULE
# ============================================================

def _build_menu(vehicule_list, can_add: bool):
    """Construieste meniul cu lista de masini si butoane."""
    rows = []
    for v in vehicule_list:
        label = f"🚗 {v.nr_inmatriculare}"
        if v.marca_model:
            label += f" — {v.marca_model[:20]}"
        rows.append([InlineKeyboardButton(label, callback_data=f"vehicul|view|{v.id}")])

    if can_add:
        rows.append([InlineKeyboardButton("➕ Adaugă mașină", callback_data="vehicul|add")])

    rows.append([InlineKeyboardButton("❌ Închide", callback_data="nav|close")])
    return InlineKeyboardMarkup(rows)


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE,
                    edit: bool = False):
    """Afiseaza meniul masinilor."""
    user_id = _get_user_id(update)
    if not user_id:
        return

    session = get_session()
    try:
        vehicule_list = vehicule_repo.list_active(session, user_id)
    finally:
        session.close()

    forma = _get_forma_juridica(user_id)
    max_v = vehicule_repo.max_vehicule_for_forma(forma)
    can_add = len(vehicule_list) < max_v

    if not vehicule_list:
        text = (
            "🚗 *Mașinile mele*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Nu ai nicio mașină înregistrată.\n\n"
            "Adaugă mașina cu care lucrezi — e necesară pentru "
            "foaia de parcurs și deductibilitatea combustibilului."
        )
    else:
        lines = [_vehicul_line(v) for v in vehicule_list]
        text = (
            "🚗 *Mașinile mele*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            + "\n\n".join(lines)
        )
        if not can_add:
            if max_v == 1:
                text += (
                    "\n\n_Forma ta juridică permite o singură mașină. "
                    "Pentru a schimba mașina, editeaz-o pe cea existentă._"
                )

    markup = _build_menu(vehicule_list, can_add)

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=markup
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=text,
            parse_mode="Markdown", reply_markup=markup,
        )


async def handle_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Apelat cand user-ul apasa butonul din meniul principal."""
    _clear_wizard(context)
    await show_menu(update, context, edit=False)


# ============================================================
#       DETALII VEHICUL
# ============================================================

async def _show_vehicul_detail(update, context, user_id, vehicul_id):
    session = get_session()
    try:
        v = vehicule_repo.get_by_id(session, vehicul_id, user_id)
        if not v:
            await update.callback_query.edit_message_text("⚠️ Mașina nu a fost găsită.")
            return
        nume = v.marca_model or "—"
        tip = TIP_DETINERE_LABELS.get(v.tip_detinere or "", "—")
        km = f"{v.km_curent:,} km".replace(",", ".") if v.km_curent else "—"
        text = (
            f"🚗 *{v.nr_inmatriculare}*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🚙 Marca/model: *{nume}*\n"
            f"⛽ Normă consum: *{v.norma_consum:g} L/100km*\n"
            f"📋 Deținere: *{tip}*\n"
            f"🛣️ Kilometraj curent: *{km}*\n"
        )
        # Avertisment fiscal pentru comodat
        if v.tip_detinere == TIP_DETINERE_COMODAT:
            text += (
                "\n💡 _Mașină în comodat: combustibilul e deductibil "
                "pe baza foii de parcurs, dar RCA/CASCO nu sunt deductibile._"
            )
    finally:
        session.close()

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Editează", callback_data=f"vehicul|edit|{vehicul_id}")],
        [InlineKeyboardButton("🗑️ Șterge", callback_data=f"vehicul|del|{vehicul_id}")],
        [InlineKeyboardButton("⬅️ Înapoi", callback_data="vehicul|menu")],
    ])
    await update.callback_query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=markup
    )


# ============================================================
#       WIZARD - ADAUGARE / EDITARE
# ============================================================

async def _start_add_wizard(update, context, user_id):
    """Porneste wizard-ul de adaugare a unei masini."""
    # Verificam limita pe forma juridica
    session = get_session()
    try:
        count = vehicule_repo.count_active(session, user_id)
    finally:
        session.close()

    forma = _get_forma_juridica(user_id)
    max_v = vehicule_repo.max_vehicule_for_forma(forma)

    if count >= max_v:
        await update.callback_query.edit_message_text(
            f"⚠️ Ai atins limita de {max_v} "
            f"{'mașină' if max_v == 1 else 'mașini'} pentru forma ta juridică.\n\n"
            "Editează mașina existentă dacă vrei să o schimbi.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Înapoi", callback_data="vehicul|menu")
            ]]),
        )
        return

    context.user_data[_WIZARD_KEY] = {
        "mode": "add", "step": "nr", "data": {},
    }
    await update.callback_query.edit_message_text(
        "➕ *Adaugă mașină* (1/4)\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Scrie *numărul de înmatriculare*.\n"
        "Exemplu: `BN 12 ABC`\n\n"
        "_Scrie /anulare pentru a renunța._",
        parse_mode="Markdown",
    )


async def _start_edit_wizard(update, context, user_id, vehicul_id):
    """Afiseaza meniul de editare - alegerea campului."""
    session = get_session()
    try:
        v = vehicule_repo.get_by_id(session, vehicul_id, user_id)
        if not v:
            await update.callback_query.edit_message_text("⚠️ Mașina nu a fost găsită.")
            return
    finally:
        session.close()

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔢 Nr. înmatriculare", callback_data=f"vehicul|ef|{vehicul_id}|nr")],
        [InlineKeyboardButton("🚙 Marcă / model", callback_data=f"vehicul|ef|{vehicul_id}|marca")],
        [InlineKeyboardButton("⛽ Normă consum", callback_data=f"vehicul|ef|{vehicul_id}|consum")],
        [InlineKeyboardButton("📋 Tip deținere", callback_data=f"vehicul|ef|{vehicul_id}|tip")],
        [InlineKeyboardButton("⬅️ Înapoi", callback_data=f"vehicul|view|{vehicul_id}")],
    ])
    await update.callback_query.edit_message_text(
        "✏️ *Editare mașină*\n\nCe vrei să modifici?",
        parse_mode="Markdown", reply_markup=markup,
    )


async def _edit_field(update, context, user_id, vehicul_id, field):
    """Porneste editarea unui camp specific."""
    if field == "tip":
        # Tip detinere -> butoane direct
        context.user_data[_WIZARD_KEY] = {
            "mode": "edit", "step": "tip", "vehicul_id": vehicul_id, "data": {},
        }
        await _ask_tip_detinere(update, context, edit=True)
        return

    if field == "consum":
        context.user_data[_WIZARD_KEY] = {
            "mode": "edit", "step": "consum", "vehicul_id": vehicul_id, "data": {},
        }
        await _ask_consum(update, context, edit=True)
        return

    # nr / marca -> input text
    prompts = {
        "nr": "Scrie noul *număr de înmatriculare*.\nExemplu: `BN 12 ABC`",
        "marca": "Scrie noua *marcă și model*.\nExemplu: `Dacia Logan`",
    }
    context.user_data[_WIZARD_KEY] = {
        "mode": "edit", "step": field, "vehicul_id": vehicul_id, "data": {},
    }
    await update.callback_query.edit_message_text(
        f"✏️ *Editare*\n\n{prompts.get(field, 'Scrie noua valoare.')}\n\n"
        "_Scrie /anulare pentru a renunța._",
        parse_mode="Markdown",
    )


async def _ask_consum(update, context, edit=False):
    """Afiseaza butoanele pentru norma de consum."""
    row = [
        InlineKeyboardButton(f"{c:g}", callback_data=f"vehicul|setc|{c:g}")
        for c in CONSUM_PRESETS
    ]
    markup = InlineKeyboardMarkup([
        row,
        [InlineKeyboardButton("❌ Anulează", callback_data="vehicul|cancel")],
    ])
    step_label = "" if edit else " (3/4)"
    text = (
        f"⛽ *Normă consum{step_label}*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Alege norma ta de consum (L/100km) sau scrie o valoare proprie.\n\n"
        "_Pentru oraș/aglomerație, 7.5 e o valoare uzuală._"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=markup
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=text,
            parse_mode="Markdown", reply_markup=markup,
        )


async def _ask_tip_detinere(update, context, edit=False):
    """Afiseaza butoanele pentru tipul de detinere."""
    rows = [
        [InlineKeyboardButton(TIP_DETINERE_LABELS[t], callback_data=f"vehicul|tip|{t}")]
        for t in TIP_ORDER
    ]
    rows.append([InlineKeyboardButton("❌ Anulează", callback_data="vehicul|cancel")])
    step_label = "" if edit else " (4/4)"
    text = (
        f"📋 *Tip deținere{step_label}*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Cum deții mașina? Asta decide deductibilitatea RCA/CASCO:\n\n"
        "• *Comodat* — mașină personală → RCA/CASCO nedeductibile\n"
        "• *Proprietate/Leasing/Închiriere* → RCA/CASCO deductibile"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows)
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=text,
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows),
        )


# ============================================================
#       PROCESARE INPUT TEXT (wizard)
# ============================================================

async def handle_wizard_text(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Proceseaza input text cand user-ul e intr-un wizard de vehicul.
    Returneaza True daca a consumat mesajul, False altfel.
    """
    wizard = context.user_data.get(_WIZARD_KEY)
    if not wizard:
        return False

    text = (update.message.text or "").strip()

    # Anulare
    if text.lower() in ("/anulare", "anulare", "/cancel"):
        _clear_wizard(context)
        await update.message.reply_text("❌ Operațiune anulată.")
        await show_menu(update, context, edit=False)
        return True

    step = wizard.get("step")
    mode = wizard.get("mode")

    # --- Pas: numar inmatriculare ---
    if step == "nr":
        nr = text.upper()
        if len(nr) < 4:
            await update.message.reply_text(
                "⚠️ Numărul pare prea scurt. Scrie-l complet, ex: `BN 12 ABC`",
                parse_mode="Markdown",
            )
            return True
        if mode == "add":
            wizard["data"]["nr_inmatriculare"] = nr
            wizard["step"] = "marca"
            await update.message.reply_text(
                "➕ *Adaugă mașină* (2/4)\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "Scrie *marca și modelul*.\n"
                "Exemplu: `Dacia Logan`\n\n"
                "_Scrie `-` dacă vrei să sari peste._",
                parse_mode="Markdown",
            )
        else:  # edit
            await _apply_edit(update, context, wizard, "nr_inmatriculare", nr)
        return True

    # --- Pas: marca/model ---
    if step == "marca":
        marca = None if text == "-" else text
        if mode == "add":
            wizard["data"]["marca_model"] = marca
            wizard["step"] = "consum"
            await _ask_consum(update, context, edit=False)
        else:  # edit
            await _apply_edit(update, context, wizard, "marca_model", marca)
        return True

    # --- Pas: consum (text liber) ---
    if step == "consum":
        consum = _parse_consum(text)
        if consum is None:
            await update.message.reply_text(
                "⚠️ Valoare invalidă. Scrie un număr între 3 și 25, ex: `7.5`",
                parse_mode="Markdown",
            )
            return True
        if mode == "add":
            wizard["data"]["norma_consum"] = consum
            wizard["step"] = "tip"
            await _ask_tip_detinere(update, context, edit=False)
        else:  # edit
            await _apply_edit(update, context, wizard, "norma_consum", consum)
        return True

    # Step necunoscut - resetam ca sa nu blocam user-ul
    _clear_wizard(context)
    return False


def _parse_consum(text: str):
    """Parseaza norma de consum dintr-un text. Returneaza float sau None."""
    cleaned = text.replace(",", ".").replace("l", "").replace("L", "").strip()
    try:
        val = float(cleaned)
    except ValueError:
        return None
    if 3.0 <= val <= 25.0:
        return val
    return None


# ============================================================
#       FINALIZARE (creare / editare in DB)
# ============================================================

async def _finalize_add(update, context, wizard, tip_detinere):
    """Creeaza vehiculul in DB la sfarsitul wizard-ului de adaugare."""
    user_id = _get_user_id(update)
    data = wizard.get("data", {})
    _clear_wizard(context)

    session = get_session()
    try:
        v = vehicule_repo.create(
            session, user_id=user_id,
            nr_inmatriculare=data.get("nr_inmatriculare"),
            marca_model=data.get("marca_model"),
            norma_consum=data.get("norma_consum", 7.5),
            tip_detinere=tip_detinere,
        )
        audit_repo.write(
            session, entity_type="vehicul", entity_id=v.id,
            action="create", user_id=user_id, source="user",
            after=vehicule_repo.to_dict(v),
        )
        session.commit()
        vehicul_id = v.id
    except Exception as e:
        session.rollback()
        logger.error(f"finalize_add error: {e}")
        await _safe_reply(update, context, "❌ Eroare la salvarea mașinii.")
        return
    finally:
        session.close()

    nume = data.get("marca_model") or "—"
    tip_label = TIP_DETINERE_LABELS.get(tip_detinere, "—")
    msg = (
        "✅ *Mașină adăugată!*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🚗 {data.get('nr_inmatriculare')} — {nume}\n"
        f"⛽ {data.get('norma_consum', 7.5):g} L/100km · {tip_label}\n\n"
        "Acum poți folosi foaia de parcurs pentru această mașină."
    )
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("🚗 Mașinile mele", callback_data="vehicul|menu")
    ]])
    if update.callback_query:
        await update.callback_query.edit_message_text(
            msg, parse_mode="Markdown", reply_markup=markup
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=msg,
            parse_mode="Markdown", reply_markup=markup,
        )


async def _apply_edit(update, context, wizard, field, value):
    """Aplica o editare de camp in DB."""
    user_id = _get_user_id(update)
    vehicul_id = wizard.get("vehicul_id")
    _clear_wizard(context)

    session = get_session()
    try:
        v = vehicule_repo.get_by_id(session, vehicul_id, user_id)
        if not v:
            await _safe_reply(update, context, "⚠️ Mașina nu a fost găsită.")
            return
        before = vehicule_repo.to_dict(v)
        vehicule_repo.update(session, v, **{field: value})
        audit_repo.write(
            session, entity_type="vehicul", entity_id=v.id,
            action="update", user_id=user_id, source="user",
            before=before, after=vehicule_repo.to_dict(v),
            note=f"field={field}",
        )
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"apply_edit error: {e}")
        await _safe_reply(update, context, "❌ Eroare la salvare.")
        return
    finally:
        session.close()

    msg = "✅ Modificare salvată."
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("🚗 Vezi mașina", callback_data=f"vehicul|view|{vehicul_id}")
    ]])
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=markup)
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=msg, reply_markup=markup
        )


async def _safe_reply(update, context, text):
    """Trimite un mesaj indiferent daca update e callback sau mesaj."""
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(text)
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id, text=text
            )
    except Exception:
        pass


# ============================================================
#       STERGERE
# ============================================================

async def _ask_delete(update, context, user_id, vehicul_id):
    session = get_session()
    try:
        v = vehicule_repo.get_by_id(session, vehicul_id, user_id)
        if not v:
            await update.callback_query.edit_message_text("⚠️ Mașina nu a fost găsită.")
            return
        nr = v.nr_inmatriculare
    finally:
        session.close()

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Da, șterge", callback_data=f"vehicul|delok|{vehicul_id}"),
            InlineKeyboardButton("❌ Nu", callback_data=f"vehicul|view|{vehicul_id}"),
        ],
    ])
    await update.callback_query.edit_message_text(
        f"🗑️ *Ștergere mașină*\n\n"
        f"Sigur vrei să ștergi *{nr}*?\n\n"
        "_Foile de parcurs deja înregistrate rămân în istoric._",
        parse_mode="Markdown", reply_markup=markup,
    )


async def _do_delete(update, context, user_id, vehicul_id):
    session = get_session()
    try:
        v = vehicule_repo.get_by_id(session, vehicul_id, user_id)
        if not v:
            await update.callback_query.edit_message_text("⚠️ Mașina nu a fost găsită.")
            return
        before = vehicule_repo.to_dict(v)
        nr = v.nr_inmatriculare
        vehicule_repo.soft_delete(session, v)
        audit_repo.write(
            session, entity_type="vehicul", entity_id=v.id,
            action="delete", user_id=user_id, source="user",
            before=before, after={"activ": False},
        )
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"do_delete error: {e}")
        await update.callback_query.edit_message_text("❌ Eroare la ștergere.")
        return
    finally:
        session.close()

    await update.callback_query.edit_message_text(
        f"✅ Mașina *{nr}* a fost ștearsă.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🚗 Mașinile mele", callback_data="vehicul|menu")
        ]]),
    )


# ============================================================
#       CALLBACK ROUTER
# ============================================================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          parts: list):
    """Router pentru callback-urile din namespace-ul 'vehicul'."""
    query = update.callback_query
    user_id = _get_user_id(update)
    if not user_id:
        await query.edit_message_text("⚠️ Eroare identificare utilizator.")
        return

    action = parts[1] if len(parts) > 1 else ""

    try:
        if action == "menu":
            _clear_wizard(context)
            await show_menu(update, context, edit=True)

        elif action == "add":
            await _start_add_wizard(update, context, user_id)

        elif action == "view":
            await _show_vehicul_detail(update, context, user_id, int(parts[2]))

        elif action == "edit":
            await _start_edit_wizard(update, context, user_id, int(parts[2]))

        elif action == "ef":  # edit field
            await _edit_field(update, context, user_id, int(parts[2]), parts[3])

        elif action == "setc":  # set consum din buton
            await _handle_setc(update, context, float(parts[2]))

        elif action == "tip":  # set tip detinere
            await _handle_tip(update, context, parts[2])

        elif action == "del":
            await _ask_delete(update, context, user_id, int(parts[2]))

        elif action == "delok":
            await _do_delete(update, context, user_id, int(parts[2]))

        elif action == "cancel":
            _clear_wizard(context)
            await show_menu(update, context, edit=True)

    except Exception as e:
        logger.error(f"vehicul callback error parts={parts}: {e}")
        try:
            await query.edit_message_text(f"❌ Eroare: {str(e)[:150]}")
        except Exception:
            pass


async def _handle_setc(update, context, consum):
    """Buton consum apasat in wizard."""
    wizard = context.user_data.get(_WIZARD_KEY)
    if not wizard:
        await update.callback_query.edit_message_text("⚠️ Sesiune expirată.")
        return

    if wizard.get("mode") == "add":
        wizard["data"]["norma_consum"] = consum
        wizard["step"] = "tip"
        await _ask_tip_detinere(update, context, edit=False)
    else:  # edit
        await _apply_edit(update, context, wizard, "norma_consum", consum)


async def _handle_tip(update, context, tip):
    """Buton tip detinere apasat in wizard."""
    wizard = context.user_data.get(_WIZARD_KEY)
    if not wizard:
        await update.callback_query.edit_message_text("⚠️ Sesiune expirată.")
        return

    if tip not in TIP_DETINERE_LABELS:
        await update.callback_query.edit_message_text("⚠️ Tip invalid.")
        return

    if wizard.get("mode") == "add":
        await _finalize_add(update, context, wizard, tip)
    else:  # edit
        await _apply_edit(update, context, wizard, "tip_detinere", tip)
