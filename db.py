from config import settings
import os
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float,
    DateTime, Text
)
from sqlalchemy.orm import declarative_base, sessionmaker

# URL de conexiune – îl vei seta ca env var în Render:
# DATABASE_URL = postgres://user:pass@host:port/dbname
DATABASE_URL = settings.database_url

if not DATABASE_URL:
    # Fallback la SQLite local (pentru teste sau dacă DB nu e setată)
    DATABASE_URL = "sqlite:///contabil_pfa.db"

engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Info de bază
    data_doc = Column(String(20), index=True)        # "DD.MM.YYYY"
    platforma = Column(String(50), index=True)       # Bolt, Uber, Petrom, Lukoil etc.
    tip = Column(String(30), index=True)             # VENIT, CHELTUIALA, FACTURA_COMISION

    brut = Column(Float, default=0.0)
    comision = Column(Float, default=0.0)
    tva = Column(Float, default=0.0)
    net = Column(Float, default=0.0)
    cash = Column(Float, default=0.0)
    banca = Column(Float, default=0.0)

    detalii = Column(Text, default="")

    # JSON brut returnat de AI (pentru audit)
    raw_json = Column(Text, default="")

    # Imagine / fișier – deocamdată doar un identificator
    image_id = Column(String(200), default="")

    # Încredere internă (la început punem 1.0)
    confidence = Column(Float, default=1.0)


def init_db():
    """Creează tabelele dacă nu există."""
    Base.metadata.create_all(bind=engine)


def get_session():
    """Returnează o sesiune SQLAlchemy gata de folosit."""
    return SessionLocal()
