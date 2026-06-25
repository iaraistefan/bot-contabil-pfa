"""
Izolare multi-tenant LA GRANIȚĂ (audit #5 / I1).

Securitatea backend e corectă (scope pe user_id în repo-uri), DAR era PRESUPUSĂ, nu
dovedită — toate testele web mock-uiau `_require_user`. Aici creăm 2 useri REALI (A, B)
și exercităm izolarea prin seam-ul DEV_USER_ID (auth REAL, NU mock), exact ca
test_document_download. Dacă un refactor sparge scope-ul, testul cade.

Plus întărirea preventivă a footgun-ului `documents.get_by_id` (user_id obligatoriu) —
elimină CLASA de bug (niciun viitor apelant poate „uita" user_id), nu doar starea curentă.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.http import app as webapp
from app.repositories import documents as documents_repo
from app.models import User, Document, Transaction, Vehicul, TripLog


def _setup(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    monkeypatch.setattr(webapp, "get_session", lambda: Session())

    s = Session()
    A = User(telegram_id=111)
    B = User(telegram_id=222)
    s.add_all([A, B])
    s.commit()
    aid, bid = A.id, B.id

    def _seed_income(uid, brut, counterparty):
        doc = Document(user_id=uid, data_doc="15.06.2026", tip="VENIT",
                       brut=brut, status="posted")
        s.add(doc)
        s.commit()
        tx = Transaction(
            user_id=uid, document_id=doc.id, tx_type="INCOME",
            category="venit_bolt", amount_brut=brut, amount_net=brut,
            occurred_on=date(2026, 6, 15), period_year=2026, period_month=6,
            counterparty=counterparty,
        )
        s.add(tx)
        s.commit()
        return doc.id

    a_doc = _seed_income(aid, 100.0, "A-CORP")
    b_doc = _seed_income(bid, 999.0, "B-SECRET")

    # B: vehicul + tură (ca să verificăm că nu se scurg către A)
    bveh = Vehicul(user_id=bid, nr_inmatriculare="B-99-XXX", activ=True)
    s.add(bveh)
    s.commit()
    s.add(TripLog(user_id=bid, vehicul_id=bveh.id, trip_date=date(2026, 6, 10),
                  km=42.0, period_year=2026, period_month=6))
    s.commit()

    ids = {"A": aid, "B": bid, "a_doc": a_doc, "b_doc": b_doc}
    s.close()
    return ids, Session


def _client(monkeypatch, uid):
    monkeypatch.setenv("DEV_USER_ID", str(uid))
    webapp.flask_app.config["TESTING"] = True
    return webapp.flask_app.test_client()


# ── Izolare la graniță (auth real prin DEV_USER_ID) ──────────

def test_transactions_izolate(monkeypatch, tmp_path):
    ids, _ = _setup(tmp_path, monkeypatch)
    c = _client(monkeypatch, ids["A"])
    r = c.get("/api/v1/transactions/2026/6")
    assert r.status_code == 200
    body = r.get_json()
    cps = [t["counterparty"] for t in body["transactions"]]
    assert "A-CORP" in cps              # A își vede tranzacția
    assert "B-SECRET" not in cps        # NU vede tranzacția lui B
    assert body["count"] == 1


def test_period_izolat(monkeypatch, tmp_path):
    ids, _ = _setup(tmp_path, monkeypatch)
    c = _client(monkeypatch, ids["A"])
    r = c.get("/api/v1/period/2026/6")
    assert r.status_code == 200
    totals = r.get_json()
    # venitul lui A (100), NU al lui B (999) și nici suma (1099)
    assert totals["income_total"] == 100.0
    assert totals["income_total"] not in (999.0, 1099.0)


def test_parcurs_izolat(monkeypatch, tmp_path):
    ids, _ = _setup(tmp_path, monkeypatch)
    c = _client(monkeypatch, ids["A"])
    r = c.get("/api/v1/parcurs/2026/6")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ture"] == []           # tura lui B nu se scurge
    assert body["vehicul"] is None      # vehiculul lui B nu apare


# ── get_by_id: ownership + întărire footgun ──────────────────

def test_get_by_id_respecta_ownership(monkeypatch, tmp_path):
    ids, Session = _setup(tmp_path, monkeypatch)
    s = Session()
    # A NU poate citi documentul lui B prin id
    assert documents_repo.get_by_id(s, doc_id=ids["b_doc"], user_id=ids["A"]) is None
    # B își citește propriul document
    own = documents_repo.get_by_id(s, doc_id=ids["b_doc"], user_id=ids["B"])
    assert own is not None and own.id == ids["b_doc"]
    s.close()


def test_get_by_id_user_id_obligatoriu(monkeypatch, tmp_path):
    # ÎNTĂRIRE: imposibil să apelezi get_by_id fără user_id (elimină clasa de bug —
    # niciun apelant viitor nu poate „uita" scope-ul și transforma footgun-ul în hole).
    ids, Session = _setup(tmp_path, monkeypatch)
    s = Session()
    with pytest.raises(TypeError):
        documents_repo.get_by_id(s, doc_id=ids["b_doc"])   # fără user_id → interzis
    s.close()


# ── DEV_USER_ID gating ───────────────────────────────────────

def test_dev_user_id_dezactivat_in_productie(monkeypatch, tmp_path):
    ids, _ = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(webapp.settings, "env", "production")
    monkeypatch.setenv("DEV_USER_ID", str(ids["A"]))
    webapp.flask_app.config["TESTING"] = True
    c = webapp.flask_app.test_client()
    # env=production + fără X-Telegram-Init-Data → DEV_USER_ID NU e cheie universală
    r = c.get("/api/v1/transactions/2026/6")
    assert r.status_code == 401
