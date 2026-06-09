"""
Teste PAS 1 felia 4 — reconciliere de prezență venit Bolt.

- detecție luni Bolt din clasificare (fixture real → aprilie 2026)
- has_bolt_income True/False pe DB
- nudge text când lună nesincronizată / None când tot sincronizat (tăcere)
- REGRESIE: _remove_existing_bolt_income neschimbat funcțional după refactor
  (sursă unică de filtru — atinge producția Bolt sync)
"""
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.integrations.imports.bank_statement import BankTxn
from app.integrations.imports.bt_parser import parse_bt_pdf
from app.integrations.imports.classify import (
    classify_bt, BankTxnClasificat, VENIT_BOLT, CHELTUIALA_BUSINESS,
)
from app.integrations.imports import bolt_reconcile
from app.integrations import bolt_sync
from app.activities.ridesharing import RidesharingActivity as ACT
from app.models import User, Document, Transaction

_FIXTURE = Path(__file__).parent / "fixtures" / "extras_bt_anon.pdf"


def _setup(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    s = Session()
    u = User(telegram_id=1, activity_code="ridesharing")
    s.add(u)
    s.commit()
    uid = u.id
    s.close()
    return Session, uid


def _add_bolt_income(Session, uid, data_doc="30.04.2026"):
    """Creează un Document VENIT Bolt + o tranzacție (ca sync-ul)."""
    s = Session()
    doc = Document(user_id=uid, tip="VENIT", platforma="Bolt",
                   data_doc=data_doc, status="posted")
    s.add(doc)
    s.commit()
    tx = Transaction(user_id=uid, document_id=doc.id, tx_type="INCOME",
                     category="ride_revenue", amount_brut=1000.0)
    s.add(tx)
    s.commit()
    did = doc.id
    s.close()
    return did


def _cl_bolt(suma, d):
    return BankTxnClasificat(BankTxn(d, suma, "IN", "Incasare OP BOLT RO"), VENIT_BOLT, "et")


# ──────────────────────────────────────────────────────────────
# Detecție luni Bolt din clasificare
# ──────────────────────────────────────────────────────────────
def test_bolt_months_pe_fixture():
    txns = parse_bt_pdf(_FIXTURE.read_bytes())
    clasificate = [classify_bt(t, ACT) for t in txns]
    luni = bolt_reconcile.bolt_months_in_statement(clasificate)
    assert luni == {(2026, 4)}                  # fixture aprilie 2026


def test_bolt_months_multiple_si_ignora_non_bolt():
    clasificate = [
        _cl_bolt(100.0, date(2026, 3, 10)),
        _cl_bolt(200.0, date(2026, 4, 14)),
        _cl_bolt(150.0, date(2026, 4, 20)),     # tot aprilie → set, nu dublură
        BankTxnClasificat(BankTxn(date(2026, 5, 1), 50.0, "OUT", "lukoil"),
                          CHELTUIALA_BUSINESS, "et", categorie="fuel"),  # ignorat
    ]
    luni = bolt_reconcile.bolt_months_in_statement(clasificate)
    assert luni == {(2026, 3), (2026, 4)}


# ──────────────────────────────────────────────────────────────
# has_bolt_income True/False
# ──────────────────────────────────────────────────────────────
def test_has_bolt_income(tmp_path):
    Session, uid = _setup(tmp_path)
    _add_bolt_income(Session, uid, data_doc="30.04.2026")
    s = Session()
    assert bolt_sync.has_bolt_income(s, uid, 2026, 4) is True
    assert bolt_sync.has_bolt_income(s, uid, 2026, 5) is False   # altă lună
    assert bolt_sync.has_bolt_income(s, uid, 2025, 4) is False   # alt an
    s.close()


def test_has_bolt_income_ignora_rejected(tmp_path):
    Session, uid = _setup(tmp_path)
    did = _add_bolt_income(Session, uid, data_doc="30.04.2026")
    s = Session()
    s.get(Document, did).status = "rejected"
    s.commit()
    assert bolt_sync.has_bolt_income(s, uid, 2026, 4) is False   # rejected nu contează
    s.close()


# ──────────────────────────────────────────────────────────────
# Nudge — text când nesincronizat / None când sincronizat (tăcere)
# ──────────────────────────────────────────────────────────────
def test_nudge_luna_nesincronizata(tmp_path):
    Session, uid = _setup(tmp_path)
    clasificate = [_cl_bolt(248.33, date(2026, 4, 14))]
    s = Session()
    msg = bolt_reconcile.bolt_reconcile_nudge(s, uid, clasificate)
    s.close()
    assert msg is not None
    assert "Verificare venit Bolt" in msg
    assert "Aprilie 2026" in msg
    assert "/bolt 2026 4" in msg
    assert "nu apar încă sincronizate" in msg   # neutru, nu acuzator
    assert "nete, nu brute" in msg              # explică de ce nu din extras


def test_nudge_none_cand_sincronizat(tmp_path):
    Session, uid = _setup(tmp_path)
    _add_bolt_income(Session, uid, data_doc="30.04.2026")   # aprilie sincronizat
    clasificate = [_cl_bolt(248.33, date(2026, 4, 14))]
    s = Session()
    msg = bolt_reconcile.bolt_reconcile_nudge(s, uid, clasificate)
    s.close()
    assert msg is None                          # tăcere — nu deranjăm


def test_nudge_none_fara_bolt_in_extras(tmp_path):
    Session, uid = _setup(tmp_path)
    clasificate = [BankTxnClasificat(
        BankTxn(date(2026, 4, 1), 50.0, "OUT", "lukoil"),
        CHELTUIALA_BUSINESS, "et", categorie="fuel")]
    s = Session()
    assert bolt_reconcile.bolt_reconcile_nudge(s, uid, clasificate) is None
    s.close()


# ──────────────────────────────────────────────────────────────
# REGRESIE — _remove_existing_bolt_income neschimbat după refactor
# ──────────────────────────────────────────────────────────────
def test_regresie_remove_existing_bolt_income(tmp_path):
    Session, uid = _setup(tmp_path)
    did = _add_bolt_income(Session, uid, data_doc="30.04.2026")
    s = Session()
    removed = bolt_sync._remove_existing_bolt_income(s, uid, 2026, 4)
    s.commit()
    assert removed == 1                          # un document înlocuit
    assert s.get(Document, did).status == "rejected"
    assert s.query(Transaction).filter_by(document_id=did).count() == 0  # tx șterse
    s.close()


def test_regresie_remove_existing_alta_luna_neatinsa(tmp_path):
    Session, uid = _setup(tmp_path)
    did = _add_bolt_income(Session, uid, data_doc="30.04.2026")
    s = Session()
    removed = bolt_sync._remove_existing_bolt_income(s, uid, 2026, 5)   # mai, nu aprilie
    s.commit()
    assert removed == 0                          # nimic atins
    assert s.get(Document, did).status == "posted"
    s.close()
