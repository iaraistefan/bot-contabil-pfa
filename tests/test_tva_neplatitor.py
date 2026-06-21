"""
Corectură GOL TVA NEPLĂTITOR — `_post_factura_comision` crea VAT_IN necondiționat.

Bug: pentru neplătitori (majoritatea ridesharing) reverse-charge-ul genera VAT_OUT
(datorat, D301) DAR ȘI VAT_IN (deductibil) → Net TVA = vat_out − vat_in = 0, deși
neplătitorul NU poate deduce → datorează vat_out. Inconsistent cu D301.

Fix: VAT_IN se creează DOAR pentru cei cu drept de deducere (PLATITOR_21 exclusiv).
NEPLATITOR și SPECIAL_INTRACOM (art. 317) datorează (vat_out) dar NU deduc.
Forward-only — istoricul NU se rescrie; userii afectați primesc un semnal în raport.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User, Document, Transaction
from app.services import posting, tax_engine

Y, M = 2026, 5
COMISION = 657.0   # 21% reverse-charge → vat ≈ 137.97


def _setup(tmp_path, monkeypatch, regim_tva):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    monkeypatch.setattr(posting.audit_repo, "write", lambda *a, **k: None)
    s = Session()
    u = User(telegram_id=999, activity_code="ridesharing", regim_tva=regim_tva)
    s.add(u)
    s.commit()
    uid = u.id
    s.close()
    return Session, uid


def _post_comision(Session, uid):
    s = Session()
    d = Document(user_id=uid, tip="FACTURA_COMISION", status="posted", data_doc="05.05.2026")
    s.add(d)
    s.commit()
    tx_ids = posting.post_document(
        s, user_id=uid, document_id=d.id, tip="FACTURA_COMISION",
        platforma="Bolt", detalii="comision Bolt EE", brut=0.0, comision=COMISION,
        tva=0.0, net=0.0, cash=0.0, banca=0.0, data_doc="05.05.2026",
    )
    s.commit()
    s.close()
    return tx_ids


def _vat_types(Session, uid):
    s = Session()
    types = [t.tx_type for t in s.query(Transaction)
             .filter(Transaction.user_id == uid).all()]
    s.close()
    return types


def _totals(Session, uid):
    s = Session()
    t = tax_engine.compute_period(s, user_id=uid, year=Y, month=M)
    s.close()
    return t


# ════════════════════════════════════════════════════════════
#   PREDICAT — _can_deduct_vat (PLATITOR_21 EXCLUSIV)
# ════════════════════════════════════════════════════════════

def test_predicat_can_deduct_doar_platitor(tmp_path, monkeypatch):
    for regim, asteptat in [("PLATITOR_21", True), ("NEPLATITOR", False),
                            ("SPECIAL_INTRACOM", False)]:
        sub = tmp_path / regim
        sub.mkdir()
        Session, uid = _setup(sub, monkeypatch, regim)
        s = Session()
        assert posting._can_deduct_vat(s, uid) is asteptat, regim
        s.close()


def test_predicat_user_inexistent_false(tmp_path, monkeypatch):
    Session, uid = _setup(tmp_path, monkeypatch, "PLATITOR_21")
    s = Session()
    assert posting._can_deduct_vat(s, 99999) is False
    s.close()


# ════════════════════════════════════════════════════════════
#   FIX — neplătitor: VAT_OUT fără VAT_IN → Net TVA = vat_out
# ════════════════════════════════════════════════════════════

def test_neplatitor_vat_out_fara_vat_in(tmp_path, monkeypatch):
    Session, uid = _setup(tmp_path, monkeypatch, "NEPLATITOR")
    tx_ids = _post_comision(Session, uid)
    types = _vat_types(Session, uid)
    assert "VAT_OUT" in types and "VAT_IN" not in types   # datorat, NU deductibil
    assert len(tx_ids) == 1                                 # o singură tranzacție TVA
    t = _totals(Session, uid)
    assert t["vat_out_total"] > 0
    assert t["vat_in_total"] == 0.0
    assert t["vat_net"] == t["vat_out_total"]              # Net TVA = de plată (nu 0!)
    assert t["vat_poate_deduce"] is False


def test_special_intracom_ca_neplatitor(tmp_path, monkeypatch):
    # SPECIAL_INTRACOM (art. 317): datorează reverse-charge dar NU deduce → ca neplătitor
    Session, uid = _setup(tmp_path, monkeypatch, "SPECIAL_INTRACOM")
    _post_comision(Session, uid)
    types = _vat_types(Session, uid)
    assert "VAT_OUT" in types and "VAT_IN" not in types
    t = _totals(Session, uid)
    assert t["vat_net"] == t["vat_out_total"] and t["vat_in_total"] == 0.0


# ════════════════════════════════════════════════════════════
#   REGRESIE 0 — plătitor: VAT_OUT + VAT_IN → Net TVA 0 (neschimbat)
# ════════════════════════════════════════════════════════════

def test_platitor_regresie_vat_in_creat_net_zero(tmp_path, monkeypatch):
    Session, uid = _setup(tmp_path, monkeypatch, "PLATITOR_21")
    tx_ids = _post_comision(Session, uid)
    types = _vat_types(Session, uid)
    assert "VAT_OUT" in types and "VAT_IN" in types        # ambele (comportament istoric)
    assert len(tx_ids) == 2
    t = _totals(Session, uid)
    assert t["vat_out_total"] > 0
    assert t["vat_in_total"] == t["vat_out_total"]
    assert t["vat_net"] == 0.0                              # se compensează → 0 (REGRESIE 0)
    assert t["vat_poate_deduce"] is True


# ════════════════════════════════════════════════════════════
#   SEMNAL FORWARD — raportul avertizează neplătitorul afectat
# ════════════════════════════════════════════════════════════

def test_raport_semnal_neplatitor(tmp_path, monkeypatch):
    Session, uid = _setup(tmp_path, monkeypatch, "NEPLATITOR")
    _post_comision(Session, uid)
    t = _totals(Session, uid)
    msg = tax_engine.format_report_message(t)
    assert "reverse-charge" in msg and "luni anterioare" in msg   # semnal istoric


def test_raport_fara_semnal_platitor(tmp_path, monkeypatch):
    Session, uid = _setup(tmp_path, monkeypatch, "PLATITOR_21")
    _post_comision(Session, uid)
    t = _totals(Session, uid)
    msg = tax_engine.format_report_message(t)
    assert "luni anterioare" not in msg                          # plătitor → fără semnal
