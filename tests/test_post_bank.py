"""
Teste PAS 3 felia 3 — serviciu postare bancă (app/integrations/imports/post_bank.py).

Zona de SCRIERE → teste tari, în special:
- GARDA STRUCTURALĂ: doar CHELTUIALA_BUSINESS + DE_VERIFICAT se postează, chiar
  dacă `decisions` cere și restul (VENIT_BOLT / PLATA / RETURNARE / COMISION) → blocate.
- RE-RULARE pe fixture: a doua oară = 0 postări, toate dubluri (dedup PAS 2 + serviciu).

DB sqlite izolat; auditul izolat (BigInteger PK nu auto-incrementeaza pe sqlite).
"""
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.integrations.imports.bank_statement import BankTxn
from app.integrations.imports.bt_parser import parse_bt_pdf
from app.integrations.imports.classify import (
    classify_bt, BankTxnClasificat,
    VENIT_BOLT, PLATA_TAXA, RETURNARE_TAXA, COMISION_BANCAR,
    CHELTUIALA_BUSINESS, DE_VERIFICAT,
)
from app.integrations.imports import post_bank
from app.integrations.imports.post_bank import post_bank_expenses
from app.activities.ridesharing import RidesharingActivity as ACT
from app.models import User, SourceFile, Document, Transaction

_FIXTURE = Path(__file__).parent / "fixtures" / "extras_bt_anon.pdf"


def _setup(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    # Auditul (BigInteger PK) nu e obiectul testului — un singur patch acoperă și
    # post_bank, și posting (același modul app.repositories.audit).
    monkeypatch.setattr(post_bank.audit_repo, "write", lambda *a, **k: None)
    s = Session()
    u = User(telegram_id=1, activity_code="ridesharing")
    s.add(u)
    s.commit()
    sf = SourceFile(user_id=u.id, kind="bank_statement", sha256="deadbeef")
    s.add(sf)
    s.commit()
    uid, sfid = u.id, sf.id
    s.close()
    return Session, uid, sfid


def _cl(bucket, suma, descr, directie="OUT", d=date(2026, 4, 1)):
    return BankTxnClasificat(BankTxn(d, suma, directie, descr), bucket, "et")


# ──────────────────────────────────────────────────────────────
# 1. GARDĂ STRUCTURALĂ — doar bucketele permise se postează
# ──────────────────────────────────────────────────────────────
def test_garda_exclude_bucketele_nepermise(tmp_path, monkeypatch):
    Session, uid, sfid = _setup(tmp_path, monkeypatch)
    # câte unul din FIECARE bucket; sume distincte ca să nu interfereze fingerprint-ul
    clasificate = [
        _cl(VENIT_BOLT, 100.0, "bolt", directie="IN"),
        _cl(PLATA_TAXA, 40.0, "trezorerie"),
        _cl(RETURNARE_TAXA, 40.0, "returnare", directie="IN"),
        _cl(COMISION_BANCAR, 0.51, "comision plata op"),
        _cl(CHELTUIALA_BUSINESS, 200.0, "lukoil motorina"),
        _cl(DE_VERIFICAT, 31.81, "plata pos persoana fizica"),
    ]
    # decisions CERE postarea TUTUROR (chiar și a celor nepermise)
    decisions = [
        "ride_revenue", "other_expense", "other_expense",
        "other_expense", "fuel", "other_expense",
    ]
    s = Session()
    res = post_bank_expenses(
        s, user_id=uid, source_file_id=sfid,
        clasificate=clasificate, decisions=decisions,
    )
    s.commit()

    # postate DOAR CHELTUIALA_BUSINESS + DE_VERIFICAT
    assert res["posted"] == 2
    # blocate structural: VENIT_BOLT, PLATA_TAXA, RETURNARE_TAXA, COMISION_BANCAR
    assert res["skipped_blocked"] == 4

    # în DB: exact 2 Document-uri, AMBELE CHELTUIALA (niciun VENIT etc.)
    docs = s.query(Document).all()
    assert len(docs) == 2
    assert all(d.tip == "CHELTUIALA" for d in docs)
    # categoriile postate: fuel (business) + other_expense (de verificat)
    cats = sorted(t.category for t in s.query(Transaction).all())
    assert cats == ["fuel", "other_expense"]
    s.close()


def test_decizie_none_sarit_ca_personal(tmp_path, monkeypatch):
    Session, uid, sfid = _setup(tmp_path, monkeypatch)
    clasificate = [_cl(DE_VERIFICAT, 31.81, "plata pos")]
    s = Session()
    res = post_bank_expenses(
        s, user_id=uid, source_file_id=sfid,
        clasificate=clasificate, decisions=[None],
    )
    s.commit()
    assert res["posted"] == 0
    assert res["skipped_personal"] == 1
    assert s.query(Document).count() == 0      # nimic scris
    s.close()


# ──────────────────────────────────────────────────────────────
# 2. RE-RULARE pe FIXTURE — a doua oară = 0 postări, toate dubluri
# ──────────────────────────────────────────────────────────────
def _fixture_decisions(clasificate):
    """Business auto → categoria din classify; DE_VERIFICAT → other_expense; rest → None."""
    out = []
    for r in clasificate:
        if r.bucket == CHELTUIALA_BUSINESS:
            out.append(r.categorie)
        elif r.bucket == DE_VERIFICAT:
            out.append("other_expense")
        else:
            out.append(None)
    return out


def test_rerun_fixture_zero_dubluri(tmp_path, monkeypatch):
    Session, uid, sfid = _setup(tmp_path, monkeypatch)
    txns = parse_bt_pdf(_FIXTURE.read_bytes())
    clasificate = [classify_bt(t, ACT) for t in txns]
    decisions = _fixture_decisions(clasificate)

    # pe fixture: 0 CHELTUIALA_BUSINESS, 6 DE_VERIFICAT → 6 de postat
    n_postabile = sum(1 for d in decisions if d is not None)
    assert n_postabile == 6

    # --- rularea 1 ---
    s1 = Session()
    res1 = post_bank_expenses(
        s1, user_id=uid, source_file_id=sfid,
        clasificate=clasificate, decisions=decisions,
    )
    s1.commit()
    s1.close()
    assert res1["posted"] == 6
    assert res1["skipped_dup"] == 0

    # --- rularea 2 (ACELEAȘI date) ---
    s2 = Session()
    res2 = post_bank_expenses(
        s2, user_id=uid, source_file_id=sfid,
        clasificate=clasificate, decisions=decisions,
    )
    s2.commit()
    assert res2["posted"] == 0                  # nicio postare nouă
    assert res2["skipped_dup"] == 6             # toate prinse ca dubluri

    # DB: tot 6 tranzacții (re-upload-ul NU a dublat nimic)
    assert s2.query(Transaction).count() == 6
    assert s2.query(Document).count() == 6
    s2.close()


# ──────────────────────────────────────────────────────────────
# Suport — postare corectă (override + fingerprint + Document)
# ──────────────────────────────────────────────────────────────
def test_posteaza_business_cu_override_si_fingerprint(tmp_path, monkeypatch):
    Session, uid, sfid = _setup(tmp_path, monkeypatch)
    clasificate = [_cl(CHELTUIALA_BUSINESS, 200.0, "lukoil motorina")]
    s = Session()
    res = post_bank_expenses(
        s, user_id=uid, source_file_id=sfid,
        clasificate=clasificate, decisions=["fuel"],
    )
    s.commit()
    assert res["posted"] == 1
    tx = s.query(Transaction).one()
    assert tx.category == "fuel"
    assert tx.deductibility_pct == 50           # override onorat
    assert tx.import_fingerprint is not None    # fingerprint stocat
    doc = s.query(Document).one()
    assert doc.tip == "CHELTUIALA"
    assert doc.source_file_id == sfid           # legat de extras
    assert doc.prompt_version == "bank_bt_v1"
    s.close()


def test_sumar_deductibil(tmp_path, monkeypatch):
    Session, uid, sfid = _setup(tmp_path, monkeypatch)
    clasificate = [
        _cl(CHELTUIALA_BUSINESS, 200.0, "lukoil motorina"),     # fuel 50% → 100
        _cl(DE_VERIFICAT, 100.0, "plata pos", d=date(2026, 4, 2)),  # other 100% → 100
    ]
    s = Session()
    res = post_bank_expenses(
        s, user_id=uid, source_file_id=sfid,
        clasificate=clasificate, decisions=["fuel", "other_expense"],
    )
    s.commit()
    assert res["posted"] == 2
    assert res["deductibil_sum"] == 200.0       # 200*0.5 + 100*1.0
    s.close()
