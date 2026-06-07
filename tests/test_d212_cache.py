"""
Teste pentru cache-ul cu fingerprint al compute_d212_anual (Faza 3 perf).

Accent pe ANTI-STALE: după add/delete/lock tranzacție, al 2-lea apel întoarce
cifra NOUĂ (nu cea cached). Fingerprint-ul = starea datelor.
"""

import threading
import time
from types import SimpleNamespace

from app.services import tax_engine
from app.models import User, Transaction
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _db(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    s = Session()
    u = User(telegram_id=1)
    s.add(u)
    s.commit()
    return s, u.id


def _add_tx(s, uid, amount=100.0, year=2026, locked=False):
    tx = Transaction(user_id=uid, document_id=1, tx_type="INCOME", category="x",
                     amount_brut=amount, period_year=year, period_month=5,
                     locked=locked)
    s.add(tx)
    s.commit()
    return tx


def _spy(monkeypatch):
    """Înlocuiește calculul scump cu un fake care numără apelurile."""
    calls = {"n": 0}
    def fake(session, *, user_id, an):
        calls["n"] += 1
        return SimpleNamespace(call_n=calls["n"])
    monkeypatch.setattr(tax_engine, "_compute_d212_anual_uncached", fake)
    return calls


# ────────────────────────────────────────────────────────────
# HIT + ANTI-STALE (cel mai important)
# ────────────────────────────────────────────────────────────

def test_hit_si_anti_stale_la_add(monkeypatch, tmp_path):
    tax_engine._D212_CACHE.clear()
    s, uid = _db(tmp_path)
    _add_tx(s, uid, 100.0)
    calls = _spy(monkeypatch)

    r1 = tax_engine.compute_d212_anual(s, user_id=uid, an=2026)
    r2 = tax_engine.compute_d212_anual(s, user_id=uid, an=2026)
    assert r1.call_n == 1 and r2.call_n == 1     # al 2-lea = HIT (date neschimbate)
    assert calls["n"] == 1                       # compute scump chemat O DATĂ

    _add_tx(s, uid, 50.0)                         # DATE NOI → fingerprint diferit
    r3 = tax_engine.compute_d212_anual(s, user_id=uid, an=2026)
    assert r3.call_n == 2                         # RECOMPUTE — cifra NOUĂ, nu stale
    assert calls["n"] == 2


def test_anti_stale_la_delete(monkeypatch, tmp_path):
    tax_engine._D212_CACHE.clear()
    s, uid = _db(tmp_path)
    _add_tx(s, uid, 100.0)
    tx2 = _add_tx(s, uid, 50.0)
    calls = _spy(monkeypatch)

    tax_engine.compute_d212_anual(s, user_id=uid, an=2026)      # miss → 1
    s.delete(tx2)
    s.commit()
    r = tax_engine.compute_d212_anual(s, user_id=uid, an=2026)  # count scade → recompute
    assert r.call_n == 2 and calls["n"] == 2


def test_anti_stale_la_lock(monkeypatch, tmp_path):
    tax_engine._D212_CACHE.clear()
    s, uid = _db(tmp_path)
    tx = _add_tx(s, uid, 100.0)
    calls = _spy(monkeypatch)

    tax_engine.compute_d212_anual(s, user_id=uid, an=2026)      # miss → 1
    tx.locked = True                                            # iese din locked=False
    s.commit()
    r = tax_engine.compute_d212_anual(s, user_id=uid, an=2026)  # fingerprint diferit
    assert r.call_n == 2 and calls["n"] == 2


def test_alt_an_nu_invalideaza(monkeypatch, tmp_path):
    tax_engine._D212_CACHE.clear()
    s, uid = _db(tmp_path)
    _add_tx(s, uid, 100.0, year=2026)
    calls = _spy(monkeypatch)

    tax_engine.compute_d212_anual(s, user_id=uid, an=2026)      # miss → 1
    _add_tx(s, uid, 999.0, year=2025)                          # tx pe ALT an
    r = tax_engine.compute_d212_anual(s, user_id=uid, an=2026)  # 2026 neschimbat → HIT
    assert r.call_n == 1 and calls["n"] == 1


def test_chei_separate_per_user(monkeypatch, tmp_path):
    tax_engine._D212_CACHE.clear()
    s, uid = _db(tmp_path)
    alt = User(telegram_id=2)
    s.add(alt)
    s.commit()
    _add_tx(s, uid, 100.0)
    _add_tx(s, alt.id, 200.0)
    calls = _spy(monkeypatch)

    tax_engine.compute_d212_anual(s, user_id=uid, an=2026)      # user A → 1
    tax_engine.compute_d212_anual(s, user_id=alt.id, an=2026)   # user B → 2 (cheie alta)
    tax_engine.compute_d212_anual(s, user_id=uid, an=2026)      # A din nou → HIT
    assert calls["n"] == 2


# ────────────────────────────────────────────────────────────
# Thread-safety (lock pe dict-ul de cache)
# ────────────────────────────────────────────────────────────

def test_thread_safety(monkeypatch):
    tax_engine._D212_CACHE.clear()
    monkeypatch.setattr(tax_engine, "_d212_fingerprint", lambda s, u, a: (1, 1, 1.0))
    def fake(session, *, user_id, an):
        time.sleep(0.005)
        return SimpleNamespace(v=42)
    monkeypatch.setattr(tax_engine, "_compute_d212_anual_uncached", fake)

    results, errors = [], []
    def worker():
        try:
            results.append(tax_engine.compute_d212_anual(None, user_id=7, an=2026))
        except Exception as e:    # pragma: no cover
            errors.append(e)
    ts = [threading.Thread(target=worker) for _ in range(12)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert not errors
    assert len(results) == 12 and all(r.v == 42 for r in results)
