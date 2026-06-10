"""
Teste felia 5c-c-1 — logică pură + sync UI confirmare taxe (bank_tax_ui.py).

Zero async/Telegram/wiring. Golden pe fixture (compensate=[] → nimic de propus) +
finalize tot-sau-nimic (rollback complet pe excepție).
"""
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.integrations.imports.bank_statement import BankTxn
from app.integrations.imports.bt_parser import parse_bt_pdf
from app.integrations.imports.classify import (
    classify_bt, BankTxnClasificat, ObligatieHint, PLATA_TAXA, RETURNARE_TAXA,
)
from app.integrations.imports.dedup import compute_fingerprints
from app.integrations.imports import tax_recording
from app.activities.ridesharing import RidesharingActivity as ACT
from app.services import bank_tax_ui as ui
from app.models import User, ObligationPayment

_FIXTURE = Path(__file__).parent / "fixtures" / "extras_bt_anon.pdf"


def _setup(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    s = Session()
    u = User(telegram_id=1)
    s.add(u)
    s.commit()
    uid = u.id
    s.close()
    return Session, uid


def _plata(cod, suma, tip="TVA", luna=1, an=2026, d=date(2026, 4, 27)):
    o = ObligatieHint(tip, cod, luna, an, _luna_nume(luna))
    return BankTxnClasificat(BankTxn(d, suma, "OUT", "plata trezorerie"), PLATA_TAXA, "et", oblig=o)


def _retur(cod, suma, tip="TVA", luna=1, an=2026, d=date(2026, 4, 30)):
    o = ObligatieHint(tip, cod, luna, an, _luna_nume(luna))
    return BankTxnClasificat(BankTxn(d, suma, "IN", "returnare plata"), RETURNARE_TAXA, "et", oblig=o)


def _luna_nume(n):
    return ui._LUNI_NUME.get(n, str(n))


# ──────────────────────────────────────────────────────────────
# ⭐ GOLDEN pe fixture — compensate=[] → buton absent, nimic de propus
# ──────────────────────────────────────────────────────────────
def test_golden_fixture_fara_taxe_reale():
    txns = parse_bt_pdf(_FIXTURE.read_bytes())
    clasificate = [classify_bt(t, ACT) for t in txns]
    assert ui.has_real_tax(clasificate) is False       # toate respinse → buton absent
    assert ui.real_tax_fingerprints(clasificate) == set()
    assert ui.real_tax_payments(clasificate) == []


# ──────────────────────────────────────────────────────────────
# has_real_tax / real_tax_fingerprints — sintetic real
# ──────────────────────────────────────────────────────────────
def test_has_real_tax_si_fingerprints_sintetic():
    cl = [_plata("D301", 138.0)]                        # fără returnare → reală
    assert ui.has_real_tax(cl) is True
    fps = compute_fingerprints([r.txn for r in cl])
    assert ui.real_tax_fingerprints(cl) == {fps[0]}


def test_has_real_tax_false_cand_respinsa():
    cl = [_plata("D301", 138.0), _retur("D301", 138.0)]  # compensată → 0 reale
    assert ui.has_real_tax(cl) is False
    assert ui.real_tax_fingerprints(cl) == set()


# ──────────────────────────────────────────────────────────────
# format_tax_propose — tip · perioadă — sumă
# ──────────────────────────────────────────────────────────────
def test_format_tax_propose():
    reale = [_plata("D301", 138.0, luna=1), _plata("D100", 13.0, tip="Impozit", luna=1)]
    msg = ui.format_tax_propose(reale)
    assert "D301 · Ianuarie 2026 — *138,00 lei*" in msg
    assert "D100 · Ianuarie 2026 — *13,00 lei*" in msg
    assert "Le marchez ca *achitate*" in msg
    assert "nu au fost respinse" in msg                 # transparență


# ──────────────────────────────────────────────────────────────
# format_tax_result — succes / re-import / eroare
# ──────────────────────────────────────────────────────────────
def test_format_tax_result_succes_plural():
    msg = ui.format_tax_result({"ok": True, "result": {"recorded": 2, "skipped_dup": 0}})
    assert "Am marcat *2 obligații* ca achitate" in msg


def test_format_tax_result_succes_singular():
    msg = ui.format_tax_result({"ok": True, "result": {"recorded": 1, "skipped_dup": 0}})
    assert "Am marcat *1 obligație* ca achitată" in msg


def test_format_tax_result_reimport():
    msg = ui.format_tax_result({"ok": True, "result": {"recorded": 0, "skipped_dup": 2}})
    assert "2 erau deja marcate" in msg


def test_format_tax_result_eroare():
    msg = ui.format_tax_result({"ok": False, "error": "boom"})
    assert "Nimic nu a fost marcat" in msg
    assert "Reîncearcă" in msg


# ──────────────────────────────────────────────────────────────
# ⭐ finalize_tax_recording — tot-sau-nimic
# ──────────────────────────────────────────────────────────────
def test_finalize_succes(tmp_path):
    Session, uid = _setup(tmp_path)
    cl = [_plata("D301", 138.0)]
    fps = compute_fingerprints([r.txn for r in cl])
    s = Session()
    outcome = ui.finalize_tax_recording(
        s, user_id=uid, source_file_id=None,
        clasificate=cl, confirmed_fingerprints={fps[0]},
    )
    s.close()
    assert outcome["ok"] is True
    assert outcome["result"]["recorded"] == 1
    s2 = Session()
    assert s2.query(ObligationPayment).count() == 1
    s2.close()


def test_finalize_rollback_pe_exceptie(tmp_path, monkeypatch):
    Session, uid = _setup(tmp_path)
    cl = [_plata("D301", 138.0)]
    fps = compute_fingerprints([r.txn for r in cl])

    def _boom(*a, **k):
        raise RuntimeError("record down")
    monkeypatch.setattr(tax_recording, "record_tax_payments", _boom)

    s = Session()
    outcome = ui.finalize_tax_recording(
        s, user_id=uid, source_file_id=None,
        clasificate=cl, confirmed_fingerprints={fps[0]},
    )
    s.close()
    assert outcome["ok"] is False
    s2 = Session()
    assert s2.query(ObligationPayment).count() == 0     # rollback complet, zero parțial
    s2.close()
