"""
Database engine, session factory, and declarative Base.
This module contains NO models — they live in app/models.py.
Import order: db.py defines Base; app/models.py imports and extends it.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from config import settings

# URL de conexiune – în Render e setat prin DATABASE_URL env var.
DATABASE_URL = settings.database_url
engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def init_db():
    """Creează tabelele dacă nu există. Import lazy pentru a evita ciclurile."""
    from app import models  # noqa: F401 — înregistrează modelele pe Base
    Base.metadata.create_all(bind=engine)
    # Migrații pentru coloane adăugate ulterior (idempotente, sigure).
    _run_light_migrations()


def _run_light_migrations():
    """
    Migrații ușoare, idempotente, pentru coloane adăugate după create_all.
    create_all NU adaugă coloane noi la tabele existente, de aceea facem
    ALTER TABLE ... IF NOT EXISTS aici. Sigur de rulat la fiecare pornire.
    """
    import logging
    from sqlalchemy import text

    statements = [
        # Date bancare pentru D301 (banca + IBAN setabile de fiecare user)
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS banca VARCHAR(120)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS iban VARCHAR(34)",
    ]
    try:
        with engine.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))
        logging.getLogger(__name__).info("Light migrations: OK")
    except Exception as e:
        # Nu blocam pornirea aplicatiei daca o migratie minora esueaza;
        # doar logam (pe SQLite vechi IF NOT EXISTS poate sa nu existe,
        # dar pe Postgres-ul din Render functioneaza).
        logging.getLogger(__name__).warning("Light migrations skipped: %s", e)


def get_session():
    """Returnează o sesiune SQLAlchemy gata de folosit."""
    return SessionLocal()
