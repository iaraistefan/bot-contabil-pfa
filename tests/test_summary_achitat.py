"""
Teste felia 5c-b — adnotarea „✅ achitat" în sumarul „De plătit acum".

Pe `_plata_line_text` + `_safe_has_payment` (scheduler.py). Aditiv: linia de bază
rămâne BYTE-IDENTICĂ; „achitat" apare DOAR când obligația are o plată înregistrată.
"""
from datetime import date
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.repositories import obligation_payments as repo
from app.services import scheduler

# format de bază istoric (byte-identic) pentru D301 138.00 termen 25.02.2026
_LINIE_BAZA = "  • D301: *138.00 RON* — termen 25.02.2026"


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


def _obl(cod="D301", suma=138.0, termen=date(2026, 2, 25), an=2026, luna=1):
    return SimpleNamespace(
        definitie=SimpleNamespace(cod=cod),
        suma_estimata=suma, termen=termen,
        perioada_an=an, perioada_luna=luna,
    )


def _pay(s, uid, cod="D301", an=2026, luna=1, fp="fp1"):
    repo.create_payment(
        s, user_id=uid, obligation_code=cod, perioada_an=an, perioada_luna=luna,
        suma_platita=138.0, data_platii=date(2026, 4, 27), import_fingerprint=fp,
    )
    s.commit()


# ──────────────────────────────────────────────────────────────
# ⭐ REGRESIE byte-identică — fără plată → exact formatul istoric
# ──────────────────────────────────────────────────────────────
def test_regresie_linie_byte_identica_fara_plata(tmp_path):
    Session, uid = _setup(tmp_path)
    s = Session()
    line = scheduler._plata_line_text(s, uid, _obl())
    s.close()
    assert line == _LINIE_BAZA              # caracter cu caracter, fără „achitat"
    assert "achitat" not in line


# ──────────────────────────────────────────────────────────────
# Achitat — plată înregistrată → linia capătă „✅ achitat", baza neschimbată
# ──────────────────────────────────────────────────────────────
def test_achitat_apare_cand_platit(tmp_path):
    Session, uid = _setup(tmp_path)
    s = Session()
    _pay(s, uid, cod="D301", an=2026, luna=1)
    line = scheduler._plata_line_text(s, uid, _obl(cod="D301", an=2026, luna=1))
    s.close()
    assert line == _LINIE_BAZA + " ✅ *achitat*"    # baza + adnotare


# ──────────────────────────────────────────────────────────────
# ⭐ PERIOADA — D301 ianuarie marcată; D301 februarie NU
# ──────────────────────────────────────────────────────────────
def test_perioada_corecta(tmp_path):
    Session, uid = _setup(tmp_path)
    s = Session()
    _pay(s, uid, cod="D301", an=2026, luna=1)       # plată pentru IANUARIE
    line_ian = scheduler._plata_line_text(s, uid, _obl(cod="D301", an=2026, luna=1))
    line_feb = scheduler._plata_line_text(s, uid, _obl(cod="D301", an=2026, luna=2))
    s.close()
    assert "achitat" in line_ian            # ianuarie marcată
    assert "achitat" not in line_feb        # februarie NU (perioadă diferită)


# ──────────────────────────────────────────────────────────────
# ⭐ GARDA DEFENSIVĂ — has_payment crapă → linie normală, fără achitat
# ──────────────────────────────────────────────────────────────
def test_garda_defensiva_has_payment_crapa(tmp_path, monkeypatch):
    Session, uid = _setup(tmp_path)

    def _boom(*a, **k):
        raise RuntimeError("DB down")
    monkeypatch.setattr(repo, "has_payment", _boom)

    s = Session()
    line = scheduler._plata_line_text(s, uid, _obl())
    s.close()
    assert line == _LINIE_BAZA              # sumarul nu suferă; fără „achitat"
    assert "achitat" not in line


# ──────────────────────────────────────────────────────────────
# Mapare cod — "D100 poz. 634" → split()[0]="D100" ↔ plata stocată "D100"
# ──────────────────────────────────────────────────────────────
def test_mapare_cod_d100_sufix(tmp_path):
    Session, uid = _setup(tmp_path)
    s = Session()
    _pay(s, uid, cod="D100", an=2026, luna=1)       # stocat scurt
    o = _obl(cod="D100 poz. 634", suma=7.0, an=2026, luna=1)
    line = scheduler._plata_line_text(s, uid, o)
    s.close()
    assert "✅ *achitat*" in line            # split()[0]="D100" face match
    assert "D100 poz. 634" in line          # afișajul păstrează codul complet
