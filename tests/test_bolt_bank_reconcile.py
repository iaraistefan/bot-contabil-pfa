"""
Felia 4c — reconciliere BANCARĂ cumulativă (Bolt încasat-în-bancă vs net bancabil).

A TREIA axă, ortogonală de prezență (4a) și pas 1 brut↔declarat (4b).
CUMULATIV pe an (payout săptămânal nu respectă luna → verdict lunar ar minți).
NET vs NET, cu capcana #1: net bancabil EXCLUDE cursele cash (Bolt depune doar
card/app; cashul îl încasezi în mână). Prag larg max(50 lei, 2%).
"""

from datetime import date

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.integrations.imports import bolt_reconcile
from app.integrations import bolt_sync
from app.integrations.imports.bank_statement import BankTxn
from app.integrations.imports.classify import BankTxnClasificat, VENIT_BOLT, CHELTUIALA_BUSINESS
from app.models import User

AN = 2026


def _cl_bolt(suma, d):
    return BankTxnClasificat(BankTxn(d, suma, "IN", "Incasare OP BOLT RO"), VENIT_BOLT, "et")


# ══════════════════════════════════════════════════════════════
# bank_bolt_net_in_year — sumare pură pe an (nu doar datele)
# ══════════════════════════════════════════════════════════════
def test_bank_net_in_year_sumeaza():
    cl = [
        _cl_bolt(1000.0, date(2026, 3, 5)),
        _cl_bolt(1200.0, date(2026, 7, 12)),
        _cl_bolt(500.0, date(2025, 12, 30)),   # alt an — exclus
        BankTxnClasificat(BankTxn(date(2026, 4, 1), 50.0, "OUT", "lukoil"),
                          CHELTUIALA_BUSINESS, "et"),  # nu-i Bolt
    ]
    assert bolt_reconcile.bank_bolt_net_in_year(cl, 2026) == 2200.0
    assert bolt_reconcile.bank_bolt_net_in_year(cl, 2025) == 500.0


# ══════════════════════════════════════════════════════════════
# 1 + 6. bolt_bank_reconcile_cumulative — status pe toleranță (pur)
# ══════════════════════════════════════════════════════════════
def test_banca_egal_net_bancabil_ok():
    _, _, dif, status = bolt_reconcile.bolt_bank_reconcile_cumulative(5000.0, 5000.0)
    assert dif == 0.0 and status == "OK"


def test_reziduu_mic_sub_prag_ok():
    # 40 lei diferență pe 5000 → sub max(50, 100)=100 → OK (reziduuri 2%/TVA)
    _, _, dif, status = bolt_reconcile.bolt_bank_reconcile_cumulative(5040.0, 5000.0)
    assert dif == 40.0 and status == "OK"


def test_banca_mult_sub_bancabil_discrepanta():
    # bancă 3000 vs bancabil 5000 → -2000, peste max(50, 100) → DISCREPANȚĂ
    _, _, dif, status = bolt_reconcile.bolt_bank_reconcile_cumulative(3000.0, 5000.0)
    assert dif == -2000.0 and status == "DISCREPANTA"


def test_boundary_prag_bancar():
    # bancabil 10000 → prag = max(50, 2%×10000)=200. 200 → OK ; 200.01 → DISCREPANȚĂ.
    assert bolt_reconcile.bolt_bank_reconcile_cumulative(10200.0, 10000.0)[3] == "OK"
    assert bolt_reconcile.bolt_bank_reconcile_cumulative(10200.01, 10000.0)[3] == "DISCREPANTA"


def test_indisponibil_net_bancabil_none():
    bank, bancabil, dif, status = bolt_reconcile.bolt_bank_reconcile_cumulative(5000.0, None)
    assert status == "INDISPONIBIL" and bancabil is None and dif is None


# ══════════════════════════════════════════════════════════════
# net_bancabil_an — capcana #1 (EXCLUDE cash) — CRUCIAL
# ══════════════════════════════════════════════════════════════
def _db_cache(tmp_path):
    """DB cu tabelul bolt_orders (raw SQL, ca migrarea 008)."""
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    with eng.begin() as c:
        c.execute(text("""
            CREATE TABLE bolt_orders (
                user_id INTEGER, order_reference TEXT, order_status TEXT,
                payment_method TEXT, ride_price REAL, commission REAL,
                net_earnings REAL, tip REAL, cash_discount REAL, ride_distance INTEGER,
                finished_ts INTEGER, period_year INTEGER, period_month INTEGER,
                updated_at TEXT
            )
        """))
    return eng, sessionmaker(bind=eng)


def _order(uid, ref, pm, net, py=AN, pm_month=3, status="finished"):
    return {"uid": uid, "ref": ref, "status": status, "pm": pm, "net": net,
            "py": py, "pmonth": pm_month}


def _insert_orders(eng, orders):
    with eng.begin() as c:
        for o in orders:
            c.execute(text("""
                INSERT INTO bolt_orders (user_id, order_reference, order_status,
                    payment_method, ride_price, commission, net_earnings, tip,
                    cash_discount, ride_distance, finished_ts, period_year, period_month)
                VALUES (:uid, :ref, :status, :pm, 0, 0, :net, 0, 0, 0, 0, :py, :pmonth)
            """), o)


def test_net_bancabil_exclude_cash(tmp_path, monkeypatch):
    # CRUCIAL (capcana #1): 3 curse card (net 300) + 2 cash (net 200).
    # net bancabil = DOAR card = 300. Cashul (200) NU intră în bancă → exclus.
    eng, S = _db_cache(tmp_path)
    monkeypatch.setattr(bolt_sync, "get_session", lambda: S())
    _insert_orders(eng, [
        _order(7, "a", "card", 100.0), _order(7, "b", None, 100.0),   # card/app → bancabil
        _order(7, "c", "card", 100.0),
        _order(7, "d", "cash", 100.0), _order(7, "e", "cash", 100.0),  # cash → EXCLUS
    ])
    assert bolt_sync.net_bancabil_an(7, AN) == 300.0   # NU 500 — cashul exclus


def test_net_bancabil_cache_miss_none(tmp_path, monkeypatch):
    eng, S = _db_cache(tmp_path)
    monkeypatch.setattr(bolt_sync, "get_session", lambda: S())
    assert bolt_sync.net_bancabil_an(7, AN) is None    # an neadus → INDISPONIBIL


def test_net_bancabil_toate_cash_zero(tmp_path, monkeypatch):
    eng, S = _db_cache(tmp_path)
    monkeypatch.setattr(bolt_sync, "get_session", lambda: S())
    _insert_orders(eng, [_order(7, "d", "cash", 100.0)])
    assert bolt_sync.net_bancabil_an(7, AN) == 0.0     # rânduri, dar toate cash → 0 (nu None)


# ══════════════════════════════════════════════════════════════
# 3. Șofer cu cash → NU false-alarmă (integrare net_bancabil + reconcile)
# ══════════════════════════════════════════════════════════════
def test_sofer_cu_cash_nu_false_alarma(tmp_path, monkeypatch):
    # Bancă încasat = 300 (doar card). Bolt total net = 500 (300 card + 200 cash).
    # Fără excludere cash → 300 vs 500 = discrepanță FALSĂ. Cu excludere → 300 vs 300 OK.
    eng, S = _db_cache(tmp_path)
    monkeypatch.setattr(bolt_sync, "get_session", lambda: S())
    _insert_orders(eng, [
        _order(7, "a", "card", 100.0), _order(7, "b", "card", 100.0),
        _order(7, "c", "card", 100.0),
        _order(7, "d", "cash", 100.0), _order(7, "e", "cash", 100.0),
    ])
    bancabil = bolt_sync.net_bancabil_an(7, AN)
    _, _, dif, status = bolt_reconcile.bolt_bank_reconcile_cumulative(300.0, bancabil)
    assert status == "OK" and dif == 0.0               # NU false-alarmă


# ══════════════════════════════════════════════════════════════
# 2 + 4. Nudge — discrepanță cu cifre / indisponibil tăcere
# ══════════════════════════════════════════════════════════════
def test_nudge_discrepanta_cu_cifre(tmp_path, monkeypatch):
    eng, S = _db_cache(tmp_path)
    monkeypatch.setattr(bolt_sync, "get_session", lambda: S())
    _insert_orders(eng, [_order(7, "a", "card", 5000.0)])   # bancabil 5000
    cl = [_cl_bolt(3000.0, date(AN, 3, 5))]                  # bancă doar 3000
    s = S()
    msg = bolt_reconcile.bank_reconcile_nudge(s, 7, cl, AN)
    s.close()
    assert msg is not None
    assert "3000.00" in msg and "5000.00" in msg
    assert "Reconciliere bancară" in msg and "/bolt" in msg
    assert "Cashul nu intră" in msg                          # neutru, explică


def test_nudge_ok_intarire(tmp_path, monkeypatch):
    eng, S = _db_cache(tmp_path)
    monkeypatch.setattr(bolt_sync, "get_session", lambda: S())
    _insert_orders(eng, [_order(7, "a", "card", 3000.0)])
    cl = [_cl_bolt(3000.0, date(AN, 3, 5))]
    s = S()
    msg = bolt_reconcile.bank_reconcile_nudge(s, 7, cl, AN)
    s.close()
    assert msg is not None and "✅" in msg and "confirmă" in msg


def test_nudge_none_cache_indisponibil(tmp_path, monkeypatch):
    eng, S = _db_cache(tmp_path)          # cache gol
    monkeypatch.setattr(bolt_sync, "get_session", lambda: S())
    cl = [_cl_bolt(3000.0, date(AN, 3, 5))]
    s = S()
    assert bolt_reconcile.bank_reconcile_nudge(s, 7, cl, AN) is None   # INDISPONIBIL → tăcere
    s.close()


def test_nudge_none_fara_bolt_in_extras(tmp_path, monkeypatch):
    eng, S = _db_cache(tmp_path)
    monkeypatch.setattr(bolt_sync, "get_session", lambda: S())
    cl = [BankTxnClasificat(BankTxn(date(AN, 4, 1), 50.0, "OUT", "lukoil"),
                            CHELTUIALA_BUSINESS, "et")]
    s = S()
    assert bolt_reconcile.bank_reconcile_nudge(s, 7, cl, AN) is None
    s.close()


# ══════════════════════════════════════════════════════════════
# append_bank_nudge — aditiv + defensiv
# ══════════════════════════════════════════════════════════════
_PREVIEW = "✅ *34 tranzacții*"


def test_append_bank_nudge_defensiv(tmp_path, monkeypatch):
    eng, S = _db_cache(tmp_path)
    monkeypatch.setattr(bolt_sync, "get_session", lambda: S())
    monkeypatch.setattr(bolt_reconcile, "bank_reconcile_nudge",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    s = S()
    out = bolt_reconcile.append_bank_nudge(_PREVIEW, s, 7, [], AN)
    s.close()
    assert out == _PREVIEW                 # preview neatins la eroare


# ══════════════════════════════════════════════════════════════
# 5. ORTOGONALITATE — pas 2 (bancar) nu atinge pas 1 (brut) nici prezența
# ══════════════════════════════════════════════════════════════
def test_ortogonalitate_axe_independente():
    # Pas 1 (brut↔declarat) — funcție + constante proprii, neatinse
    assert bolt_reconcile.bolt_amount_reconcile(1000.0, 1000.0)[3] == "OK"
    assert bolt_reconcile.RECON_TOL_ABS == 5.0
    # Pas 2 (bancar) — constante proprii, LARGI, separate
    assert bolt_reconcile.BANK_RECON_TOL_ABS == 50.0
    assert bolt_reconcile.BANK_RECON_TOL_PCT == 0.02
    # Prezența — funcție proprie, neatinsă
    assert hasattr(bolt_reconcile, "bolt_reconcile_nudge")
    # Cele 3 axe folosesc funcții distincte (nume diferite → zero suprapunere)
    assert bolt_reconcile.bolt_amount_reconcile is not bolt_reconcile.bolt_bank_reconcile_cumulative
