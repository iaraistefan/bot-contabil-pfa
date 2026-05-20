"""
Migrări de bază de date pentru schema evolutivă.

Folosim ALTER TABLE IF NOT EXISTS (Postgres 9.6+) — idempotent.
Rulează la fiecare pornire a botului. Dacă coloana există deja, nu face nimic.

Ordinea migrărilor contează — adaugă mereu la sfârșit, nu modifica cele vechi.
"""

import logging
from sqlalchemy import text

from db import get_session

logger = logging.getLogger(__name__)


MIGRATIONS = [
    {
        "id": "001_user_profile_fields",
        "description": "Add user profile fields (firma, CUI, regim, activitate)",
        "sql": [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS firma_nume VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS firma_cui VARCHAR(20)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS firma_forma_juridica VARCHAR(20)",
            "CREATE INDEX IF NOT EXISTS ix_users_firma_cui ON users(firma_cui)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS regim_tva VARCHAR(20)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS regim_impunere VARCHAR(20)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS caen_principal VARCHAR(10)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS activity_code VARCHAR(50)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS judet VARCHAR(50)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS localitate VARCHAR(100)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS data_inceput_activitate DATE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_step INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(150)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS telefon VARCHAR(30)",
        ],
    },
    {
        "id": "002_documents_user_id_not_null",
        "description": (
            "Backfill orphan documents (user_id=NULL) and enforce NOT NULL "
            "for multi-tenant data integrity"
        ),
        "sql": [
            """
            UPDATE documents
            SET status = 'rejected'
            WHERE user_id IS NULL AND status != 'rejected'
            """,
            """
            DELETE FROM transactions
            WHERE document_id IN (SELECT id FROM documents WHERE user_id IS NULL)
            """,
            """
            UPDATE documents
            SET user_id = (SELECT MIN(id) FROM users)
            WHERE user_id IS NULL
            """,
            "ALTER TABLE documents ALTER COLUMN user_id SET NOT NULL",
        ],
    },
    {
        "id": "003_documents_vat_id",
        "description": (
            "Add vat_id field to Document for VAT engine — automatic detection "
            "of supplier country (RO/UE/non-UE) and VAT treatment"
        ),
        "sql": [
            "ALTER TABLE documents ADD COLUMN IF NOT EXISTS vat_id VARCHAR(20)",
            "CREATE INDEX IF NOT EXISTS ix_documents_vat_id ON documents(vat_id)",
        ],
    },
    {
        "id": "004_proactive_alerts",
        "description": (
            "Pas 10.1: Proactive Alerts — adaugă tabelul fiscal_alert_sent "
            "(anti-spam) și 3 coloane în users pentru configurare alerte"
        ),
        "sql": [
            """
            CREATE TABLE IF NOT EXISTS fiscal_alert_sent (
                id              SERIAL PRIMARY KEY,
                user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                obligation_code VARCHAR(50) NOT NULL,
                period_year     INTEGER NOT NULL,
                period_month    INTEGER NOT NULL,
                alert_type      VARCHAR(30) NOT NULL,
                sent_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status          VARCHAR(20) NOT NULL DEFAULT 'delivered'
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ix_fas_unique
                ON fiscal_alert_sent (
                    user_id, obligation_code, period_year,
                    period_month, alert_type
                )
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_fas_user_sent_at
                ON fiscal_alert_sent (user_id, sent_at DESC)
            """,
            """
            ALTER TABLE users
                ADD COLUMN IF NOT EXISTS proactive_alerts_enabled
                BOOLEAN NOT NULL DEFAULT TRUE
            """,
            """
            ALTER TABLE users
                ADD COLUMN IF NOT EXISTS proactive_alerts_hour
                INTEGER NOT NULL DEFAULT 8
            """,
            """
            ALTER TABLE users
                ADD COLUMN IF NOT EXISTS proactive_alerts_advance_days
                INTEGER NOT NULL DEFAULT 7
            """,
        ],
    },
    {
        "id": "005_trip_logs",
        "description": (
            "Pas 14: Foaie de parcurs — tabelul trip_logs pentru jurnal "
            "km auto (deductibilitate combustibil)"
        ),
        "sql": [
            """
            CREATE TABLE IF NOT EXISTS trip_logs (
                id              SERIAL PRIMARY KEY,
                user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                trip_date       DATE NOT NULL,
                km              DOUBLE PRECISION NOT NULL DEFAULT 0,
                odometer_start  INTEGER,
                odometer_end    INTEGER,
                purpose         VARCHAR(255),
                period_year     INTEGER NOT NULL,
                period_month    INTEGER NOT NULL,
                created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_trip_logs_user_period
                ON trip_logs (user_id, period_year, period_month)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_trip_logs_date
                ON trip_logs (user_id, trip_date)
            """,
        ],
    },
    # Aici vom adăuga migrări noi în viitor
]


def _ensure_migrations_table():
    """Creează tabelul de tracking al migrărilor dacă nu există."""
    session = get_session()
    try:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id VARCHAR(100) PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                description TEXT
            )
        """))
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to create schema_migrations table: {e}")
        raise
    finally:
        session.close()


def _is_applied(migration_id: str) -> bool:
    session = get_session()
    try:
        result = session.execute(
            text("SELECT 1 FROM schema_migrations WHERE id = :id"),
            {"id": migration_id}
        ).first()
        return result is not None
    except Exception:
        return False
    finally:
        session.close()


def _mark_applied(migration_id: str, description: str):
    session = get_session()
    try:
        session.execute(
            text("""
                INSERT INTO schema_migrations (id, description)
                VALUES (:id, :desc)
                ON CONFLICT (id) DO NOTHING
            """),
            {"id": migration_id, "desc": description}
        )
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to mark migration {migration_id} as applied: {e}")
        raise
    finally:
        session.close()


def run_migrations():
    """
    Rulează toate migrările care nu au fost aplicate încă.
    Idempotent — sigur de apelat de oricâte ori.
    """
    logger.info("🔄 Verificare migrări DB...")

    try:
        _ensure_migrations_table()
    except Exception as e:
        logger.error(f"❌ Cannot ensure schema_migrations table: {e}")
        return

    applied_count = 0
    skipped_count = 0

    for migration in MIGRATIONS:
        mid = migration["id"]
        desc = migration["description"]

        if _is_applied(mid):
            skipped_count += 1
            continue

        logger.info(f"🚀 Aplic migrare: {mid} — {desc}")
        session = get_session()
        try:
            for sql in migration["sql"]:
                session.execute(text(sql))
            session.commit()
            _mark_applied(mid, desc)
            logger.info(f"✅ Migrare {mid} aplicată cu succes")
            applied_count += 1
        except Exception as e:
            session.rollback()
            logger.error(f"❌ Migrare {mid} EȘUATĂ: {e}")
            raise
        finally:
            session.close()

    logger.info(
        f"✅ Migrări terminate: {applied_count} aplicate, {skipped_count} sărite (deja aplicate)"
    )
