"""
Golden test pentru parserul BT (Faza 3 — import extras bancar, felia 1).

Fixture: tests/fixtures/extras_bt_anon.pdf — extras BT real (aprilie 2026)
ANONIMIZAT (nume/CUI/IBAN/REF fictive), dar cu structura coloanelor, pozițiile
x, sumele reale și RULAJ TOTAL CONT (checksum-ul) păstrate EXACT.

Zona de bani → accent pe corectitudine:
- golden count + sume de control (= RULAJ TOTAL CONT din extras),
- spot-check pe tranzacții concrete (BOLT, ANTHROPIC/merchant, returnare),
- NEGATIV: sumele de zgomot din descriere (6.05 EUR, 0.00 comision) NU sunt capturate,
- checksum: parserul se auto-verifică și ridică eroare la nepotrivire.
"""
from datetime import date
from pathlib import Path

import pytest

from app.integrations.imports.bt_parser import parse_bt_pdf, _finalize
from app.integrations.imports.bank_statement import BankTxn, BankStatementError

FIXTURE = Path(__file__).parent / "fixtures" / "extras_bt_anon.pdf"


@pytest.fixture(scope="module")
def txns():
    return parse_bt_pdf(FIXTURE.read_bytes())


# ────────────────────────────────────────────────────────────
# GOLDEN COUNT + SUME DE CONTROL (= RULAJ TOTAL CONT)
# ────────────────────────────────────────────────────────────

def test_golden_count(txns):
    assert len(txns) == 34


def test_sume_control(txns):
    out = round(sum(t.suma for t in txns if t.directie == "OUT"), 2)
    inc = round(sum(t.suma for t in txns if t.directie == "IN"), 2)
    assert out == 769.77          # = RULAJ TOTAL CONT Debit
    assert inc == 1019.45         # = RULAJ TOTAL CONT Credit


def test_split_directie(txns):
    assert sum(1 for t in txns if t.directie == "OUT") == 23
    assert sum(1 for t in txns if t.directie == "IN") == 11


# ────────────────────────────────────────────────────────────
# SPOT-CHECK pe tranzacții concrete
# ────────────────────────────────────────────────────────────

def test_spot_bolt_incasare(txns):
    # 14/04 încasare BOLT 248.33 (credit → IN)
    m = [t for t in txns if t.data == date(2026, 4, 14) and t.suma == 248.33]
    assert len(m) == 1 and m[0].directie == "IN"


def test_spot_plata_card(txns):
    # 02/04 plată POS 31.81 (debit → OUT)
    m = [t for t in txns if t.data == date(2026, 4, 2) and t.suma == 31.81]
    assert len(m) == 1 and m[0].directie == "OUT"


def test_spot_returnare(txns):
    # 30/04 returnare plată 7.00 (credit → IN)
    m = [t for t in txns if t.data == date(2026, 4, 30) and t.suma == 7.00]
    assert len(m) == 1 and m[0].directie == "IN"


def test_spot_comision(txns):
    # comisioane OP de 0.51 (8 bucăți, toate OUT)
    com = [t for t in txns if t.suma == 0.51]
    assert len(com) == 8 and all(t.directie == "OUT" for t in com)


def test_descriere_curata(txns):
    # descrierea NU începe cu data și NU se termină cu suma (contractul neutru)
    t = [t for t in txns if t.data == date(2026, 4, 14) and t.suma == 248.33][0]
    assert not t.descriere[:10].count("/") >= 2     # fără dd/mm/yyyy în față
    assert "Incasare OP" in t.descriere
    assert not t.descriere.endswith("248.33")


def test_carry_forward_data(txns):
    # a 2-a tranzacție din 20/04 (Incasare OP 194.32) n-are dată proprie →
    # moștenește 20/04 prin carry-forward
    m = [t for t in txns if t.data == date(2026, 4, 20) and t.suma == 194.32]
    assert len(m) == 1 and m[0].directie == "IN"


# ────────────────────────────────────────────────────────────
# NEGATIV — zgomotul din descriere NU e capturat ca tranzacție
# ────────────────────────────────────────────────────────────

def test_zgomot_nu_e_capturat(txns):
    sume = [t.suma for t in txns]
    # 6.05 (valoare tranzactie EUR) și 0.00 (comision) apar în descriere, NU în coloane
    assert 6.05 not in sume
    assert 0.00 not in sume
    # 13.99 (valoarea EUR Netflix) la fel — nu e o tranzacție RON
    assert 13.99 not in sume


def test_fara_rezidual_de_control(txns):
    # valorile de sold/total NU trebuie să apară ca tranzacții
    sume = [t.suma for t in txns]
    for ctrl in (529.54, 779.22, 684.21, 459.22):   # SOLD ANTERIOR/FINAL, TOTAL DISPONIBIL
        assert ctrl not in sume


# ────────────────────────────────────────────────────────────
# CHECKSUM — auto-verificare
# ────────────────────────────────────────────────────────────

def test_checksum_se_potriveste(txns):
    # _finalize cu control corect → trece fără eroare
    res = _finalize(txns, (769.77, 1019.45))
    assert res is txns


def test_checksum_nepotrivit_ridica_eroare(txns):
    with pytest.raises(BankStatementError, match="Checksum nepotrivit"):
        _finalize(txns, (999.99, 1019.45))


def test_checksum_lipsa_ridica_eroare(txns):
    with pytest.raises(BankStatementError):
        _finalize(txns, (None, None))


def test_pdf_fara_total_ridica_eroare():
    # un PDF gol/fără RULAJ TOTAL CONT → eroare clară, nu date parțiale
    import io
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 700, "fără tabel de tranzacții")
    c.showPage()
    c.save()
    with pytest.raises(BankStatementError, match="RULAJ TOTAL CONT negăsit"):
        parse_bt_pdf(buf.getvalue())
