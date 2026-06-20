"""
Migrari de baza de date pentru schema evolutiva.

Folosim ALTER TABLE IF NOT EXISTS (Postgres 9.6+) - idempotent.
Ruleaza la fiecare pornire a botului. Daca coloana exista deja, nu face nimic.

Ordinea migrarilor conteaza - adauga mereu la sfarsit, nu modifica cele vechi.
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
            "Add vat_id field to Document for VAT engine - automatic detection "
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
            "Pas 10.1: Proactive Alerts - adauga tabelul fiscal_alert_sent "
            "(anti-spam) si 3 coloane in users pentru configurare alerte"
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
            "Pas 14: Foaie de parcurs - tabelul trip_logs pentru jurnal "
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
    {
        "id": "006_vehicule_foaie_parcurs",
        "description": (
            "Pas A: tabelul vehicule (flota PFA/SRL/II) + extindere "
            "trip_logs cu vehicul_id, status open/closed si ore tura"
        ),
        "sql": [
            # --- 1. Tabel nou: vehicule ---
            """
            CREATE TABLE IF NOT EXISTS vehicule (
                id                SERIAL PRIMARY KEY,
                user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                nr_inmatriculare  VARCHAR(20) NOT NULL,
                marca_model       VARCHAR(120),
                norma_consum      DOUBLE PRECISION NOT NULL DEFAULT 7.5,
                tip_detinere      VARCHAR(20),
                km_curent         INTEGER,
                activ             BOOLEAN NOT NULL DEFAULT TRUE,
                created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_vehicule_user_activ
                ON vehicule (user_id, activ)
            """,
            # --- 2. Extindere trip_logs (idempotent) ---
            """
            ALTER TABLE trip_logs
                ADD COLUMN IF NOT EXISTS vehicul_id INTEGER
                REFERENCES vehicule(id) ON DELETE SET NULL
            """,
            """
            ALTER TABLE trip_logs
                ADD COLUMN IF NOT EXISTS status VARCHAR(20)
                NOT NULL DEFAULT 'closed'
            """,
            """
            ALTER TABLE trip_logs
                ADD COLUMN IF NOT EXISTS ora_start VARCHAR(5)
            """,
            """
            ALTER TABLE trip_logs
                ADD COLUMN IF NOT EXISTS ora_stop VARCHAR(5)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_trip_logs_vehicul
                ON trip_logs (vehicul_id)
            """,
        ],
    },
    {
        "id": "007_documents_numar_document",
        "description": (
            "Pas R1.2: adauga numar_document in documents pentru "
            "detectarea EXACTA a duplicatelor (serie + numar document)"
        ),
        "sql": [
            "ALTER TABLE documents ADD COLUMN IF NOT EXISTS numar_document VARCHAR(80)",
            """
            CREATE INDEX IF NOT EXISTS ix_documents_numar_document
                ON documents (numar_document)
            """,
        ],
    },
    {
        "id": "008_bolt_orders_cache",
        "description": (
            "Pas 2 Bolt: tabel cache bolt_orders (istoric curse din API, "
            "dedup pe order_reference) pentru colectare zilnica automata"
        ),
        "sql": [
            """
            CREATE TABLE IF NOT EXISTS bolt_orders (
                id              SERIAL PRIMARY KEY,
                user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                order_reference VARCHAR(120) NOT NULL,
                order_status    VARCHAR(40),
                payment_method  VARCHAR(20),
                ride_price      DOUBLE PRECISION NOT NULL DEFAULT 0,
                commission      DOUBLE PRECISION NOT NULL DEFAULT 0,
                net_earnings    DOUBLE PRECISION NOT NULL DEFAULT 0,
                tip             DOUBLE PRECISION NOT NULL DEFAULT 0,
                cash_discount   DOUBLE PRECISION NOT NULL DEFAULT 0,
                finished_ts     BIGINT,
                period_year     INTEGER,
                period_month    INTEGER,
                created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ix_bolt_orders_unique
                ON bolt_orders (user_id, order_reference)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_bolt_orders_period
                ON bolt_orders (user_id, period_year, period_month)
            """,
        ],
    },
    {
        "id": "009_bolt_orders_ride_distance",
        "description": (
            "A.1: adauga ride_distance (metri, distanta cu pasager) in "
            "bolt_orders pentru legarea cu foaia de parcurs / combustibil"
        ),
        "sql": [
            """
            ALTER TABLE bolt_orders
                ADD COLUMN IF NOT EXISTS ride_distance INTEGER NOT NULL DEFAULT 0
            """,
        ],
    },
    {
        "id": "010_monthly_summary",
        "description": (
            "Faza 3: sumar lunar automat - tabelul summary_sent (anti-dublura) "
            "cu unicitate pe (user_id, period_year, period_month)"
        ),
        "sql": [
            """
            CREATE TABLE IF NOT EXISTS summary_sent (
                id              SERIAL PRIMARY KEY,
                user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                period_year     INTEGER NOT NULL,
                period_month    INTEGER NOT NULL,
                sent_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ix_summary_sent_unique
                ON summary_sent (user_id, period_year, period_month)
            """,
        ],
    },
    {
        "id": "011_transactions_import_fingerprint",
        "description": (
            "Felia 3 (import extras): import_fingerprint pe transactions — "
            "anti-dublura la nivel de tranzactie bancara (occurred_on+amount+"
            "directie+descriere normalizata+ocurenta). Nullable, aditiv."
        ),
        "sql": [
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS import_fingerprint VARCHAR(64)",
            """
            CREATE INDEX IF NOT EXISTS ix_transactions_import_fingerprint
                ON transactions (user_id, import_fingerprint)
            """,
        ],
    },
    {
        "id": "012_obligation_payments",
        "description": (
            "Felia 5b: tabel obligation_payments — faptul platii unei obligatii "
            "fiscale detectate din extras (obligatia ramane efemera). Anti-dublura "
            "pe (user_id, import_fingerprint); plati multiple/transe permise."
        ),
        "sql": [
            """
            CREATE TABLE IF NOT EXISTS obligation_payments (
                id                 SERIAL PRIMARY KEY,
                created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                user_id            INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                obligation_code    VARCHAR(20) NOT NULL,
                perioada_an        INTEGER NOT NULL,
                perioada_luna      INTEGER NOT NULL DEFAULT 0,
                suma_platita       DOUBLE PRECISION NOT NULL,
                data_platii        DATE NOT NULL,
                sursa              VARCHAR(20) NOT NULL DEFAULT 'bank_import',
                import_fingerprint VARCHAR(64) NOT NULL,
                source_file_id     INTEGER REFERENCES source_files(id)
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ix_oblig_pay_fingerprint
                ON obligation_payments (user_id, import_fingerprint)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_oblig_pay_lookup
                ON obligation_payments (user_id, obligation_code, perioada_an, perioada_luna)
            """,
        ],
    },
    {
        "id": "013_user_regim_nerezident",
        "description": (
            "Fiscal #3 (sub-pas A): regim impozit nerezident pe comisionul "
            "platformelor (per-platforma). Bolt: 2% cu certificat / 16% fara. "
            "Nullable FARA default — NULL = neintrebat/neconfigurat, NU o rata "
            "presupusa (a presupune o cota e exact bug-ul pe care il reparam)."
        ),
        "sql": [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS regim_nerezident VARCHAR(20)",
        ],
    },
    {
        "id": "014_regim_nerezident_per_platforma",
        "description": (
            "Suport Uber (sub-pas A): regim nerezident PER-PLATFORMA "
            "(regim_nerezident_bolt/_uber). Backfill NE-DISTRUCTIV: copiaza "
            "alegerea Bolt existenta in _bolt DOAR unde _bolt e NULL si vechiul "
            "e setat; vechiul regim_nerezident RAMANE (deprecat, fallback)."
        ),
        "sql": [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS regim_nerezident_bolt VARCHAR(20)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS regim_nerezident_uber VARCHAR(20)",
            # Backfill ne-distructiv + idempotent (doar unde _bolt inca NULL).
            # Valorile existente sunt deja BOLT_* (capturate la #3 sub-pas E).
            """
            UPDATE users
            SET regim_nerezident_bolt = regim_nerezident
            WHERE regim_nerezident_bolt IS NULL
              AND regim_nerezident IS NOT NULL
            """,
        ],
    },
    {
        "id": "015_bolt_credentials_per_user",
        "description": (
            "Bolt sync per-user (#2-A): credentiale Bolt Fleet API proprii per user. "
            "client_id in clar (identificator OAuth); client_secret_enc CRIPTAT (Fernet, "
            "niciodata in clar). Nullable: userii existenti NULL = neconectati (neschimbat). "
            "Inert (storage) — conectarea efectiva = #2-B."
        ),
        "sql": [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS bolt_client_id VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS bolt_client_secret_enc VARCHAR(500)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS bolt_connected_at TIMESTAMP",
        ],
    },
    {
        "id": "016_user_norma_venit",
        "description": (
            "Norma anuala de venit (lei) pentru PFA pe NORMA_VENIT — valoarea din "
            "decizia AJFP a judetului (OMF 1960/2025), dupa judet + tip localitate. "
            "Nullable: userii pe sistem real / fara norma completata = NULL (motorul "
            "D212 e regim-aware si trateaza NULL ca norma necompletata, fara cifra presupusa)."
        ),
        "sql": [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS norma_venit_anuala DOUBLE PRECISION",
        ],
    },
    # Aici vom adauga migrari noi in viitor
]


def _ensure_migrations_table():
    """Creeaza tabelul de tracking al migrarilor daca nu exista."""
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
    Ruleaza toate migrarile care nu au fost aplicate inca.
    Idempotent - sigur de apelat de oricate ori.
    """
    logger.info("Verificare migrari DB...")

    try:
        _ensure_migrations_table()
    except Exception as e:
        logger.error(f"Cannot ensure schema_migrations table: {e}")
        return

    applied_count = 0
    skipped_count = 0

    for migration in MIGRATIONS:
        mid = migration["id"]
        desc = migration["description"]

        if _is_applied(mid):
            skipped_count += 1
            continue

        logger.info(f"Aplic migrare: {mid} - {desc}")
        session = get_session()
        try:
            for sql in migration["sql"]:
                session.execute(text(sql))
            session.commit()
            _mark_applied(mid, desc)
            logger.info(f"Migrare {mid} aplicata cu succes")
            applied_count += 1
        except Exception as e:
            session.rollback()
            logger.error(f"Migrare {mid} ESUATA: {e}")
            raise
        finally:
            session.close()

    logger.info(
        f"Migrari terminate: {applied_count} aplicate, {skipped_count} sarite (deja aplicate)"
    )
