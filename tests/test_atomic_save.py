"""
coada-bugs #1 — `execute_confirmed_save` salvare ATOMICĂ.

Înainte: fiecare item se comitea separat (persist_document + persist_transactions
cu sesiune+commit proprii) → eșec mid-loop lăsa date parțiale + documente orfane,
raportate ca succes. Acum: o sesiune comună, UN commit, rollback TOTAL la orice
eșec → ori toți itemii intră, ori niciunul.

Testul-cheie: 5 itemi, crapă la al 3-lea → ZERO în DB (nu 2).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User, Document, Transaction
from app.ai.schemas import ExtractionItem
import bot_contabil as bot


def _setup(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    # auditul nu e obiectul testului (BigInteger PK nu auto-incrementeaza pe sqlite)
    monkeypatch.setattr(bot.audit_repo, "write", lambda *a, **k: None)
    s = Session()
    u = User(telegram_id=999, activity_code="ridesharing")
    s.add(u)
    s.commit()
    uid = u.id
    s.close()
    return Session, uid


def _item(i):
    return ExtractionItem(
        tip="CHELTUIALA", data="05.04.2026", platforma="Lukoil",
        detalii=f"motorina {i}", brut=100.0 + i,
        comision=0.0, tva=0.0, net=0.0, cash=0.0,
    )


def _counts(Session, uid):
    s = Session()
    nd = s.query(Document).filter(Document.user_id == uid).count()
    nt = s.query(Transaction).filter(Transaction.user_id == uid).count()
    s.close()
    return nd, nt


def _run_atomic(Session, uid, items):
    """Reproduce EXACT blocul atomic din execute_confirmed_save (o sesiune, un commit)."""
    s = Session()
    committed = False
    try:
        bot._persist_all_items(
            s, items=items, user_id=uid, source_file_id=None,
            raw_response="", prompt_version="t",
        )
        s.commit()
        committed = True
    except Exception:
        s.rollback()
    finally:
        s.close()
    return committed


def _fail_at(n_target, monkeypatch):
    """persist_transactions crapă la al n_target-lea apel (mid-loop)."""
    calls = {"n": 0}
    orig = bot.persist_transactions

    def failing(session, **kw):
        calls["n"] += 1
        if calls["n"] == n_target:
            raise RuntimeError(f"boom la item {n_target}")
        return orig(session, **kw)

    monkeypatch.setattr(bot, "persist_transactions", failing)
    return orig


# ── TESTUL-CHEIE: 5 itemi, eșec la 3 → ROLLBACK TOTAL (0, nu 2) ─────

def test_rollback_total_esec_la_item_3(tmp_path, monkeypatch):
    Session, uid = _setup(tmp_path, monkeypatch)
    _fail_at(3, monkeypatch)

    items = [_item(i) for i in range(5)]            # 5 itemi
    committed = _run_atomic(Session, uid, items)

    assert committed is False
    # ROLLBACK TOTAL: itemii 1-2 (deja add-uiți în sesiune) sunt ANULAȚI și ei.
    # Cu vechiul cod (commit per item) ar fi rămas 2 documente → bug-ul.
    assert _counts(Session, uid) == (0, 0)


# ── Succes: toate salvate, un singur commit ─────────────────────────

def test_succes_toate_salvate(tmp_path, monkeypatch):
    Session, uid = _setup(tmp_path, monkeypatch)
    items = [_item(i) for i in range(3)]
    assert _run_atomic(Session, uid, items) is True
    assert _counts(Session, uid) == (3, 3)          # 3 doc + 3 tranzacții


# ── Orfan prevenit: doc fără tranzacții nu poate rămâne ─────────────

def test_niciun_document_orfan(tmp_path, monkeypatch):
    # persist_transactions crapă la item 1 — DUPĂ ce doc-ul item 1 a fost creat.
    # Rollback total → niciun Document „posted" fără tranzacțiile lui.
    Session, uid = _setup(tmp_path, monkeypatch)
    _fail_at(1, monkeypatch)
    assert _run_atomic(Session, uid, [_item(0), _item(1)]) is False
    nd, nt = _counts(Session, uid)
    assert nd == 0 and nt == 0                       # niciun orfan (doc fără tx)


# ── Idempotență: eșec+rollback → retry salvează curat, nimic dublat ─

def test_idempotent_retry_dupa_esec(tmp_path, monkeypatch):
    Session, uid = _setup(tmp_path, monkeypatch)
    orig = _fail_at(3, monkeypatch)

    items = [_item(i) for i in range(5)]
    # 1) primul attempt crapă la item 3 → rollback total → 0
    assert _run_atomic(Session, uid, items) is False
    assert _counts(Session, uid) == (0, 0)

    # 2) retry curat (fără mock) → exact 5, NIMIC dublat din attemptul eșuat
    monkeypatch.setattr(bot, "persist_transactions", orig)
    assert _run_atomic(Session, uid, items) is True
    assert _counts(Session, uid) == (5, 5)
