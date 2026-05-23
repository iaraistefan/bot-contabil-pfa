"""
SQLAlchemy ORM models for the PFA accounting bot.
Single source of truth for all DB tables.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime,
    Float, ForeignKey, Index, Integer, JSON, String, Text,
    UniqueConstraint,
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

    # === Profil firma ===
    firma_nume = Column(String(255), nullable=True)
    firma_cui = Column(String(20), nullable=True, index=True)
    firma_forma_juridica = Column(String(20), nullable=True)
    # Valori: PFA / II / IF / SRL_MICRO / SRL_NORMAL / PROFESIE_LIBERALA

    # === Regim fiscal ===
    regim_tva = Column(String(20), nullable=True)
    # Valori: NEPLATITOR / PLATITOR_21 / SPECIAL_INTRACOM
    regim_impunere = Column(String(20), nullable=True)
    # Valori: SISTEM_REAL / NORMA_VENIT / MICRO_1 / MICRO_3

    # === Activitate ===
    caen_principal = Column(String(10), nullable=True)
    activity_code = Column(String(50), nullable=True)

    # === Locatie ===
    judet = Column(String(50), nullable=True)
    localitate = Column(String(100), nullable=True)

    # === Stare ===
    data_inceput_activitate = Column(Date, nullable=True)
    onboarding_completed = Column(Boolean, nullable=False, default=False)
    onboarding_step = Column(Integer, nullable=False, default=0)

    # === Contact ===
    email = Column(String(150), nullable=True)
    telefon = Column(String(30), nullable=True)

    # === Pas 10.1 - Proactive alerts config ===
    proactive_alerts_enabled = Column(Boolean, nullable=False, default=True)
    proactive_alerts_hour = Column(Integer, nullable=False, default=8)
    proactive_alerts_advance_days = Column(Integer, nullable=False, default=7)

    # === Relations ===
    documents = relationship("Document", back_populates="user")
    source_files = relationship("SourceFile", back_populates="user")
    transactions = relationship("Transaction", back_populates="user")
    tax_periods = relationship("TaxPeriod", back_populates="user")
    fiscal_alerts = relationship("FiscalAlert", back_populates="user")
    fiscal_alerts_sent = relationship(
        "FiscalAlertSent", back_populates="user",
        cascade="all, delete-orphan",
    )
    # Pas 14 - Foaie de parcurs
    trip_logs = relationship(
        "TripLog", back_populates="user",
        cascade="all, delete-orphan",
    )
    # Pas A - Vehicule
    vehicule = relationship(
        "Vehicul", back_populates="user",
        cascade="all, delete-orphan",
    )

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
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
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

    # === VAT_ID al furnizorului (Pas 8.2) ===
    vat_id = Column(String(20), nullable=True, index=True)

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
    """Alerte legislative (modificari ANAF/MOf) - generate de AI fiscal_monitor."""
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


# ============================================================
# Pas 10.1 - FiscalAlertSent (Proactive Alerts anti-spam)
# ============================================================

class FiscalAlertSent(Base):
    """
    Pas 10.1 - Tracking pentru alerte proactive trimise (anti-spam).
    NU se confunda cu FiscalAlert (alerte legislative ANAF/MOf).
    """
    __tablename__ = "fiscal_alert_sent"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    obligation_code = Column(String(50), nullable=False)
    period_year = Column(Integer, nullable=False)
    period_month = Column(Integer, nullable=False)
    alert_type = Column(String(30), nullable=False)
    sent_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    status = Column(String(20), nullable=False, default="delivered")

    user = relationship("User", back_populates="fiscal_alerts_sent")

    __table_args__ = (
        UniqueConstraint(
            "user_id", "obligation_code", "period_year",
            "period_month", "alert_type",
            name="ix_fas_unique",
        ),
        Index("ix_fas_user_sent_at", "user_id", "sent_at"),
    )

    def __repr__(self):
        return (
            f"<FiscalAlertSent user={self.user_id} "
            f"{self.obligation_code} {self.period_year}/{self.period_month:02d} "
            f"type={self.alert_type}>"
        )


# ============================================================
# Pas A - Vehicul (masini PFA/SRL/II - flota)
# ============================================================

# Tipuri de detinere - relevante fiscal pentru deductibilitatea RCA/CASCO
TIP_DETINERE_PROPRIETATE = "PROPRIETATE"   # achizitionat pe firma
TIP_DETINERE_COMODAT = "COMODAT"           # masina personala in folosinta
TIP_DETINERE_LEASING = "LEASING"           # leasing financiar/operational
TIP_DETINERE_INCHIRIERE = "INCHIRIERE"     # inchiriat

TIP_DETINERE_LABELS = {
    TIP_DETINERE_PROPRIETATE: "Proprietatea firmei",
    TIP_DETINERE_COMODAT: "Comodat (masina personala)",
    TIP_DETINERE_LEASING: "Leasing",
    TIP_DETINERE_INCHIRIERE: "Inchiriere",
}


class Vehicul(Base):
    """
    Pas A - Vehicul folosit in activitate.

    Un PFA poate avea o singura masina (un titular). Un SRL sau I.I.
    poate avea mai multe (flota, mai multi soferi) - constrangerea se
    aplica la nivel de UI pe baza formei juridice.

    Campuri relevante fiscal:
      - norma_consum   : L/100km, folosita in foaia de parcurs
      - tip_detinere   : decide daca RCA/CASCO sunt deductibile:
                         PROPRIETATE/LEASING/INCHIRIERE -> da
                         COMODAT (masina personala)     -> nu (doar combustibil)
      - km_curent      : ultimul odometru cunoscut (sincronizat din foaia
                         de parcurs)
    """
    __tablename__ = "vehicule"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    nr_inmatriculare = Column(String(20), nullable=False)
    marca_model = Column(String(120), nullable=True)
    norma_consum = Column(Float, nullable=False, default=7.5)  # L/100km
    tip_detinere = Column(String(20), nullable=True)  # vezi TIP_DETINERE_*
    km_curent = Column(Integer, nullable=True)
    activ = Column(Boolean, nullable=False, default=True)  # soft-delete
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
        nullable=False,
    )

    user = relationship("User", back_populates="vehicule")
    trip_logs = relationship("TripLog", back_populates="vehicul")

    __table_args__ = (
        Index("ix_vehicule_user_activ", "user_id", "activ"),
    )

    def __repr__(self):
        return (
            f"<Vehicul id={self.id} {self.nr_inmatriculare} "
            f"{self.marca_model!r} activ={self.activ}>"
        )


# ============================================================
# Pas 14 + A - TripLog (Foaie de parcurs / jurnal km auto)
# ============================================================

# Status-uri tura
TRIP_STATUS_OPEN = "open"      # tura pornita (start dat, stop lipsa)
TRIP_STATUS_CLOSED = "closed"  # tura incheiata (start + stop)


class TripLog(Base):
    """
    Pas 14 + A - Foaie de parcurs: o intrare = o tura (zi de deplasare).

    Justifica deductibilitatea cheltuielilor auto (combustibil) prin
    documentarea km parcursi in interesul activitatii.

    WORKFLOW start/stop:
      1. `parcurs start 125430` -> creeaza rand status=open,
         odometer_start=125430
      2. `parcurs stop 125680`  -> completeaza odometer_end=125680,
         km=250, status=closed

    Campuri:
      - vehicul_id     : masina folosita (Pas A)
      - trip_date      : ziua deplasarii
      - km             : km parcursi in interes business (= end - start)
      - odometer_start : citire bord la inceputul turei
      - odometer_end   : citire bord la sfarsitul turei
      - status         : open / closed (vezi TRIP_STATUS_*)
      - ora_start      : ora pornirii turei, format "HH:MM"
      - ora_stop       : ora incheierii turei, format "HH:MM"
      - purpose        : scop/traseu (ex: "curse Bolt Bistrita")
      - period_*       : derivate din trip_date pentru raportare rapida
    """
    __tablename__ = "trip_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Pas A - legatura cu masina
    vehicul_id = Column(
        Integer, ForeignKey("vehicule.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    trip_date = Column(Date, nullable=False, index=True)
    km = Column(Float, nullable=False, default=0.0)
    odometer_start = Column(Integer, nullable=True)
    odometer_end = Column(Integer, nullable=True)
    # Pas A - workflow start/stop
    status = Column(String(20), nullable=False, default=TRIP_STATUS_CLOSED)
    ora_start = Column(String(5), nullable=True)   # "08:30"
    ora_stop = Column(String(5), nullable=True)    # "17:45"
    purpose = Column(String(255), nullable=True)
    period_year = Column(Integer, nullable=False, index=True)
    period_month = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User", back_populates="trip_logs")
    vehicul = relationship("Vehicul", back_populates="trip_logs")

    __table_args__ = (
        Index("ix_trip_logs_user_period", "user_id", "period_year", "period_month"),
    )

    def __repr__(self):
        return (
            f"<TripLog user={self.user_id} {self.trip_date} "
            f"km={self.km} status={self.status} purpose={self.purpose!r}>"
        )
