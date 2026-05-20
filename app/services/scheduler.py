"""
Scheduler pentru reminder-uri și monitorizare fiscală.

JOBS:
  • Luni 08:00   — reminder săptămânal generic (check_and_remind)
  • Luni 08:30   — dashboard compliance săptămânal (Pas 10.3) ← NOU
  • Ziua 20, 09:00 — alerte termene fiscale (legacy)
  • Ziua 1, 07:00  — monitorizare legislativă AI
  • Zilnic 08:00  — alerte proactive obligații (Pas 10.1)

CHANGELOG:
  • v1: Reminder săptămânal + alerte termene + monitorizare AI
  • v2 (Pas 10.1): + job zilnic check_and_send_proactive_alerts
  • v3 (Pas 10.3): + job Luni 08:30 send_weekly_compliance_dashboard
"""

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

logger = logging.getLogger(__name__)
ROMANIA_TZ = pytz.timezone("Europe/Bucharest")


# ============================================================
#                  HELPER — TELEGRAM SEND
# ============================================================

def _send_telegram_message(bot_token: str, chat_id: int, text: str) -> None:
    import requests
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Scheduler send_message failed for chat_id={chat_id}: {e}")


# ============================================================
#               JOB 1: REMINDER SĂPTĂMÂNAL (Luni 08:00)
# ============================================================

def check_and_remind(bot_token: str) -> None:
    """Reminder săptămânal — Luni 08:00."""
    from db import get_session
    from app.models import User, Document

    session = get_session()
    try:
        users = session.query(User).all()
        now = datetime.now(ROMANIA_TZ)
        week_ago = now - timedelta(days=7)

        for user in users:
            if not user.telegram_id:
                continue

            recent_docs = (
                session.query(Document)
                .filter(
                    Document.user_id == user.id,
                    Document.created_at >= week_ago.replace(tzinfo=None),
                    Document.status != "rejected",
                )
                .count()
            )

            total_docs = (
                session.query(Document)
                .filter(Document.user_id == user.id, Document.status != "rejected")
                .count()
            )

            if recent_docs == 0:
                msg = (
                    f"⏰ *Reminder săptămânal — Contabil PFA*\n\n"
                    f"Nu ai înregistrat niciun document în ultimele 7 zile.\n\n"
                    f"📸 Trimite-mi:\n"
                    f"• Bonuri combustibil\n"
                    f"• Facturi comision Bolt/Uber\n"
                    f"• Screenshot câștiguri din aplicație\n\n"
                    f"📊 Total documente până acum: *{total_docs}*\n\n"
                    f"_Datele neînregistrate la timp pot cauza probleme la D301._"
                )
            else:
                msg = (
                    f"✅ *Săptămâna aceasta — Contabil PFA*\n\n"
                    f"Ai înregistrat *{recent_docs} document{'e' if recent_docs > 1 else ''}* "
                    f"în ultimele 7 zile. Bravo!\n\n"
                    f"📊 Total: *{total_docs}* documente\n"
                    f"Folosește /raport pentru situația lunii curente."
                )

            _send_telegram_message(bot_token, user.telegram_id, msg)
            logger.info(f"Weekly reminder sent to user_id={user.id}")

    except Exception as e:
        logger.error(f"check_and_remind error: {e}")
    finally:
        session.close()


# ============================================================
#         JOB 2: ALERTĂ TERMENE FISCALE (Ziua 20, 09:00)
# ============================================================
# LEGACY — păstrat pentru compatibilitate.

def check_fiscal_deadlines(bot_token: str) -> None:
    """Alertă termene fiscale — ziua 20 a fiecărei luni."""
    from db import get_session
    from app.models import User, Transaction
    from app.domain.fiscal_calendar import format_fiscal_message

    now = datetime.now(ROMANIA_TZ)
    year, month = now.year, now.month

    session = get_session()
    try:
        users = session.query(User).all()
        for user in users:
            if not user.telegram_id:
                continue
            has_bolt = (
                session.query(Transaction)
                .filter(
                    Transaction.user_id == user.id,
                    Transaction.period_year == year,
                    Transaction.period_month == month,
                    Transaction.vat_treatment == "REVERSE_CHARGE",
                    Transaction.tx_type == "EXPENSE",
                )
                .count()
            ) > 0
            msg = format_fiscal_message(year, month, has_bolt_invoice=has_bolt)
            _send_telegram_message(bot_token, user.telegram_id, msg)
            logger.info(f"Fiscal deadline alert sent to user_id={user.id}")
    except Exception as e:
        logger.error(f"check_fiscal_deadlines error: {e}")
    finally:
        session.close()


# ============================================================
#         JOB 3: MONITORIZARE LEGISLATIVĂ (Ziua 1, 07:00)
# ============================================================

def run_fiscal_monitoring(bot_token: str) -> None:
    """Monitorizare legislativă cu OpenAI Web Search. Ziua 1, 07:00."""
    from db import get_session
    from app.models import User, FiscalAlert
    from app.ai.fiscal_monitor import run_fiscal_research, format_alert_telegram

    now = datetime.now(ROMANIA_TZ)
    year, month = now.year, now.month

    logger.info(f"Running fiscal monitoring for {year}/{month:02d}...")

    session = get_session()
    try:
        users = session.query(User).all()
        if not users:
            logger.info("No users found for fiscal monitoring.")
            return

        result = run_fiscal_research(year, month)

        for user in users:
            if not user.telegram_id:
                continue

            alert = FiscalAlert(
                user_id=user.id,
                research_year=year,
                research_month=month,
                title=result.get("title", "Research lunar"),
                summary=result.get("summary", ""),
                full_response=result.get("raw_response", "")[:5000],
                sources_json=[
                    {
                        "url": c.get("source_url", ""),
                        "name": c.get("source_name", ""),
                    }
                    for c in result.get("changes", [])
                    if c.get("source_url")
                ],
                urgency=result.get("urgency", "none"),
                has_changes=result.get("has_changes", False),
                seen=False,
            )
            session.add(alert)
            session.flush()

            telegram_msg = format_alert_telegram(result)
            if telegram_msg:
                _send_telegram_message(bot_token, user.telegram_id, telegram_msg)
                logger.info(
                    f"Fiscal alert sent to user_id={user.id} "
                    f"urgency={result.get('urgency')}"
                )
            else:
                _send_telegram_message(
                    bot_token, user.telegram_id,
                    f"✅ *Monitorizare fiscală {now.strftime('%B %Y')}*\n\n"
                    f"Nu am găsit modificări legislative relevante pentru PFA-ul tău "
                    f"în această lună.\n\n"
                    f"_Verificare automată efectuată pe ANAF.ro și Monitorul Oficial._"
                )

        session.commit()
        logger.info(f"Fiscal monitoring complete for {year}/{month:02d}")

    except Exception as e:
        session.rollback()
        logger.error(f"run_fiscal_monitoring error: {e}")
    finally:
        session.close()


# ============================================================
#    JOB 4: ALERTE PROACTIVE OBLIGAȚII (Zilnic 08:00) — Pas 10.1
# ============================================================

def run_proactive_alerts(bot_token: str) -> None:
    """
    Job zilnic — alerte pentru obligații fiscale cu termen apropiat.
    Anti-spam: tabelul fiscal_alert_sent previne trimiterea dublă.
    """
    try:
        from app.services.proactive_alerts import check_and_send_proactive_alerts
        stats = check_and_send_proactive_alerts(bot_token)
        logger.info(
            f"✅ Proactive alerts job done: "
            f"{stats.get('users_processed', 0)} users processed, "
            f"{stats.get('alerts_sent', 0)} alerts sent, "
            f"{stats.get('errors', 0)} errors"
        )
    except Exception as e:
        logger.error(f"run_proactive_alerts error: {e}")


# ============================================================
#  ⭐ JOB 5: WEEKLY COMPLIANCE DASHBOARD (Luni 08:30) — Pas 10.3
# ============================================================

def run_weekly_dashboard(bot_token: str) -> None:
    """
    Job săptămânal — dashboard compliance cu score 0-100.
    Rulează Luni 08:30 (după reminder-ul de la 08:00).
    """
    try:
        from app.services.proactive_alerts import send_weekly_compliance_dashboard
        stats = send_weekly_compliance_dashboard(bot_token)
        logger.info(
            f"✅ Weekly dashboard job done: "
            f"{stats.get('dashboards_sent', 0)} dashboards sent, "
            f"{stats.get('errors', 0)} errors"
        )
    except Exception as e:
        logger.error(f"run_weekly_dashboard error: {e}")


# ============================================================
#                    SCHEDULER STARTUP
# ============================================================

def start_scheduler(bot_token: str) -> BackgroundScheduler:
    """Pornește toate job-urile schedulerului."""
    scheduler = BackgroundScheduler(timezone=ROMANIA_TZ)

    # Reminder săptămânal: Luni 08:00
    scheduler.add_job(
        func=lambda: check_and_remind(bot_token),
        trigger=CronTrigger(
            day_of_week="mon", hour=8, minute=0, timezone=ROMANIA_TZ
        ),
        id="weekly_reminder",
        name="Weekly document reminder",
        replace_existing=True,
    )

    # ⭐ Pas 10.3: Dashboard compliance: Luni 08:30
    scheduler.add_job(
        func=lambda: run_weekly_dashboard(bot_token),
        trigger=CronTrigger(
            day_of_week="mon", hour=8, minute=30, timezone=ROMANIA_TZ
        ),
        id="weekly_dashboard",
        name="Weekly compliance dashboard",
        replace_existing=True,
    )

    # Alertă termene fiscale (legacy): ziua 20, ora 09:00
    scheduler.add_job(
        func=lambda: check_fiscal_deadlines(bot_token),
        trigger=CronTrigger(
            day=20, hour=9, minute=0, timezone=ROMANIA_TZ
        ),
        id="fiscal_deadline_alert",
        name="Monthly fiscal deadline alert (legacy)",
        replace_existing=True,
    )

    # Monitorizare legislativă: ziua 1 a lunii, ora 07:00
    scheduler.add_job(
        func=lambda: run_fiscal_monitoring(bot_token),
        trigger=CronTrigger(
            day=1, hour=7, minute=0, timezone=ROMANIA_TZ
        ),
        id="fiscal_monitoring",
        name="Monthly fiscal law monitoring",
        replace_existing=True,
    )

    # Pas 10.1: Alerte proactive obligații — ZILNIC 08:00
    scheduler.add_job(
        func=lambda: run_proactive_alerts(bot_token),
        trigger=CronTrigger(
            hour=8, minute=0, timezone=ROMANIA_TZ
        ),
        id="proactive_alerts",
        name="Daily proactive fiscal obligation alerts",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "✅ Scheduler started:\n"
        "   • Luni 08:00 — reminder săptămânal\n"
        "   • Luni 08:30 — dashboard compliance ⭐ NOU (Pas 10.3)\n"
        "   • Ziua 20, 09:00 — alerte termene fiscale (legacy)\n"
        "   • Ziua 1, 07:00 — monitorizare legislativă\n"
        "   • Zilnic 08:00 — alerte proactive obligații (Pas 10.1)"
    )
    return scheduler
