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


def get_session():
    """Returnează o sesiune SQLAlchemy gata de folosit."""
    return SessionLocal()
