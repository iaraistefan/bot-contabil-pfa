"""
Teste PAS 2 felia 3 — helper dedup pur (app/integrations/imports/dedup.py).

Dedup-ul e inima anti-dublurii → testele sunt tari:
- STABILITATE la re-descărcare (REF/RRN diferit → același fingerprint)
- TIEBREAKER (linii legitim identice → fingerprint-uri distincte)
- re-upload determinist (aceeași listă → aceleași amprente)
- independență de ordine
- exists_fingerprint True/False pe DB (sqlite)
- GOLDEN pe fixture REAL: 34 tranzacții → 34 fingerprint-uri unice
"""
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.integrations.imports.bank_statement import BankTxn
from app.integrations.imports.bt_parser import parse_bt_pdf
from app.integrations.imports.dedup import (
    normalize_descriere,
    fingerprint,
    compute_fingerprints,
    exists_fingerprint,
)
from app.models import User, Document, Transaction

_FIXTURE = Path(__file__).parent / "fixtures" / "extras_bt_anon.pdf"


def _t(directie, suma, descriere, d=date(2026, 4, 2)):
    return BankTxn(d, suma, directie, descriere)


# ──────────────────────────────────────────────────────────────
# NORMALIZARE — scoate părțile volatile
# ──────────────────────────────────────────────────────────────
def test_normalize_scoate_ref_rrn_tid():
    n = normalize_descriere(
        "Plata POS MERCHANTX RRN: 609108383488 TID:XXXXXXXX REF: 000XXXX000000XX"
    )
    assert "609108383488" not in n
    assert "rrn" not in n and "ref" not in n and "tid" not in n
    assert "merchantx" in n          # nucleul descriptiv rămâne


def test_normalize_scoate_zgomot_si_runuri_lungi():
    n = normalize_descriere(
        "Plata POS comision tranzactie 0.00RON valoare tranzactie: 6.05EUR +10000000000"
    )
    assert "comision" not in n        # zgomotul denoise scos
    assert "10000000000" not in n     # run lung de cifre scos
    assert "plata pos" in n


# ──────────────────────────────────────────────────────────────
# 1. STABILITATE la re-descărcare — REF/RRN diferit → ACELAȘI fingerprint
#    (dovada că safe-by-default funcționează: re-upload nu produce dubluri)
# ──────────────────────────────────────────────────────────────
def test_stabilitate_ref_variabil_acelasi_fingerprint():
    baza = "Plata la POS non-BT cu card VISA EPOS MERCHANTX persoana fizica"
    t1 = _t("OUT", 31.81, baza + " RRN: 111111111111 REF: 000AAA111")
    t2 = _t("OUT", 31.81, baza + " RRN: 999999999999 REF: 000ZZZ999")
    assert fingerprint(t1) == fingerprint(t2)


def test_stabilitate_whitespace_si_case():
    t1 = _t("OUT", 50.0, "Plata POS   CAFE X")
    t2 = _t("OUT", 50.0, "plata pos cafe x")
    assert fingerprint(t1) == fingerprint(t2)


# ──────────────────────────────────────────────────────────────
# 2. TIEBREAKER — două linii LEGITIM identice → fingerprint-uri DISTINCTE
# ──────────────────────────────────────────────────────────────
def test_tiebreaker_linii_identice_distincte():
    t = _t("OUT", 0.51, "Comision plata OP")
    fps = compute_fingerprints([t, t, t])
    assert len(set(fps)) == 3                  # 3 distincte, nu colapsate
    # consistență cu fingerprint(txn, ocurenta)
    assert fps[0] == fingerprint(t, 0)
    assert fps[1] == fingerprint(t, 1)
    assert fps[2] == fingerprint(t, 2)


# ──────────────────────────────────────────────────────────────
# 3. Re-upload ACELAȘI extras → EXACT aceleași fingerprint-uri
# ──────────────────────────────────────────────────────────────
def test_reupload_determinist():
    txns = parse_bt_pdf(_FIXTURE.read_bytes())
    assert compute_fingerprints(txns) == compute_fingerprints(txns)


# ──────────────────────────────────────────────────────────────
# 4. Independența de ordine — linii diferite → fingerprint independent de poziție
# ──────────────────────────────────────────────────────────────
def test_independenta_de_ordine():
    a = _t("OUT", 10.0, "Merchant A", d=date(2026, 4, 1))
    b = _t("OUT", 20.0, "Merchant B", d=date(2026, 4, 2))
    f1 = compute_fingerprints([a, b])
    f2 = compute_fingerprints([b, a])
    assert set(f1) == set(f2)
    assert f1[0] == f2[1]                       # amprenta lui a, indiferent de poziție
    assert f1[1] == f2[0]


# ──────────────────────────────────────────────────────────────
# 5. exists_fingerprint pe DB (sqlite izolat)
# ──────────────────────────────────────────────────────────────
def _setup_db(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    s = Session()
    u = User(telegram_id=1)
    u2 = User(telegram_id=2)
    s.add_all([u, u2])
    s.commit()
    doc = Document(user_id=u.id, tip="CHELTUIALA", status="posted")
    s.add(doc)
    s.commit()
    tx = Transaction(
        user_id=u.id, document_id=doc.id, tx_type="EXPENSE",
        category="fuel", amount_brut=31.81, import_fingerprint="fp_exista",
    )
    s.add(tx)
    s.commit()
    return s, u.id, u2.id


def test_exists_fingerprint(tmp_path):
    s, uid, other_uid = _setup_db(tmp_path)
    assert exists_fingerprint(s, uid, "fp_exista") is True
    assert exists_fingerprint(s, uid, "fp_lipsa") is False
    # izolare per-user: alt user NU vede fingerprint-ul
    assert exists_fingerprint(s, other_uid, "fp_exista") is False
    s.close()


# ──────────────────────────────────────────────────────────────
# 6. GOLDEN pe FIXTURE REAL — 34 tranzacții → 34 fingerprint-uri UNICE
#    (zero coliziune falsă; cele 8 comisioane de 0,51 identice → tiebreaker)
# ──────────────────────────────────────────────────────────────
def test_golden_fixture_34_fingerprint_unice():
    txns = parse_bt_pdf(_FIXTURE.read_bytes())
    fps = compute_fingerprints(txns)
    assert len(fps) == 34
    assert len(set(fps)) == 34                  # zero coliziuni pe extrasul real
