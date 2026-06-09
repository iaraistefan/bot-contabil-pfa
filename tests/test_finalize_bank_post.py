"""
Teste PAS 4b felia 3 — commit TOT-SAU-NIMIC + gaura orfană (money-critical).

`finalize_bank_post` e sync, testabil izolat. Glue-ul async e subțire (apelează
doar funcții pure/sync testate). DB sqlite izolat; audit izolat.
"""
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.integrations.imports.bank_statement import BankTxn
from app.integrations.imports.classify import (
    BankTxnClasificat, VENIT_BOLT, PLATA_TAXA, CHELTUIALA_BUSINESS, DE_VERIFICAT,
)
from app.integrations.imports import post_bank
from app.services import posting
from app.services import bank_import_ui as ui
from app.models import User, SourceFile, Document, Transaction


def _setup(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    monkeypatch.setattr(post_bank.audit_repo, "write", lambda *a, **k: None)
    s = Session()
    u = User(telegram_id=1, activity_code="ridesharing")
    s.add(u)
    s.commit()
    sf = SourceFile(user_id=u.id, kind="bank_statement", sha256="x")
    s.add(sf)
    s.commit()
    uid, sfid = u.id, sf.id
    s.close()
    return Session, uid, sfid


def _cl(bucket, categorie=None, suma=100.0, descr="x", directie="OUT",
        d=date(2026, 4, 1)):
    return BankTxnClasificat(BankTxn(d, suma, directie, descr), bucket, "et",
                             categorie=categorie)


# ──────────────────────────────────────────────────────────────
# GAURA ORFANĂ — post_document=[] → ridică → rollback → 0 tx ȘI 0 docs
# ──────────────────────────────────────────────────────────────
def test_gaura_orfana_zero_tx_si_zero_docs(tmp_path, monkeypatch):
    Session, uid, sfid = _setup(tmp_path, monkeypatch)
    # post_document înghite eroarea și întoarce [] (gaura). Document-ul s-a creat
    # ÎNAINTE → ar rămâne orfan dacă am comite. Trebuie rollback complet.
    monkeypatch.setattr(posting, "post_document", lambda *a, **k: [])
    clasificate = [_cl(CHELTUIALA_BUSINESS, categorie="fuel", suma=200.0)]

    s = Session()
    outcome = ui.finalize_bank_post(
        s, user_id=uid, source_file_id=sfid,
        clasificate=clasificate, decisions=["fuel"],
    )
    s.close()
    assert outcome["ok"] is False

    s2 = Session()
    assert s2.query(Transaction).count() == 0
    assert s2.query(Document).count() == 0      # ZERO Document orfan rămas
    s2.close()


# ──────────────────────────────────────────────────────────────
# TOT-SAU-NIMIC — crash la a 3-a linie (din 4) → DB 0 (nu 2)
# ──────────────────────────────────────────────────────────────
def test_tot_sau_nimic_crash_mijloc(tmp_path, monkeypatch):
    Session, uid, sfid = _setup(tmp_path, monkeypatch)
    real = posting.post_document
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("boom la a 3-a linie")
        return real(*a, **k)

    monkeypatch.setattr(posting, "post_document", flaky)
    # 4 cheltuieli de verificat (date/sume distincte)
    clasificate = [
        _cl(DE_VERIFICAT, suma=10.0 + i, descr=f"m{i}", d=date(2026, 4, 1 + i))
        for i in range(4)
    ]
    decisions = ["other_expense"] * 4

    s = Session()
    outcome = ui.finalize_bank_post(
        s, user_id=uid, source_file_id=sfid,
        clasificate=clasificate, decisions=decisions,
    )
    s.close()
    assert outcome["ok"] is False

    s2 = Session()
    # rollback COMPLET — nu rămân cele 2 „reușite" înainte de crash
    assert s2.query(Transaction).count() == 0
    assert s2.query(Document).count() == 0
    s2.close()


# ──────────────────────────────────────────────────────────────
# SUCCES — commit, DB are rândurile
# ──────────────────────────────────────────────────────────────
def test_finalize_succes(tmp_path, monkeypatch):
    Session, uid, sfid = _setup(tmp_path, monkeypatch)
    clasificate = [
        _cl(CHELTUIALA_BUSINESS, categorie="fuel", suma=200.0),
        _cl(DE_VERIFICAT, suma=100.0, descr="pos", d=date(2026, 4, 2)),
    ]
    s = Session()
    outcome = ui.finalize_bank_post(
        s, user_id=uid, source_file_id=sfid,
        clasificate=clasificate, decisions=["fuel", "other_expense"],
    )
    s.close()
    assert outcome["ok"] is True
    assert outcome["result"]["posted"] == 2

    s2 = Session()
    assert s2.query(Transaction).count() == 2
    assert s2.query(Document).count() == 2
    s2.close()


# ──────────────────────────────────────────────────────────────
# STARE — store/get/clear + suprascriere + has_postable
# ──────────────────────────────────────────────────────────────
class _Ctx:
    def __init__(self):
        self.user_data = {}


def test_store_get_clear_state():
    ctx = _Ctx()
    st = ui.init_state([_cl(DE_VERIFICAT)], 1)
    ui.store_state(ctx, st)
    assert ui.get_state(ctx) is st
    ui.clear_state(ctx)
    assert ui.get_state(ctx) is None


def test_overwrite_state_curat():
    ctx = _Ctx()
    ui.store_state(ctx, ui.init_state([_cl(DE_VERIFICAT, descr="a")], 1))
    ui.store_state(ctx, ui.init_state([_cl(CHELTUIALA_BUSINESS, categorie="fuel")], 2))
    st = ui.get_state(ctx)
    assert st["source_file_id"] == 2            # extras nou suprascrie curat
    assert st["deverificat_idx"] == []


def test_has_postable():
    assert ui.has_postable([_cl(CHELTUIALA_BUSINESS, categorie="fuel")]) is True
    assert ui.has_postable([_cl(DE_VERIFICAT)]) is True
    assert ui.has_postable(
        [_cl(VENIT_BOLT, directie="IN"), _cl(PLATA_TAXA)]
    ) is False                                   # nimic postabil → fără buton
