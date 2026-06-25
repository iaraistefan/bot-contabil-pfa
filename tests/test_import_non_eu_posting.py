"""
Efectul fiscal REAL al clasificării US/non-UE → IMPORT_NON_EU (increment fiscal).

Facturile de servicii din afara UE (US: OpenAI/AWS) sunt clasificate FACTURA_COMISION
→ `_post_factura_comision` creează VAT_OUT (taxare inversă, D301 datorat). Înainte de fix,
vat_engine returna UNKNOWN pentru US → VAT_OUT eticheta „UNKNOWN" + D301 nesemnalat.
După fix → vat_treatment „IMPORT_NON_EU" (D301 fără D390), pe VAT_OUT-ul creat.

Acoperire pe POSTING (nu doar clasificare): dovedim eticheta corectă pe tranzacția reală.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User, Document, Transaction
from app.services import posting

Y, M = 2026, 5
SUMA = 500.0   # factură SaaS US (ex. OpenAI), reverse-charge 21% → ~105 RON D301


def _setup(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    monkeypatch.setattr(posting.audit_repo, "write", lambda *a, **k: None)
    s = Session()
    # neplătitor cu cod special (art. 317) — cazul tipic: datorează D301, nu deduce
    u = User(telegram_id=777, activity_code="ridesharing", regim_tva="NEPLATITOR")
    s.add(u)
    s.commit()
    uid = u.id
    s.close()
    return Session, uid


def _post_us_saas(Session, uid):
    s = Session()
    d = Document(user_id=uid, tip="FACTURA_COMISION", status="posted", data_doc="05.05.2026")
    s.add(d)
    s.commit()
    posting.post_document(
        s, user_id=uid, document_id=d.id, tip="FACTURA_COMISION",
        platforma="OpenAI", detalii="OpenAI API subscription", brut=0.0, comision=SUMA,
        tva=0.0, net=0.0, cash=0.0, banca=0.0, data_doc="05.05.2026",
    )
    s.commit()
    s.close()


def test_us_saas_genereaza_vat_out_import_non_eu(tmp_path, monkeypatch):
    Session, uid = _setup(tmp_path, monkeypatch)
    _post_us_saas(Session, uid)

    s = Session()
    txs = s.query(Transaction).filter(Transaction.user_id == uid).all()
    vat_out = [t for t in txs if t.tx_type == "VAT_OUT"]
    s.close()

    # taxarea inversă (D301 datorat) se creează — efectul fiscal real
    assert len(vat_out) == 1
    # ...și e etichetată IMPORT_NON_EU (NU mai e „UNKNOWN") → D301 fără D390
    assert vat_out[0].vat_treatment == "IMPORT_NON_EU"
    assert vat_out[0].amount_vat > 0           # TVA reverse-charge calculat
