"""
Felia 4b — reconciliere pe SUMĂ a venitului Bolt (axa curată: API brut vs declarat).

Ortogonal de reconcilierea de PREZENȚĂ (has_bolt_income, test_bolt_reconcile.py):
prezența acoperă luni NEsincronizate; suma acoperă luni SINCRONIZATE dar divergente.
Ambele BRUTE, lunare, tip-exclusive → comparabile direct. Prag: max(5 lei, 1%).
"""

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.integrations.imports import bolt_reconcile
from app.integrations import bolt_sync
from app.integrations.imports.bank_statement import BankTxn
from app.integrations.imports.classify import BankTxnClasificat, VENIT_BOLT
from app.models import User, Document, Transaction


def _db(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S()
    u = User(telegram_id=1, activity_code="ridesharing")
    s.add(u); s.commit(); uid = u.id; s.close()
    return S, uid


# ══════════════════════════════════════════════════════════════
# 1 + 4 + 6. bolt_amount_reconcile — status pe toleranță (pur)
# ══════════════════════════════════════════════════════════════
def test_suma_egala_ok():
    api, dec, dif, status = bolt_reconcile.bolt_amount_reconcile(1000.0, 1000.0)
    assert (api, dec, dif, status) == (1000.0, 1000.0, 0.0, "OK")


def test_rotunjire_mica_sub_prag_ok():
    # 3 lei diferență pe 1000 → sub max(5, 10)=10 → OK (rotunjire, nu eroare)
    _, _, dif, status = bolt_reconcile.bolt_amount_reconcile(1000.0, 1003.0)
    assert dif == 3.0 and status == "OK"


def test_divergenta_peste_prag_discrepanta():
    # 250 lei lipsă pe 5000 → peste max(5, 50)=50 → DISCREPANȚĂ
    api, dec, dif, status = bolt_reconcile.bolt_amount_reconcile(5000.0, 4750.0)
    assert dif == -250.0 and status == "DISCREPANTA"


def test_boundary_prag_absolut_domina_la_sume_mici():
    # brut mic → prag = max(5, 1) = 5. Exact 5 → OK ; 5.01 → DISCREPANȚĂ.
    assert bolt_reconcile.bolt_amount_reconcile(100.0, 105.0)[3] == "OK"
    assert bolt_reconcile.bolt_amount_reconcile(100.0, 105.01)[3] == "DISCREPANTA"


def test_boundary_prag_relativ_domina_la_sume_mari():
    # brut mare → prag = max(5, 1%×10000) = 100. Exact 100 → OK ; 100.01 → DISCREPANȚĂ.
    assert bolt_reconcile.bolt_amount_reconcile(10000.0, 10100.0)[3] == "OK"
    assert bolt_reconcile.bolt_amount_reconcile(10000.0, 10100.01)[3] == "DISCREPANTA"


# ══════════════════════════════════════════════════════════════
# 3. INDISPONIBIL — brut_api None + get_month_summary cache_only
# ══════════════════════════════════════════════════════════════
def test_indisponibil_brut_api_none():
    api, dec, dif, status = bolt_reconcile.bolt_amount_reconcile(None, 1000.0)
    assert status == "INDISPONIBIL" and api is None and dec == 1000.0
    # confirm_line pe indisponibil → None (tăcere, nu inventăm)
    assert bolt_reconcile.bolt_amount_confirm_line(None, 1000.0) is None


def test_get_month_summary_cache_only_miss(monkeypatch):
    # cache_only=True, cache gol → source cache_miss, n=0, ZERO lovire API.
    monkeypatch.setattr(bolt_sync, "_cache_read_period", lambda *a, **k: [])
    s = bolt_sync.get_month_summary(7, 2026, 4, cache_only=True)
    assert s["source"] == "cache_miss" and s["n"] == 0 and s["brut"] == 0.0


# ══════════════════════════════════════════════════════════════
# 2. Linia de confirmare (b) — ✅ pe OK, ⚠️ cu cifre + cauze pe discrepanță
# ══════════════════════════════════════════════════════════════
def test_confirm_line_ok_pozitiv():
    line = bolt_reconcile.bolt_amount_confirm_line(1000.0, 1000.0)
    assert "confirmă" in line and "1000.00" in line and "✅" in line


def test_confirm_line_discrepanta_cu_cifre_si_cauze():
    line = bolt_reconcile.bolt_amount_confirm_line(5000.0, 4750.0)
    assert "4750.00" in line and "5000.00" in line     # ambele cifre
    assert "-250.00" in line                           # diferența semnată
    assert "sync mai vechi" in line and "manual" in line  # cauze normale (neutru)
    assert "/bolt" in line                             # acțiunea de corecție


# ══════════════════════════════════════════════════════════════
# declared_bolt_brut — din income_by_platform (sursă unică)
# ══════════════════════════════════════════════════════════════
def _income(uid, counterparty, amount, y=2026, m=4):
    return Transaction(
        user_id=uid, document_id=1, tx_type="INCOME", category="ride_revenue",
        amount_brut=amount, amount_vat=0.0, amount_net=amount, currency="RON",
        payment_method="CARD", counterparty=counterparty,
        period_year=y, period_month=m, locked=False,
    )


def test_declared_bolt_brut_din_registru(tmp_path):
    S, uid = _db(tmp_path)
    s = S()
    s.add_all([_income(uid, "Bolt Operations OÜ", 700.0),
               _income(uid, "Bolt Operations OÜ", 300.0),
               _income(uid, "Uber B.V.", 500.0)])       # Uber — nu intră la bolt
    s.commit()
    assert bolt_reconcile.declared_bolt_brut(s, uid, 2026, 4) == 1000.0
    s.close()


def test_declared_bolt_brut_zero_fara_bolt(tmp_path):
    S, uid = _db(tmp_path)
    assert bolt_reconcile.declared_bolt_brut(S(), uid, 2026, 4) == 0.0


# ══════════════════════════════════════════════════════════════
# 5. ORTOGONALITATE prezență ↔ sumă — nu se dublează
# ══════════════════════════════════════════════════════════════
def _add_bolt_income_doc(S, uid):
    s = S()
    doc = Document(user_id=uid, tip="VENIT", platforma="Bolt",
                   data_doc="30.04.2026", status="posted")
    s.add(doc); s.commit()
    s.add(Transaction(user_id=uid, document_id=doc.id, tx_type="INCOME",
                      category="ride_revenue", amount_brut=1000.0,
                      counterparty="Bolt Operations OÜ",
                      period_year=2026, period_month=4, locked=False))
    s.commit(); s.close()


def _cl_bolt(suma, d):
    return BankTxnClasificat(BankTxn(d, suma, "IN", "Incasare OP BOLT RO"), VENIT_BOLT, "et")


def test_ortogonalitate_sync_diverg_prezenta_tace_suma_vorbeste(tmp_path):
    # Lună SINCRONIZATĂ (are venit Bolt) → prezența TACE (nu cere /bolt inutil).
    # Dar suma poate diverge → axa sumă o prinde. Cele două NU se dublează.
    S, uid = _db(tmp_path)
    _add_bolt_income_doc(S, uid)
    clasificate = [_cl_bolt(248.33, date(2026, 4, 14))]
    s = S()
    prezenta = bolt_reconcile.bolt_reconcile_nudge(s, uid, clasificate)
    s.close()
    assert prezenta is None                            # SINCRONIZAT → prezența tace

    # Axa sumă, independent: API 1200 vs declarat 1000 → discrepanță (prezența nu o vede)
    _, _, _, status = bolt_reconcile.bolt_amount_reconcile(1200.0, 1000.0)
    assert status == "DISCREPANTA"


def test_ortogonalitate_nesync_prezenta_vorbeste(tmp_path):
    # Lună NEsincronizată → prezența vorbește; suma nu se aplică (nimic declarat).
    S, uid = _db(tmp_path)
    clasificate = [_cl_bolt(248.33, date(2026, 4, 14))]
    s = S()
    prezenta = bolt_reconcile.bolt_reconcile_nudge(s, uid, clasificate)
    s.close()
    assert prezenta is not None and "Verificare venit Bolt" in prezenta
