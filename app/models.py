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
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)
    name = Column(String(200), nullable=True)

    documents = relationship("Document", back_populates="user")
    source_files = relationship("SourceFile", back_populates="user")

    def __repr__(self):
        return f"<User id={self.id} telegram_id={self.telegram_id} name={self.name!r}>"


class SourceFile(Base):
    __tablename__ = "source_files"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    kind = Column(String(20), nullable=False, default="photo")
    telegram_file_id = Column(String(300), nullable=True)
    sha256 = Column(String(64), nullable=False, index=True)
    mime = Column(String(100), nullable=True)
    bytes_size = Column(Integer, nullable=True)
    storage_path = Column(String(500), nullable=True)

    user = relationship("User", back_populates="source_files")
    documents = relationship("Document", back_populates="source_file")

    def __repr__(self):
        return f"<SourceFile id={self.id} sha={self.sha256[:8]}... user_id={self.user_id}>"


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Legături
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    # NEW: legătura cu fișierul sursă (NULL pentru mesajele text)
    source_file_id = Column(Integer, ForeignKey("source_files.id"), nullable=True, index=True)

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
    raw_json = Column(Text, default="")              # răspunsul brut AI pentru audit
    image_id = Column(String(200), default="")       # legacy field, păstrat
    confidence = Column(Float, default=1.0)

    # NEW: status + prompt version
    status = Column(String(20), nullable=False, default="posted", index=True)
    prompt_version = Column(String(50), nullable=True)

    # Relații
    user = relationship("User", back_populates="documents")
    source_file = relationship("SourceFile", back_populates="documents")

    def __repr__(self):
        return f"<Document id={self.id} tip={self.tip} brut={self.brut} status={self.status}>"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    entity_type = Column(String(50), nullable=False, index=True)
    entity_id = Column(Integer, nullable=False, index=True)
    action = Column(String(50), nullable=False)
    source = Column(String(20), nullable=False, default="system")

    before_json = Column(JSON, nullable=True)
    after_json = Column(JSON, nullable=True)
    note = Column(String(500), nullable=True)

    def __repr__(self):
        return f"<AuditLog {self.entity_type}:{self.entity_id} {self.action} @{self.created_at}>"
