"""
Tripwire-ul declanșatorului: sună când o factură de comision nu mai respectă tiparul
pe care se sprijină luna în care semnalăm D100/D301/D390.

CONTEXT (detaliat în app/domain/declansator_termen.py): luna alertei se ia din data
facturii, dar legea leagă D100 de plata venitului (art. 224 alin. 5) și D301/D390 de
exigibilitate (art. 324 alin. 2). Coincid pe două verigi: mecanismul de reținere a
comisionului din curse (tare — plata cade obligatoriu în luna acoperită) plus datarea
facturii în ultima zi a perioadei (slabă — doar ea ne lasă să echivalăm luna datei cu
perioada acoperită, fiindcă perioada, deși tipărită pe factură, nu e captată).
Tripwire-ul păzește veriga slabă. Măsurat pe 5 facturi reale (dec. 2025 – apr. 2026),
5/5, iar tiparul e confirmat pe factura tipărită Bolt RO1126-158556.

Testele acoperă DOUĂ straturi:
  • predicatul pur — inclusiv februarie bisect/nebisect, unde un tabel scris de mână
    ar greși;
  • efectul real pe postare — urma ajunge în audit_logs, iar tranzacțiile se creează
    identic (tripwire-ul nu blochează nimic).
"""

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain import declansator_termen as dt
from app.models import Document, Transaction, User
from app.services import posting

COMISION = 657.22   # suma facturii Bolt ianuarie 2026, din producție


# ============================================================
#   1. PREDICATUL PUR
# ============================================================

def test_ultima_zi_a_lunii_pe_lunile_reale_masurate():
    """Cele 5 date din producție — toate sunt ultima zi, tripwire-ul TACE."""
    for d in (date(2025, 12, 31), date(2026, 1, 31), date(2026, 2, 28),
              date(2026, 3, 31), date(2026, 4, 30)):
        assert dt.este_ultima_zi_a_lunii(d), d
        assert dt.verifica_factura_comision(d) is None, d


def test_februarie_bisect_si_nebisect():
    """
    Capcana care ar prinde un tabel de zile scris de mână: 28 februarie e ultima zi
    în 2026 (nebisect), dar NU în 2024 (bisect, ultima e 29).
    """
    assert dt.este_ultima_zi_a_lunii(date(2026, 2, 28))
    assert dt.verifica_factura_comision(date(2026, 2, 28)) is None

    assert not dt.este_ultima_zi_a_lunii(date(2024, 2, 28))
    ab = dt.verifica_factura_comision(date(2024, 2, 28))
    assert ab is not None
    assert ab.ultima_zi_a_lunii == 29

    assert dt.este_ultima_zi_a_lunii(date(2024, 2, 29))
    assert dt.verifica_factura_comision(date(2024, 2, 29)) is None


def test_data_in_interiorul_lunii_declanseaza():
    """Factura emisă la mijlocul lunii — coincidența nu mai e garantată."""
    ab = dt.verifica_factura_comision(date(2026, 1, 15))
    assert ab is not None
    assert ab.motiv == dt.MOTIV_NU_E_ULTIMA_ZI
    assert ab.data_factura == date(2026, 1, 15)
    assert ab.ultima_zi_a_lunii == 31
    # nota trebuie să spună de ce contează, nu doar CE s-a întâmplat
    assert "224" in ab.nota and "324" in ab.nota


def test_factura_in_luna_urmatoare_celei_acoperite_declanseaza():
    """
    Scenariul de ÎNTÂRZIERE: Bolt (sau Uber) emite pe 03.02 pentru ianuarie →
    period devine februarie → D100 semnalat pe 25 martie, dar venitul s-a plătit în
    ianuarie, deci termenul legal era 25 februarie.
    """
    ab = dt.verifica_factura_comision(date(2026, 2, 3))
    assert ab is not None
    assert ab.motiv == dt.MOTIV_NU_E_ULTIMA_ZI


def test_data_lipsa_declanseaza_cu_motiv_propriu():
    """Fără dată, period rămâne NULL → obligația nu apare în NICIO lună."""
    ab = dt.verifica_factura_comision(None)
    assert ab is not None
    assert ab.motiv == dt.MOTIV_DATA_LIPSA
    assert ab.data_factura is None
    assert ab.ultima_zi_a_lunii is None


def test_ultima_zi_pe_toate_lunile_unui_an():
    """Invariant: exact o zi pe lună trece, și e cea din monthrange."""
    import calendar
    for luna in range(1, 13):
        ultima = calendar.monthrange(2026, luna)[1]
        treceri = [z for z in range(1, ultima + 1)
                   if dt.verifica_factura_comision(date(2026, luna, z)) is None]
        assert treceri == [ultima], (luna, treceri)


# ============================================================
#   2. EFECTUL REAL PE POSTARE
# ============================================================

def _setup(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    s = Session()
    # neplătitor cu cod special (art. 317) — cazul real al userului măsurat
    u = User(telegram_id=4242, activity_code="ridesharing", regim_tva="NEPLATITOR")
    s.add(u)
    s.commit()
    uid = u.id
    s.close()
    return Session, uid


def _posteaza_factura(Session, uid, data_doc):
    s = Session()
    d = Document(user_id=uid, tip="FACTURA_COMISION", status="posted", data_doc=data_doc)
    s.add(d)
    s.commit()
    doc_id = d.id
    posting.post_document(
        s, user_id=uid, document_id=doc_id, tip="FACTURA_COMISION",
        platforma="Bolt Operations OÜ", detalii="Comision Bolt ianuarie 2026",
        brut=COMISION, comision=COMISION, tva=0.0, net=COMISION,
        cash=0.0, banca=0.0, data_doc=data_doc,
    )
    s.commit()
    s.close()
    return doc_id


def _spion_audit(monkeypatch):
    """
    Prinde apelurile de audit în loc să le lase să scrie.

    DE CE spion și nu citire din audit_logs: `AuditLog.id` e `BigInteger` primary key,
    iar SQLite autoincrementează DOAR `INTEGER PRIMARY KEY` → orice scriere reală de
    audit pică pe „NOT NULL constraint failed: audit_logs.id" în suită (motivul pentru
    care și testele de posting existente îl monkeypatchează). Artefact de mediu de test,
    nu de producție (Postgres are bigserial). Verificăm deci APELUL nostru — partea pe
    care o controlăm — iar faptul că un audit rupt nu strică postarea îl dovedește
    `test_urma_care_crapa_la_flush_nu_pierde_factura`, pe modul real de eșec (crapă la flush).
    """
    apeluri = []

    def _capture(session, **kw):
        apeluri.append(kw)

    monkeypatch.setattr(posting.audit_repo, "write", _capture)
    return apeluri


def _urme(apeluri):
    return [a for a in apeluri if a.get("action") == dt.ACTIUNE_AUDIT]


def test_factura_pe_ultima_zi_nu_lasa_urma(tmp_path, monkeypatch):
    """Tiparul respectat → tăcere. Altfel tripwire-ul ar fi zgomot de fond."""
    apeluri = _spion_audit(monkeypatch)
    Session, uid = _setup(tmp_path)
    _posteaza_factura(Session, uid, "31.01.2026")
    assert _urme(apeluri) == []


def test_factura_atipica_lasa_urma_in_audit(tmp_path, monkeypatch):
    """Abaterea ajunge în audit_logs, interogabilă peste luni după `action`."""
    apeluri = _spion_audit(monkeypatch)
    Session, uid = _setup(tmp_path)
    doc_id = _posteaza_factura(Session, uid, "03.02.2026")

    urme = _urme(apeluri)
    assert len(urme) == 1
    u = urme[0]
    assert u["entity_type"] == "document"
    assert u["entity_id"] == doc_id
    assert u["user_id"] == uid
    assert "03.02.2026" in u["note"]
    assert u["after"]["motiv"] == dt.MOTIV_NU_E_ULTIMA_ZI
    assert u["after"]["data_factura"] == "2026-02-03"
    assert u["after"]["ultima_zi_a_lunii"] == 28


def test_tripwire_nu_blocheaza_postarea(tmp_path, monkeypatch):
    """
    Cel mai important test: o factură atipică se postează IDENTIC. Tripwire-ul
    observă, nu intervine — nici perioada nu se mută.
    """
    _spion_audit(monkeypatch)
    Session, uid = _setup(tmp_path)
    _posteaza_factura(Session, uid, "03.02.2026")

    s = Session()
    txs = s.query(Transaction).filter(Transaction.user_id == uid).all()
    vat_out = [t for t in txs if t.tx_type == "VAT_OUT"]
    s.close()

    assert len(vat_out) == 1                      # taxarea inversă s-a creat
    assert vat_out[0].amount_vat > 0
    # perioada rămâne CEA DERIVATĂ DIN FACTURĂ — tripwire-ul nu corectează nimic
    assert (vat_out[0].period_year, vat_out[0].period_month) == (2026, 2)
    assert vat_out[0].occurred_on == date(2026, 2, 3)


def test_urma_care_crapa_la_flush_nu_pierde_factura(tmp_path, monkeypatch):
    """
    REGRESIA care a prins prima versiune a tripwire-ului — cel mai important test
    despre modul de eșec.

    `audit_repo.write` face doar `session.add()`, fără flush. Un rând de audit invalid
    NU crapă deci la apel, ci mai TÂRZIU, la primul autoflush, în mijlocul postării —
    și otrăvește toată tranzacția. Prima versiune avea doar try/except în jurul
    apelului: confort fals, factura se pierdea. Fixul e SAVEPOINT + flush pe loc, în
    `_tripwire_declansator`.

    Reproducem exact acel mod de eșec: urma adaugă un rând care trece la `add()` și
    cade la `flush()` (entity_type e NOT NULL). Celelalte audit-uri devin no-op,
    fiindcă scrierea reală pică oricum pe SQLite (vezi `_spion_audit`) — vrem să
    izolăm DOAR calea tripwire-ului. Scoate `begin_nested` și testul ăsta cade.
    """
    from app.models import AuditLog

    Session, uid = _setup(tmp_path)

    def _urma_invalida(session, **kw):
        if kw.get("action") != dt.ACTIUNE_AUDIT:
            return
        session.add(AuditLog(entity_type=None, entity_id=1, action="INVALID"))

    monkeypatch.setattr(posting.audit_repo, "write", _urma_invalida)
    _posteaza_factura(Session, uid, "03.02.2026")

    s = Session()
    vat_out = (
        s.query(Transaction)
        .filter(Transaction.user_id == uid, Transaction.tx_type == "VAT_OUT")
        .all()
    )
    s.close()
    assert len(vat_out) == 1        # factura s-a postat, deși urma s-a pierdut


def test_exceptie_in_tripwire_nu_pierde_factura(tmp_path, monkeypatch):
    """A doua cale de eșec: audit_repo aruncă direct, nu la flush."""
    Session, uid = _setup(tmp_path)

    def _explodeaza(*a, **k):
        raise RuntimeError("audit indisponibil")

    monkeypatch.setattr(posting.audit_repo, "write", _explodeaza)
    _posteaza_factura(Session, uid, "03.02.2026")

    s = Session()
    vat_out = (
        s.query(Transaction)
        .filter(Transaction.user_id == uid, Transaction.tx_type == "VAT_OUT")
        .all()
    )
    s.close()
    assert len(vat_out) == 1
