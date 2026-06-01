"""
Migratie: adauga coloanele banca + iban in tabela users.

Idempotenta (ADD COLUMN IF NOT EXISTS) — sigur de rulat de oricate ori,
nu strica datele existente.

CUM SE RULEAZA:
  Optiunea 1 — adauga apelul in migratia ta existenta (migrations.py),
  alaturi de celelalte ALTER TABLE.

  Optiunea 2 — ruleaza o singura data manual:
      python migration_banca_iban.py
  (necesita DATABASE_URL in environment, ca restul aplicatiei)
"""

import logging

logger = logging.getLogger(__name__)


# SQL-urile de adaugat (Postgres suporta IF NOT EXISTS la ADD COLUMN)
MIGRATION_STATEMENTS = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS banca VARCHAR(120)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS iban VARCHAR(34)",
]


def run_migration(engine) -> None:
    """
    Aplica migratia pe engine-ul dat (SQLAlchemy Engine).
    Apeleaza asta din migrations.py-ul tau, dupa create_all.
    """
    from sqlalchemy import text
    with engine.begin() as conn:
        for stmt in MIGRATION_STATEMENTS:
            conn.execute(text(stmt))
            logger.info("Migratie aplicata: %s", stmt)
    logger.info("Migratie banca+iban: OK")


if __name__ == "__main__":
    # Rulare standalone (foloseste acelasi engine ca aplicatia)
    logging.basicConfig(level=logging.INFO)
    try:
        from db import engine  # acelasi import ca in restul aplicatiei
    except Exception as e:
        raise SystemExit(
            f"Nu pot importa engine din db.py: {e}\n"
            f"Ruleaza din radacina proiectului, cu DATABASE_URL setat."
        )
    run_migration(engine)
    print("✅ Coloanele banca + iban au fost adaugate (sau existau deja).")
