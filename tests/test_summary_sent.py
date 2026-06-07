"""
Teste pentru modelul SummarySent (Faza 3 — garda anti-dublura sumar lunar).

DB sqlite izolat (tmp). Verifica:
- insert OK pentru (user, an, luna)
- al doilea insert pe aceeasi (user, an, luna) -> respins (unicitate)
- alta luna / alt an -> permis
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from app.models import User, SummarySent


def _session(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    s = Session()
    u = User(telegram_id=555)
    s.add(u)
    s.commit()
    return s, u.id


def test_insert_si_unicitate(tmp_path):
    s, uid = _session(tmp_path)

    # primul sumar pentru mai 2026 -> OK
    s.add(SummarySent(user_id=uid, period_year=2026, period_month=5))
    s.commit()
    assert s.query(SummarySent).count() == 1

    # al doilea pe aceeasi (user, an, luna) -> respins de unicitate
    s.add(SummarySent(user_id=uid, period_year=2026, period_month=5))
    with pytest.raises(IntegrityError):
        s.commit()
    s.rollback()
    assert s.query(SummarySent).count() == 1

    # alta luna -> permis
    s.add(SummarySent(user_id=uid, period_year=2026, period_month=6))
    s.commit()
    # alt an, aceeasi luna -> permis
    s.add(SummarySent(user_id=uid, period_year=2025, period_month=5))
    s.commit()
    assert s.query(SummarySent).count() == 3
    s.close()


def test_verificare_deja_trimis(tmp_path):
    # pattern-ul folosit de job: SELECT dupa (user, an, luna)
    s, uid = _session(tmp_path)
    s.add(SummarySent(user_id=uid, period_year=2026, period_month=5))
    s.commit()

    deja = (
        s.query(SummarySent)
        .filter_by(user_id=uid, period_year=2026, period_month=5)
        .first()
    )
    assert deja is not None                      # luna 5 -> deja trimis
    lipsa = (
        s.query(SummarySent)
        .filter_by(user_id=uid, period_year=2026, period_month=4)
        .first()
    )
    assert lipsa is None                         # luna 4 -> netrimis
    s.close()
