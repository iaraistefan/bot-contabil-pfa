"""
SQLAlchemy ORM models for the PFA accounting bot.
Single source of truth for all DB tables.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime,
    Float, ForeignKey, Integer, JSON, String, Text,
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

    # === Profil firmă (NOI) ===
    firma_nume = Column(String(255), nullable=True)
    firma_cui = Column(String(20), nullable=True, index=True)
    firma_forma_juridica = Column(String(20), nullable=True)
    # Valori: PFA / II / IF / SRL_MICRO / SRL_NORMAL / PROFESIE_LIBERALA

    # === Regim fiscal (NOI) ===
    regim_tva = Column(String(20), nullable=True)
    # Valori: NEPLATITOR / PLATITOR_21 / SPECIAL_INTRACOM
    regim_impunere = Column(String(20), nullable=True)
    # Valori: SISTEM_REAL / NORMA_VENIT / MICRO_1 / MICRO_3

    # === Activitate (NOI) ===
    caen_principal = Column(String(10), nullable=True)
    activity_code = Column(String(50), nullable=True)
    # Valori: ridesharing / it_freelance / ecommerce / consulting /
    #         construction / medical / transport / real_estate / education / generic

    # === Locație (NOI) ===
    judet = Column(String(50), nullable=True)
    localitate = Column(String(100), nullable=True)

    # === Stare (NOI) ===
    data_inceput_activitate = Column(Date, nullable=True)
    onboarding_completed = Column(Boolean, nullable=False, default=False)
    onboarding_step = Column(Integer, nullable=False, default=0)
    # 0 = neînceput
    # 1 = primul nume colectat
    # 2 = formă juridică selectată
    # 3 = denumire firmă completată
    # 4 = CUI completat și validat
    # 5 = CAEN selectat
    # 6 = activitate aleasă
    # 7 = regim TVA confirmat
    # 8 = regim impunere confirmat
    # 9 = județ/localitate
    # 10 = data început
    # 99 = COMPLETED

    # === Contact (NOI, opțional) ===
    email = Column(String(150), nullable=True)
    telefon = Column(String(30), nullable=True)

    # === Relations (existente) ===
    documents = relationship("Document", back_populates="user")
    source_files = relationship("SourceFile", back_populates="user")
    transactions = relationship("Transaction", back_populates="user")
    tax_periods = relationship("TaxPeriod", back_populates="user")
    fiscal_alerts = relationship("FiscalAlert", back_populates="user")

    def __repr__(self):
        return f"<User id={self.id} telegram_id={self.telegram_id} firma={self.firma_nume!r}>"


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
        return f"<SourceFile id={self.id} sha={self.sha256[:8]}...>"


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    source_file_id = Column(Integer, ForeignKey("source_files.id"), nullable=True, index=True)
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
    status = Column(String(20), nullable=False, default="posted", index=True)
    prompt_version = Column(String(50), nullable=True)

    user = relationship("User", back_populates="documents")
    source_file = relationship("SourceFile", back_populates="documents")
    transactions = relationship("Transaction", back_populates="document")
    export_logs = relationship("ExportLog", back_populates="document")

    def __repr__(self):
        return f"<Document id={self.id} tip={self.tip} brut={self.brut} status={self.status}>"


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    tx_type = Column(String(20), nullable=False, index=True)
    category = Column(String(50), nullable=False, index=True)
    amount_brut = Column(Float, nullable=False, default=0.0)
    amount_vat = Column(Float, nullable=False, default=0.0)
    amount_net = Column(Float, nullable=False, default=0.0)
    currency = Column(String(5), nullable=False, default="RON")
    deductibility_pct = Column(Integer, nullable=False, default=100)
    payment_method = Column(String(20), nullable=True)
    counterparty = Column(String(200), nullable=True)
    vat_treatment = Column(String(30), nullable=True, default="NA")
    occurred_on = Column(Date, nullable=True, index=True)
    period_year = Column(Integer, nullable=True, index=True)
    period_month = Column(Integer, nullable=True, index=True)
    locked = Column(Boolean, nullable=False, default=False)
    posted_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="transactions")
    document = relationship("Document", back_populates="transactions")

    def __repr__(self):
        return f"<Transaction id={self.id} type={self.tx_type} amount={self.amount_brut}>"


class TaxPeriod(Base):
    __tablename__ = "tax_periods"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    computed_at = Column(DateTime, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    year = Column(Integer, nullable=False, index=True)
    month = Column(Integer, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="open")
    totals_json = Column(JSON, nullable=True)

    user = relationship("User", back_populates="tax_periods")

    def __repr__(self):
        return f"<TaxPeriod {self.year}/{self.month:02d} user={self.user_id}>"


class FiscalAlert(Base):
    __tablename__ = "fiscal_alerts"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    research_year = Column(Integer, nullable=False, index=True)
    research_month = Column(Integer, nullable=False, index=True)
    title = Column(String(300), nullable=False)
    summary = Column(Text, nullable=False)
    full_response = Column(Text, nullable=True)
    sources_json = Column(JSON, nullable=True)
    urgency = Column(String(20), nullable=False, default="info")
    has_changes = Column(Boolean, nullable=False, default=False)
    seen = Column(Boolean, nullable=False, default=False)

    user = relationship("User", back_populates="fiscal_alerts")

    def __repr__(self):
        return f"<FiscalAlert {self.research_year}/{self.research_month:02d} urgency={self.urgency}>"


class ExportLog(Base):
    __tablename__ = "export_logs"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    target = Column(String(30), nullable=False, index=True)
    entity_type = Column(String(30), nullable=False, default="document")
    entity_id = Column(Integer, nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True, index=True)
    external_ref = Column(String(500), nullable=True)
    status = Column(String(10), nullable=False, default="ok")
    response_msg = Column(Text, nullable=True)

    document = relationship("Document", back_populates="export_logs")

    def __repr__(self):
        return f"<ExportLog {self.target}:{self.entity_id} {self.status}>"


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
        return f"<AuditLog {self.entity_type}:{self.entity_id} {self.action}>"
