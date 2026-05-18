"""
Pas 11.4 — Plată Fiscală: Wizard Telegram pentru plăți ANAF.

Acesta e UI-ul pentru toată infrastructura din Pas 11 (Compliance Engine):
  • Pas 11.1: anaf_iban_db (IBAN-uri oficiale per județ)
  • Pas 11.2: fiscal_calendar v2 (obligații + termene + sume)
  • Pas 11.3: compliance_guardian (validare + audit)

WORKFLOW:
1. User apasă "💳 Plată Fiscală" din meniu (sau /plata_fiscala)
2. Bot afișează tipurile de obligații aplicabile (filtrate pe profilul user-ului)
3. User alege tipul (ex: D301)
4. Bot afișează lunile disponibile
5. User alege luna
6. Bot calculează automat: IBAN + sumă + termen + cod buget + beneficiar
7. Afișează mesaj complet cu toate datele OP, gata de copiat

DESIGN:
- Acest modul conține TOATĂ logica Telegram + handler-ele
- bot_contabil.py face doar DELEGATE către funcțiile de aici
- Patch-ul în bot_contabil.py = 5 linii (vezi instrucțiunile)
"""

import logging
from datetime import datetime, date
from typing import Optional, List, Dict

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import ContextTypes

from app.repositories import users as users_repo
from app.domain.fiscal_profile import (
    FiscalProfile, FormaJuridica, RegimTVA, from_user_id,
)
from app.domain.fiscal_calendar import (
    DEFINITII_OBLIGATII, DefinitieObligatie,
    compute_obligation, FrecventaObligatie,
)
from app.domain.compliance_guardian import (
    validate_payment, get_compliance_status,
    format_payment_validation_telegram,
    format_compliance_status_telegram,
    ValidationVerdict,
)
from app.integrations.anaf_iban_db import get_iban_for_obligation

logger = logging.getLogger(__name__)


# ============================================================
#                    CONSTANTE
# ============================================================

BTN_PLATA = "💳 Plată Fiscală"

LUNI_SHORT = {
    1: "Ian", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Mai", 6: "Iun",
    7: "Iul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}
LUNI_LONG = {
    1: "Ianuarie", 2: "Februarie", 3: "Martie", 4: "Aprilie",
    5: "Mai", 6: "Iunie", 7: "Iulie", 8: "August",
    9: "Septembrie", 10: "Octombrie", 11: "Noiembrie", 12: "Decembrie",
}

# Județ -> cod scurt pentru mapping cu anaf_iban_db
JUDET_NAME_TO_CODE = {
    "BISTRITA-NASAUD": "BN", "BISTRIȚA-NĂSĂUD": "BN",
    "BISTRITA NASAUD": "BN", "BN": "BN",
    "BUCURESTI": "B", "BUCUREȘTI": "B", "B": "B",
    "CLUJ": "CJ", "TIMIS": "TM", "TIMIȘ": "TM",
    "IASI": "IS", "IAȘI": "IS",
    # Extindem pe parcurs
}


# ============================================================
#                    CONTEXT BUILDER
# ============================================================

def _profile_to_guardian_context(
    fiscal_profile: FiscalProfile,
    profile_dict: dict,
) -> dict:
    """
    Mapează FiscalProfile + profile_dict la contextul cerut de compliance_guardian.

    Returns dict cu: forma_juridica, activity_code, judet, is_vat_payer,
                     has_cod_special_tva, cui
    """
    judet_raw = (profile_dict.get("judet") or "").upper().strip()
    judet_code = JUDET_NAME_TO_CODE.get(judet_raw, judet_raw[:2] if judet_raw else None)

    is_vat_payer = fiscal_profile.regim_tva == RegimTVA.PLATITOR_21
    has_cod_special_tva = fiscal_profile.regim_tva == RegimTVA.SPECIAL_INTRACOM

    return {
        "forma_juridica": fiscal_profile.forma_juridica.value,
        "activity_code": fiscal_profile.activity_code,
        "judet": judet_code or "BN",
        "is_vat_payer": is_vat_payer,
        "has_cod_special_tva": has_cod_special_tva,
        "cui": profile_dict.get("firma_cui") or "",
        "firma_nume": profile_dict.get("firma_nume") or "",
        "cnp": profile_dict.get("cnp") or "",
    }


# ============================================================
#                    DB QUERIES
# ============================================================

def _get_intracom_base_for_month(
    session, user_id: int, year: int, month: int
) -> float:
    """
    Caută în DB factura Bolt (sau alt furnizor intracom) pentru luna respectivă
    și returnează BAZA (comisionul fără TVA).

    Folosit pentru a calcula automat:
      • D301 = 21% × baza
      • D100 poz. 634 = 2% × baza
    """
    try:
        from app.models import Document
        from app.enums import DocType

        # Căutăm facturi de comision posted, pentru luna țintă
        target_month_str = f"{month:02d}.{year}"

        docs = (
            session.query(Document)
            .filter(
                Document.user_id == user_id,
                Document.tip == DocType.FACTURA_COMISION.value
                    if hasattr(DocType, 'value') else DocType.FACTURA_COMISION,
                Document.status == "posted",
            )
            .all()
        )

        total_baza = 0.0
        for d in docs:
            if d.data_doc and target_month_str in d.data_doc:
                # Baza = comisionul (fără TVA)
                total_baza += float(d.comision or 0)

        return round(total_baza, 2)
    except Exception as e:
        logger.error(f"_get_intracom_base_for_month error: {e}")
        return 0.0


def _get_available_intracom_months(
    session, user_id: int
) -> List[tuple]:
    """
    Returnează lista (year, month) pentru lunile cu facturi Bolt.

    Folosit pentru a afișa picker-ul de luni doar cu lunile relevante.
    """
    try:
        from app.models import Document
        from app.enums import DocType

        docs = (
            session.query(Document.data_doc)
            .filter(
                Document.user_id == user_id,
                Document.tip == DocType.FACTURA_COMISION.value
                    if hasattr(DocType, 'value') else DocType.FACTURA_COMISION,
                Document.status == "posted",
            )
            .all()
        )

        months_set = set()
        for (data_doc,) in docs:
            if not data_doc:
                continue
            try:
                d = datetime.strptime(data_doc, "%d.%m.%Y")
                months_set.add((d.year, d.month))
            except (ValueError, TypeError):
                continue

        return sorted(months_set, reverse=True)
    except Exception as e:
        logger.error(f"_get_available_intracom_months error: {e}")
        return []


# ============================================================
#                    KEYBOARD BUILDERS
# ============================================================

def _build_obligation_picker(applicable_obligations: List[str]) -> InlineKeyboardMarkup:
    """
    Construiește picker pentru tipuri de obligații aplicabile user-ului.
    """
    # Mapping cod intern → buton afișat
    OBLIGATII_DISPLAY = {
        "D301": "📋 D301 — TVA reverse charge (lunar)",
        "D100_634": "💼 D100 poz. 634 — Impozit 2% Bolt (lunar)",
        "D212": "📅 D212 — Declarația Unică (anual)",
        "D207": "📊 D207 — Informativă anuală",
        "D390": "📤 D390 — Recapitulativă VIES",
        "D300": "📋 D300 — Decont TVA standard",
        "D101": "🏢 D101 — Impozit profit SRL",
        "D700": "⚙️ D700 — Cod special TVA (o dată)",
    }

    rows = []
    # Doar obligațiile relevante user-ului
    for cod in applicable_obligations:
        label = OBLIGATII_DISPLAY.get(cod, cod)
        rows.append([
            InlineKeyboardButton(label, callback_data=f"plata|obl|{cod}")
        ])

    # Buton extra: compliance status complet
    rows.append([
        InlineKeyboardButton(
            "📈 Status Compliance complet",
            callback_data="plata|status"
        )
    ])
    rows.append([InlineKeyboardButton("❌ Închide", callback_data="nav|close")])
    return InlineKeyboardMarkup(rows)


def _build_month_picker_plata(
    obligation_code: str,
    available_months: List[tuple],
) -> InlineKeyboardMarkup:
    """
    Picker pentru luni cu facturi Bolt (sau toate dacă obligație anuală).
    """
    rows = []
    if not available_months:
        # Fallback: ultimele 6 luni
        today = date.today()
        for offset in range(0, 6):
            m = today.month - offset
            y = today.year
            if m <= 0:
                m += 12
                y -= 1
            available_months.append((y, m))

    # Maxim 8 luni afișate, 2 per rând
    for i in range(0, min(len(available_months), 8), 2):
        row = []
        for j in range(i, min(i + 2, len(available_months))):
            year, month = available_months[j]
            label = f"{LUNI_SHORT[month]} {year}"
            row.append(InlineKeyboardButton(
                label,
                callback_data=f"plata|period|{obligation_code}|{year}|{month}"
            ))
        rows.append(row)

    rows.append([
        InlineKeyboardButton("⬅️ Înapoi", callback_data="plata|back"),
        InlineKeyboardButton("❌ Închide", callback_data="nav|close"),
    ])
    return InlineKeyboardMarkup(rows)


def _build_payment_detail_buttons(
    obligation_code: str, year: int, month: int
) -> InlineKeyboardMarkup:
    """Butoane pentru mesajul de detaliu plată."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Marchează plătit",
                callback_data=f"plata|paid|{obligation_code}|{year}|{month}"
            ),
        ],
        [
            InlineKeyboardButton("⬅️ Înapoi", callback_data="plata|back"),
            InlineKeyboardButton("❌ Închide", callback_data="nav|close"),
        ],
    ])


# ============================================================
#                    LOGICA PRINCIPALĂ
# ============================================================

def get_applicable_obligations_codes(
    fiscal_profile: FiscalProfile,
    ctx: dict,
) -> List[str]:
    """
    Returnează lista de coduri obligații aplicabile profilului user-ului.

    Filtrăm cele 8 obligații din DEFINITII_OBLIGATII pe baza:
    - Forma juridică
    - Activitate
    - Status TVA (plătitor / neplătitor / cod special)
    """
    from app.domain.fiscal_calendar import _matches_forma_juridica

    fj = ctx["forma_juridica"]
    activity = ctx["activity_code"]
    is_vat_payer = ctx["is_vat_payer"]
    has_cod_special_tva = ctx["has_cod_special_tva"]

    applicable = []
    for key, definitie in DEFINITII_OBLIGATII.items():
        # Forma juridică match strict
        if not _matches_forma_juridica(
            fj, is_vat_payer, has_cod_special_tva,
            definitie.forme_juridice,
        ):
            continue
        # Activitate match
        if "*" not in definitie.activitati and activity not in definitie.activitati:
            continue
        applicable.append(key)

    return applicable


def build_payment_detail_message(
    session,
    user_id: int,
    obligation_code: str,
    period_year: int,
    period_month: int,
) -> str:
    """
    Construiește mesajul complet de detaliu plată pentru o obligație + lună.

    Conține: IBAN + sumă + termen + cod buget + beneficiar + termen depășire.
    """
    # Profil user
    fiscal_profile = from_user_id(session, user_id)
    profile_dict = users_repo.get_profile_dict(session, user_id) or {}
    ctx = _profile_to_guardian_context(fiscal_profile, profile_dict)

    # Definiția obligației
    definitie = DEFINITII_OBLIGATII.get(obligation_code)
    if not definitie:
        return f"❌ Obligație necunoscută: {obligation_code}"

    # Baza intracom (dacă e cazul)
    has_intracom = False
    intracom_base = 0.0
    if obligation_code in ("D301", "D100_634", "D390"):
        intracom_base = _get_intracom_base_for_month(
            session, user_id, period_year, period_month
        )
        has_intracom = intracom_base > 0

    # Calculează obligația
    obligatie = compute_obligation(
        definitie,
        period_year, period_month,
        ctx["forma_juridica"], ctx["activity_code"],
        has_intracom_invoice=has_intracom,
        intracom_base_amount=intracom_base,
        has_cod_special_tva=ctx["has_cod_special_tva"],
        is_vat_payer=ctx["is_vat_payer"],
        judet=ctx["judet"],
    )

    # Construim mesajul
    lines = [
        f"💳 *PLATĂ FISCALĂ — {definitie.cod}*",
        f"📅 _Perioada: {LUNI_LONG.get(period_month, period_month)} {period_year}_",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    if not obligatie.aplicabil_acum:
        lines.extend([
            f"⚠️ *Această obligație nu se aplică ție:*",
            f"_{obligatie.motiv_neaplicabil}_",
            "",
            "💡 Verifică profilul fiscal cu /profil",
        ])
        return "\n".join(lines)

    # Numele obligației
    lines.append(f"📋 *{definitie.nume}*")
    lines.append(f"_{definitie.descriere[:200]}_")
    lines.append("")

    # Baza + sumă
    if intracom_base > 0:
        lines.append(f"📊 *Calcul:*")
        lines.append(f"  • Bază factură: `{intracom_base:.2f} RON`")
        if obligatie.suma_estimata:
            lines.append(
                f"  • Sumă datorată: *`{obligatie.suma_estimata:.2f} RON`*"
            )
            lines.append(f"  _Formula: {definitie.formula_suma}_")
        lines.append("")
    elif obligation_code in ("D301", "D100_634", "D390"):
        lines.append(
            f"⚠️ *Nu am găsit factură Bolt pentru "
            f"{LUNI_LONG.get(period_month)} {period_year}.*"
        )
        lines.append("Verifică că ai încărcat factura.")
        lines.append("")

    # IBAN + cod buget
    if obligatie.iban_cont:
        lines.append(f"🏦 *IBAN PLATĂ:*")
        lines.append(f"`{obligatie.iban_cont.iban}`")
        lines.append(f"  📋 Cod buget: `{obligatie.iban_cont.cod_buget}`")
        id_tip = obligatie.iban_cont.tip_identificare_beneficiar.value
        if id_tip == "CUI":
            lines.append(f"  🆔 Identificare: *CUI* `{ctx['cui']}`")
        else:
            cnp_masked = (
                ctx['cnp'][:4] + "*****" + ctx['cnp'][-2:]
                if ctx.get('cnp') and len(ctx['cnp']) >= 6
                else "verifică pe SPV"
            )
            lines.append(f"  🆔 Identificare: *CNP* `{cnp_masked}`")
        if ctx.get('firma_nume'):
            lines.append(f"  👤 Beneficiar: _{ctx['firma_nume']}_")
        lines.append("")
    elif obligation_code in ("D207", "D390", "D700"):
        lines.append(f"📝 *NU se plătește* — doar declarație")
        lines.append(f"  Depune prin SPV: {definitie.portal_anaf}")
        lines.append("")

    # Termen
    termen_str = obligatie.termen.strftime("%d.%m.%Y")
    if obligatie.zile_ramase < 0:
        zile_str = f"DEPĂȘIT cu *{abs(obligatie.zile_ramase)} zile*"
        emoji = "🔴"
    elif obligatie.zile_ramase <= 3:
        zile_str = f"{obligatie.zile_ramase} zile rămase (URGENT)"
        emoji = "🟠"
    elif obligatie.zile_ramase <= 7:
        zile_str = f"{obligatie.zile_ramase} zile rămase"
        emoji = "🟡"
    else:
        zile_str = f"{obligatie.zile_ramase} zile rămase"
        emoji = "🟢"

    lines.append(f"📅 *Termen*: `{termen_str}` ({emoji} {zile_str})")

    # Avertismente
    if obligatie.zile_ramase < 0 and obligatie.suma_estimata:
        majorari = obligatie.suma_estimata * 0.0002 * abs(obligatie.zile_ramase)
        lines.append(f"")
        lines.append(
            f"⚠️ *Termen depășit — estimare majorări:* "
            f"`~{majorari:.2f} RON` (0.02%/zi)"
        )

    # Bonus info
    if definitie.bonus_info:
        lines.append("")
        lines.append(f"💡 _{definitie.bonus_info}_")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📋 _Copiază IBAN-ul în aplicația bancară._")
    lines.append("_⚠️ Verifică cu contabilul înainte de plată._")

    return "\n".join(lines)


# ============================================================
#                    TELEGRAM HANDLERS
# ============================================================

async def handle_menu_button(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
):
    """Handler pentru butonul 💳 Plată Fiscală din meniu."""
    from db import get_session

    tg_id = update.effective_user.id
    session = get_session()
    try:
        from app.repositories import users as users_repo
        user = users_repo.get_by_telegram_id(session, telegram_id=tg_id)
        if not user:
            await update.message.reply_text("⚠️ Eroare identificare utilizator.")
            return

        fiscal_profile = from_user_id(session, user.id)
        profile_dict = users_repo.get_profile_dict(session, user.id) or {}
        ctx = _profile_to_guardian_context(fiscal_profile, profile_dict)
    finally:
        session.close()

    applicable = get_applicable_obligations_codes(fiscal_profile, ctx)
    if not applicable:
        await update.message.reply_text(
            "📭 *Nu am identificat obligații fiscale aplicabile.*\n\n"
            "Verifică profilul cu /profil sau /reset_profil.",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(
        f"💳 *PLATĂ FISCALĂ*\n"
        f"_Profil: {fiscal_profile.forma_juridica.value} · "
        f"{ctx['activity_code']}_\n\n"
        f"Alege tipul plății:",
        parse_mode="Markdown",
        reply_markup=_build_obligation_picker(applicable),
    )


async def handle_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, parts: List[str],
):
    """
    Handler pentru callback queries cu namespace 'plata'.

    Formate callback_data:
      plata|obl|<COD>            → user a ales tipul obligației
      plata|period|<COD>|<Y>|<M> → user a ales luna
      plata|paid|<COD>|<Y>|<M>   → marchează ca plătit
      plata|back                 → înapoi la lista de obligații
      plata|status               → compliance status complet
    """
    from db import get_session

    query = update.callback_query
    tg_id = update.effective_user.id
    session = get_session()
    try:
        from app.repositories import users as users_repo
        user = users_repo.get_by_telegram_id(session, telegram_id=tg_id)
        if not user:
            await query.edit_message_text("⚠️ Eroare identificare utilizator.")
            return
        user_id = user.id

        fiscal_profile = from_user_id(session, user_id)
        profile_dict = users_repo.get_profile_dict(session, user_id) or {}
        ctx = _profile_to_guardian_context(fiscal_profile, profile_dict)

        if len(parts) < 2:
            return

        action = parts[1]

        if action == "back":
            applicable = get_applicable_obligations_codes(fiscal_profile, ctx)
            await query.edit_message_text(
                f"💳 *PLATĂ FISCALĂ*\n"
                f"_Profil: {fiscal_profile.forma_juridica.value}_\n\n"
                f"Alege tipul plății:",
                parse_mode="Markdown",
                reply_markup=_build_obligation_picker(applicable),
            )
            return

        if action == "obl":
            obligation_code = parts[2]
            definitie = DEFINITII_OBLIGATII.get(obligation_code)
            if not definitie:
                await query.edit_message_text(
                    f"❌ Obligație necunoscută: {obligation_code}"
                )
                return

            # Pentru obligații anuale (D212, D207, D700, D300, D101),
            # nu mai întrebăm luna — folosim luna curentă/precedentă
            if definitie.frecventa in (
                FrecventaObligatie.ANUALA, FrecventaObligatie.UNICA,
                FrecventaObligatie.TRIMESTRIALA,
            ):
                today = date.today()
                year, month = today.year, today.month
                msg = build_payment_detail_message(
                    session, user_id, obligation_code, year, month
                )
                await query.edit_message_text(
                    msg, parse_mode="Markdown",
                    reply_markup=_build_payment_detail_buttons(
                        obligation_code, year, month
                    ),
                )
                return

            # Lunar: arătăm picker cu lunile cu facturi Bolt
            if obligation_code in ("D301", "D100_634", "D390"):
                available_months = _get_available_intracom_months(
                    session, user_id
                )
                if not available_months:
                    await query.edit_message_text(
                        f"📭 *Nicio factură Bolt găsită.*\n\n"
                        f"Pentru {definitie.cod} ai nevoie de o factură "
                        f"intracomunitară încărcată. Trimite poza facturii "
                        f"Bolt și revino aici.",
                        parse_mode="Markdown",
                    )
                    return
            else:
                # D300 lunar (plătitor TVA) - ultimele 6 luni
                available_months = []
                today = date.today()
                for offset in range(0, 6):
                    m = today.month - offset
                    y = today.year
                    if m <= 0:
                        m += 12
                        y -= 1
                    available_months.append((y, m))

            await query.edit_message_text(
                f"📅 *{definitie.cod} — {definitie.nume}*\n\n"
                f"Pentru ce lună plătești?",
                parse_mode="Markdown",
                reply_markup=_build_month_picker_plata(
                    obligation_code, available_months
                ),
            )
            return

        if action == "period":
            obligation_code = parts[2]
            year = int(parts[3])
            month = int(parts[4])

            await query.edit_message_text(
                f"🔄 Verific {LUNI_LONG[month]} {year}...",
            )

            msg = build_payment_detail_message(
                session, user_id, obligation_code, year, month
            )
            await query.edit_message_text(
                msg, parse_mode="Markdown",
                reply_markup=_build_payment_detail_buttons(
                    obligation_code, year, month
                ),
            )
            return

        if action == "paid":
            # Pentru viitor: salvăm în DB statusul "plătit"
            # Acum doar confirmăm
            obligation_code = parts[2]
            year = int(parts[3])
            month = int(parts[4])
            await query.edit_message_text(
                f"✅ *Marcat ca plătit*\n\n"
                f"{obligation_code} pentru {LUNI_LONG.get(month, month)} {year}.\n\n"
                f"_Notă: această funcție va fi extinsă în Pas 12 (SPV "
                f"Integration) pentru verificare automată._",
                parse_mode="Markdown",
            )
            return

        if action == "status":
            today = date.today()
            year, month = today.year, today.month

            # Detectează factură Bolt curentă
            intracom_base = _get_intracom_base_for_month(
                session, user_id, year, month
            )

            status = get_compliance_status(
                year, month,
                forma_juridica=ctx["forma_juridica"],
                activity_code=ctx["activity_code"],
                has_intracom_invoice=intracom_base > 0,
                intracom_base_amount=intracom_base,
                has_cod_special_tva=ctx["has_cod_special_tva"],
                is_vat_payer=ctx["is_vat_payer"],
                judet=ctx["judet"],
                today=today,
            )

            msg = format_compliance_status_telegram(status)
            await query.edit_message_text(
                msg, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Înapoi", callback_data="plata|back"),
                    InlineKeyboardButton("❌ Închide", callback_data="nav|close"),
                ]])
            )
            return

    except Exception as e:
        logger.error(f"plata_fiscala callback error: {e}")
        try:
            await query.edit_message_text(f"❌ Eroare: {str(e)[:200]}")
        except Exception:
            pass
    finally:
        session.close()


async def handle_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
):
    """Handler pentru comanda /plata_fiscala — același ca butonul."""
    await handle_menu_button(update, context)


__all__ = [
    "BTN_PLATA",
    "handle_menu_button",
    "handle_callback",
    "handle_command",
]
