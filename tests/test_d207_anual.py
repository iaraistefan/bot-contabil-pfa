"""
D207 — agregatorul anual per brand + reconcilierea cu D100 (DECIZIA A2).

`nerezident_anual_by_brand` bucleaza cele 12 luni (tiparul din
_compute_d212_anual_uncached), apeleaza `vat_out_by_brand` per luna si acumuleaza
baza comisionului per brand = Σ vat_out / cota_tva. Prin construcție reconciliaza
cu Σ 12× baza D100 lunar → D207 anual == suma D100-urilor (ce cross-verifica ANAF).
"""

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import tax_engine
from app.services.tax_engine import vat_out_by_brand, nerezident_anual_by_brand
from app.domain.tax_rules import cota_tva
from app.models import User, Transaction

AN = 2026  # cota TVA 21% toate lunile → cifre curate


def _db(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    u = User(telegram_id=7)
    s.add(u); s.commit()
    return s, u.id


def _vat_out(uid, counterparty, amount, luna):
    return Transaction(
        user_id=uid, document_id=1, tx_type="VAT_OUT",
        category="REVERSE_CHARGE_VAT", amount_brut=amount, amount_vat=amount,
        amount_net=0.0, currency="RON", deductibility_pct=0, payment_method="CARD",
        counterparty=counterparty, vat_treatment="REVERSE_CHARGE",
        period_year=AN, period_month=luna, locked=False,
    )


# ════════════════════════════════════════════════════════
# 4a. Agregare pe 12 luni per brand (baza = Σ vat_out / cota)
# ════════════════════════════════════════════════════════
def test_agregare_anuala_per_brand(tmp_path):
    s, uid = _db(tmp_path)
    # Bolt in ian (vat 21 → baza 100) + mar (vat 42 → baza 200) = baza 300.
    # Uber in feb (vat 21 → baza 100). Restul lunilor: gol → 0.
    s.add_all([
        _vat_out(uid, "Bolt Operations OÜ", 21.0, 1),
        _vat_out(uid, "Bolt Operations OÜ", 42.0, 3),
        _vat_out(uid, "Uber B.V.", 21.0, 2),
    ])
    s.commit()

    anual = nerezident_anual_by_brand(s, user_id=uid, an=AN)
    assert anual["bolt"] == 300.0     # (21 + 42) / 0.21
    assert anual["uber"] == 100.0     # 21 / 0.21


# ════════════════════════════════════════════════════════
# 4b. RECONCILIERE: anual[brand] == Σ 12× baza D100 lunar[brand]
# ════════════════════════════════════════════════════════
def test_reconciliere_cu_suma_d100_lunar(tmp_path):
    s, uid = _db(tmp_path)
    s.add_all([
        _vat_out(uid, "Bolt Operations OÜ", 21.0, 1),
        _vat_out(uid, "Bolt Operations OÜ", 42.0, 3),
        _vat_out(uid, "Bolt Operations OÜ", 63.0, 7),
        _vat_out(uid, "Uber B.V.", 21.0, 2),
        _vat_out(uid, "Uber B.V.", 105.0, 11),
    ])
    s.commit()

    anual = nerezident_anual_by_brand(s, user_id=uid, an=AN)

    # Recalcul INDEPENDENT al bazei D100 lunar (vat_out_by_brand / cota_tva) pe 12 luni.
    for brand in ("bolt", "uber"):
        suma_d100_lunar = 0.0
        for m in range(1, 13):
            by = vat_out_by_brand(s, user_id=uid, year=AN, month=m)
            vat = by.get(brand, 0.0)
            if vat:
                suma_d100_lunar += vat / cota_tva(date(AN, m, 1))
        assert round(anual.get(brand, 0.0), 2) == round(suma_d100_lunar, 2)


# ════════════════════════════════════════════════════════
# 4c. Neatribuit se propaga pe cheia None (tratat la generare)
# ════════════════════════════════════════════════════════
def test_neatribuit_pe_cheia_none(tmp_path):
    s, uid = _db(tmp_path)
    s.add_all([
        _vat_out(uid, "Bolt Operations OÜ", 21.0, 1),
        _vat_out(uid, "Mister X SRL", 21.0, 5),    # brand non-rideshare → None
    ])
    s.commit()
    anual = nerezident_anual_by_brand(s, user_id=uid, an=AN)
    assert anual["bolt"] == 100.0
    assert anual[None] == 100.0                     # neatribuit → genereaza_d207 va opri


def test_an_gol(tmp_path):
    s, uid = _db(tmp_path)
    assert nerezident_anual_by_brand(s, user_id=uid, an=AN) == {}
