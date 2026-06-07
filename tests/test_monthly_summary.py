"""
Teste pentru run_monthly_summary (Faza 3 PAS 3) — pasul cel mai sensibil.

DB sqlite izolat (monkeypatch db.get_session) + compute_period mock +
_send_telegram_message mock. Verifică izolarea per-user, garda anti-dublură,
skip lună goală, și robustețea liniei de plată.
"""

from datetime import datetime, date

import db
from app.services import scheduler, tax_engine
from app.models import User, SummarySent
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _db(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    monkeypatch.setattr(db, "get_session", lambda: Session())
    return Session


def _prev(now=None):
    return scheduler.luna_precedenta(now or datetime.now(scheduler.ROMANIA_TZ))


# ────────────────────────────────────────────────────────────
# Orchestrare: izolare + gardă + skip gol + skip deja-trimis
# ────────────────────────────────────────────────────────────

def test_orchestrare_completa(monkeypatch, tmp_path):
    Session = _db(tmp_path, monkeypatch)
    s = Session()
    uA = User(telegram_id=1001)  # are date -> primește
    uB = User(telegram_id=1002)  # lună goală -> skip
    uC = User(telegram_id=1003)  # crapă la compute_period -> nu blochează
    uD = User(telegram_id=1004)  # deja trimis -> skip
    s.add_all([uA, uB, uC, uD]); s.commit()
    idA, idB, idC, idD = uA.id, uB.id, uC.id, uD.id
    py, pm = _prev()
    s.add(SummarySent(user_id=idD, period_year=py, period_month=pm)); s.commit()
    s.close()

    tx = {idA: 5, idB: 0}

    def fake_cp(session, *, user_id, year, month):
        if user_id == idC:
            raise RuntimeError("date stricate")
        return {"tx_count": tx.get(user_id, 0)}

    monkeypatch.setattr(tax_engine, "compute_period", fake_cp)
    monkeypatch.setattr(scheduler, "_build_summary_message", lambda *a, **k: "MSG")
    sends = []
    monkeypatch.setattr(scheduler, "_send_telegram_message",
                        lambda token, chat, text: sends.append(chat) or True)

    scheduler.run_monthly_summary("tok")

    # A a primit; B (gol), C (eroare), D (deja) NU
    assert sends == [1001]

    s = Session()
    assert s.query(SummarySent).filter_by(user_id=idA).count() == 1   # gardă scrisă
    assert s.query(SummarySent).filter_by(user_id=idB).count() == 0   # gol → fără gardă
    assert s.query(SummarySent).filter_by(user_id=idC).count() == 0   # eroare → fără gardă
    assert s.query(SummarySent).filter_by(user_id=idD).count() == 1   # rămâne cel vechi
    s.close()


def test_izolare_un_user_crapat_nu_blocheaza(monkeypatch, tmp_path):
    # C (primul în listă) crapă, A tot primește
    Session = _db(tmp_path, monkeypatch)
    s = Session()
    uC = User(telegram_id=2001); uA = User(telegram_id=2002)
    s.add_all([uC, uA]); s.commit()
    idC, idA = uC.id, uA.id
    s.close()

    def fake_cp(session, *, user_id, year, month):
        if user_id == idC:
            raise RuntimeError("boom")
        return {"tx_count": 3}

    monkeypatch.setattr(tax_engine, "compute_period", fake_cp)
    monkeypatch.setattr(scheduler, "_build_summary_message", lambda *a, **k: "MSG")
    sends = []
    monkeypatch.setattr(scheduler, "_send_telegram_message",
                        lambda token, chat, text: sends.append(chat) or True)

    scheduler.run_monthly_summary("tok")
    assert 2002 in sends            # A a primit, deși C a crăpat


def test_send_esuat_nu_marcheaza_garda(monkeypatch, tmp_path):
    Session = _db(tmp_path, monkeypatch)
    s = Session()
    u = User(telegram_id=3001); s.add(u); s.commit(); uid = u.id; s.close()

    monkeypatch.setattr(tax_engine, "compute_period",
                        lambda session, *, user_id, year, month: {"tx_count": 9})
    monkeypatch.setattr(scheduler, "_build_summary_message", lambda *a, **k: "MSG")
    # trimitere eșuată
    monkeypatch.setattr(scheduler, "_send_telegram_message",
                        lambda token, chat, text: False)

    scheduler.run_monthly_summary("tok")

    s = Session()
    # garda NU s-a scris -> se reîncearcă data viitoare
    assert s.query(SummarySent).filter_by(user_id=uid).count() == 0
    s.close()


# ────────────────────────────────────────────────────────────
# Linia de plată: doar sumă > 0, robustă la eroare
# ────────────────────────────────────────────────────────────

class _Def:
    def __init__(self, cod): self.cod = cod


class _Obl:
    def __init__(self, cod, suma, termen):
        self.definitie = _Def(cod); self.suma_estimata = suma; self.termen = termen


def test_plata_line_doar_suma_pozitiva(monkeypatch):
    from app.services import proactive_alerts
    from app.domain import fiscal_calendar

    monkeypatch.setattr(proactive_alerts, "_build_user_context", lambda s, u: {
        "forma_juridica": "PFA", "activity_code": "ridesharing",
        "has_cod_special_tva": True, "is_vat_payer": False, "judet": "BN",
    })
    monkeypatch.setattr(proactive_alerts, "_get_intracom_base_for_month",
                        lambda s, u, y, m: 712.65)
    monkeypatch.setattr(fiscal_calendar, "get_obligations_for_user", lambda *a, **k: [
        _Obl("D301", 149.65, date(2026, 7, 25)),
        _Obl("D100 poz. 634", 14.25, date(2026, 7, 25)),
        _Obl("D390", None, date(2026, 7, 25)),     # declarativ → exclus
    ])

    line = scheduler._format_plata_line(None, 1, 2026, 6, date(2026, 7, 2))
    assert "D301" in line and "149.65" in line
    assert "D100" in line and "14.25" in line
    assert "D390" not in line                       # fără plată → nu apare
    assert "25.07.2026" in line


def test_plata_line_robust_la_eroare(monkeypatch):
    from app.services import proactive_alerts
    from app.domain import fiscal_calendar

    monkeypatch.setattr(proactive_alerts, "_build_user_context", lambda s, u: {
        "forma_juridica": "PFA", "activity_code": "ridesharing",
        "has_cod_special_tva": True, "is_vat_payer": False, "judet": "BN",
    })
    monkeypatch.setattr(proactive_alerts, "_get_intracom_base_for_month",
                        lambda s, u, y, m: 100.0)

    def _boom(*a, **k):
        raise RuntimeError("calendar down")
    monkeypatch.setattr(fiscal_calendar, "get_obligations_for_user", _boom)

    line = scheduler._format_plata_line(None, 1, 2026, 6, date(2026, 7, 2))
    assert line == ""                               # eroare → linia se omite, nu crapă


# ────────────────────────────────────────────────────────────
# build_summary_for_user — sursa unica (job + comanda)
# ────────────────────────────────────────────────────────────

class _U:
    def __init__(self, uid): self.id = uid


def test_build_summary_for_user_luna_goala_none(monkeypatch):
    monkeypatch.setattr(tax_engine, "compute_period",
                        lambda session, *, user_id, year, month: {"tx_count": 0})
    assert scheduler.build_summary_for_user(None, _U(1), 2026, 6) is None


def test_build_summary_for_user_mesaj_si_nu_scrie_garda(monkeypatch, tmp_path):
    Session = _db(tmp_path, monkeypatch)
    monkeypatch.setattr(tax_engine, "compute_period",
                        lambda session, *, user_id, year, month: {"tx_count": 4})
    monkeypatch.setattr(scheduler, "_build_summary_message", lambda *a, **k: "SUMAR")

    s = Session()
    out = scheduler.build_summary_for_user(s, _U(1), 2026, 6, date(2026, 7, 2))
    assert out == "SUMAR"
    # preview nu scrie niciodata garda
    assert s.query(SummarySent).count() == 0
    s.close()
