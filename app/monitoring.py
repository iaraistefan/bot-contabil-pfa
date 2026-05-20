"""
Pas 13.1 — Monitoring & Error Tracking cu Sentry.

Sentry capturează automat erorile bot-ului și trimite notificări
(email) cu stack trace complet, contextul user-ului și frecvența.

ACTIVARE:
  • Setează variabila de mediu SENTRY_DSN în Render.
  • Dacă SENTRY_DSN lipsește → Sentry e dezactivat, bot-ul merge normal.

VARIABILE DE MEDIU:
  • SENTRY_DSN          — URL-ul proiectului Sentry (obligatoriu pt activare)
  • SENTRY_ENVIRONMENT  — "production" / "staging" (opțional, default production)
  • RENDER_GIT_COMMIT   — setat automat de Render (folosit ca release tag)

INTEGRARE în bot_contabil.py:
  • Import: from app import monitoring
  • La pornire (primul lucru): monitoring.init_sentry()
  • În handle_error(): monitoring.capture_exception(error)
  • În ensure_user(): monitoring.set_user_context(...)

CHANGELOG:
  • v1 (Pas 13.1, 18.05.2026): Versiune inițială
"""

import logging
import os

logger = logging.getLogger(__name__)

# Flag intern — știm dacă Sentry a fost inițializat cu succes
_sentry_active = False


def init_sentry() -> bool:
    """
    Inițializează Sentry pentru error tracking.

    Returns True dacă Sentry a fost activat, False altfel.
    Sigur de apelat oricând — dacă ceva eșuează, bot-ul merge normal.
    """
    global _sentry_active

    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        logger.info("ℹ️ Sentry dezactivat (SENTRY_DSN nu e setat)")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration

        # Logging integration: INFO+ devin breadcrumbs, ERROR+ devin evenimente
        sentry_logging = LoggingIntegration(
            level=logging.INFO,
            event_level=logging.ERROR,
        )

        environment = os.environ.get("SENTRY_ENVIRONMENT", "production")
        release = os.environ.get("RENDER_GIT_COMMIT", "unknown")
        if release and release != "unknown":
            release = release[:12]

        sentry_sdk.init(
            dsn=dsn,
            integrations=[sentry_logging],
            environment=environment,
            release=release,
            # Fără performance monitoring — economisim cota gratuită
            traces_sample_rate=0.0,
            # Nu trimite date personale (PII) by default
            send_default_pii=False,
            # Atașează stack trace la mesaje
            attach_stacktrace=True,
            # Câte breadcrumbs păstrăm
            max_breadcrumbs=50,
        )

        _sentry_active = True
        logger.info(
            f"✅ Sentry activat (env={environment}, release={release})"
        )
        return True

    except ImportError:
        logger.warning(
            "⚠️ sentry-sdk nu e instalat — Sentry dezactivat. "
            "Adaugă 'sentry-sdk' în requirements.txt."
        )
        return False
    except Exception as e:
        logger.error(f"❌ Sentry init failed: {e}")
        return False


def is_active() -> bool:
    """Returnează True dacă Sentry e activ."""
    return _sentry_active


def capture_exception(error, **context) -> None:
    """
    Trimite manual o excepție la Sentry.

    Args:
        error: excepția de trimis
        **context: perechi cheie-valoare adăugate ca extra context

    Sigur de apelat chiar dacă Sentry nu e activ (nu face nimic).
    """
    if not _sentry_active:
        return
    try:
        import sentry_sdk
        with sentry_sdk.push_scope() as scope:
            for key, value in context.items():
                scope.set_extra(key, value)
            sentry_sdk.capture_exception(error)
    except Exception:
        pass  # Sentry indisponibil — ignorăm silențios


def capture_message(message: str, level: str = "info", **context) -> None:
    """
    Trimite manual un mesaj la Sentry.

    Args:
        message: textul mesajului
        level: "debug" / "info" / "warning" / "error" / "fatal"
        **context: perechi cheie-valoare adăugate ca extra context
    """
    if not _sentry_active:
        return
    try:
        import sentry_sdk
        with sentry_sdk.push_scope() as scope:
            for key, value in context.items():
                scope.set_extra(key, value)
            sentry_sdk.capture_message(message, level=level)
    except Exception:
        pass


def set_user_context(user_id=None, telegram_id=None) -> None:
    """
    Setează contextul user-ului pentru Sentry.

    Astfel, când apare o eroare, vezi în Sentry exact ce user a fost
    afectat (fără date personale — doar ID-uri).
    """
    if not _sentry_active:
        return
    try:
        import sentry_sdk
        data = {}
        if user_id is not None:
            data["id"] = str(user_id)
        if telegram_id is not None:
            data["telegram_id"] = str(telegram_id)
        if data:
            sentry_sdk.set_user(data)
    except Exception:
        pass


def add_breadcrumb(message: str, category: str = "bot", level: str = "info") -> None:
    """
    Adaugă un breadcrumb (urmă) — util pentru a vedea pașii dinaintea
    unei erori în Sentry.
    """
    if not _sentry_active:
        return
    try:
        import sentry_sdk
        sentry_sdk.add_breadcrumb(
            category=category,
            message=message,
            level=level,
        )
    except Exception:
        pass
