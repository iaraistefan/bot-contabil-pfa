"""
Teste PAS 1 felia 3 — parametri aditivi în post_document:
`category_override` + `import_fingerprint`.

Atinge cod de PRODUCȚIE (post_document; foto + Bolt depind de el), deci REGRESIA
e obligatorie: cu params absenți (default None) comportamentul e IDENTIC.

DB sqlite izolat în tmp; auditul (BigInteger PK) izolat — nu e obiectul testului.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User, Document, Transaction
from app.services import posting


def _setup(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    # Auditul nu e obiectul testului (BigInteger PK nu auto-incrementeaza pe sqlite).
    monkeypatch.setattr(posting.audit_repo, "write", lambda *a, **k: None)
    s = Session()
    u = User(telegram_id=999, activity_code="ridesharing")
    s.add(u)
    s.commit()
    uid = u.id
    s.close()
    return Session, uid


def _doc(Session, uid, tip="CHELTUIALA"):
    s = Session()
    d = Document(user_id=uid, tip=tip, status="posted", data_doc="05.04.2026")
    s.add(d)
    s.commit()
    did = d.id
    s.close()
    return did


def _post(Session, uid, did, **kw):
    """Apel post_document + commit; întoarce (Session, tx_ids)."""
    s = Session()
    tx_ids = posting.post_document(s, user_id=uid, document_id=did, **kw)
    s.commit()
    s.close()
    return tx_ids


# ──────────────────────────────────────────────────────────────
# 1. REGRESIE FOTO — CHELTUIALA fără params noi = comportament istoric
# ──────────────────────────────────────────────────────────────
def test_regresie_foto_cheltuiala_fara_params(tmp_path, monkeypatch):
    Session, uid = _setup(tmp_path, monkeypatch)
    did = _doc(Session, uid)
    # apel EXACT ca persist_transactions (foto): fără category_override/fingerprint
    tx_ids = _post(
        Session, uid, did, tip="CHELTUIALA",
        platforma="Lukoil", detalii="motorina", brut=200.0, comision=0.0,
        tva=0.0, net=200.0, cash=0.0, banca=0.0, data_doc="05.04.2026",
    )
    s = Session()
    tx = s.get(Transaction, tx_ids[0])
    # categoria vine din scoring semantic (NU override), deductibil din activitate
    assert tx.category == "fuel"
    assert tx.deductibility_pct == 50
    assert tx.tx_type == "EXPENSE"
    assert tx.amount_brut == 200.0
    assert tx.import_fingerprint is None        # param absent → None
    s.close()


# ──────────────────────────────────────────────────────────────
# 2. REGRESIE BOLT — VENIT bit-identic; ramura VENIT nu vede params noi
# ──────────────────────────────────────────────────────────────
def test_regresie_bolt_venit_neatins(tmp_path, monkeypatch):
    Session, uid = _setup(tmp_path, monkeypatch)
    did = _doc(Session, uid, tip="VENIT")
    # apel EXACT ca bolt_sync.post_month (VENIT)
    tx_ids = _post(
        Session, uid, did, tip="VENIT",
        platforma="Bolt", detalii="Venituri Bolt", brut=699.45, comision=378.0,
        tva=0.0, net=321.45, cash=0.0, banca=699.45, data_doc="30.04.2026",
    )
    s = Session()
    txs = [s.get(Transaction, i) for i in tx_ids]
    # INCOME card (cash=0 → fără tx cash) + EXPENSE platform_commission
    income = [t for t in txs if t.tx_type == "INCOME"]
    expense = [t for t in txs if t.tx_type == "EXPENSE"]
    assert len(income) == 1 and income[0].category == "ride_revenue"
    assert income[0].amount_brut == 699.45
    assert len(expense) == 1 and expense[0].category == "platform_commission"
    assert expense[0].amount_brut == 378.0
    # niciun tx nu primește fingerprint (nu e pasat, ramura VENIT nici nu-l vede)
    assert all(t.import_fingerprint is None for t in txs)
    s.close()


def test_regresie_bolt_venit_cu_params_explicit_none(tmp_path, monkeypatch):
    # Chiar pasați explicit ca None → identic cu absența lor (bit-identic).
    Session, uid = _setup(tmp_path, monkeypatch)
    did = _doc(Session, uid, tip="VENIT")
    tx_ids = _post(
        Session, uid, did, tip="VENIT",
        platforma="Bolt", detalii="Venituri Bolt", brut=699.45, comision=378.0,
        tva=0.0, net=321.45, cash=0.0, banca=699.45, data_doc="30.04.2026",
        category_override=None, import_fingerprint=None,
    )
    s = Session()
    txs = [s.get(Transaction, i) for i in tx_ids]
    assert sorted(t.tx_type for t in txs) == ["EXPENSE", "INCOME"]
    assert all(t.import_fingerprint is None for t in txs)
    s.close()


# ──────────────────────────────────────────────────────────────
# 3. OVERRIDE ONORAT — categoria din felia 2, deductibil derivat identic
# ──────────────────────────────────────────────────────────────
def test_override_categorie_onorat(tmp_path, monkeypatch):
    Session, uid = _setup(tmp_path, monkeypatch)
    did = _doc(Session, uid)
    tx_ids = _post(
        Session, uid, did, tip="CHELTUIALA",
        platforma=None, detalii="orice text", brut=100.0, comision=0.0,
        tva=0.0, net=100.0, cash=0.0, banca=0.0, data_doc="05.04.2026",
        category_override="fuel",
    )
    s = Session()
    tx = s.get(Transaction, tx_ids[0])
    assert tx.category == "fuel"
    assert tx.deductibility_pct == 50      # = get_deductibility_pct("fuel"), ca felia 2
    s.close()


def test_override_other_expense_100(tmp_path, monkeypatch):
    # DE_VERIFICAT confirmat business fără categorie specifică → other_expense 100%.
    Session, uid = _setup(tmp_path, monkeypatch)
    did = _doc(Session, uid)
    tx_ids = _post(
        Session, uid, did, tip="CHELTUIALA",
        platforma=None, detalii="plata pos persoana fizica", brut=242.01,
        comision=0.0, tva=0.0, net=242.01, cash=0.0, banca=0.0,
        data_doc="23.04.2026", category_override="other_expense",
    )
    s = Session()
    tx = s.get(Transaction, tx_ids[0])
    assert tx.category == "other_expense"
    assert tx.deductibility_pct == 100
    s.close()


# ──────────────────────────────────────────────────────────────
# 4. OVERRIDE SARE PESTE RE-CLASIFICARE — text TOXIC neutralizat
#    (dovada că invariantul "override mereu non-None pentru bancă =
#     fals-pozitiv structural imposibil pe SCRIERE" chiar ține)
# ──────────────────────────────────────────────────────────────
_TOXIC = "comision tranzactie 0.00RON persoana fizica"


def test_text_toxic_fara_override_da_fals_pozitiv(tmp_path, monkeypatch):
    # ÎNTÂI dovedim că textul E toxic: fără override, re-clasificarea îl prinde
    # ca platform_commission (exact fals-pozitivul corectat în felia 2 la denoise).
    Session, uid = _setup(tmp_path, monkeypatch)
    did = _doc(Session, uid)
    tx_ids = _post(
        Session, uid, did, tip="CHELTUIALA",
        platforma=None, detalii=_TOXIC, brut=242.01, comision=0.0, tva=0.0,
        net=242.01, cash=0.0, banca=0.0, data_doc="23.04.2026",
    )
    s = Session()
    tx = s.get(Transaction, tx_ids[0])
    assert tx.category == "platform_commission"   # toxic CONFIRMAT
    s.close()


def test_text_toxic_cu_override_neutralizat(tmp_path, monkeypatch):
    # ACELAȘI text toxic + override → detect_expense_category NU rulează →
    # categoria e cea din override, fals-pozitivul e IMPOSIBIL.
    Session, uid = _setup(tmp_path, monkeypatch)
    did = _doc(Session, uid)
    tx_ids = _post(
        Session, uid, did, tip="CHELTUIALA",
        platforma=None, detalii=_TOXIC, brut=242.01, comision=0.0, tva=0.0,
        net=242.01, cash=0.0, banca=0.0, data_doc="23.04.2026",
        category_override="other_expense",
    )
    s = Session()
    tx = s.get(Transaction, tx_ids[0])
    assert tx.category == "other_expense"
    assert tx.category != "platform_commission"   # fals-pozitivul structural imposibil
    s.close()


# ──────────────────────────────────────────────────────────────
# 5. FINGERPRINT STOCAT
# ──────────────────────────────────────────────────────────────
def test_import_fingerprint_stocat(tmp_path, monkeypatch):
    Session, uid = _setup(tmp_path, monkeypatch)
    did = _doc(Session, uid)
    tx_ids = _post(
        Session, uid, did, tip="CHELTUIALA",
        platforma=None, detalii="x", brut=31.81, comision=0.0, tva=0.0,
        net=31.81, cash=0.0, banca=0.0, data_doc="02.04.2026",
        category_override="other_expense", import_fingerprint="abc123",
    )
    s = Session()
    tx = s.get(Transaction, tx_ids[0])
    assert tx.import_fingerprint == "abc123"
    s.close()
