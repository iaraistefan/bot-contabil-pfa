"""
Pas A.3 - Modul foaie de parcurs (jurnal km auto).

v2 (Modernizare UI): flux principal cu BUTOANE, nu comenzi text.
  - Buton "Porneste tura" -> wizard care cere DOAR kilometrajul -> data auto (azi)
  - Buton "Inchide tura"  -> wizard care cere DOAR kilometrajul -> data auto
  - Meniu contextual: arata "Porneste" SAU "Inchide" dupa starea curenta
  - Comenzile text raman ca backup (compatibilitate).

Comenzi text (backup):
  parcurs start <KM>            - porneste o tura
  parcurs stop <KM>             - inchide tura curenta
  parcurs <KM_START> <KM_STOP>  - tura completa
  parcurs                       - status / jurnal

INTEGRARE in bot_contabil.py (handle_text_wrapper):
  # INAINTE de comenzi si procesare documente:
  if foaie_parcurs.is_in_wizard(context):
      handled = await foaie_parcurs.handle_wizard_text(update, context)
      if handled:
          return
  if foaie_parcurs.match_command(text):
      await foaie_parcurs.handle_command(update, context)
      return

CALLBACK namespace "parcurs":
  parcurs|status               - status / sumar luna curenta
  parcurs|wiz_start            - porneste wizard "porneste tura"
  parcurs|wiz_stop             - porneste wizard "inchide tura"
  parcurs|wiz_cancel           - anuleaza wizard-ul curent
  parcurs|luni                 - alege luna pentru jurnal
  parcurs|jurnal|<an>|<luna>   - afiseaza jurnalul lunii
  parcurs|excel|<an>|<luna>    - genereaza Excel
  parcurs|delok|<trip_id>      - executa stergerea unei ture

CHANGELOG:
  - v1 (Pas A.3): Versiune initiala (comenzi text)
  - v2 (Modernizare): wizard cu butoane, meniu contextual, mesaje curate
  - v2.1 (A.1.b): defalcare km business in cu pasager (Bolt) vs pozitionare
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
from app.services import combustibil
from app.integrations import bolt_sync  # A.1.b: km cu pasager (cache-only)
from app.models import TRIP_STATUS_OPEN, TRIP_STATUS_CLOSED

logger = logging.getLogger(__name__)

BTN_PARCURS = "🛣️ Foaie parcurs"

RO_TZ = pytz.timezone("Europe/Bucharest")

# Sanity check: km parcursi intr-o tura peste aceasta valoare = suspect
MAX_KM_TURA = 1500

# Cheia de stare a wizard-ului cu butoane (in context.user_data)
_WIZARD_KEY = "parcurs_wizard"

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
    Km personali = suma "gap-urilor" de odometru intre ture consecutive.
    """
    closed = [t for t in trips if t.status == TRIP_STATUS_CLOSED]
    has_open = any(t.status == TRIP_STATUS_OPEN for t in trips)

    km_business = sum((t.km or 0.0) for t in closed)

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
#       LOGICA PURA - executare start / stop
#       (reutilizata atat de comenzi text cat si de wizard)
# ============================================================

def _execute_start(user_id: int, km: int, purpose: str = None) -> dict:
    """
    Porneste o tura. Returneaza dict:
      {"ok": bool, "message": str}
    Commit-ul se face inauntru.
    """
    if km is None or km <= 0:
        return {"ok": False, "message": (
            "⚠️ Kilometrajul nu e valid. Scrie doar numărul de pe bord "
            "(ex: 125430)."
        )}

    session = get_session()
    try:
        # 1. Tura deja deschisa?
        open_trip = trip_repo.get_open_trip(session, user_id)
        if open_trip:
            ora = f" ({open_trip.ora_start})" if open_trip.ora_start else ""
            return {"ok": False, "message": (
                f"⚠️ Ai deja o tură pornită la "
                f"*{_fmt_km(open_trip.odometer_start)} km*{ora}.\n\n"
                f"Închide-o întâi din meniu."
            )}

        # 2. Masina default
        vehicul = vehicule_repo.get_default(session, user_id)
        if not vehicul:
            return {"ok": False, "message": (
                "⚠️ Nu ai nicio mașină înregistrată.\n\n"
                "Adaugă întâi mașina din meniul *🚗 Mașinile mele*."
            )}

        # 3. Sanity check fata de km cunoscut
        avertisment = ""
        if vehicul.km_curent and km < vehicul.km_curent:
            avertisment = (
                f"\n\n⚠️ _{_fmt_km(km)} km e sub kilometrajul cunoscut "
                f"({_fmt_km(vehicul.km_curent)} km). Verifică cifra._"
            )

        now = _now_ro()
        ora = now.strftime("%H:%M")

        trip = trip_repo.create_open(
            session, user_id=user_id, vehicul_id=vehicul.id,
            odometer_start=km, trip_date=now.date(),
            ora_start=ora, purpose=purpose,
        )
        vehicule_repo.update_km_curent(session, vehicul, km)
        audit_repo.write(
            session, entity_type="trip_log", entity_id=trip.id,
            action="start", user_id=user_id, source="user",
            after=trip_repo.to_dict(trip),
        )
        session.commit()

        zi = now.strftime("%d.%m.%Y")
        traseu_line = f"\n📍 Traseu: {purpose}" if purpose else ""
        return {"ok": True, "message": (
            "🟢 *Tură pornită!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🛣️ Bord start: *{_fmt_km(km)} km*\n"
            f"📅 Data: *{zi}*\n"
            f"🕐 Ora: *{ora}*\n"
            f"🚙 Mașina: {vehicul.nr_inmatriculare}{traseu_line}\n\n"
            f"_Când termini cursa, apasă butonul Închide tura._"
            f"{avertisment}"
        )}
    except Exception as e:
        session.rollback()
        logger.error(f"_execute_start error: {e}")
        return {"ok": False, "message": "❌ Eroare la pornirea turei."}
    finally:
        session.close()


def _execute_stop(user_id: int, km: int) -> dict:
    """
    Inchide tura deschisa. Returneaza dict {"ok": bool, "message": str}.
    """
    if km is None or km <= 0:
        return {"ok": False, "message": (
            "⚠️ Kilometrajul nu e valid. Scrie doar numărul de pe bord "
            "(ex: 125680)."
        )}

    session = get_session()
    try:
        open_trip = trip_repo.get_open_trip(session, user_id)
        if not open_trip:
            return {"ok": False, "message": (
                "⚠️ Nu ai nicio tură pornită.\n\n"
                "Pornește una din meniu cu butonul Pornește o tură."
            )}

        start_km = open_trip.odometer_start or 0
        if km <= start_km:
            return {"ok": False, "message": (
                f"⚠️ Kilometrajul de stop ({_fmt_km(km)}) trebuie să fie "
                f"mai mare decât cel de start ({_fmt_km(start_km)}).\n\n"
                "Verifică cifra de pe bord și încearcă din nou."
            )}

        km_parcursi = km - start_km
        avertisment = ""
        if km_parcursi > MAX_KM_TURA:
            avertisment = (
                f"\n\n⚠️ _{_fmt_km(km_parcursi)} km într-o tură pare mult. "
                f"Dacă ai greșit cifra, șterge tura din jurnal._"
            )

        now = _now_ro()
        ora_stop = now.strftime("%H:%M")

        trip_repo.close_trip(
            session, open_trip, odometer_end=km, ora_stop=ora_stop
        )

        if open_trip.vehicul_id:
            vehicul = vehicule_repo.get_by_id(
                session, open_trip.vehicul_id, user_id
            )
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
            interval = f"\n🕐 Interval: {open_trip.ora_start} → {ora_stop}"

        return {"ok": True, "message": (
            "🏁 *Tură încheiată!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🛣️ {_fmt_km(start_km)} → {_fmt_km(km)} km\n"
            f"📊 *Parcurși azi: {_fmt_km(km_parcursi)} km*{interval}\n\n"
            f"_Tura a fost adăugată în foaia de parcurs._"
            f"{avertisment}"
        )}
    except Exception as e:
        session.rollback()
        logger.error(f"_execute_stop error: {e}")
        return {"ok": False, "message": "❌ Eroare la închiderea turei."}
    finally:
        session.close()


def _execute_complete(user_id: int, km_start: int, km_stop: int) -> dict:
    """Inregistreaza o tura completa (start + stop) intr-un pas."""
    if km_stop <= km_start:
        return {"ok": False, "message": (
            f"⚠️ Al doilea număr ({_fmt_km(km_stop)}) trebuie să fie "
            f"mai mare decât primul ({_fmt_km(km_start)})."
        )}

    session = get_session()
    try:
        vehicul = vehicule_repo.get_default(session, user_id)
        if not vehicul:
            return {"ok": False, "message": (
                "⚠️ Nu ai nicio mașină înregistrată.\n\n"
                "Adaugă întâi mașina din meniul *🚗 Mașinile mele*."
            )}

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
            avertisment = (
                f"\n\n⚠️ _{_fmt_km(km_parcursi)} km pare mult pentru o tură._"
            )

        return {"ok": True, "message": (
            "✅ *Tură înregistrată!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🛣️ {_fmt_km(km_start)} → {_fmt_km(km_stop)} km\n"
            f"📊 *Parcurși: {_fmt_km(km_parcursi)} km*\n"
            f"🚙 Mașina: {vehicul.nr_inmatriculare}"
            f"{avertisment}"
        )}
    except Exception as e:
        session.rollback()
        logger.error(f"_execute_complete error: {e}")
        return {"ok": False, "message": "❌ Eroare la înregistrarea turei."}
    finally:
        session.close()


# ============================================================
#       WIZARD CU BUTOANE
# ============================================================

def is_in_wizard(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """True daca user-ul e in wizard-ul de foaie de parcurs."""
    return _WIZARD_KEY in context.user_data


def cancel_wizard(context: ContextTypes.DEFAULT_TYPE):
    """Anuleaza wizard-ul (sterge starea)."""
    context.user_data.pop(_WIZARD_KEY, None)


def _start_wizard(context: ContextTypes.DEFAULT_TYPE, action: str):
    """Initializeaza wizard-ul pentru 'start' sau 'stop'."""
    context.user_data[_WIZARD_KEY] = {"action": action}


async def handle_wizard_text(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Primeste numarul de km scris de user in cadrul wizard-ului.
    Returneaza True daca mesajul a fost consumat de wizard.
    """
    wizard = context.user_data.get(_WIZARD_KEY)
    if not wizard:
        return False

    action = wizard.get("action")
    text = (update.message.text or "").strip()
    km = _parse_int(text)

    user_id = _get_user_id(update)
    if not user_id:
        cancel_wizard(context)
        await update.message.reply_text("⚠️ Eroare identificare utilizator.")
        return True

    if km is None or km <= 0:
        # Nu anulam wizard-ul - lasam user-ul sa reincerce
        await update.message.reply_text(
            "⚠️ Te rog scrie *doar numărul* de pe bord — fără litere.\n"
            "Exemplu: `125430`\n\n"
            "_Sau apasă ❌ pe mesajul de mai sus ca să anulezi._",
            parse_mode="Markdown",
        )
        return True

    # Avem un numar valid - executam si curatam wizard-ul
    cancel_wizard(context)

    if action == "start":
        result = _execute_start(user_id, km)
    elif action == "stop":
        result = _execute_stop(user_id, km)
    else:
        await update.message.reply_text("⚠️ Acțiune necunoscută.")
        return True

    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("🛣️ Foaie de parcurs", callback_data="parcurs|status")
    ]])
    await update.message.reply_text(
        result["message"], parse_mode="Markdown", reply_markup=markup
    )
    return True


# ============================================================
#       COMANDA TEXT (backup)
# ============================================================

def match_command(text: str) -> bool:
    """True daca textul e o comanda de foaie de parcurs."""
    if not text:
        return False
    return text.strip().lower().startswith("parcurs")


async def handle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Proceseaza o comanda text 'parcurs ...' (backup pentru butoane)."""
    text = (update.message.text or "").strip()
    tokens = text.split()
    rest = tokens[1:]

    user_id = _get_user_id(update)
    if not user_id:
        await update.message.reply_text("⚠️ Eroare identificare utilizator.")
        return

    if not rest:
        await _show_status(update, context, user_id)
        return

    sub = rest[0].lower()

    if sub == "start":
        km = _parse_int(rest[1]) if len(rest) > 1 else None
        purpose = " ".join(rest[2:]) if len(rest) > 2 else None
        result = _execute_start(user_id, km, purpose)
        await _reply_result(update, result)

    elif sub == "stop":
        km = _parse_int(rest[1]) if len(rest) > 1 else None
        result = _execute_stop(user_id, km)
        await _reply_result(update, result)

    elif sub in ("status", "jurnal"):
        await _show_status(update, context, user_id)

    else:
        nums = [_parse_int(x) for x in rest]
        valid = [n for n in nums if n is not None]
        if len(valid) == 2:
            result = _execute_complete(user_id, valid[0], valid[1])
            await _reply_result(update, result)
        else:
            await update.message.reply_text(
                "⚠️ Comandă neînțeleasă.\n\n"
                "Cel mai simplu: apasă butonul *🛣️ Foaie parcurs* din meniu "
                "și folosește butoanele.",
                parse_mode="Markdown",
            )


async def _reply_result(update: Update, result: dict):
    """Trimite rezultatul unei operatii, cu buton spre meniu."""
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("🛣️ Foaie de parcurs", callback_data="parcurs|status")
    ]])
    await update.message.reply_text(
        result["message"], parse_mode="Markdown", reply_markup=markup
    )


# ============================================================
#       STATUS / SUMAR LUNA  (meniu modern cu butoane)
# ============================================================

async def _show_status(update, context, user_id, via_callback=False):
    """Afiseaza meniul foii de parcurs: tura curenta + sumar + butoane."""
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
        f"🛣️ *Foaie de parcurs — {LUNI_LONG[month]} {year}*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    if open_trip:
        ora = f" la {open_trip.ora_start}" if open_trip.ora_start else ""
        zi = ""
        if open_trip.trip_date:
            zi = open_trip.trip_date.strftime("%d.%m")
        lines.append("🟢 *TURĂ ÎN CURS*")
        lines.append(f"   Pornită {zi}{ora}")
        lines.append(f"   Bord start: *{_fmt_km(open_trip.odometer_start)} km*")
        lines.append("")

    lines.append(
        f"📊 *{summary['nr_ture']}* ture · "
        f"*{_fmt_km(summary['km_business'])} km* business"
    )
    if summary["km_personal"] > 0:
        lines.append(
            f"🏠 {_fmt_km(summary['km_personal'])} km personali · "
            f"business {summary['pct_business']:.0f}%"
        )

    # A.1.b: defalcare business = cu pasager (Bolt) + pozitionare (mers gol)
    try:
        bolt_km = bolt_sync.get_month_km(user_id, year, month)
        km_bolt = bolt_km.get("km", 0.0)
        if km_bolt > 0:
            kmb = summary["km_business"]
            if kmb > 0:
                km_poz = kmb - km_bolt
                if km_poz >= -1:  # toleranta mica de rotunjire
                    km_poz = max(km_poz, 0.0)
                    lines.append(
                        f"🚗 cu pasager (Bolt): *{_fmt_km(km_bolt)} km* · "
                        f"poziționare: {_fmt_km(km_poz)} km"
                    )
                else:
                    lines.append(
                        f"🚗 cu pasager (Bolt): *{_fmt_km(km_bolt)} km*"
                    )
                    lines.append(
                        "⚠️ _Bolt arată mai mulți km cu pasager decât ai în "
                        "foaie — probabil ai ture neînchise sau lipsă._"
                    )
            else:
                lines.append(
                    f"🚗 _Bolt confirmă {_fmt_km(km_bolt)} km cu pasager luna "
                    f"asta. Pornește/închide ture ca să adaugi poziționarea "
                    f"și să justifici combustibilul._"
                )
    except Exception as e:
        logger.error(f"bolt km in status error: {e}")

    if summary["nr_ture"] == 0 and not open_trip:
        lines.append("")
        lines.append("_Nicio tură încă. Apasă butonul Pornește o tură._")

    # Sectiunea combustibil deductibil
    try:
        fuel_summary = combustibil.get_fuel_summary(user_id, year, month)
        fuel_section = combustibil.format_fuel_section(fuel_summary)
        if fuel_section:
            lines.append("")
            lines.append(fuel_section)
    except Exception as e:
        logger.error(f"fuel section in status error: {e}")

    text = "\n".join(lines)

    # --- Butoane contextuale (layout: actiune principala mare, rest 2x2) ---
    rows = []
    if open_trip:
        rows.append([InlineKeyboardButton(
            "🏁  Închide tura de azi", callback_data="parcurs|wiz_stop"
        )])
    else:
        rows.append([InlineKeyboardButton(
            "🚗  Pornește o tură", callback_data="parcurs|wiz_start"
        )])
    rows.append([
        InlineKeyboardButton(
            "📋 Jurnal", callback_data=f"parcurs|jurnal|{year}|{month}"
        ),
        InlineKeyboardButton(
            "📥 Excel", callback_data=f"parcurs|excel|{year}|{month}"
        ),
    ])
    rows.append([
        InlineKeyboardButton("🗓️ Altă lună", callback_data="parcurs|luni"),
        InlineKeyboardButton("🚙 Mașina mea", callback_data="vehicul|menu"),
    ])
    rows.append([InlineKeyboardButton("❌ Închide", callback_data="nav|close")])
    markup = InlineKeyboardMarkup(rows)

    if via_callback and update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=markup
        )
    else:
        await update.message.reply_text(
            text, parse_mode="Markdown", reply_markup=markup
        )


# ============================================================
#       WIZARD - pornire din callback
# ============================================================

async def _ask_km(update, context, action: str):
    """Porneste wizard-ul si cere kilometrajul printr-un mesaj cu buton anulare."""
    _start_wizard(context, action)
    query = update.callback_query

    if action == "start":
        title = "🚗 *Pornește o tură*"
        hint = "Scrie acum *kilometrajul de pe bord* (cifra de la odometru)."
        example = "Exemplu: `125430`"
    else:
        title = "🏁 *Închide tura*"
        hint = "Scrie acum *kilometrajul de pe bord* (cât arată odometrul ACUM)."
        example = "Exemplu: `125680`"

    text = (
        f"{title}\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{hint}\n"
        f"{example}\n\n"
        "📅 _Data se completează automat (azi)._"
    )
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Anulează", callback_data="parcurs|wiz_cancel")
    ]])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)


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
    if len(text) > 4000:
        text = text[:3900] + "\n\n_...listă prea lungă, trunchiată._"

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📥 Descarcă foaia Excel",
            callback_data=f"parcurs|excel|{year}|{month}"
        )],
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
        f"✅ Foaie de parcurs generată pentru {LUNI_LONG[month]} {year}.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🛣️ Foaie de parcurs", callback_data="parcurs|status")
        ]]),
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
    row = []
    for (y, m) in months[:24]:
        label = f"{LUNI_SHORT[m]} {y}"
        row.append(InlineKeyboardButton(
            label, callback_data=f"parcurs|jurnal|{y}|{m}"
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
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
            InlineKeyboardButton("🛣️ Foaie de parcurs", callback_data="parcurs|status")
        ]]),
    )


# ============================================================
#       MENIU BUTTON & CALLBACK ROUTER
# ============================================================

async def handle_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Apelat cand user-ul apasa butonul din meniu."""
    cancel_wizard(context)  # daca era un wizard vechi agatat, il curatam
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
            cancel_wizard(context)
            await _show_status(update, context, user_id, via_callback=True)

        elif action == "wiz_start":
            await _ask_km(update, context, "start")

        elif action == "wiz_stop":
            await _ask_km(update, context, "stop")

        elif action == "wiz_cancel":
            cancel_wizard(context)
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
