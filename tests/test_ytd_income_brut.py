"""
Teste pentru pre-check-ul ieftin _ytd_income_brut (Faza 3 plafon — PAS 2).

SUM(amount_brut) DOAR pe: tx_type=INCOME, period_year=an, locked=False.
"""

from app.services.proactive_alerts import _ytd_income_brut, PLAFON_PRECHECK_RON
from app.models import User, Transaction
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _db(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    s = Session()
    u = User(telegram_id=42)
    s.add(u)
    s.commit()
    return s, u.id


def _tx(uid, **kw):
    base = dict(user_id=uid, document_id=1, tx_type="INCOME",
               category="ride_revenue", amount_brut=0.0, amount_vat=0.0,
               amount_net=0.0, currency="RON", period_year=2026,
               period_month=5, locked=False)
    base.update(kw)
    return Transaction(**base)


def test_suma_doar_income_anul_si_unlocked(tmp_path):
    s, uid = _db(tmp_path)
    s.add_all([
        _tx(uid, amount_brut=1000.0),                       # INCOME 2026 → numără
        _tx(uid, amount_brut=500.0),                        # INCOME 2026 → numără
        _tx(uid, tx_type="EXPENSE", amount_brut=300.0),     # EXPENSE → NU
        _tx(uid, tx_type="VAT_OUT", amount_brut=99.0),      # VAT_OUT → NU
        _tx(uid, period_year=2025, amount_brut=9999.0),     # alt an → NU
        _tx(uid, locked=True, amount_brut=7777.0),          # locked → NU
    ])
    s.commit()
    assert _ytd_income_brut(s, uid, 2026) == 1500.0         # doar cele 2 INCOME 2026
    s.close()


def test_suma_zero_fara_tranzactii(tmp_path):
    s, uid = _db(tmp_path)
    assert _ytd_income_brut(s, uid, 2026) == 0.0            # coalesce → 0, nu None
    s.close()


def test_izolare_pe_user(tmp_path):
    s, uid = _db(tmp_path)
    alt = User(telegram_id=99)
    s.add(alt)
    s.commit()
    s.add_all([_tx(uid, amount_brut=200.0), _tx(alt.id, amount_brut=5000.0)])
    s.commit()
    assert _ytd_income_brut(s, uid, 2026) == 200.0          # doar userul cerut
    s.close()


def test_constanta_precheck():
    assert PLAFON_PRECHECK_RON == 38_880                    # 0.8 × 48.600 (CAS 12 SMB)
