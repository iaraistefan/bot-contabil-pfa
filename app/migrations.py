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


# Lista migrărilor — fiecare e o listă de comenzi SQL idempotente.
# Pentru a adăuga o migrare nouă, adaugă o intrare nouă cu ID unic.

MIGRATIONS = [
    {
        "id": "001_user_profile_fields",
        "description": "Add user profile fields (firma, CUI, regim, activitate)",
        "sql": [
            # Profil firmă
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS firma_nume VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS firma_cui VARCHAR(20)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS firma_forma_juridica VARCHAR(20)",
            "CREATE INDEX IF NOT EXISTS ix_users_firma_cui ON users(firma_cui)",

            # Regim fiscal
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS regim_tva VARCHAR(20)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS regim_impunere VARCHAR(20)",

            # Activitate
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS caen_principal VARCHAR(10)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS activity_code VARCHAR(50)",

            # Locație
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS judet VARCHAR(50)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS localitate VARCHAR(100)",

            # Stare onboarding
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS data_inceput_activitate DATE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_step INTEGER NOT NULL DEFAULT 0",

            # Contact
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(150)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS telefon VARCHAR(30)",
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
