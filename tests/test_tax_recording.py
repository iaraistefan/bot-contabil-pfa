"""
Teste felia 5c-a — serviciu pur record_tax_payments (înregistrare plăți confirmate).

Cheie: FINGERPRINT (valoare stabilă), nu index/id(). Garda compensare ține PESTE
confirmarea userului (o plată respinsă confirmată din greșeală → refuzată structural).
"""
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.integrations.imports.bank_statement import BankTxn
from app.integrations.imports.bt_parser import parse_bt_pdf
from app.integrations.imports.classify import (
    classify_bt, BankTxnClasificat, ObligatieHint, PLATA_TAXA, RETURNARE_TAXA,
)
from app.integrations.imports.dedup import compute_fingerprints
from app.integrations.imports.tax_recording import record_tax_payments
from app.activities.ridesharing import RidesharingActivity as ACT
from app.models import User, ObligationPayment

_FIXTURE = Path(__file__).parent / "fixtures" / "extras_bt_anon.pdf"


def _setup(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    s = Session()
    u = User(telegram_id=1)
    s.add(u)
    s.commit()
    uid = u.id
    s.close()
    return Session, uid


def _cl(bucket, directie, descr, suma, cod="D301", tip="TVA", luna=1, an=2026,
        d=date(2026, 4, 27)):
    o = ObligatieHint(tip, cod, luna, an, "Ianuarie")
    return BankTxnClasificat(BankTxn(d, suma, directie, descr), bucket, "et", oblig=o)


def _plata(descr, suma, **kw):
    return _cl(PLATA_TAXA, "OUT", descr, suma, **kw)


def _retur(descr, suma, **kw):
    return _cl(RETURNARE_TAXA, "IN", descr, suma, **kw)


# ──────────────────────────────────────────────────────────────
# ⭐ GOLDEN pe fixture — toate plățile respinse → 0 înregistrate
# ──────────────────────────────────────────────────────────────
def test_golden_fixture_zero_recorded(tmp_path):
    Session, uid = _setup(tmp_path)
    txns = parse_bt_pdf(_FIXTURE.read_bytes())
    clasificate = [classify_bt(t, ACT) for t in txns]
    fps = compute_fingerprints([r.txn for r in clasificate])
    # userul „confirmă" toate plățile de taxe (PLATA_TAXA) din extras
    confirmed = {fps[i] for i, r in enumerate(clasificate) if r.bucket == PLATA_TAXA}
    assert len(confirmed) == 8                  # 8 plăți pe fixture

    s = Session()
    res = record_tax_payments(
        s, user_id=uid, source_file_id=None,
        clasificate=clasificate, confirmed_fingerprints=confirmed,
    )
    s.commit()
    assert res["recorded"] == 0                 # toate respinse → 0 înregistrate
    assert res["skipped_blocked"] == 8          # confirmate dar nereale → blocate
    assert s.query(ObligationPayment).count() == 0
    s.close()


# ──────────────────────────────────────────────────────────────
# ⭐ GARDA peste confirmare — plată respinsă confirmată → blocată
# ──────────────────────────────────────────────────────────────
def test_garda_plata_respinsa_confirmata_blocata(tmp_path):
    Session, uid = _setup(tmp_path)
    cl = [
        _plata("plata trezorerie tva d301 ianuarie", 138.0),
        _retur("returnare plata tva d301 ianuarie", 138.0),   # respinge plata
    ]
    fps = compute_fingerprints([r.txn for r in cl])
    confirmed = {fps[0]}                         # userul confirmă plata (care e respinsă)

    s = Session()
    res = record_tax_payments(
        s, user_id=uid, source_file_id=None,
        clasificate=cl, confirmed_fingerprints=confirmed,
    )
    s.commit()
    assert res["recorded"] == 0
    assert res["skipped_blocked"] == 1          # garda ține peste confirmarea userului
    assert s.query(ObligationPayment).count() == 0
    s.close()


# ──────────────────────────────────────────────────────────────
# Plată reală confirmată → înregistrată; re-rulare → dedup
# ──────────────────────────────────────────────────────────────
def test_plata_reala_confirmata_inregistrata_si_dedup(tmp_path):
    Session, uid = _setup(tmp_path)
    cl = [_plata("plata trezorerie tva d301 ianuarie", 138.0)]   # fără returnare → reală
    fps = compute_fingerprints([r.txn for r in cl])
    confirmed = {fps[0]}

    s = Session()
    res = record_tax_payments(
        s, user_id=uid, source_file_id=None,
        clasificate=cl, confirmed_fingerprints=confirmed,
    )
    s.commit()
    assert res["recorded"] == 1
    pay = s.query(ObligationPayment).one()
    assert pay.obligation_code == "D301"        # din hint, formă scurtă
    assert pay.perioada_an == 2026 and pay.perioada_luna == 1
    assert pay.suma_platita == 138.0
    s.close()

    # re-rulare aceleași date → dedup pe fingerprint (0 noi)
    s2 = Session()
    res2 = record_tax_payments(
        s2, user_id=uid, source_file_id=None,
        clasificate=cl, confirmed_fingerprints=confirmed,
    )
    s2.commit()
    assert res2["recorded"] == 0
    assert res2["skipped_dup"] == 1
    assert s2.query(ObligationPayment).count() == 1
    s2.close()


def test_plata_reala_neconfirmata_nu_inregistrata(tmp_path):
    Session, uid = _setup(tmp_path)
    cl = [_plata("plata trezorerie tva d301", 138.0)]
    s = Session()
    res = record_tax_payments(
        s, user_id=uid, source_file_id=None,
        clasificate=cl, confirmed_fingerprints=set(),       # nimic confirmat
    )
    s.commit()
    assert res["recorded"] == 0
    assert res["skipped_blocked"] == 0          # nimic confirmat → nimic blocat
    assert s.query(ObligationPayment).count() == 0
    s.close()
