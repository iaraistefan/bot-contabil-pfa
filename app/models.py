"""
SQLAlchemy ORM models for the PFA accounting bot.

Single source of truth for all DB tables.
Import Base from db.py so all models register on the same declarative registry.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from db import Base


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
