"""
Scheduler pentru reminder-uri săptămânale.

Folosește APScheduler (deja disponibil sau adăugat în requirements.txt).
Rulează în background thread, independent de bot și Flask.

Funcționalitate:
- În fiecare Luni dimineață (08:00 Romania) → verifică dacă user-ul
  a încărcat documente în ultimele 7 zile.
- Dacă NU → trimite reminder Telegram.
- Dacă DA → trimite confirmare scurtă cu statistici.
- În ziua de 20 a fiecărei luni → alertă D301/D390 dacă există facturi Bolt.
- Pe 10 mai în fiecare an → alertă Declarație Unică (termen 25 mai).
"""

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

logger = logging.getLogger(__name__)

ROMANIA_TZ = pytz.timezone("Europe/Bucharest")


def _send_telegram_message(bot_token: str, chat_id: int, text: str) -> None:
    """Trimite mesaj Telegram sincron (pentru scheduler)."""
    import requests
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Scheduler send_message failed: {e}")


def check_and_remind(bot_token: str) -> None:
    """
    Verifică toți userii activi și trimite reminder-uri dacă e cazul.
    Apelat automat de scheduler în fiecare Luni la 08:00.
    """
    from db import get_session
    from app.models import User, Document, Transaction

    session = get_session()
    try:
        users = session.query(User).all()
        now = datetime.now(ROMANIA_TZ)
        week_ago = now - timedelta(days=7)

        for user in users:
            if not user.telegram_id:
                continue

            # Câte documente în ultima săptămână?
            recent_docs = (
                session.query(Document)
                .filter(
                    Document.user_id == user.id,
                    Document.created_at >= week_ago.replace(tzinfo=None),
                    Document.status != "rejected",
                )
                .count()
            )

            # Câte documente total?
            total_docs = (
                session.query(Document)
                .filter(Document.user_id == user.id, Document.status != "rejected")
                .count()
            )

            if recent_docs == 0:
                # Niciun document în ultimele 7 zile → reminder
                msg = (
                    f"⏰ *Reminder săptămânal — Contabil PFA*\n\n"
                    f"Nu ai înregistrat niciun document în ultimele 7 zile.\n\n"
                    f"📸 Trimite-mi:\n"
                    f"• Bonuri combustibil\n"
                    f"• Facturi comision Bolt/Uber\n"
                    f"• Screenshot câștiguri din aplicație\n\n"
                    f"📊 Total documente până acum: *{total_docs}*\n\n"
                    f"_Datele neînregistrate la timp pot cauza probleme la D301 și Declarația Unică._"
                )
            else:
                # Documente existente → confirmare pozitivă
                msg = (
                    f"✅ *Săptămâna aceasta — Contabil PFA*\n\n"
                    f"Ai înregistrat *{recent_docs} document{'e' if recent_docs > 1 else ''}* "
                    f"în ultimele 7 zile. Bravo!\n\n"
                    f"📊 Total: *{total_docs}* documente\n\n"
                    f"Folosește /raport pentru a vedea situația lunii curente."
                )

            _send_telegram_message(bot_token, user.telegram_id, msg)
            logger.info(f"Reminder sent to user_id={user.id} (recent_docs={recent_docs})")

    except Exception as e:
        logger.error(f"Scheduler check_and_remind error: {e}")
    finally:
        session.close()


def check_fiscal_deadlines(bot_token: str) -> None:
    """
    Trimite alertă fiscală pe 20 a fiecărei luni.
    Verifică dacă există facturi Bolt în luna curentă → D301/D390 alert.
    """
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

            # Verifică dacă există tranzacții REVERSE_CHARGE în luna curentă
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
            logger.info(f"Fiscal alert sent to user_id={user.id} (has_bolt={has_bolt})")

    except Exception as e:
        logger.error(f"Scheduler check_fiscal_deadlines error: {e}")
    finally:
        session.close()


def start_scheduler(bot_token: str) -> BackgroundScheduler:
    """
    Pornește scheduler-ul în background.
    Returnează instanța pentru a putea fi oprită dacă e nevoie.
    """
    scheduler = BackgroundScheduler(timezone=ROMANIA_TZ)

    # Reminder săptămânal: Luni 08:00 Romania
    scheduler.add_job(
        func=lambda: check_and_remind(bot_token),
        trigger=CronTrigger(day_of_week="mon", hour=8, minute=0, timezone=ROMANIA_TZ),
        id="weekly_reminder",
        name="Weekly document reminder",
        replace_existing=True,
    )

    # Alertă fiscală: ziua 20 a fiecărei luni, ora 09:00
    scheduler.add_job(
        func=lambda: check_fiscal_deadlines(bot_token),
        trigger=CronTrigger(day=20, hour=9, minute=0, timezone=ROMANIA_TZ),
        id="fiscal_deadline_alert",
        name="Monthly fiscal deadline alert",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("✅ Scheduler started (weekly reminder + fiscal alerts)")
    return scheduler
