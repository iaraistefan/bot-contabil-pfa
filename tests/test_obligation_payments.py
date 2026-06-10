"""
Teste PAS felia 5b — model + repo ObligationPayment (fundație, zero consumator).

- create + re-create ACELAȘI fingerprint → 1 singur rând (anti-dublură re-import)
- has_payment True/False + izolare per-user
- sentinel anual (perioada_luna=0)
- plăți MULTIPLE distincte (fingerprint-uri diferite, aceeași obligație → tranșe)
- create_all idempotent (tabel creat fără eroare)
"""
from datetime import date

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.models import User, ObligationPayment
from app.repositories import obligation_payments as repo


def _setup(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    s = Session()
    u, u2 = User(telegram_id=1), User(telegram_id=2)
    s.add_all([u, u2])
    s.commit()
    uid, uid2 = u.id, u2.id
    s.close()
    return Session, uid, uid2


def _create(s, uid, fp, cod="D301", an=2026, luna=1, suma=138.0):
    return repo.create_payment(
        s, user_id=uid, obligation_code=cod, perioada_an=an, perioada_luna=luna,
        suma_platita=suma, data_platii=date(2026, 4, 27), import_fingerprint=fp,
    )


# ──────────────────────────────────────────────────────────────
# Anti-dublură la re-import: același fingerprint → 1 singur rând
# ──────────────────────────────────────────────────────────────
def test_re_create_acelasi_fingerprint_un_singur_rand(tmp_path):
    Session, uid, _ = _setup(tmp_path)
    s = Session()
    p1 = _create(s, uid, "fp1")
    s.commit()
    p2 = _create(s, uid, "fp1")          # re-import aceeași linie
    s.commit()
    assert p1.id == p2.id                 # întoarce existentul, NU dublează
    assert s.query(ObligationPayment).count() == 1
    s.close()


# ──────────────────────────────────────────────────────────────
# has_payment True/False + izolare per-user
# ──────────────────────────────────────────────────────────────
def test_has_payment_true_false_izolare(tmp_path):
    Session, uid, uid2 = _setup(tmp_path)
    s = Session()
    _create(s, uid, "fp1", cod="D301", an=2026, luna=1)
    s.commit()
    assert repo.has_payment(s, uid, "D301", 2026, 1) is True
    assert repo.has_payment(s, uid, "D301", 2026, 2) is False    # altă lună
    assert repo.has_payment(s, uid, "D100", 2026, 1) is False    # alt cod
    assert repo.has_payment(s, uid, "D301", 2025, 1) is False    # alt an
    assert repo.has_payment(s, uid2, "D301", 2026, 1) is False   # alt user
    s.close()


# ──────────────────────────────────────────────────────────────
# Sentinel anual (perioada_luna=0)
# ──────────────────────────────────────────────────────────────
def test_sentinel_anual_luna_zero(tmp_path):
    Session, uid, _ = _setup(tmp_path)
    s = Session()
    _create(s, uid, "fpA", cod="D212", an=2026, luna=0)
    s.commit()
    assert repo.has_payment(s, uid, "D212", 2026, 0) is True
    s.close()


# ──────────────────────────────────────────────────────────────
# Plăți multiple distincte (tranșe) — cheia pe fingerprint, nu pe perioadă
# ──────────────────────────────────────────────────────────────
def test_plati_multiple_distincte_transe(tmp_path):
    Session, uid, _ = _setup(tmp_path)
    s = Session()
    _create(s, uid, "fpX", cod="D212", an=2026, luna=0, suma=500.0)
    s.commit()
    _create(s, uid, "fpY", cod="D212", an=2026, luna=0, suma=300.0)  # tranșa 2
    s.commit()
    # 2 fingerprint-uri diferite, aceeași obligație → 2 rânduri (nu blocat)
    assert s.query(ObligationPayment).filter_by(user_id=uid).count() == 2
    assert repo.has_payment(s, uid, "D212", 2026, 0) is True
    s.close()


# ──────────────────────────────────────────────────────────────
# create_all idempotent (echivalent CREATE TABLE IF NOT EXISTS pe SQLite)
# ──────────────────────────────────────────────────────────────
def test_create_all_idempotent(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 'idem.db').as_posix()}")
    User.metadata.create_all(eng)
    User.metadata.create_all(eng)        # re-run nu strică
    assert "obligation_payments" in inspect(eng).get_table_names()
