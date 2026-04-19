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

    def __repr__(self):
        return f"<SourceFile id={self.id} sha={self.sha256[:8]}... user_id={self.user_id}>"


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    data_doc = Column(String(20), index=True)
    platforma = Column(String(50), index=True)
    tip = Column(String(30), index=True)

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

    user = relationship("User", back_populates="documents")


class AuditLog(Base):
    """
    Log imuabil al fiecărei modificări semnificative în DB.
    Nu există UPDATE — doar INSERT. Întrebarea "ce s-a întâmplat?" se răspunde
    cu SELECT pe coloanele entity_type + entity_id.
    """
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    entity_type = Column(String(50), nullable=False, index=True)    # 'user' / 'source_file' / 'document'
    entity_id = Column(Integer, nullable=False, index=True)
    action = Column(String(50), nullable=False)                     # 'create' / 'dedup_hit' / 'update' / 'delete' / 'error'
    source = Column(String(20), nullable=False, default="system")   # 'user' / 'ai' / 'system'

    before_json = Column(JSON, nullable=True)
    after_json = Column(JSON, nullable=True)
    note = Column(String(500), nullable=True)

    def __repr__(self):
        return f"<AuditLog {self.entity_type}:{self.entity_id} {self.action} @{self.created_at}>"
