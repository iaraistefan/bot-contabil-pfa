"""
Pas A.3 - Modul foaie de parcurs (jurnal km auto).

Comenzi text:
  parcurs start <KM>            - porneste o tura (km de pe bord)
  parcurs start <KM> <traseu>   - cu descriere traseu optionala
  parcurs stop <KM>             - inchide tura curenta
  parcurs <KM_START> <KM_STOP>  - tura completa intr-o comanda (backup)
  parcurs                       - afiseaza statusul / jurnalul lunii

Km personali se deduc automat din "gap-urile" de kilometraj intre ture
(diferenta dintre odometrul de stop al unei ture si cel de start al urmatoarei).

INTEGRARE in bot_contabil.py:
  - In handle_text_wrapper, INAINTE de procesarea documentelor:
        if foaie_parcurs.match_command(text):
            await foaie_parcurs.handle_command(update, context)
            return
  - In callback router, namespace "parcurs":
        if namespace == "parcurs":
            await foaie_parcurs.handle_callback(update, context, parts)
            return

CALLBACK namespace "parcurs":
  parcurs|status               - status / sumar luna curenta
  parcurs|luni                 - alege luna pentru jurnal
  parcurs|jurnal|<an>|<luna>   - afiseaza jurnalul lunii
  parcurs|del|<trip_id>        - cere confirmare stergere tura
  parcurs|delok|<trip_id>      - executa stergerea

CHANGELOG:
  - v1 (Pas A.3): Versiune initiala
"""

import logging
from datetime import datetime

import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db import get_session
from app.repositories import users as users_repo
from app.repositories import vehicule as vehicule_repo
from app.repositories import trip_logs as trip_repo
from app.repositories import audit as audit_repo
from app.integrations.exports import foaie_parcurs_export
from app.models import TRIP_STATUS_OPEN, TRIP_STATUS_CLOSED

logger = logging.getLogger(__name__)

BTN_PARCURS = "🛣️ Foaie parcurs"

RO_TZ = pytz.timezone("Europe/Bucharest")

# Sanity check: km parcursi intr-o tura peste aceasta valoare = suspect
MAX_KM_TURA = 1500

LUNI_LONG = {
    1: "Ianuarie", 2: "Februarie", 3: "Martie", 4: "Aprilie",
    5: "Mai", 6: "Iunie", 7: "Iulie", 8: "August",
    9: "Septembrie", 10: "Octombrie", 11: "Noiembrie", 12: "Decembrie",
}
LUNI_SHORT = {
    1: "Ian", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Mai", 6: "Iun",
    7: "Iul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


# ============================================================
#       HELPERS
# ============================================================

def _now_ro() -> datetime:
    """Data si ora curenta in timezone Romania."""
    return datetime.now(RO_TZ)


def _get_user_id(update: Update) -> int:
    session = get_session()
    try:
        user = users_repo.get_by_telegram_id(
            session, telegram_id=update.effective_user.id
        )
        return user.id if user else None
    finally:
        session.close()


def _parse_int(token: str):
    """Parseaza un intreg dintr-un token (ignora puncte/spatii din mii)."""
    if token is None:
        return None
    cleaned = token.replace(".", "").replace(",", "").replace(" ", "").strip()
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def _fmt_km(value) -> str:
    """Formateaza un numar de km cu separator de mii (125.430)."""
    try:
        return f"{int(round(value)):,}".replace(",", ".")
    except (ValueError, TypeError):
        return str(value)


# ============================================================
#       LOGICA PURA - sumar lunar
# ============================================================

def compute_month_summary(trips: list) -> dict:
    """
    Calculeaza sumarul unei luni din lista de ture.

    Km business  = suma km din turele inchise.
    Km personali = suma "gap-urilor" de odometru intre ture consecutive
                   (cand odometrul de start al unei ture > odometrul de
                   stop al turei precedente, diferenta a fost parcursa
                   in interes personal).
    """
    closed = [t for t in trips if t.status == TRIP_STATUS_CLOSED]
    has_open = any(t.status == TRIP_STATUS_OPEN for t in trips)

    km_business = sum((t.km or 0.0) for t in closed)

    # Km personali din gap-uri - doar turele cu odometru complet
    with_odo = sorted(
        [
            t for t in closed
            if t.odometer_start is not None and t.odometer_end is not None
        ],
        key=lambda t: (t.trip_date, t.odometer_start),
    )
    km_personal = 0.0
    for i in range(len(with_odo) - 1):
        gap = with_odo[i + 1].odometer_start - with_odo[i].odometer_end
        if gap > 0:
            km_personal += gap

    km_total = km_business + km_personal
    pct_business = (km_business / km_total * 100.0) if km_total > 0 else 0.0

    return {
        "nr_ture": len(closed),
        "km_business": km_business,
        "km_personal": km_personal,
        "km_total": km_total,
        "pct_business": pct_business,
        "has_open": has_open,
    }


# ============================================================
#       COMANDA TEXT
# ============================================================

def match_command(text: str) -> bool:
    """True daca textul e o comanda de foaie de parcurs."""
    if not text:
        return False
    return text.strip().lower().startswith("parcurs")


async def handle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Proceseaza o comanda text 'parcurs ...'."""
    text = (update.message.text or "").strip()
    tokens = text.split()
    rest = tokens[1:]  # tokens[0] = "parcurs"

    user_id = _get_user_id(update)
    if not user_id:
        await update.message.reply_text("⚠️ Eroare identificare utilizator.")
        return

    # Fara argumente -> status
    if not rest:
        await _show_status(update, context, user_id)
        return

    sub = rest[0].lower()

    if sub == "start":
        km = _parse_int(rest[1]) if len(rest) > 1 else None
        purpose = " ".join(rest[2:]) if len(rest) > 2 else None
        await _cmd_start(update, context, user_id, km, purpose)

    elif sub == "stop":
        km = _parse_int(rest[1]) if len(rest) > 1 else None
        await _cmd_stop(update, context, user_id, km)

    elif sub in ("status", "jurnal"):
        await _show_status(update, context, user_id)

    else:
        # Poate sunt doua numere: parcurs 125430 125680
        nums = [_parse_int(x) for x in rest]
        valid = [n for n in nums if n is not None]
        if len(valid) == 2:
            await _cmd_complete(update, context, user_id, valid[0], valid[1])
        else:
            await update.message.reply_text(
                "⚠️ Comandă neînțeleasă.\n\n"
                "Folosește:\n"
                "• `parcurs start 125430` — pornești tura\n"
                "• `parcurs stop 125680` — închizi tura\n"
                "• `parcurs 125430 125680` — tură completă\n"
                "• `parcurs` — vezi jurnalul",
                parse_mode="Markdown",
            )


# ============================================================
#       COMANDA: START
# ============================================================

async def _cmd_start(update, context, user_id, km, purpose):
    if km is None or km <= 0:
        await update.message.reply_text(
            "⚠️ Scrie kilometrajul de pe bord.\n"
            "Exemplu: `parcurs start 125430`",
            parse_mode="Markdown",
        )
        return

    session = get_session()
    try:
        # 1. Verificam daca exista deja o tura deschisa
        open_trip = trip_repo.get_open_trip(session, user_id)
        if open_trip:
            await update.message.reply_text(
                f"⚠️ Ai deja o tură pornită la *{_fmt_km(open_trip.odometer_start)} km*"
                f"{' (' + open_trip.ora_start + ')' if open_trip.ora_start else ''}.\n\n"
                f"Închide-o întâi: `parcurs stop <km>`",
                parse_mode="Markdown",
            )
            return

        # 2. Gasim masina (default = prima activa)
        vehicul = vehicule_repo.get_default(session, user_id)
        if not vehicul:
            await update.message.reply_text(
                "⚠️ Nu ai nicio mașină înregistrată.\n\n"
                "Adaugă întâi mașina din meniul *🚗 Mașinile mele*.",
                parse_mode="Markdown",
            )
            return

        # 3. Sanity check fata de km_curent al masinii
        avertisment = ""
        if vehicul.km_curent and km < vehicul.km_curent:
            avertisment = (
                f"\n\n⚠️ _Atenție: {_fmt_km(km)} km e sub kilometrajul "
                f"cunoscut ({_fmt_km(vehicul.km_curent)} km). Verifică cifra._"
            )

        now = _now_ro()
        ora = now.strftime("%H:%M")
        trip_date = now.date()

        trip = trip_repo.create_open(
            session, user_id=user_id, vehicul_id=vehicul.id,
            odometer_start=km, trip_date=trip_date,
            ora_start=ora, purpose=purpose,
        )
        vehicule_repo.update_km_curent(session, vehicul, km)
        audit_repo.write(
            session, entity_type="trip_log", entity_id=trip.id,
            action="start", user_id=user_id, source="user",
            after=trip_repo.to_dict(trip),
        )
        session.commit()

        traseu_line = f"\n📍 Traseu: {purpose}" if purpose else ""
        await update.message.reply_text(
            "🚗 *Tură pornită!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🛣️ Kilometraj start: *{_fmt_km(km)} km*\n"
            f"🕐 Ora: *{ora}*\n"
            f"🚙 Mașina: {vehicul.nr_inmatriculare}{traseu_line}\n\n"
            f"_Când termini, scrie:_ `parcurs stop <km>`"
            f"{avertisment}",
            parse_mode="Markdown",
        )
    except Exception as e:
        session.rollback()
        logger.error(f"cmd_start error: {e}")
        await update.message.reply_text("❌ Eroare la pornirea turei.")
    finally:
        session.close()


# ============================================================
#       COMANDA: STOP
# ============================================================

async def _cmd_stop(update, context, user_id, km):
    if km is None or km <= 0:
        await update.message.reply_text(
            "⚠️ Scrie kilometrajul de pe bord.\n"
            "Exemplu: `parcurs stop 125680`",
            parse_mode="Markdown",
        )
        return

    session = get_session()
    try:
        open_trip = trip_repo.get_open_trip(session, user_id)
        if not open_trip:
            await update.message.reply_text(
                "⚠️ Nu ai nicio tură pornită.\n\n"
                "Pornește una: `parcurs start <km>`\n"
                "Sau înregistrează o tură completă: `parcurs 125430 125680`",
                parse_mode="Markdown",
            )
            return

        start_km = open_trip.odometer_start or 0
        if km <= start_km:
            await update.message.reply_text(
                f"⚠️ Kilometrajul de stop ({_fmt_km(km)}) trebuie să fie "
                f"mai mare decât cel de start ({_fmt_km(start_km)}).\n\n"
                "Verifică cifra și încearcă din nou.",
                parse_mode="Markdown",
            )
            return

        km_parcursi = km - start_km
        avertisment = ""
        if km_parcursi > MAX_KM_TURA:
            avertisment = (
                f"\n\n⚠️ _{_fmt_km(km_parcursi)} km într-o tură pare mult. "
                f"Dacă ai greșit, șterge tura din jurnal._"
            )

        now = _now_ro()
        ora_stop = now.strftime("%H:%M")

        trip_repo.close_trip(session, open_trip, odometer_end=km, ora_stop=ora_stop)

        # Update km masina
        vehicul = None
        if open_trip.vehicul_id:
            vehicul = vehicule_repo.get_by_id(session, open_trip.vehicul_id, user_id)
            if vehicul:
                vehicule_repo.update_km_curent(session, vehicul, km)

        audit_repo.write(
            session, entity_type="trip_log", entity_id=open_trip.id,
            action="stop", user_id=user_id, source="user",
            after=trip_repo.to_dict(open_trip),
        )
        session.commit()

        interval = ""
        if open_trip.ora_start:
            interval = f" ({open_trip.ora_start} → {ora_stop})"

        await update.message.reply_text(
            "✅ *Tură încheiată!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🛣️ {_fmt_km(start_km)} → {_fmt_km(km)} km\n"
            f"📊 *Parcurși azi: {_fmt_km(km_parcursi)} km*{interval}\n\n"
            f"_Tura a fost adăugată în foaia de parcurs._"
            f"{avertisment}",
            parse_mode="Markdown",
        )
    except Exception as e:
        session.rollback()
        logger.error(f"cmd_stop error: {e}")
        await update.message.reply_text("❌ Eroare la închiderea turei.")
    finally:
        session.close()


# ============================================================
#       COMANDA: TURA COMPLETA
# ============================================================

async def _cmd_complete(update, context, user_id, km_start, km_stop):
    if km_stop <= km_start:
        await update.message.reply_text(
            f"⚠️ Al doilea număr ({_fmt_km(km_stop)}) trebuie să fie "
            f"mai mare decât primul ({_fmt_km(km_start)}).",
            parse_mode="Markdown",
        )
        return

    session = get_session()
    try:
        vehicul = vehicule_repo.get_default(session, user_id)
        if not vehicul:
            await update.message.reply_text(
                "⚠️ Nu ai nicio mașină înregistrată.\n\n"
                "Adaugă întâi mașina din meniul *🚗 Mașinile mele*.",
                parse_mode="Markdown",
            )
            return

        km_parcursi = km_stop - km_start
        now = _now_ro()

        trip = trip_repo.create_complete(
            session, user_id=user_id, vehicul_id=vehicul.id,
            odometer_start=km_start, odometer_end=km_stop,
            trip_date=now.date(),
        )
        vehicule_repo.update_km_curent(session, vehicul, km_stop)
        audit_repo.write(
            session, entity_type="trip_log", entity_id=trip.id,
            action="create_complete", user_id=user_id, source="user",
            after=trip_repo.to_dict(trip),
        )
        session.commit()

        avertisment = ""
        if km_parcursi > MAX_KM_TURA:
            avertisment = f"\n\n⚠️ _{_fmt_km(km_parcursi)} km pare mult pentru o tură._"

        await update.message.reply_text(
            "✅ *Tură înregistrată!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🛣️ {_fmt_km(km_start)} → {_fmt_km(km_stop)} km\n"
            f"📊 *Parcurși: {_fmt_km(km_parcursi)} km*\n"
            f"🚙 Mașina: {vehicul.nr_inmatriculare}"
            f"{avertisment}",
            parse_mode="Markdown",
        )
    except Exception as e:
        session.rollback()
        logger.error(f"cmd_complete error: {e}")
        await update.message.reply_text("❌ Eroare la înregistrarea turei.")
    finally:
        session.close()


# ============================================================
#       STATUS / SUMAR LUNA
# ============================================================

async def _show_status(update, context, user_id, via_callback=False):
    """Afiseaza tura deschisa (daca exista) si sumarul lunii curente."""
    now = _now_ro()
    year, month = now.year, now.month

    session = get_session()
    try:
        open_trip = trip_repo.get_open_trip(session, user_id)
        trips = trip_repo.list_for_month(session, user_id, year, month)
    finally:
        session.close()

    summary = compute_month_summary(trips)

    lines = [
        "🛣️ *Foaie de parcurs*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    if open_trip:
        ora = f" ({open_trip.ora_start})" if open_trip.ora_start else ""
        lines.append(
            f"🟢 *Tură în desfășurare* — pornită la "
            f"{_fmt_km(open_trip.odometer_start)} km{ora}\n"
            f"   _Închide-o cu_ `parcurs stop <km>`"
        )
        lines.append("")

    lines.append(f"📅 *{LUNI_LONG[month]} {year}*")
    lines.append(f"• Ture înregistrate: *{summary['nr_ture']}*")
    lines.append(f"• Km business: *{_fmt_km(summary['km_business'])} km*")
    if summary["km_personal"] > 0:
        lines.append(f"• Km personali (gap): *{_fmt_km(summary['km_personal'])} km*")
        lines.append(f"• Utilizare business: *{summary['pct_business']:.0f}%*")

    if summary["nr_ture"] == 0 and not open_trip:
        lines.append("")
        lines.append(
            "_Nicio tură încă. Pornește prima cu_ `parcurs start <km>`"
        )

    text = "\n".join(lines)

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Vezi jurnalul lunii", callback_data=f"parcurs|jurnal|{year}|{month}")],
        [InlineKeyboardButton("🗓️ Altă lună", callback_data="parcurs|luni")],
        [InlineKeyboardButton("❌ Închide", callback_data="nav|close")],
    ])

    if via_callback and update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=markup
        )
    else:
        await update.message.reply_text(
            text, parse_mode="Markdown", reply_markup=markup
        )


# ============================================================
#       JURNAL LUNAR
# ============================================================

async def _show_jurnal(update, context, user_id, year, month):
    """Afiseaza lista turelor dintr-o luna."""
    session = get_session()
    try:
        trips = trip_repo.list_for_month(session, user_id, year, month)
    finally:
        session.close()

    summary = compute_month_summary(trips)

    if not trips:
        await update.callback_query.edit_message_text(
            f"📭 Nicio tură în {LUNI_LONG[month]} {year}.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Înapoi", callback_data="parcurs|status")
            ]]),
        )
        return

    lines = [
        f"📋 *Jurnal parcurs — {LUNI_LONG[month]} {year}*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    for t in trips:
        zi = t.trip_date.strftime("%d.%m") if t.trip_date else "—"
        if t.status == TRIP_STATUS_OPEN:
            lines.append(
                f"🟢 *{zi}* — pornită la {_fmt_km(t.odometer_start)} km (în curs)"
            )
        else:
            odo = ""
            if t.odometer_start is not None and t.odometer_end is not None:
                odo = f"  ({_fmt_km(t.odometer_start)}→{_fmt_km(t.odometer_end)})"
            ore = ""
            if t.ora_start and t.ora_stop:
                ore = f" {t.ora_start}-{t.ora_stop}"
            traseu = f" · {t.purpose}" if t.purpose else ""
            lines.append(
                f"🚗 *{zi}*{ore} — {_fmt_km(t.km)} km{odo}{traseu}\n"
                f"   `/sterge_tura {t.id}`"
            )

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 *Total business: {_fmt_km(summary['km_business'])} km*")
    if summary["km_personal"] > 0:
        lines.append(f"🏠 Personal (gap): {_fmt_km(summary['km_personal'])} km")
        lines.append(f"📈 Business: {summary['pct_business']:.0f}% din total")

    text = "\n".join(lines)
    # Telegram limita 4096 caractere
    if len(text) > 4000:
        text = text[:3900] + "\n\n_...listă prea lungă, trunchiată._"

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Descarcă foaia Excel", callback_data=f"parcurs|excel|{year}|{month}")],
        [InlineKeyboardButton("⬅️ Înapoi", callback_data="parcurs|status")],
        [InlineKeyboardButton("❌ Închide", callback_data="nav|close")],
    ])
    await update.callback_query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=markup
    )


async def _send_excel(update, context, user_id, year, month):
    """Genereaza si trimite foaia de parcurs Excel."""
    query = update.callback_query
    await query.edit_message_text(
        f"🔄 Generez foaia de parcurs Excel pentru {LUNI_LONG[month]} {year}..."
    )
    session = get_session()
    try:
        trips = trip_repo.list_for_month(session, user_id, year, month)
        if not trips:
            await query.edit_message_text(
                f"📭 Nicio tură în {LUNI_LONG[month]} {year}."
            )
            return
        profile = users_repo.get_profile_dict(session, user_id) or {}
        pfa_name = profile.get("firma_nume") or "PFA"
        pfa_cui = profile.get("firma_cui") or ""
        vehicul = vehicule_repo.get_default(session, user_id)
        xlsx_bytes = foaie_parcurs_export.generate_foaie_parcurs_xlsx(
            trips, year, month, vehicul,
            pfa_name=pfa_name, pfa_cui=pfa_cui,
        )
        nr_inmat = vehicul.nr_inmatriculare if vehicul else ""
        fname = foaie_parcurs_export.filename_foaie_parcurs(year, month, nr_inmat)
        summary = compute_month_summary(trips)
    except Exception as e:
        logger.error(f"send_excel error: {e}")
        await query.edit_message_text("❌ Eroare la generarea foii Excel.")
        return
    finally:
        session.close()

    import io as _io
    ded = foaie_parcurs_export.calcul_deductibilitate_combustibil(
        summary["km_business"],
        vehicul.norma_consum if vehicul else 7.5,
    )
    await context.bot.send_document(
        chat_id=query.message.chat_id,
        document=_io.BytesIO(xlsx_bytes),
        filename=fname,
        caption=(
            f"📊 *Foaie de parcurs — {LUNI_LONG[month]} {year}*\n\n"
            f"🛣️ Total business: {_fmt_km(summary['km_business'])} km\n"
            f"⛽ Combustibil normat: {ded['litri_normati']:g} litri\n\n"
            f"_Tipărește: Landscape A4. Verifică cu contabilul._"
        ),
        parse_mode="Markdown",
    )
    await query.edit_message_text(
        f"✅ Foaie de parcurs generată pentru {LUNI_LONG[month]} {year}."
    )


async def _show_luni_picker(update, context, user_id):
    """Afiseaza lunile pentru care exista ture."""
    session = get_session()
    try:
        months = trip_repo.available_months(session, user_id)
    finally:
        session.close()

    if not months:
        await update.callback_query.edit_message_text(
            "📭 Nu există ture înregistrate încă.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Înapoi", callback_data="parcurs|status")
            ]]),
        )
        return

    rows = []
    for (y, m) in months[:24]:
        label = f"{LUNI_SHORT[m]} {y}"
        rows.append([InlineKeyboardButton(
            label, callback_data=f"parcurs|jurnal|{y}|{m}"
        )])
    rows.append([InlineKeyboardButton("⬅️ Înapoi", callback_data="parcurs|status")])

    await update.callback_query.edit_message_text(
        "🗓️ *Alege luna:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


# ============================================================
#       STERGERE TURA
# ============================================================

async def handle_delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comanda /sterge_tura <id>."""
    user_id = _get_user_id(update)
    if not user_id:
        await update.message.reply_text("⚠️ Eroare identificare utilizator.")
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "⚠️ Specifică ID-ul turei.\nExemplu: `/sterge_tura 12`",
            parse_mode="Markdown",
        )
        return

    trip_id = _parse_int(args[0])
    if trip_id is None:
        await update.message.reply_text("⚠️ ID invalid.")
        return

    session = get_session()
    try:
        trip = trip_repo.get_by_id(session, trip_id, user_id)
        if not trip:
            await update.message.reply_text(f"⚠️ Tura #{trip_id} nu a fost găsită.")
            return
        zi = trip.trip_date.strftime("%d.%m.%Y") if trip.trip_date else "—"
        km = _fmt_km(trip.km)
    finally:
        session.close()

    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Da, șterge", callback_data=f"parcurs|delok|{trip_id}"),
        InlineKeyboardButton("❌ Nu", callback_data="parcurs|status"),
    ]])
    await update.message.reply_text(
        f"🗑️ Ștergi tura *#{trip_id}* ({zi}, {km} km)?",
        parse_mode="Markdown", reply_markup=markup,
    )


async def _do_delete_trip(update, context, user_id, trip_id):
    session = get_session()
    try:
        trip = trip_repo.get_by_id(session, trip_id, user_id)
        if not trip:
            await update.callback_query.edit_message_text("⚠️ Tura nu a fost găsită.")
            return
        before = trip_repo.to_dict(trip)
        trip_repo.delete(session, trip)
        audit_repo.write(
            session, entity_type="trip_log", entity_id=trip_id,
            action="delete", user_id=user_id, source="user",
            before=before,
        )
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"do_delete_trip error: {e}")
        await update.callback_query.edit_message_text("❌ Eroare la ștergere.")
        return
    finally:
        session.close()

    await update.callback_query.edit_message_text(
        f"✅ Tura #{trip_id} a fost ștearsă.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🛣️ Foaie parcurs", callback_data="parcurs|status")
        ]]),
    )


# ============================================================
#       MENIU BUTTON & CALLBACK ROUTER
# ============================================================

async def handle_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Apelat cand user-ul apasa butonul din meniu."""
    user_id = _get_user_id(update)
    if not user_id:
        await update.message.reply_text("⚠️ Eroare identificare utilizator.")
        return
    await _show_status(update, context, user_id, via_callback=False)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          parts: list):
    """Router pentru callback-urile din namespace-ul 'parcurs'."""
    query = update.callback_query
    user_id = _get_user_id(update)
    if not user_id:
        await query.edit_message_text("⚠️ Eroare identificare utilizator.")
        return

    action = parts[1] if len(parts) > 1 else ""

    try:
        if action == "status":
            await _show_status(update, context, user_id, via_callback=True)
        elif action == "luni":
            await _show_luni_picker(update, context, user_id)
        elif action == "jurnal":
            year = int(parts[2])
            month = int(parts[3])
            await _show_jurnal(update, context, user_id, year, month)
        elif action == "excel":
            await _send_excel(update, context, user_id, int(parts[2]), int(parts[3]))
        elif action == "delok":
            await _do_delete_trip(update, context, user_id, int(parts[2]))
    except Exception as e:
        logger.error(f"parcurs callback error parts={parts}: {e}")
        try:
            await query.edit_message_text(f"❌ Eroare: {str(e)[:150]}")
        except Exception:
            pass
