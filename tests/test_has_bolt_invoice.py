"""
Fiscal #4 — `has_taxable_bolt_invoice`: semnalul „are factură Bolt taxabilă"
= vat_out_total>0 (sursă unică, ca web/banner), NU vechiul filtru
(EXPENSE + REVERSE_CHARGE) care era relicvă de model vechi → mereu False.

Testul DOVEDEȘTE bug-ul: pe o factură comision reală (VAT_OUT/REVERSE_CHARGE)
vechiul filtru dă False, helper-ul dă True.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import tax_engine
from app.models import User, Transaction

Y, M = 2026, 5


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
                amount_net=0.0, currency="RON", period_year=Y,
                period_month=M, locked=False)
    base.update(kw)
    return Transaction(**base)


def _old_filter_has_bolt(s, uid):
    """Filtrul VECHI (bug) — reprodus aici DOAR ca să dovedim regresia."""
    return (
        s.query(Transaction)
        .filter(
            Transaction.user_id == uid,
            Transaction.period_year == Y,
            Transaction.period_month == M,
            Transaction.vat_treatment == "REVERSE_CHARGE",
            Transaction.tx_type == "EXPENSE",
        )
        .count()
    ) > 0


def _has(s, uid):
    return tax_engine.has_taxable_bolt_invoice(s, user_id=uid, year=Y, month=M)


# ── DOVADA BUG → FIX ────────────────────────────────────────────────

def test_factura_comision_vat_out_declanseaza(tmp_path):
    # FACTURA_COMISION reală: VAT_OUT cu REVERSE_CHARGE (cum o postează
    # posting._post_factura_comision după vat-engine).
    s, uid = _db(tmp_path)
    s.add(_tx(uid, tx_type="VAT_OUT", vat_treatment="REVERSE_CHARGE",
              amount_brut=137.97, amount_vat=137.97))
    s.commit()
    # BUG: vechiul filtru (EXPENSE+REVERSE_CHARGE) NU vede VAT_OUT → False
    assert _old_filter_has_bolt(s, uid) is False
    # FIX: helper-ul aliniat la vat_out_total>0 → True (D301/D390/D100 „de depus")
    assert _has(s, uid) is True
    s.close()


# ── GRANIȚA (documentată, nerezolvată în #4) ────────────────────────

def test_report_only_expense_nu_declanseaza(tmp_path):
    # Comision DOAR din raport Bolt: EXPENSE 'AUTO_FROM_REPORT', FĂRĂ factură
    # formală → NU produce VAT_OUT → helper False. CORECT pe modelul actual
    # (reverse charge se naște din factura formală, nu din raport). Caz
    # documentat în coada-fiscala.md (#4 report-only), nerezolvat intenționat.
    s, uid = _db(tmp_path)
    s.add(_tx(uid, tx_type="EXPENSE", vat_treatment="AUTO_FROM_REPORT",
              category="platform_commission", amount_brut=300.0))
    s.commit()
    assert _has(s, uid) is False
    s.close()


# ── Cazuri de bază ──────────────────────────────────────────────────

def test_fara_nimic_false(tmp_path):
    s, uid = _db(tmp_path)
    assert _has(s, uid) is False
    s.close()


def test_vat_out_alta_luna_nu_declanseaza(tmp_path):
    # izolare pe perioadă: VAT_OUT în aprilie nu declanșează mai
    s, uid = _db(tmp_path)
    s.add(_tx(uid, tx_type="VAT_OUT", vat_treatment="REVERSE_CHARGE",
              amount_brut=100.0, amount_vat=100.0, period_month=4))
    s.commit()
    assert _has(s, uid) is False
    s.close()


def test_vat_out_locked_exclus(tmp_path):
    # locked → exclus din compute_period → helper False (consistent cu sursa)
    s, uid = _db(tmp_path)
    s.add(_tx(uid, tx_type="VAT_OUT", vat_treatment="REVERSE_CHARGE",
              amount_brut=100.0, amount_vat=100.0, locked=True))
    s.commit()
    assert _has(s, uid) is False
    s.close()
