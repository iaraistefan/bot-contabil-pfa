"""
SQLAlchemy ORM models for the PFA accounting bot.

Single source of truth for all DB tables.
Import Base from db.py so all models register on the same declarative registry.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from db import Base


class User(Base):
    """
    Un user e identificat prin telegram_id.
    Câmpurile de config (cui, regim_tva, etc.) vin la pași viitori.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)
    name = Column(String(200), nullable=True)

    # Relații (reverse)
    documents = relationship("Document", back_populates="user")

    def __repr__(self):
        return f"<User id={self.id} telegram_id={self.telegram_id} name={self.name!r}>"


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # NEW: legătura cu User-ul. Nullable ca să nu spargem rândurile existente.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

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
    raw_json = Column(Text, default="")
    image_id = Column(String(200), default="")
    confidence = Column(Float, default=1.0)

    # Relații
    user = relationship("User", back_populates="documents")
