"""
Pas 10 — Proactive Alerts: Reminder zilnic + Dashboard săptămânal.

COMPONENTE:
  • check_and_send_proactive_alerts() — job zilnic 08:00 (Pas 10.1)
  • send_weekly_compliance_dashboard() — job Luni 08:30 (Pas 10.3)
  • test_alerts_for_user() — test manual din UI (Pas 10.2)

LOGICA DE ALERTARE (zilnic, 4 puncte temporale, anti-spam):
  • 7 zile rămase  → AVERTISMENT
  • 3 zile rămase  → URGENT
  • Ziua termenului → ASTĂZI EXPIRĂ
  • Depășit         → zilnic primele 7 zile, apoi săptămânal

DASHBOARD SĂPTĂMÂNAL (Luni 08:30):
  • Score compliance 0-100
  • Obligații depășite / apropiate / de urmărit
  • Verdict colorat

ANTI-SPAM:
  • Tabelul fiscal_alert_sent — cheie unică
    (user_id, obligation_code, period_year, period_month, alert_type)

DEPENDS ON:
  • app.domain.fiscal_calendar (Pas 11.2)
  • app.models.FiscalAlertSent (migration 004)
  • app.models.User.proactive_alerts_* (migration 004)

CHANGELOG:
  • v1 (Pas 10.1): backend alerte zilnice
  • v2 (Pas 10.3): + weekly compliance dashboard
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

# Praguri scoring compliance (Pas 10.3)
SCORE_BASE = 100
PENALTY_OVERDUE = 25      # obligație depășită
PENALTY_URGENT = 10       # 0-3 zile rămase
PENALTY_SOON = 5          # 4-7 zile rămase

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
    if zile_ramase == 0:
        return ALERT_DUE_TODAY
    if zile_ramase == 3:
        return ALERT_ADVANCE_3D
    if zile_ramase == 7:
        return ALERT_ADVANCE_7D
    if zile_ramase < 0:
        days_overdue = abs(zile_ramase)
        if days_overdue <= 7:
            return ALERT_OVERDUE_DAILY_TPL.format(days=days_overdue)
        else:
            if days_overdue % 7 == 1:
                week = (days_overdue - 1) // 7 + 1
                return ALERT_OVERDUE_WEEKLY_TPL.format(week=week)
    return None


def _was_alert_sent(
    session, user_id: int, obligation_code: str,
    period_year: int, period_month: int, alert_type: str,
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
    session, user_id: int, obligation_code: str,
    period_year: int, period_month: int, alert_type: str,
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
#               CONTEXT BUILDERS
# ============================================================

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


# Pre-check plafon: cel mai mic prag relevant = 0.8 × CAS 12 SMB (48.600) = 38.880.
# Sub el, nici CAS (venit_net ≤ CA) nici TVA (240k) nu pot fi aproape → skip calculul scump.
PLAFON_PRECHECK_RON = 38_880


def _ytd_income_brut(session, user_id: int, year: int) -> float:
    """
    Cifra de afaceri brută realizată YTD = SUM(amount_brut) pe tranzacțiile INCOME
    ale anului (locked=False, ca în compute_period). UN SINGUR SUM — pre-check
    ieftin înainte de compute_d212_anual (12× compute_period). CA ≥ venit_net,
    deci e plafon superior sigur pentru gate.
    """
    from sqlalchemy import func
    from app.models import Transaction
    total = (
        session.query(func.coalesce(func.sum(Transaction.amount_brut), 0.0))
        .filter(
            Transaction.user_id == user_id,
            Transaction.period_year == year,
            Transaction.tx_type == "INCOME",
            Transaction.locked == False,
        )
        .scalar()
    )
    return float(total or 0.0)


def _get_months_to_check(today: date) -> List[Tuple[int, int]]:
    """
    Returnează lunile pentru care verificăm obligații:
    luna curentă, luna anterioară, luna în urmă cu 2.
    """
    months = []
    months.append((today.year, today.month))

    if today.month == 1:
        months.append((today.year - 1, 12))
    else:
        months.append((today.year, today.month - 1))

    if today.month == 1:
        months.append((today.year - 1, 11))
    elif today.month == 2:
        months.append((today.year - 1, 12))
    else:
        months.append((today.year, today.month - 2))

    return months


def _collect_all_obligations(
    session, user, ctx: Dict, today: date
) -> List:
    """
    Colectează toate obligațiile aplicabile din lunile relevante.
    Deduplicate pe (cod, perioada_an, perioada_luna).
    """
    from app.domain.fiscal_calendar import get_obligations_for_user
    from app.services import tax_engine

    all_obligatii = []
    seen = set()

    for year, month in _get_months_to_check(today):
        intracom_base = _get_intracom_base_for_month(
            session, user.id, year, month
        )
        try:
            # D100 split per-platformă (sub-pas D): suma/status din plan (nu 2%);
            # defensiv — eșecul planului nu suprimă alertele.
            try:
                _plan = tax_engine.d100_plan_for(session, user_id=user.id, year=year, month=month)
                _d100_suma, _d100_status = _plan.suma_declarata, _plan.status
            except Exception:
                _d100_suma = _d100_status = None
            obligatii = get_obligations_for_user(
                year, month,
                forma_juridica=ctx["forma_juridica"],
                activity_code=ctx["activity_code"],
                has_intracom_invoice=intracom_base > 0,
                intracom_base_amount=intracom_base,
                has_cod_special_tva=ctx["has_cod_special_tva"],
                is_vat_payer=ctx["is_vat_payer"],
                judet=ctx["judet"],
                only_applicable=True,
                today=today,
                d100_suma=_d100_suma,
                d100_status=_d100_status,
            )
        except Exception as e:
            logger.error(
                f"_collect_all_obligations error {year}/{month}: {e}"
            )
            continue

        for o in obligatii:
            key = (
                o.definitie.cod,
                o.perioada_an or year,
                o.perioada_luna or month,
            )
            if key in seen:
                continue
            seen.add(key)
            all_obligatii.append(o)

    return all_obligatii


# ============================================================
#               FORMAT TELEGRAM ALERT (zilnic)
# ============================================================

def _format_alert_message(obligation, alert_type: str, ctx: Dict) -> str:
    """Construiește mesajul Telegram pentru o alertă zilnică."""
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
        lines.append("🏦 IBAN PLATĂ:")
        lines.append(f"`{obligation.iban_cont.iban}`")
        lines.append(f"   Cod buget: `{obligation.iban_cont.cod_buget}`")

    if obligation.zile_ramase < 0 and obligation.suma_estimata:
        majorari = (
            obligation.suma_estimata * 0.0002 * abs(obligation.zile_ramase)
        )
        lines.append("")
        lines.append(
            f"⚠️ Majorări estimate: *{majorari:.2f} RON* (0.02%/zi)"
        )

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
#               MAIN LOGIC — ALERTE ZILNICE
# ============================================================

def _tva_plafon_message(st: dict, ca: float) -> str:
    """Mesaj TVA cu suma rămasă (din st['threshold_ron'], nu hardcodat)."""
    threshold = st["threshold_ron"]
    pct = st["utilized_pct"]
    if st["status"] == "DEPASIT_PLAFON":
        return (
            f"🔴 Ai depășit plafonul TVA de {threshold:.0f} RON (ai {ca:.0f} RON). "
            f"Ai obligația să te înregistrezi în scopuri de TVA în 10 zile de la "
            f"depășire."
        )
    remaining = max(0.0, threshold - ca)
    return (
        f"🟡 Aproape de plafon TVA: {pct:.0f}% ({ca:.0f} / {threshold:.0f} RON). "
        f"Mai ai ~{remaining:.0f} lei până devii plătitor TVA obligatoriu."
    )


def _maybe_send_plafon(session, bot_token, user, year, code, st, message) -> int:
    """
    Trimite o alertă de plafon dacă status ∈ {APROAPE, DEPASIT} și nu s-a mai
    trimis (anti-spam pe an + treaptă). Caveat uniform. Returns 1 dacă trimisă.
    """
    status = st.get("status")
    if status not in ("APROAPE_PLAFON", "DEPASIT_PLAFON"):
        return 0
    alert_type = "prag_80" if status == "APROAPE_PLAFON" else "prag_depasit"
    if _was_alert_sent(session, user.id, code, year, 0, alert_type):
        return 0
    caveat = "\n\n⚠️ Estimare orientativă — verifică cu contabilul."
    success = _send_telegram_message(bot_token, user.telegram_id, message + caveat)
    if not success:
        return 0                              # netrimis → NU marcăm → reîncearcă
    # marcăm garda DOAR după trimitere reușită (ca la sumar)
    _log_alert_sent(session, user.id, code, year, 0, alert_type, status="delivered")
    return 1


def _check_plafon_alerts(session, bot_token, user, ctx, today) -> int:
    """
    Alerte „aproape de plafon" pe realizat YTD: TVA 300k + CAS 12 SMB
    (obligatoriu) + CAS 24 SMB (baza se dublează) + CASS 60 SMB (plafonare).

    Pre-check ieftin: dacă CA YTD < PLAFON_PRECHECK_RON → skip (nu rulăm
    compute_d212_anual). Gate-ul 38.880 (= 80% din cel mai MIC prag, CAS 12)
    acoperă corect toate pragurile — cine e sub el e departe de oricare.
    Anti-spam: o alertă / cod plafon / treaptă (prag_80 / prag_depasit) / an
    (period_month=0); coduri independente (PLAFON_TVA/CAS/CAS24/CASS60). Sursă
    unică: compute_d212_anual + vat_threshold_status + prag_*_status. Robust:
    eroare → 0.
    """
    try:
        year = today.year
        ca_ytd = _ytd_income_brut(session, user.id, year)
        if ca_ytd < PLAFON_PRECHECK_RON:
            return 0                          # departe de orice plafon
        from app.services import tax_engine
        from app.domain import contributii
        r = tax_engine.compute_d212_anual(session, user_id=user.id, an=year)
        sent = 0
        # TVA — doar dacă NU e deja plătitor
        if not ctx.get("is_vat_payer"):
            st = ctx["fiscal_profile"].vat_threshold_status(r.venit_brut)
            sent += _maybe_send_plafon(
                session, bot_token, user, year, "PLAFON_TVA",
                st, _tva_plafon_message(st, r.venit_brut),
            )
        # CAS 12 SMB — CAS devine obligatoriu
        st_cas = contributii.prag_cas_status(r.venit_net, year)
        sent += _maybe_send_plafon(
            session, bot_token, user, year, "PLAFON_CAS",
            st_cas, st_cas["message"],
        )
        # CAS 24 SMB — baza CAS se dublează (eveniment distinct de 12 SMB)
        st_cas24 = contributii.prag_cas24_status(r.venit_net, year)
        sent += _maybe_send_plafon(
            session, bot_token, user, year, "PLAFON_CAS24",
            st_cas24, st_cas24["message"],
        )
        # CASS 60 SMB — CASS se plafonează (informativ)
        st_cass60 = contributii.prag_cass60_status(r.venit_net, year)
        sent += _maybe_send_plafon(
            session, bot_token, user, year, "PLAFON_CASS60",
            st_cass60, st_cass60["message"],
        )
        return sent
    except Exception as e:
        logger.error(
            f"_check_plafon_alerts error user={getattr(user, 'id', '?')}: {e}"
        )
        return 0


def _process_user_alerts(
    session, bot_token: str, user, today: Optional[date] = None,
) -> int:
    """Procesează alertele zilnice pentru un user. Returns: nr alerte trimise."""
    if today is None:
        today = date.today()

    proactive_enabled = getattr(
        user, "proactive_alerts_enabled", DEFAULT_PROACTIVE_ENABLED
    )
    if not proactive_enabled:
        return 0

    try:
        ctx = _build_user_context(session, user.id)
    except Exception as e:
        logger.error(f"Build context failed for user {user.id}: {e}")
        return 0

    from app.domain.fiscal_calendar import get_obligations_for_user
    from app.services import tax_engine

    alerts_sent = 0
    months_to_check = _get_months_to_check(today)

    for year, month in months_to_check:
        intracom_base = _get_intracom_base_for_month(
            session, user.id, year, month
        )
        has_intracom = intracom_base > 0

        try:
            # D100 plan (sub-pas D) — defensiv: eșecul nu suprimă alertele.
            try:
                _plan = tax_engine.d100_plan_for(session, user_id=user.id, year=year, month=month)
                _d100_suma, _d100_status = _plan.suma_declarata, _plan.status
            except Exception:
                _d100_suma = _d100_status = None
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
                d100_suma=_d100_suma,
                d100_status=_d100_status,
            )
        except Exception as e:
            logger.error(
                f"get_obligations error user {user.id} {year}/{month}: {e}"
            )
            continue

        for obligatie in obligatii:
            alert_type = _determine_alert_type(obligatie.zile_ramase)
            if not alert_type:
                continue

            obligation_code = obligatie.definitie.cod.split()[0]
            period_year = obligatie.perioada_an or year
            period_month = obligatie.perioada_luna or month

            if _was_alert_sent(
                session, user.id, obligation_code,
                period_year, period_month, alert_type,
            ):
                continue

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

    # alerte „aproape de plafon" (TVA / CAS) pe realizat YTD
    alerts_sent += _check_plafon_alerts(session, bot_token, user, ctx, today)
    return alerts_sent


def check_and_send_proactive_alerts(bot_token: str) -> Dict[str, int]:
    """
    Job zilnic principal — verifică toți userii și trimite alerte.
    Returns: stats {users_processed, alerts_sent, errors}
    """
    from db import get_session
    from app.models import User

    logger.info("🔔 Starting proactive alerts check...")
    stats = {"users_processed": 0, "alerts_sent": 0, "errors": 0}

    session = get_session()
    try:
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
#         Pas 10.3 — WEEKLY COMPLIANCE DASHBOARD
# ============================================================

def _compute_compliance_score(obligatii: List) -> Tuple[int, str, str]:
    """
    Calculează scorul de compliance 0-100 din lista de obligații.
    Returns: (score, verdict_label, verdict_emoji)
    """
    score = SCORE_BASE

    for o in obligatii:
        zile = o.zile_ramase
        if zile < 0:
            score -= PENALTY_OVERDUE
        elif zile <= 3:
            score -= PENALTY_URGENT
        elif zile <= 7:
            score -= PENALTY_SOON

    score = max(0, min(100, score))

    if score >= 90:
        return score, "Excelent", "🟢"
    elif score >= 70:
        return score, "Bun", "🟡"
    elif score >= 50:
        return score, "Necesită acțiune", "🟠"
    else:
        return score, "Critic", "🔴"


def _format_weekly_dashboard(
    ctx: Dict, obligatii: List, score_data: Tuple, today: date,
) -> str:
    """Construiește mesajul dashboard-ului săptămânal."""
    score, verdict_label, verdict_emoji = score_data
    week_end = today + timedelta(days=6)

    obligatii_sorted = sorted(obligatii, key=lambda o: o.zile_ramase)

    overdue = [o for o in obligatii_sorted if o.zile_ramase < 0]
    urgent = [o for o in obligatii_sorted if 0 <= o.zile_ramase <= 7]
    upcoming = [o for o in obligatii_sorted if 7 < o.zile_ramase <= 30]

    lines = [
        "📊 *DASHBOARD COMPLIANCE SĂPTĂMÂNAL*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📅 _{today.strftime('%d.%m')} – "
        f"{week_end.strftime('%d.%m.%Y')}_",
        "",
        f"{verdict_emoji} *Score: {score}/100* — {verdict_label}",
        "",
    ]

    if overdue:
        lines.append("❌ *OBLIGAȚII DEPĂȘITE:*")
        for o in overdue:
            lines.append(
                f"  • *{o.definitie.cod}* — depășit "
                f"{abs(o.zile_ramase)} zile "
                f"(`{o.termen.strftime('%d.%m')}`)"
            )
            if o.suma_estimata:
                lines.append(f"    💰 {o.suma_estimata:.2f} RON")
        lines.append("")

    if urgent:
        lines.append("🟠 *TERMEN APROPIAT (≤7 zile):*")
        for o in urgent:
            zile_txt = (
                "ASTĂZI" if o.zile_ramase == 0
                else f"{o.zile_ramase} zile"
            )
            lines.append(
                f"  • *{o.definitie.cod}* — {zile_txt} "
                f"(`{o.termen.strftime('%d.%m')}`)"
            )
            if o.suma_estimata:
                lines.append(f"    💰 {o.suma_estimata:.2f} RON")
        lines.append("")

    if upcoming:
        lines.append("🟡 *DE URMĂRIT (8-30 zile):*")
        for o in upcoming:
            lines.append(
                f"  • {o.definitie.cod} — {o.zile_ramase} zile "
                f"(`{o.termen.strftime('%d.%m')}`)"
            )
        lines.append("")

    if not overdue and not urgent and not upcoming:
        lines.append("✅ *Săptămână liniștită!*")
        lines.append("_Nicio obligație fiscală apropiată._")
        lines.append("")

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "💳 _Apasă_ `/plata_fiscala` _pentru IBAN și sume._",
    ])

    return "\n".join(lines)


def send_weekly_compliance_dashboard(bot_token: str) -> Dict[str, int]:
    """
    Job Luni 08:30 — trimite dashboard compliance săptămânal
    tuturor userilor cu alerte activate.

    Returns: stats {users_processed, dashboards_sent, errors}
    """
    from db import get_session
    from app.models import User

    logger.info("📊 Starting weekly compliance dashboard...")
    stats = {"users_processed": 0, "dashboards_sent": 0, "errors": 0}

    session = get_session()
    try:
        users = (
            session.query(User)
            .filter(User.telegram_id.isnot(None))
            .all()
        )
        today = date.today()

        for user in users:
            try:
                proactive_enabled = getattr(
                    user, "proactive_alerts_enabled",
                    DEFAULT_PROACTIVE_ENABLED,
                )
                if not proactive_enabled:
                    continue

                ctx = _build_user_context(session, user.id)
                obligatii = _collect_all_obligations(
                    session, user, ctx, today
                )
                score_data = _compute_compliance_score(obligatii)
                msg = _format_weekly_dashboard(
                    ctx, obligatii, score_data, today
                )

                success = _send_telegram_message(
                    bot_token, user.telegram_id, msg
                )
                if success:
                    stats["dashboards_sent"] += 1
                    logger.info(
                        f"Weekly dashboard sent to user {user.id} "
                        f"(score={score_data[0]})"
                    )
                stats["users_processed"] += 1
            except Exception as e:
                logger.error(
                    f"Weekly dashboard error for user {user.id}: {e}"
                )
                stats["errors"] += 1

        logger.info(
            f"✅ Weekly dashboard done: "
            f"{stats['dashboards_sent']} sent, "
            f"{stats['errors']} errors"
        )
    except Exception as e:
        logger.error(f"send_weekly_compliance_dashboard error: {e}")
    finally:
        session.close()

    return stats


# ============================================================
#               TEST MANUAL ENTRY POINT
# ============================================================

def test_alerts_for_user(bot_token: str, telegram_id: int) -> Dict:
    """
    Test manual al sistemului de alerte pentru un user specific.
    Folosit din UI Telegram (buton "🧪 Test acum").
    NU verifică anti-spam — afișează un sumar al obligațiilor.
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
        from app.services import tax_engine

        intracom_base = _get_intracom_base_for_month(
            session, user.id, today.year, today.month
        )
        # D100 plan (sub-pas D) — defensiv: eșecul nu pică tot snapshot-ul.
        try:
            _plan = tax_engine.d100_plan_for(
                session, user_id=user.id, year=today.year, month=today.month)
            _d100_suma, _d100_status = _plan.suma_declarata, _plan.status
        except Exception:
            _d100_suma = _d100_status = None

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
            d100_suma=_d100_suma,
            d100_status=_d100_status,
            today=today,
        )

        lines = [
            "🧪 *TEST ALERTE FISCALE*",
            "━━━━━━━━━━━━━━━━━━━━",
            "",
            f"👤 Profil: _{ctx['forma_juridica']} · "
            f"{ctx['activity_code']}_",
            f"📅 Luna curentă: _{LUNI_RO.get(today.month)} "
            f"{today.year}_",
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
                    f"• *{o.definitie.cod}* — "
                    f"`{o.termen.strftime('%d.%m.%Y')}` ({zile_str})"
                )
                if o.suma_estimata:
                    lines.append(f"  💰 {o.suma_estimata:.2f} RON")

        lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            "_Alertele zilnice rulează la 8:00._",
            "_Dashboard săptămânal: Luni 8:30._",
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
    "send_weekly_compliance_dashboard",
    "test_alerts_for_user",
    "ALERT_ADVANCE_7D",
    "ALERT_ADVANCE_3D",
    "ALERT_DUE_TODAY",
]
