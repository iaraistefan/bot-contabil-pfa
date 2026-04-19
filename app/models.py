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
    source_files = relationship("SourceFile", back_populates="user")

    def __repr__(self):
        return f"<User id={self.id} telegram_id={self.telegram_id} name={self.name!r}>"


class SourceFile(Base):
    """
    Un fișier primit de la user (poză, PDF, etc.).
    sha256 UNIQUE per user — blochează procesarea dublă a aceleași imagini.
    """
    __tablename__ = "source_files"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    kind = Column(String(20), nullable=False, default="photo")  # photo / pdf / text
    telegram_file_id = Column(String(300), nullable=True)       # pentru re-fetch de pe Telegram
    sha256 = Column(String(64), nullable=False, index=True)     # hex digest, 64 char
    mime = Column(String(100), nullable=True)
    bytes_size = Column(Integer, nullable=True)
    storage_path = Column(String(500), nullable=True)           # calea locală sau cheie S3

    # Relații
    user = relationship("User", back_populates="source_files")

    def __repr__(self):
        return f"<SourceFile id={self.id} sha={self.sha256[:8]}... user_id={self.user_id}>"


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Legătura cu User-ul
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
