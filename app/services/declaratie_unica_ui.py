"""
Interfata (UI) pentru Declaratia Unica in bot.

Flux complet:
  1. Alegi anul
  2. Alegi modul: Automat (din datele din bot) sau Manual (introduci cifrele)
  3. Botul intreaba daca ai fost asigurat de sanatate prin alta sursa
     (salariu >= 6 SMB, pensie) - conteaza pentru scutirea de CASS minim
  4. Primesti calculul complet: impozit + CAS + CASS + total

Calculul efectiv se face in app/domain/declaratie_unica.py (testat separat).
"""

import logging
from datetime import datetime, date

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db import get_session
from app.services import tax_engine
from app.domain import declaratie_unica as du_calc
from app.repositories import users as users_repo
from app.ro_dates import zi_luna_ro, zi_luna_ro_scurt
from app.services import banner_send

logger = logging.getLogger(__name__)

BTN_DU = "🧮 Declarația Unică"

_WIZ = "du_wizard"        # starea wizardului manual (asteapta cifre)
_PENDING = "du_pending"   # date calculate, asteapta raspunsul despre asigurare


# ============================================================
#                    HELPERS
# ============================================================

def _parse_suma(text: str):
    """Transforma text in numar. Accepta 1.854,50 sau 1854,50 sau 50000."""
    if text is None:
        return None
    curat = text.strip().replace(" ", "").replace("lei", "").replace("RON", "")
    curat = curat.replace(".", "").replace(",", ".")
    try:
        val = float(curat)
        return val if val >= 0 else None
    except ValueError:
        return None


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
    Sumeaza venitul brut si cheltuielile deductibile din datele din bot,
    parcurgand cele 12 luni. Returneaza (venit_brut, chelt_ded, luni_cu_date).
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
            if totals.get("tx_count", 0):
                luni_cu_date += 1
            venit_brut += totals.get("income_total", 0) or 0
            chelt_ded += totals.get("expense_deductible_total", 0) or 0
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


# ============================================================
#                    INTREBAREA DESPRE ASIGURARE
# ============================================================

async def _intreaba_asigurare(send_func):
    rows = [
        [InlineKeyboardButton("✅ Da, am fost asigurat altfel",
                              callback_data="du|calc|asig")],
        [InlineKeyboardButton("❌ Nu, doar PFA",
                              callback_data="du|calc|noasig")],
    ]
    await send_func(
        "🏥 *Asigurare de sănătate*\n\n"
        "Ai fost asigurat de sănătate prin ALTĂ sursă în acel an?\n"
        "_(salariu de cel puțin 6 salarii minime pe an, sau pensie — "
        "la pensie nu contează suma)_\n\n"
        "Contează mult: dacă DA și venitul PFA e sub prag, ești scutit "
        "de CASS-ul minim.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


def _banner_data(rez, an):
    """Data dict pentru banner-ul „prezentare" (D212).

    `amount` = `rez['total_taxe']` — EXACT suma pe care `format_telegram` o afișează
    (ca bannerul și textul să arate aceeași sumă). Termenele D212 (25 Mai an+1) și
    D207 (ultima zi a lui februarie an+1) — reutilizează `compute_obligation`
    (luna 5 / luna 2;
    profil-independent: termenul se calculează înainte de aplicabilitate). Luni RO.
    """
    from app.domain import fiscal_calendar as fc
    today = date.today()
    # month=12 (sfârșit an venit) → compute_obligation dă termenul din anul URMĂTOR.
    o212 = fc.compute_obligation(fc.DEFINITII_OBLIGATII["D212"], an, 12,
                                 "PFA", "ridesharing", today=today)
    o207 = fc.compute_obligation(fc.DEFINITII_OBLIGATII["D207"], an, 12,
                                 "PFA", "ridesharing", today=today)
    return {
        "amount":        rez["total_taxe"],
        "decl":          "D212 · Declarația Unică (impozit + CAS + CASS)",
        "due_label":     f"Termen: {zi_luna_ro(o212.termen)}",
        "due_sub":       "Plata se face pe CNP, prin ghișeul.ro",
        "days_left":     o212.zile_ramase,
        "secondary":     "D207 — fără plată",
        "secondary_sub": f"TERMEN {zi_luna_ro_scurt(o207.termen)}".upper(),
    }


def _banner_data_d212(rez, an):
    """
    Ca `_banner_data`, dar pentru `RezultatD212Service` (motorul unic).

    Singura diferență e de unde vine suma: `total_plata` în loc de `total_taxe`.
    Restul — termenele D212/D207 — se calculează identic, deci se refolosește. Un al
    doilea calcul de termen aici ar fi exact greșeala pe care PR-ul ăsta o repară,
    la altă scară.
    """
    d = _banner_data({"total_taxe": 0.0}, an)
    d["amount"] = getattr(rez, "total_plata", 0.0) or 0.0
    return d


def _nota_asigurare_nedeclarata(profile: dict, rez, an: int):
    """
    Textul de dezvăluire când presupunem conservator, FĂRĂ ca userul să fi răspuns.

    `None` = nu e cazul (a răspuns, sau podeaua CASS n-a fost aplicată).

    DE CE EXISTĂ: CASS are o podea de 6 salarii minime. Cine e deja asigurat prin
    altă sursă (salariu de cel puțin 6 SMB pe an, sau pensie) o sare și plătește pe
    venitul net REAL. Diferența nu e o nuanță — pe datele reale ale unui user din
    producție, 2.430 lei față de 174,56 lei pe linia CASS.
    Motorul citește `is_salariat`/`is_pensionar` din profil. Cât timp sunt NULL
    (niciodată întrebat — userii de dinaintea wizardului), presupune conservator.
    A presupune e corect; a presupune ÎN TĂCERE nu e: omul ar plăti de 7 ori mai
    mult fără să afle vreodată că exista o întrebare.

    CE NU FACE: nu recalculează. Podeaua e vizibilă din ce a întors deja motorul
    (`cass_baza > venit_net`), iar cifra alternativă e cota × venit net — aritmetică
    pe date pe care le avem, nu un al doilea calcul. Un motor de umbră care „verifică"
    primul e exact problema pe care o închide PR-ul ăsta.
    """
    if profile.get("is_salariat") is not None or profile.get("is_pensionar") is not None:
        return None                       # a răspuns — respectăm răspunsul, tăcem
    venit_net = getattr(rez, "venit_net", None)
    cass_baza = getattr(rez, "cass_baza", None)
    cass = getattr(rez, "cass", None)
    if not venit_net or not cass_baza or not cass:
        return None
    if cass_baza <= venit_net:
        return None                       # podeaua nu s-a aplicat — nimic de spus

    from app.domain.contributii import PARAMETRI_CONTRIBUTII
    try:
        cota = PARAMETRI_CONTRIBUTII[an]["cota_cass"] / 100.0
    except (KeyError, TypeError):
        return None
    cass_pe_real = round(venit_net * cota, 2)
    return (
        "\n\n━━━━━━━━━━━━━━━━━━━━\n"
        "ℹ️ *Am presupus ceva — verifică dacă e adevărat.*\n\n"
        f"Am calculat CASS pe baza minimă ({cass:.0f} lei), fiindcă nu mi-ai spus "
        f"dacă ești asigurat de sănătate *prin altă sursă*.\n\n"
        "Dacă ai *salariu de cel puțin 6 salarii minime pe an* sau *pensie*, CASS "
        f"se calculează pe venitul tău real: *{cass_pe_real:.0f} lei* în loc de "
        f"{cass:.0f}.\n\n"
        "_Contează nivelul, nu doar faptul că ești angajat: part-time sau angajare "
        "pe o parte din an pot fi sub prag._\n\n"
        # Destinația e numele EXACT al secțiunii din UI (dashboard.html, pagina
        # `setari`, blocul „Situația ta personală"). Înainte scria „configurare" —
        # adică wizardul, în care un user deja onboardat NU MAI POATE INTRA. O notă
        # care cere ceva și trimite într-o fundătură e aceeași greșeală cu
        # empty-state-ul care spunea „folosește manual" și lua butonul spre manual.
        'Spune-mi în Dashboard → Setări → „Situația ta personală”, și recalculez.'
    )


async def _finalizeaza_automat(update, context, user_id, an, luni):
    """
    Calea AUTOMATĂ, pe motorul unic (`tax_engine.compute_d212_anual`) — același
    care produce fișierul XML și care alimentează dashboardul, alertele și scheduler-ul.

    Nu mai întreabă despre asigurare: răspunsul se ia din profil, unde persistă.
    Când profilul tace, tace și el — dar ZGOMOTOS, vezi `_nota_asigurare_nedeclarata`.
    """
    from app.repositories import users as users_repo
    session = get_session()
    try:
        rez = tax_engine.compute_d212_anual(session, user_id=user_id, an=an)
        profile = users_repo.get_profile_dict(session, user_id) or {}
    finally:
        session.close()

    msg = rez.ghid_telegram or rez.ghid_plain or ""
    if luni is not None and luni < 12:
        luna_txt = "luna" if luni == 1 else "luni"
        msg = (
            f"ℹ️ *Am găsit {luni} {luna_txt} cu date pentru {an}.*\n\n"
            f"Dacă ai lucrat doar atât în {an}, cifrele sunt corecte și complete. "
            f"Altfel, folosește *Manual* cu totalul real.\n"
            f"-----------------------------------\n\n"
        ) + msg
    for av in (getattr(rez, "avertismente", None) or []):
        msg += f"\n\n⚠️ {av}"
    nota = _nota_asigurare_nedeclarata(profile, rez, an)
    if nota:
        msg += nota

    await banner_send.send_banner_or_text(
        update.callback_query, context,
        screen="prezentare", data=_banner_data_d212(rez, an),
        text=msg, caption=f"🧮 Declarația Unică {an}",
    )


async def _finalizeaza_calcul(update, context, venit_brut, chelt_ded, an, luni, asigurat):
    """
    ⚠️ CALEA MANUALĂ — SINGURUL loc rămas pe motorul VECHI (`du_calc`). TEMPORAR.

    Nu e o scăpare din unificare, e o piesă care lipsește: `compute_d212_anual`
    CITEȘTE cifrele din baza de date și nu știe să primească cifre din afara ei.
    Calea manuală există tocmai pentru cine NU are datele în bot — deci nu se putea
    muta, trebuie CONSTRUITĂ.

    CE AR CERE (măsurat, nu estimat din ochi): `compute_d212_anual` merge pe
    `_d212_args_si_avertisment(session, user_id, an)`, care citește tranzacțiile din
    DB și apoi împletește profilul (regim, normă, pensionar, salariat,
    proporționalizare, activitate mixtă). Injectarea cere: (a) parametri opționali de
    suprascriere pe venit/cheltuieli în constructorul de argumente; (b) o cale care
    OCOLEȘTE cache-ul — el e cheiat pe `(user_id, an)` și niște cifre injectate l-ar
    otrăvi pentru toți ceilalți apelanți.

    (c) DECIZIA FISCALĂ E LUATĂ, NU O REDESCHIDE: **flagurile de profil se aplică ȘI
    peste cifrele tastate manual.** Motivul, ca să nu fie nevoie de a doua dezbatere:
    regimul e CINE EȘTI, nu de unde vin cifrele. Norma de venit înseamnă că baza
    impozabilă E norma, indiferent ce venit tastezi — cheltuielile reale nici măcar
    nu-s deductibile pe normă. Iar podeaua CASS depinde de faptul că ești asigurat
    altundeva, nu de sursa numărului. Cifrele introduse manual înlocuiesc DATELE,
    niciodată PROFILUL.

    PÂNĂ ATUNCI, ce înseamnă concret: calea manuală e REGIM-OARBĂ (`du_calc` n-are
    niciun parametru prin care o normă ar putea intra — vezi semnătura lui) și
    ÎNTREABĂ despre asigurare în loc să citească profilul. Cele două căi pot deci da
    răspunsuri diferite pe același om. Diferența e mărginită: calea manuală se
    folosește doar când userul introduce el cifrele, deci știe că lucrează pe o
    ipoteză a lui.
    """
    rez = du_calc.calcul_declaratie_unica(
        venit_brut, chelt_ded, an=an, asigurat_salariat=asigurat
    )
    corp = du_calc.format_telegram(rez)
    if luni is not None and luni < 12:
        luna_txt = "luna" if luni == 1 else "luni"
        avert = (
            f"ℹ️ *Am gasit {luni} {luna_txt} cu date pentru {an}.*\n\n"
            f"Daca ai lucrat doar atat in {an}, cifrele sunt corecte si "
            f"complete. Altfel, foloseste *Manual* cu totalul real.\n"
            f"-----------------------------------\n\n"
        )
        msg = avert + corp
    else:
        msg = corp

    # Banner hero (prezentare D212) + ghidul text dedesubt — wrapper comun cu
    # fallback 3 niveluri + logger.exception (același pe toate ecranele).
    await banner_send.send_banner_or_text(
        update.callback_query, context,
        screen="prezentare", data=_banner_data(rez, an),
        text=msg, caption=f"🧮 Declarația Unică {an}",
    )


# ============================================================
#                    CALLBACK (router du|...)
# ============================================================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts):
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
        await query.edit_message_text(f"🔄 Adun datele pe {an}...")
        # UN SINGUR MOTOR. Aici se chema `du_calc` (app/domain/declaratie_unica.py),
        # un al doilea motor care răspundea la ACEEAȘI întrebare cu alt răspuns.
        # Vezi `_MOTIVUL_UNIFICARII` la finalul fișierului.
        venit_brut, chelt_ded, luni = _sumar_anual_din_date(user_id, an)
        if venit_brut <= 0 and chelt_ded <= 0:
            # Butoanele se PĂSTREAZĂ: înainte, mesajul îi cerea userului să treacă pe
            # manual și îi lua exact butonul care duce acolo (edit fără reply_markup).
            await query.edit_message_text(
                f"📭 Nu am date înregistrate pentru {an}.\n\n"
                f"Introdu tu cifrele — butonul e mai jos.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✍️ Introduc eu cifrele",
                                          callback_data=f"du|manual|{an}")],
                    [InlineKeyboardButton("❌ Închide", callback_data="nav|close")],
                ]),
            )
            return
        await _finalizeaza_automat(update, context, user_id, an, luni)
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

    if actiune == "calc":
        asigurat = (len(parts) > 2 and parts[2] == "asig")
        pending = context.user_data.pop(_PENDING, None)
        if not pending:
            await query.edit_message_text(
                "⏳ Sesiunea a expirat. Reia cu /declaratie_unica."
            )
            return
        await _finalizeaza_calcul(
            update, context,
            pending["venit_brut"], pending["chelt_ded"],
            pending["an"], pending["luni"], asigurat=asigurat,
        )
        return


# ============================================================
#                    WIZARD MANUAL (text)
# ============================================================

def is_in_wizard(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return _WIZ in context.user_data


def cancel_wizard(context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop(_WIZ, None)
    context.user_data.pop(_PENDING, None)


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
        context.user_data.pop(_WIZ, None)
        # Datele manuale sunt pe tot anul (luni=None => fara avertisment).
        context.user_data[_PENDING] = {
            "venit_brut": venit_brut, "chelt_ded": suma,
            "an": an, "luni": None,
        }
        await _intreaba_asigurare(update.message.reply_text)
        return True

    return False


# ============================================================
#   DE CE UN SINGUR MOTOR — istoria, ca să nu se refacă
# ============================================================
_MOTIVUL_UNIFICARII = """
Până la PR-ul ăsta, D212 avea DOUĂ motoare care răspundeau la aceeași întrebare:

  A) app/domain/declaratie_unica.py (`du_calc`) — pe drumul din MENIU
  B) app/services/tax_engine.compute_d212_anual — pe drumul cu FIȘIER, plus
     dashboard, alerte proactive și scheduler

MĂSURAT pe profilul real al unui user din producție (2025, venit net 1.745,61 lei),
cele două nu divergeau în matematică — ci în SURSA RĂSPUNSULUI:

  · (A) ÎNTREBA userul „ești asigurat prin altă sursă?" și îi lua răspunsul ca
    parametru, fără să-l scrie nicăieri. Răspuns „nu" → CASS 2.430 lei.
    Răspuns „da" → CASS 174,56 lei. De 7,3 ori diferență, pe o apăsare de buton
    care se evapora.
  · (B) CITEȘTE `is_salariat` / `is_pensionar` din profil și nu întreabă niciodată.

Același om, același an, aceleași date, două cifre. Nimic nu semnala diferența.

A doua ruptură, structurală: `du_calc` n-are parametru de regim, activitate sau
sesiune (vezi semnătura). Nu e o ramură lipsă pentru normă — e o poartă inexistentă.
Pentru un user pe normă de venit din 2026 încolo, (A) ar fi calculat mereu sistem
real. Asta e datoria P10/P11 din audit, închisă aici.

DECIZIA: un singur drum, un singur motor. Calea automată trece pe (B). Întrebarea
despre asigurare NU se mai pune aici — răspunsul trăiește în profil, unde persistă,
iar când profilul tace, `_nota_asigurare_nedeclarata` o spune pe față.

Ce a rămas pe (A): DOAR calea manuală, marcată și explicată la `_finalizeaza_calcul`.

Gardianul care oprește reapariția clasei: tests/test_un_singur_motor_fiscal.py.
"""
