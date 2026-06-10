"""
Teste PAS 2 felia 5a — compensare plată↔returnare (cazul de aur al feliei 5).

Pe extrasul REAL, toate plățile de taxe au fost respinse (returnare-pereche) →
0 plăți reale → nimic de marcat achitat. Acesta e testul-ancoră: o felie care
ar da altceva pe fixture ar marca FALS obligații achitate (eroare fiscală).
"""
from datetime import date
from pathlib import Path

from app.integrations.imports.bank_statement import BankTxn
from app.integrations.imports.bt_parser import parse_bt_pdf
from app.integrations.imports.classify import (
    classify_bt, BankTxnClasificat, ObligatieHint, PLATA_TAXA, RETURNARE_TAXA,
)
from app.integrations.imports.tax_payments import compensate, real_payment_indices
from app.activities.ridesharing import RidesharingActivity as ACT

_FIXTURE = Path(__file__).parent / "fixtures" / "extras_bt_anon.pdf"


def _plata(tip, decl, luna, an, suma, d=date(2026, 4, 27)):
    o = ObligatieHint(tip, decl, luna, an, "X")
    return BankTxnClasificat(BankTxn(d, suma, "OUT", "plata"), PLATA_TAXA, "et", oblig=o)


def _retur(tip, decl, luna, an, suma, d=date(2026, 4, 30)):
    o = ObligatieHint(tip, decl, luna, an, "X")
    return BankTxnClasificat(BankTxn(d, suma, "IN", "returnare"), RETURNARE_TAXA, "et", oblig=o)


# ──────────────────────────────────────────────────────────────
# 1. ⭐ CAZUL DE AUR — fixture real: 8 plăți + 8 returnări → 0 reale
# ──────────────────────────────────────────────────────────────
def test_fixture_cazul_de_aur_zero_reale():
    txns = parse_bt_pdf(_FIXTURE.read_bytes())
    clasificate = [classify_bt(t, ACT) for t in txns]
    reale = compensate(clasificate)
    assert reale == []          # toate respinse → ZERO plăți reale → nimic achitat


# ──────────────────────────────────────────────────────────────
# 2. re-plată — 2 plăți + 1 returnare → 1 reală (NU „anulează tot")
# ──────────────────────────────────────────────────────────────
def test_re_plata_o_singura_reala():
    cl = [
        _plata("TVA", "D301", 1, 2026, 138.0),
        _plata("TVA", "D301", 1, 2026, 138.0),
        _retur("TVA", "D301", 1, 2026, 138.0),
    ]
    reale = compensate(cl)
    assert len(reale) == 1
    assert reale[0].bucket == PLATA_TAXA


# ──────────────────────────────────────────────────────────────
# 3. sumă diferită — plată 138 + returnare 40 (același tip+lună) → 138 reală
# ──────────────────────────────────────────────────────────────
def test_suma_diferita_grupuri_distincte():
    cl = [
        _plata("TVA", "D301", 1, 2026, 138.0),
        _retur("TVA", "D301", 1, 2026, 40.0),   # altă sumă → alt grup, n-o atinge
    ]
    reale = compensate(cl)
    assert len(reale) == 1
    assert round(reale[0].txn.suma, 2) == 138.0


# ──────────────────────────────────────────────────────────────
# 4. returnări > plăți — 1 plată + 2 returnări → 0, NU negativ, NU crapă
# ──────────────────────────────────────────────────────────────
def test_returnari_mai_multe_decat_plati():
    cl = [
        _plata("Impozit", "D100", 2, 2026, 4.0),
        _retur("Impozit", "D100", 2, 2026, 4.0),
        _retur("Impozit", "D100", 2, 2026, 4.0),
    ]
    assert compensate(cl) == []          # max(0, 1-2) = 0


# ──────────────────────────────────────────────────────────────
# 5. fără hint — oblig=None → necompensat, nu apare ca plată reală
#    (5c oricum nu o poate match-ui → zero „achitat" fals)
# ──────────────────────────────────────────────────────────────
def test_fara_hint_iesita_din_compensare():
    cl = [BankTxnClasificat(
        BankTxn(date(2026, 4, 1), 50.0, "OUT", "plata"), PLATA_TAXA, "et", oblig=None)]
    assert compensate(cl) == []


# ──────────────────────────────────────────────────────────────
# 6. plată reală fără returnare → rămâne reală
# ──────────────────────────────────────────────────────────────
def test_plata_fara_returnare_ramane_reala():
    cl = [_plata("TVA", "D301", 3, 2026, 41.0)]
    reale = compensate(cl)
    assert len(reale) == 1
    assert reale[0].oblig.luna == 3


# ──────────────────────────────────────────────────────────────
# 7. DETERMINISM — aceeași listă de 2 ori → exact același rezultat
# ──────────────────────────────────────────────────────────────
def test_compensare_determinista_fixture():
    txns = parse_bt_pdf(_FIXTURE.read_bytes())
    cl = [classify_bt(t, ACT) for t in txns]
    assert compensate(cl) == compensate(cl)


def test_compensare_determinista_mixt():
    cl = [
        _plata("TVA", "D301", 1, 2026, 138.0),
        _plata("TVA", "D301", 1, 2026, 138.0),
        _retur("TVA", "D301", 1, 2026, 138.0),
        _plata("Impozit", "D100", 3, 2026, 4.0),
    ]
    assert compensate(cl) == compensate(cl)


# ──────────────────────────────────────────────────────────────
# real_payment_indices — sursa unică (compensate = wrapper); pe INDICI
# ──────────────────────────────────────────────────────────────
def test_real_payment_indices_pe_indici():
    cl = [
        _plata("TVA", "D301", 1, 2026, 138.0),   # idx 0
        _plata("TVA", "D301", 1, 2026, 138.0),   # idx 1
        _retur("TVA", "D301", 1, 2026, 138.0),   # idx 2 (respinge una)
        _plata("Impozit", "D100", 3, 2026, 4.0),  # idx 3 (fără returnare → reală)
    ]
    idx = real_payment_indices(cl)
    # 2 plăți D301 - 1 returnare = 1 reală; + D100 reală = 2 indici
    assert len(idx) == 2
    assert 3 in idx                              # D100 (fără pereche) e reală
    assert idx[0] in (0, 1)                      # una din cele 2 plăți D301
    # consistență cu compensate (wrapper): aceleași obiecte
    assert compensate(cl) == [cl[i] for i in idx]
