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

    # === Coduri fiscale suplimentare (Faza 1 - declaratii) ===
    # Cod special TVA art. 317 - pentru D301 / D390 (operatiuni intracom).
    # La unii PFA difera de CUI-ul normal (ex: CUI 53067338, special 53148882).
    cod_special_tva = Column(String(20), nullable=True)
    # CNP titular - pentru Declaratia Unica D212 (venit personal). Dato sensibila.
    cnp = Column(String(13), nullable=True)

    # === Regim fiscal ===
    regim_tva = Column(String(20), nullable=True)
    # Valori: NEPLATITOR / PLATITOR_21 / SPECIAL_INTRACOM
    regim_impunere = Column(String(20), nullable=True)
    # Valori: SISTEM_REAL / NORMA_VENIT / MICRO_1 / MICRO_3
    # [DEPRECAT — vezi regim_nerezident_bolt] Pastrat ca fallback de recuperare
    # (NU sters): captarea Bolt din #3 a scris aici; backfill non-distructiv in _bolt.
    regim_nerezident = Column(String(20), nullable=True)
    # Regim impozit nerezident PER-PLATFORMA (suport Uber). enum RegimNerezident:
    # _bolt: BOLT_CU_CRF (2%) / BOLT_FARA_CRF (16%); _uber: UBER_CU_CRF (0%) /
    # UBER_FARA_CRF (16%). NULL = neconfigurat (NU presupunem cota, vezi #3).
    regim_nerezident_bolt = Column(String(20), nullable=True)
    regim_nerezident_uber = Column(String(20), nullable=True)

    # === Activitate ===
    caen_principal = Column(String(10), nullable=True)
    activity_code = Column(String(50), nullable=True)

    # === Locatie ===
    judet = Column(String(50), nullable=True)
    localitate = Column(String(100), nullable=True)
    # Adresa de facturare (§1.7 Felia 3): factura fiscala cere strada + nr, nu doar
    # judet/localitate. Se completeaza din datele de facturare colectate de Stripe la
    # checkout, DOAR daca lipsesc (ce a scris userul in onboarding are prioritate).
    adresa_strada = Column(String(255), nullable=True)
    cod_postal = Column(String(20), nullable=True)
    # Norma anuala de venit (lei) pentru PFA pe NORMA_VENIT — valoarea din decizia
    # AJFP a judetului (OMF 1960/2025), dupa judet + tip localitate. NULL = necompletat
    # (impozitul pe norma nu se poate calcula -> prompt, NU presupunem o cifra).
    norma_venit_anuala = Column(Float, nullable=True)
    # Cazuri-limita CAS/CASS (PAS 2). NULL/False = caz standard (regresie 0).
    # is_pensionar: scutit de CAS pe PFA (art. 150) + CASS pe net real sub prag.
    #   Art. 174 alin. (7) lit. c): pensiile NU au prag — orice pensie califica.
    # is_salariat: are salarii de CEL PUTIN 6 salarii minime pe an (art. 174 alin.
    #   (7) lit. a)) -> deja asigurat la nivelul cerut de lege -> CASS pe net real
    #   sub prag, fara podea. ⚠️ NU inseamna „angajat" pur si simplu: part-time sau
    #   angajare partiala de an pot fi SUB prag, si atunci podeaua SE aplica.
    #   (CAS pe PFA ramane prag-based pe net PFA, neafectat.)
    is_pensionar = Column(Boolean, nullable=True)
    is_salariat = Column(Boolean, nullable=True)
    # Casă de marcat (PAS 3): userul a DECLARAT că încasează numerar de la pasageri.
    # Semnalul „ai nevoie de AMEF" = declarat SAU income_cash>0 (date reale au prioritate).
    # NULL/False = nedeclarat (semnalul se poate aprinde din date oricum).
    incaseaza_numerar = Column(Boolean, nullable=True)

    # === Stare ===
    data_inceput_activitate = Column(Date, nullable=True)
    # Proportionalizare mid-an (PAS 4a): incetarea activitatii in cursul anului.
    # La INCEPERE mid-an plafonul CAS se recalculeaza proportional (12 SMB × luni/12);
    # la INCETARE doar semnalam (zona legal ambigua). NULL = activitate pe tot anul
    # (regresie 0). Norma se prorata pe zilele de activitate in ambele cazuri.
    data_sfarsit_activitate = Column(Date, nullable=True)
    # Activitate mixta (PAS 4b, OPANAF D212 pct. 3.5.11): userul pe NORMA a adaugat in
    # cursul anului o activitate NEeligibila pentru norma -> sistem real DE LA DATA
    # adaugarii. Venit net anual = fractiune norma (pana la data) + venit real (dupa).
    # NULL/False = fara activitate mixta (regresie 0).
    are_activitate_neeligibila_norma = Column(Boolean, nullable=True)
    data_activitate_neeligibila = Column(Date, nullable=True)
    onboarding_completed = Column(Boolean, nullable=False, default=False)
    onboarding_step = Column(Integer, nullable=False, default=0)

    # === Contact ===
    email = Column(String(150), nullable=True)
    telefon = Column(String(30), nullable=True)

    # === Date bancare (pentru D301 - banca + IBAN obligatorii in formular) ===
    banca = Column(String(120), nullable=True)
    iban = Column(String(34), nullable=True)

    # === Pas 10.1 - Proactive alerts config ===
    proactive_alerts_enabled = Column(Boolean, nullable=False, default=True)
    proactive_alerts_hour = Column(Integer, nullable=False, default=8)
    proactive_alerts_advance_days = Column(Integer, nullable=False, default=7)

    # === Bolt Fleet API per-user (#2-A) — credențiale proprii pentru sync auto ===
    # client_id în CLAR (identificator OAuth, inutil singur); client_secret CRIPTAT
    # (token Fernet, NICIODATĂ în clar — vezi app.domain.crypto). NULL = neconectat
    # (comportament neschimbat; sync-ul API rămâne owner-only prin env). Setate în #2-B.
    bolt_client_id = Column(String(255), nullable=True)
    bolt_client_secret_enc = Column(String(500), nullable=True)
    bolt_connected_at = Column(DateTime, nullable=True)

    # Abonament SaaS Stripe (Felia 1 — fundatia de DATE, fara Stripe API real inca).
    # ID-uri Stripe publice pt cont (NU secrete → fara _enc, spre deosebire de Bolt).
    # NULL = neabonat (comportament neschimbat; nimeni nu le citeste inca — gating = Felia 4).
    stripe_customer_id = Column(String(255), nullable=True)
    stripe_subscription_id = Column(String(255), nullable=True)
    stripe_status = Column(String(50), nullable=True)   # active / canceled / past_due / None
    stripe_tier = Column(String(50), nullable=True)     # START / PRO / MAX; None = neabonat
    # Reverse trial (§1.8): 30 zile PRO complet la onboarding, fara card → apoi FREE.
    # NULL = fara trial (userii vechi / neonboardati). trial_ends_at > acum = in trial.
    trial_ends_at = Column(DateTime, nullable=True)

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
    monthly_summaries_sent = relationship(
        "SummarySent", back_populates="user",
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

    # === Pas R1.2 - numarul documentului (serie + nr) ===
    numar_document = Column(String(80), nullable=True, index=True)

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

    # === Felia 3 (import extras) — anti-dublură la nivel de tranzacție bancară ===
    # Amprentă stabilă a liniei de extras (occurred_on+amount+directie+descriere
    # normalizată+ocurență). NULL pentru tranzacțiile non-import (foto/Bolt/manual).
    import_fingerprint = Column(String(64), nullable=True, index=True)

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
# Faza 3 - SummarySent (sumar lunar automat - anti-dublura)
# ============================================================

class SummarySent(Base):
    """
    Tracking pentru sumarul lunar automat trimis pe Telegram (anti-dublura).
    period_year/period_month = luna INCHEIATA pentru care s-a trimis sumarul.
    Un singur sumar per user per luna (unicitate la nivel DB).
    """
    __tablename__ = "summary_sent"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    period_year = Column(Integer, nullable=False)
    period_month = Column(Integer, nullable=False)
    sent_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User", back_populates="monthly_summaries_sent")

    __table_args__ = (
        UniqueConstraint(
            "user_id", "period_year", "period_month",
            name="ix_summary_sent_unique",
        ),
    )

    def __repr__(self):
        return (
            f"<SummarySent user={self.user_id} "
            f"{self.period_year}/{self.period_month:02d}>"
        )


# ============================================================
# Felia 5 - ObligationPayment (plati de obligatii detectate din extras)
# ============================================================

class ObligationPayment(Base):
    """
    Plata unei obligatii fiscale, detectata din extras bancar (felia 5).

    Stocheaza DOAR faptul platii — obligatia ramane EFEMERA (calculata on-the-fly
    in fiscal_calendar). Prezenta unui rand pentru (user, cod, an, luna) = obligatia
    e achitata; lipsa = neachitata. Sursa unica de adevar a obligatiei NU se dubleaza.

    Anti-dublura pe import_fingerprint (re-import acelasi extras = skip). Plati
    MULTIPLE distincte pe aceeasi obligatie (transe/corectii) sunt permise — cheia
    e amprenta liniei bancare, NU (cod, perioada).

    perioada_luna: 1-12 lunar (D301/D100); 0 = anual (sentinel, ex. D212).
    Fara FK la Transaction: plata de taxa NU se posteaza ca tranzactie (felia 3 o
    exclude). Dovada = import_fingerprint + source_file_id + suma + data.
    """
    __tablename__ = "obligation_payments"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    obligation_code = Column(String(20), nullable=False)   # "D301"/"D100" (forma scurta)
    perioada_an = Column(Integer, nullable=False)
    perioada_luna = Column(Integer, nullable=False, default=0)  # 0 = anual (sentinel)
    suma_platita = Column(Float, nullable=False)           # suma reala din extras (Float, ca tot sistemul)
    data_platii = Column(Date, nullable=False)
    sursa = Column(String(20), nullable=False, default="bank_import")
    import_fingerprint = Column(String(64), nullable=False)
    source_file_id = Column(
        Integer, ForeignKey("source_files.id"), nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "import_fingerprint",
            name="ix_oblig_pay_fingerprint",
        ),
        Index(
            "ix_oblig_pay_lookup",
            "user_id", "obligation_code", "perioada_an", "perioada_luna",
        ),
    )

    def __repr__(self):
        return (
            f"<ObligationPayment user={self.user_id} {self.obligation_code} "
            f"{self.perioada_an}/{self.perioada_luna:02d} suma={self.suma_platita}>"
        )


# ============================================================
# Pas A - Vehicul (masini PFA/SRL/II - flota)
# ============================================================

TIP_DETINERE_PROPRIETATE = "PROPRIETATE"
TIP_DETINERE_COMODAT = "COMODAT"
TIP_DETINERE_LEASING = "LEASING"
TIP_DETINERE_INCHIRIERE = "INCHIRIERE"

TIP_DETINERE_LABELS = {
    TIP_DETINERE_PROPRIETATE: "Proprietatea firmei",
    TIP_DETINERE_COMODAT: "Comodat (masina personala)",
    TIP_DETINERE_LEASING: "Leasing",
    TIP_DETINERE_INCHIRIERE: "Inchiriere",
}

# Regim de utilizare al vehiculului (deductibilitate auto — vezi Vehicul.regim_utilizare
# + posting._resolve_auto_deductibility). ⚠️ Valorile trebuie EXACT "MIXT"/"EXCLUSIV"
# (posting.py le compară literal).
REGIM_UTILIZARE_MIXT = "MIXT"
REGIM_UTILIZARE_EXCLUSIV = "EXCLUSIV"

REGIM_UTILIZARE_LABELS = {
    REGIM_UTILIZARE_MIXT: "🚗 Și personal, și pentru curse",
    REGIM_UTILIZARE_EXCLUSIV: "🎯 Doar pentru curse",
}


class Vehicul(Base):
    """Pas A - Vehicul folosit in activitate."""
    __tablename__ = "vehicule"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    nr_inmatriculare = Column(String(20), nullable=False)
    marca_model = Column(String(120), nullable=True)
    norma_consum = Column(Float, nullable=False, default=7.5)
    tip_detinere = Column(String(20), nullable=True)
    # Regim de utilizare al vehiculului pt deductibilitate auto (art. 25 alin.
    # (3) lit. l)): MIXT = personal+business → 50% · EXCLUSIV = doar business
    # justificat prin foaie de parcurs → 100%. Default MIXT = comportamentul
    # actual (toate mașinile 50%). ⚠️ Momentan NIMENI nu-l citește (pur aditiv);
    # deductibilitatea rămâne 50% până la felia care activează regimul (după CECCAR).
    regim_utilizare = Column(String(20), nullable=False, default="MIXT")
    km_curent = Column(Integer, nullable=True)
    activ = Column(Boolean, nullable=False, default=True)
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

TRIP_STATUS_OPEN = "open"
TRIP_STATUS_CLOSED = "closed"


class TripLog(Base):
    """Pas 14 + A - Foaie de parcurs: o intrare = o tura (zi de deplasare)."""
    __tablename__ = "trip_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    vehicul_id = Column(
        Integer, ForeignKey("vehicule.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    trip_date = Column(Date, nullable=False, index=True)
    km = Column(Float, nullable=False, default=0.0)
    odometer_start = Column(Integer, nullable=True)
    odometer_end = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default=TRIP_STATUS_CLOSED)
    ora_start = Column(String(5), nullable=True)
    ora_stop = Column(String(5), nullable=True)
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


# ══════════════════════════════════════════════════════════════
# Facturare abonament (§1.7 Felia 3, Brick 3a)
# ══════════════════════════════════════════════════════════════

FACTURA_PENDING = "pending"
FACTURA_EMISA = "emisa"
FACTURA_EROARE = "eroare"


class FacturaAbonament(Base):
    """
    Factura fiscala pentru o plata de abonament Stripe (Felia 3).

    DE CE EXISTA: niciun procesator de plati nu emite factura fiscala (§1.7↔§1.3).
    Dupa incasare generam factura la Oblio, care o trimite in SPV (e-Factura B2C
    obligatorie din 1 ian 2025). Tabelul tine EVIDENTA acestei traduceri
    plata Stripe → document fiscal.

    ANTI-DUBLURA: stripe_invoice_id e UNIQUE. Webhook-urile Stripe se pot livra de
    mai multe ori (retry, duplicate) — fara constrangerea asta, o singura plata ar
    putea produce doua facturi fiscale, ceea ce e o problema REALA la ANAF, nu doar
    o inconsecventa de date. Baza refuza dublura; codul nu trebuie sa fie perfect.

    STATUS: pending (de emis) → emisa (avem serie+numar de la Oblio) sau eroare
    (cu eroare_text pentru diagnostic + reluare). Un rand `pending` ramas in urma =
    o factura de reluat, nu o plata pierduta: activarea abonamentului (2c) NU depinde
    de emiterea facturii.

    Brick 3a = doar tabelul (fundatia). Scrierea randurilor + apelul Oblio = 3b.
    """
    __tablename__ = "factura_abonament"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # RESTRICT, nu CASCADE (spre deosebire de restul tabelelor per-user): factura
    # emisa e DOCUMENT FISCAL, cu arhivare obligatorie 10 ani. Nu are voie sa dispara
    # odata cu userul. Stergerea unui user cu facturi ESUEAZA — deliberat: cine sterge
    # trebuie sa se ocupe intai de documente, nu sa le piarda tacut.
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )

    # Id-ul facturii DIN STRIPE — cheia idempotentei (o plata = o factura fiscala).
    stripe_invoice_id = Column(String(255), nullable=False, unique=True)

    # Ce ne intoarce Oblio dupa emitere. NULL cat timp status='pending'.
    oblio_serie = Column(String(20), nullable=True)
    oblio_numar = Column(String(20), nullable=True)     # string: Oblio poate da "0001"
    oblio_invoice_id = Column(String(100), nullable=True)

    status = Column(String(20), nullable=False, default=FACTURA_PENDING)
    eroare_text = Column(Text, nullable=True)           # doar pt diagnostic/reluare
    emisa_at = Column(DateTime, nullable=True)

    user = relationship("User")

    __table_args__ = (
        Index("ix_factura_abonament_user_status", "user_id", "status"),
    )

    def __repr__(self):
        return (
            f"<FacturaAbonament user={self.user_id} {self.status} "
            f"stripe={self.stripe_invoice_id} oblio={self.oblio_serie}{self.oblio_numar}>"
        )


# Tipurile arhivate. D700 NU intra: e cerere de inregistrare prin SPV (ghid text,
# fara XML si fara perioada), nu declaratie.
DECL_TIPURI_ARHIVATE = ("D100", "D301", "D390", "D207", "D212")


class DeclaratieGenerata(Base):
    """
    ARHIVA declaratiilor generate — inputurile SI rezultatul, la momentul generarii.

    DE CE (blocantul F1): pana acum nu se persista nimic. Generatoarele din
    app/integrations/anaf/ sunt pure, XML-ul pleca prin BytesIO si disparea. NU e
    gaura de conformitate (copia autoritativa e in SPV), ci de REPRODUCTIBILITATE:
    recalcularea unui an trecut citea TACIT profilul de azi, deci putea da alt numar
    decat s-a depus, iar noi nu puteam distinge „motorul era gresit atunci" de
    „userul a raspuns altfel atunci".

    IMUTABIL: append-only, fara cale de update. O declaratie generata e FAPT ISTORIC.
    Repository-ul expune doar create + citiri.

    FARA constrangere de unicitate pe (user, tip, perioada, d_rec) — DELIBERAT.
    Doua generari ale aceleiasi perioade sunt doua evenimente reale; unicitatea ar
    transforma o arhiva append-only intr-un tabel de stare.
    """
    __tablename__ = "declaratii_generate"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # RESTRICT, nu CASCADE (ca la factura_abonament): arhiva fiscala nu are voie sa
    # dispara odata cu userul. Stergerea unui user cu declaratii ESUEAZA — deliberat.
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )

    tip = Column(String(10), nullable=False, index=True)   # vezi DECL_TIPURI_ARHIVATE
    an = Column(Integer, nullable=False, index=True)
    # NULL pentru anuale (D207, D212) — n-au luna.
    luna = Column(Integer, nullable=True)
    # 0 = initiala, 1 = rectificativa. Azi mereu 0 (niciun call-site nu-l seteaza),
    # dar coloana exista ca prima rectificativa sa nu ceara migrare.
    d_rec = Column(Integer, nullable=False, default=0)

    # Inputurile, ca JSON — conventia casei (totals_json, sources_json, before/after_json).
    # Serializare pe LISTA EXPLICITA de campuri (declaratii_arhiva._CAMPURI_*), NU dump
    # de obiect: `firma` si `profile` sunt obiecte, iar un dump ar lega arhiva de forma
    # lor interna. Un gardian cade daca semnatura unui generator capata un parametru
    # necunoscut arhivei.
    inputuri_json = Column(JSON, nullable=True)
    # Rezultatul: sume, avertismente[], ghid_plain. Ghidul e „de ce"-ul deja compus —
    # materia prima pentru „Audit Trail" (I1).
    rezultat_json = Column(JSON, nullable=True)

    # XML-ul generat. NULL la D212 (calcul + ghid, fara fisier) si la generarile
    # esuate. Masurat: 629-1083 octeti pe perioada tipica -> inline, fara storage extern.
    xml = Column(Text, nullable=True)
    nume_fisier_xml = Column(String(120), nullable=True)

    # Se arhiveaza SI esecurile: „am incercat si n-a iesit" e informatie fiscala
    # (ex. D100 la cota 0 = scutit, sau profil neconfigurat).
    generat = Column(Boolean, nullable=False, default=True)
    motiv_negenerat = Column(String(50), nullable=True)

    user = relationship("User")

    __table_args__ = (
        Index("ix_declaratii_generate_user_tip_an", "user_id", "tip", "an"),
    )

    def __repr__(self):
        per = f"{self.an}" + (f"/{self.luna:02d}" if self.luna else "")
        return (
            f"<DeclaratieGenerata {self.tip} {per} user={self.user_id} "
            f"d_rec={self.d_rec} generat={self.generat}>"
        )
