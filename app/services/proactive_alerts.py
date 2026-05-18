"""
Pas 10.1 — Proactive Alerts: Reminder zilnic Telegram pentru obligații fiscale.

ARHITECTURĂ:
- Job zilnic la 8:00 (configurable per user)
- Pentru fiecare user onboarded:
    1. Construiește contextul (formă juridică, factură Bolt curentă)
    2. Calculează obligațiile aplicabile (folosind fiscal_calendar)
    3. Filtrează cele cu termen apropiat sau depășit
    4. Trimite alerte Telegram (cu anti-spam prin tabelul fiscal_alert_sent)
- Logica de alertare smart (4 puncte temporale, fără spam):
    • 7 zile rămase  → AVERTISMENT
    • 3 zile rămase  → URGENT
    • Ziua termenului → ASTĂZI EXPIRĂ
    • Depășit         → zilnic primele 7 zile, apoi săptămânal

ANTI-SPAM:
- Tabelul `fiscal_alert_sent` păstrează cheia unică:
    (user_id, obligation_code, period_year, period_month, alert_type)
- Înainte de trimitere → check dacă există → skip dacă da

DEPENDS ON:
- app.domain.fiscal_calendar (Pas 11.2)
- app.domain.compliance_guardian (Pas 11.3)
- app.services.plata_fiscala (Pas 11.4) — helper-e (importate privat)
- app.models.FiscalAlertSent (NOU — migration 004)
- app.models.User.proactive_alerts_* (NOU — migration 004)

CHANGELOG:
- v1 (16.05.2026, Pas 10.1): Versiune inițială backend
"""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pytz
import requests

logger = logging.getLogger(__name__)
ROMANIA_TZ = pytz.timezone("Europe/Bucharest")


# ============================================================
#                    CONSTANTE
# ============================================================

# Tipuri de alerte (corespund cu coloana alert_type din DB)
ALERT_ADVANCE_7D = "advance_7d"
ALERT_ADVANCE_3D = "advance_3d"
ALERT_DUE_TODAY = "due_today"
ALERT_OVERDUE_DAILY_TPL = "overdue_d{days}"      # primele 7 zile
ALERT_OVERDUE_WEEKLY_TPL = "overdue_w{week}"     # săptămânile 2+

# Default-uri pentru useri fără setări configurate
DEFAULT_PROACTIVE_ENABLED = True
DEFAULT_ALERTS_HOUR = 8
DEFAULT_ADVANCE_DAYS = 7

LUNI_RO = {
    1: "Ianuarie", 2: "Februarie", 3: "Martie", 4: "Aprilie",
    5: "Mai", 6: "Iunie", 7: "Iulie", 8: "August",
    9: "Septembrie", 10: "Octombrie", 11: "Noiembrie", 12: "Decembrie",
}


# ============================================================
#                    HELPER FUNCTIONS
# ============================================================

def _send_telegram_message(
    bot_token: str, chat_id: int, text: str
) -> bool:
    """Trimite mesaj Telegram. Returnează True dacă a reușit."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(
            f"_send_telegram_message failed for chat_id={chat_id}: {e}"
        )
        return False


def _determine_alert_type(zile_ramase: int) -> Optional[str]:
    """
    Determină ce tip de alertă să trimitem pentru o obligație.

    Returns None dacă nu e momentul de alertat (anti-spam).
    """
    # Ziua termenului
    if zile_ramase == 0:
        return ALERT_DUE_TODAY
    # 3 zile rămase
    if zile_ramase == 3:
        return ALERT_ADVANCE_3D
    # 7 zile rămase
    if zile_ramase == 7:
        return ALERT_ADVANCE_7D
    # Depășit
    if zile_ramase < 0:
        days_overdue = abs(zile_ramase)
        if days_overdue <= 7:
            return ALERT_OVERDUE_DAILY_TPL.format(days=days_overdue)
        else:
            # Săptămânale: ziua 8, 15, 22, etc.
            if days_overdue % 7 == 1:
                week = (days_overdue - 1) // 7 + 1
                return ALERT_OVERDUE_WEEKLY_TPL.format(week=week)
    # Altfel — nu alertăm (1, 2, 4, 5, 6 zile rămase)
    return None


def _was_alert_sent(
    session,
    user_id: int,
    obligation_code: str,
    period_year: int,
    period_month: int,
    alert_type: str,
) -> bool:
    """Verifică dacă o alertă specifică a fost deja trimisă."""
    try:
        from app.models import FiscalAlertSent
        exists = (
            session.query(FiscalAlertSent)
            .filter(
                FiscalAlertSent.user_id == user_id,
                FiscalAlertSent.obligation_code == obligation_code,
                FiscalAlertSent.period_year == period_year,
                FiscalAlertSent.period_month == period_month,
                FiscalAlertSent.alert_type == alert_type,
            )
            .first()
        ) is not None
        return exists
    except Exception as e:
        logger.error(f"_was_alert_sent error: {e}")
        # Fail-safe: returnăm True pentru a NU trimite (evităm spam la erori DB)
        return True


def _log_alert_sent(
    session,
    user_id: int,
    obligation_code: str,
    period_year: int,
    period_month: int,
    alert_type: str,
    status: str = "delivered",
) -> None:
    """Salvează în DB că am trimis o alertă."""
    try:
        from app.models import FiscalAlertSent
        record = FiscalAlertSent(
            user_id=user_id,
            obligation_code=obligation_code,
            period_year=period_year,
            period_month=period_month,
            alert_type=alert_type,
            status=status,
        )
        session.add(record)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"_log_alert_sent error: {e}")


# ============================================================
#               CONTEXT BUILDERS (similar plata_fiscala)
# ============================================================
# Le duplicăm aici pentru a NU modifica plata_fiscala.py existent.
# DRY trade-off: 30 linii duplicate vs zero risc de regresie.

JUDET_NAME_TO_CODE = {
    "BISTRITA-NASAUD": "BN", "BISTRIȚA-NĂSĂUD": "BN",
    "BISTRITA NASAUD": "BN", "BN": "BN",
    "BUCURESTI": "B", "BUCUREȘTI": "B", "B": "B",
    "CLUJ": "CJ", "TIMIS": "TM", "TIMIȘ": "TM",
    "IASI": "IS", "IAȘI": "IS",
}


def _build_user_context(session, user_id: int) -> Dict:
    """Construiește contextul fiscal pentru un user."""
    from app.domain.fiscal_profile import from_user_id, RegimTVA
    from app.repositories import users as users_repo

    fiscal_profile = from_user_id(session, user_id)
    profile_dict = users_repo.get_profile_dict(session, user_id) or {}

    judet_raw = (profile_dict.get("judet") or "").upper().strip()
    judet_code = JUDET_NAME_TO_CODE.get(
        judet_raw, judet_raw[:2] if judet_raw else "BN"
    )

    is_vat_payer = fiscal_profile.regim_tva == RegimTVA.PLATITOR_21
    has_cod_special_tva = (
        fiscal_profile.regim_tva == RegimTVA.SPECIAL_INTRACOM
    )

    return {
        "fiscal_profile": fiscal_profile,
        "profile_dict": profile_dict,
        "forma_juridica": fiscal_profile.forma_juridica.value,
        "activity_code": fiscal_profile.activity_code,
        "judet": judet_code,
        "is_vat_payer": is_vat_payer,
        "has_cod_special_tva": has_cod_special_tva,
        "cui": profile_dict.get("firma_cui") or "",
        "firma_nume": profile_dict.get("firma_nume") or "",
    }


def _get_intracom_base_for_month(
    session, user_id: int, year: int, month: int
) -> float:
    """Caută factura Bolt pentru luna respectivă și returnează baza."""
    try:
        from app.models import Document
        from app.enums import DocType

        target_month_str = f"{month:02d}.{year}"
        doc_type = (
            DocType.FACTURA_COMISION.value
            if hasattr(DocType, 'value')
            else DocType.FACTURA_COMISION
        )

        docs = (
            session.query(Document)
            .filter(
                Document.user_id == user_id,
                Document.tip == doc_type,
                Document.status == "posted",
            )
            .all()
        )

        total_baza = 0.0
        for d in docs:
            if d.data_doc and target_month_str in d.data_doc:
                total_baza += float(d.comision or 0)

        return round(total_baza, 2)
    except Exception as e:
        logger.error(f"_get_intracom_base_for_month error: {e}")
        return 0.0


# ============================================================
#               FORMAT TELEGRAM ALERT
# ============================================================

def _format_alert_message(
    obligation,  # ObligatieCalculate
    alert_type: str,
    ctx: Dict,
) -> str:
    """Construiește mesajul Telegram pentru o alertă."""
    # Header bazat pe tipul alertei
    if alert_type == ALERT_ADVANCE_7D:
        header = "🟡 *AVERTISMENT FISCAL — 7 zile rămase*"
    elif alert_type == ALERT_ADVANCE_3D:
        header = "🟠 *URGENT — 3 zile rămase*"
    elif alert_type == ALERT_DUE_TODAY:
        header = "🔴 *ASTĂZI EXPIRĂ TERMENUL!*"
    elif alert_type.startswith("overdue"):
        zile = abs(obligation.zile_ramase)
        header = f"❌ *TERMEN DEPĂȘIT cu {zile} zile*"
    else:
        header = "📅 *Reminder fiscal*"

    lines = [
        header,
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📋 *{obligation.definitie.cod}* — {obligation.definitie.nume}",
        f"📅 Perioada: _{LUNI_RO.get(obligation.perioada_luna, '?')} "
        f"{obligation.perioada_an}_",
        f"⏰ Termen: `{obligation.termen.strftime('%d.%m.%Y')}`",
    ]

    if obligation.suma_estimata:
        lines.append(f"💰 Sumă: *{obligation.suma_estimata:.2f} RON*")
        if obligation.baza_calcul:
            lines.append(
                f"   _bază: {obligation.baza_calcul:.2f} RON × "
                f"{obligation.definitie.formula_suma}_"
            )

    if obligation.iban_cont:
        lines.append("")
        lines.append(f"🏦 IBAN PLATĂ:")
        lines.append(f"`{obligation.iban_cont.iban}`")
        lines.append(f"   Cod buget: `{obligation.iban_cont.cod_buget}`")

    # Majorări pentru overdue
    if obligation.zile_ramase < 0 and obligation.suma_estimata:
        majorari = (
            obligation.suma_estimata * 0.0002 * abs(obligation.zile_ramase)
        )
        lines.append("")
        lines.append(
            f"⚠️ Majorări estimate: *{majorari:.2f} RON* (0.02%/zi)"
        )

    # Bonus info
    if obligation.definitie.bonus_info:
        lines.append("")
        lines.append(f"💡 _{obligation.definitie.bonus_info}_")

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "💳 _Apasă_ `/plata_fiscala` _pentru detalii complete._",
        "_⚠️ Verifică cu contabilul înainte de plată._",
    ])

    return "\n".join(lines)


# ============================================================
#               MAIN LOGIC — PER USER
# ============================================================

def _get_months_to_check(today: date) -> List[Tuple[int, int]]:
    """
    Returnează lunile pentru care verificăm obligații.

    Includem:
    - Luna curentă (declarăm luna curentă → termen luna următoare)
    - Luna anterioară (termen curent sau aproape)
    - Luna în urmă cu 2 (pentru overdue)
    """
    months = []

    # Luna curentă
    months.append((today.year, today.month))

    # Luna anterioară
    if today.month == 1:
        months.append((today.year - 1, 12))
    else:
        months.append((today.year, today.month - 1))

    # Luna în urmă cu 2
    if today.month == 1:
        months.append((today.year - 1, 11))
    elif today.month == 2:
        months.append((today.year - 1, 12))
    else:
        months.append((today.year, today.month - 2))

    return months


def _process_user_alerts(
    session,
    bot_token: str,
    user,
    today: Optional[date] = None,
) -> int:
    """
    Procesează alertele pentru un singur user.

    Returns: numărul de alerte trimise.
    """
    if today is None:
        today = date.today()

    # Check enable
    proactive_enabled = getattr(
        user, "proactive_alerts_enabled", DEFAULT_PROACTIVE_ENABLED
    )
    if not proactive_enabled:
        return 0

    # Build context
    try:
        ctx = _build_user_context(session, user.id)
    except Exception as e:
        logger.error(f"Build context failed for user {user.id}: {e}")
        return 0

    # Importăm aici ca să evităm circular imports
    from app.domain.fiscal_calendar import get_obligations_for_user

    alerts_sent = 0
    months_to_check = _get_months_to_check(today)

    for year, month in months_to_check:
        # Factura Bolt pentru luna respectivă
        intracom_base = _get_intracom_base_for_month(
            session, user.id, year, month
        )
        has_intracom = intracom_base > 0

        # Obligațiile aplicabile
        try:
            obligatii = get_obligations_for_user(
                year, month,
                forma_juridica=ctx["forma_juridica"],
                activity_code=ctx["activity_code"],
                has_intracom_invoice=has_intracom,
                intracom_base_amount=intracom_base,
                has_cod_special_tva=ctx["has_cod_special_tva"],
                is_vat_payer=ctx["is_vat_payer"],
                judet=ctx["judet"],
                only_applicable=True,
                today=today,
            )
        except Exception as e:
            logger.error(
                f"get_obligations error for user {user.id} {year}/{month}: {e}"
            )
            continue

        for obligatie in obligatii:
            # Determină dacă e momentul de alertat
            alert_type = _determine_alert_type(obligatie.zile_ramase)
            if not alert_type:
                continue

            # Cod scurt pentru DB (D100 din "D100 poz. 634")
            obligation_code = obligatie.definitie.cod.split()[0]
            period_year = obligatie.perioada_an or year
            period_month = obligatie.perioada_luna or month

            # Anti-spam check
            if _was_alert_sent(
                session, user.id, obligation_code,
                period_year, period_month, alert_type,
            ):
                continue

            # Construiește și trimite
            msg = _format_alert_message(obligatie, alert_type, ctx)

            success = _send_telegram_message(
                bot_token, user.telegram_id, msg
            )

            _log_alert_sent(
                session, user.id, obligation_code,
                period_year, period_month, alert_type,
                status="delivered" if success else "failed",
            )

            if success:
                alerts_sent += 1
                logger.info(
                    f"Alert sent: user={user.id} "
                    f"obligation={obligation_code} type={alert_type} "
                    f"period={period_year}/{period_month}"
                )

    return alerts_sent


# ============================================================
#               PUBLIC API — JOB ENTRY POINT
# ============================================================

def check_and_send_proactive_alerts(bot_token: str) -> Dict[str, int]:
    """
    Job zilnic principal — verifică toți userii pentru obligații
    apropiate și trimite alerte.

    Returns: stats {users_processed, alerts_sent}
    """
    from db import get_session
    from app.models import User

    logger.info("🔔 Starting proactive alerts check...")
    stats = {"users_processed": 0, "alerts_sent": 0, "errors": 0}

    session = get_session()
    try:
        # Userii care au telegram_id (= activi)
        users = (
            session.query(User)
            .filter(User.telegram_id.isnot(None))
            .all()
        )

        today = date.today()

        for user in users:
            try:
                sent = _process_user_alerts(
                    session, bot_token, user, today=today
                )
                stats["alerts_sent"] += sent
                stats["users_processed"] += 1
            except Exception as e:
                logger.error(
                    f"Proactive alerts error for user {user.id}: {e}"
                )
                stats["errors"] += 1
                session.rollback()

        logger.info(
            f"✅ Proactive alerts done: "
            f"{stats['users_processed']} users, "
            f"{stats['alerts_sent']} alerts, "
            f"{stats['errors']} errors"
        )

    except Exception as e:
        logger.error(f"check_and_send_proactive_alerts fatal error: {e}")
    finally:
        session.close()

    return stats


# ============================================================
#               TEST MANUAL ENTRY POINT
# ============================================================

def test_alerts_for_user(
    bot_token: str, telegram_id: int
) -> Dict:
    """
    Test manual al sistemului de alerte pentru un user specific.

    Folosit din UI Telegram (buton "🧪 Test acum").

    Differența față de jobul zilnic:
    - NU verifică anti-spam (trimite toate alertele aplicabile)
    - Marchează totul cu suffix "_test" pentru a NU bloca alerte reale

    Returns: stats + lista de obligații găsite
    """
    from db import get_session
    from app.models import User

    session = get_session()
    try:
        user = (
            session.query(User)
            .filter(User.telegram_id == telegram_id)
            .first()
        )
        if not user:
            return {"error": "User not found"}

        ctx = _build_user_context(session, user.id)
        today = date.today()

        from app.domain.fiscal_calendar import get_obligations_for_user

        # Verificăm pentru luna curentă (în care suntem)
        intracom_base = _get_intracom_base_for_month(
            session, user.id, today.year, today.month
        )

        obligatii = get_obligations_for_user(
            today.year, today.month,
            forma_juridica=ctx["forma_juridica"],
            activity_code=ctx["activity_code"],
            has_intracom_invoice=intracom_base > 0,
            intracom_base_amount=intracom_base,
            has_cod_special_tva=ctx["has_cod_special_tva"],
            is_vat_payer=ctx["is_vat_payer"],
            judet=ctx["judet"],
            only_applicable=True,
            today=today,
        )

        # Mesaj sumar test
        lines = [
            "🧪 *TEST ALERTE FISCALE*",
            "━━━━━━━━━━━━━━━━━━━━",
            "",
            f"👤 Profil: _{ctx['forma_juridica']} · {ctx['activity_code']}_",
            f"📅 Luna curentă: _{LUNI_RO.get(today.month)} {today.year}_",
            "",
        ]

        if not obligatii:
            lines.append(
                "✅ *Nicio obligație aplicabilă pentru luna curentă.*"
            )
        else:
            lines.append(f"📋 *{len(obligatii)} obligații aplicabile:*")
            lines.append("")
            for o in obligatii:
                zile_str = (
                    f"DEPĂȘIT {abs(o.zile_ramase)}z"
                    if o.zile_ramase < 0
                    else f"{o.zile_ramase}z rămase"
                )
                lines.append(
                    f"• *{o.definitie.cod}* — `{o.termen.strftime('%d.%m.%Y')}` "
                    f"({zile_str})"
                )
                if o.suma_estimata:
                    lines.append(f"  💰 {o.suma_estimata:.2f} RON")

        lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            "_Sistemul de alerte rulează zilnic la 8:00._",
            "_Vei primi notificare cu 7 zile, 3 zile și ziua termenului._",
        ])

        msg = "\n".join(lines)
        _send_telegram_message(bot_token, telegram_id, msg)

        return {
            "success": True,
            "obligatii_count": len(obligatii),
            "obligatii": [o.definitie.cod for o in obligatii],
        }

    except Exception as e:
        logger.error(f"test_alerts_for_user error: {e}")
        return {"error": str(e)}
    finally:
        session.close()


__all__ = [
    "check_and_send_proactive_alerts",
    "test_alerts_for_user",
    "ALERT_ADVANCE_7D",
    "ALERT_ADVANCE_3D",
    "ALERT_DUE_TODAY",
]
