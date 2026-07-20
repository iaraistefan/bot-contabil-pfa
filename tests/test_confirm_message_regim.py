"""
Item D (audit final) — mesajul de confirmare „✅ Gata, am salvat" arată procentul
deductibil REGIM-AWARE = EXACT ce s-a scris în registru.

Înainte: _build_confirm_message → _resolve_expense_meta folosea procentul STATIC
al categoriei (get_effective_deductibility). Scrierea (_post_cheltuiala →
_resolve_auto_deductibility) era deja regim-aware → afișaj ≠ scriere: user EXCLUSIV
vedea 50% dar primea 100%; comodat insurance vedea 50% dar primea 0%.

Acum afișajul trece prin ACELAȘI _resolve_auto_deductibility (oglindește #94/
post_bank). Vehicul REAL în DB (nu monkeypatch) → curge prin lookup-ul de vehicul.

⚠️ Aserțiile țintesc MARKERUL LINIEI de procent — "(100%)", "(50% din",
"Nu se deduce (0%)" — NU substring-ul brut "100%"/"50%", fiindcă NOTA explicativă
a categoriei conține și ea „…50% … 100% …" ca text pedagogic (nu procentul aplicat).
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User, Vehicul
from app.ai.schemas import ExtractionItem
from app.activities.ridesharing import RidesharingActivity as ACT
import bot_contabil as bot


def _setup(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    s = Session()
    u = User(telegram_id=7, activity_code="ridesharing")
    s.add(u)
    s.commit()
    uid = u.id
    s.close()
    return Session, uid


def _add_vehicul(Session, uid, *, regim="MIXT", tip=None):
    s = Session()
    s.add(Vehicul(
        user_id=uid, nr_inmatriculare="B-01-XYZ", activ=True,
        regim_utilizare=regim, tip_detinere=tip,
    ))
    s.commit()
    s.close()


def _chelt(platforma, detalii, brut=100.0):
    it = ExtractionItem(
        tip="CHELTUIALA", data="05.04.2026", platforma=platforma,
        detalii=detalii, brut=brut,
        comision=0.0, tva=0.0, net=0.0, cash=0.0,
    )
    return [(it, 1, [1])]


# ── EXCLUSIV + combustibil → linia de procent 100% (nu 50 static) ────
def test_confirm_fuel_exclusiv_arata_100(tmp_path):
    Session, uid = _setup(tmp_path)
    _add_vehicul(Session, uid, regim="EXCLUSIV")
    s = Session()
    msg = bot._build_confirm_message(
        _chelt("Lukoil", "motorina"), ACT, session=s, user_id=uid
    )
    s.close()
    assert "(100%)" in msg          # linia „Deductibil: X RON (100%)"
    assert "(50% din" not in msg    # NU procentul static


# ── COMODAT + „Asigurare" → linia „Nu se deduce (0%)" (regresie N2) ──
def test_confirm_insurance_comodat_arata_0(tmp_path):
    # ⚠️ REGRESIE N2: cuvântul „Asigurare" conține substring-ul „rar" (keyword
    # `registration`, listat înaintea `car_insurance`). Cu matcher-ul substring naiv
    # afișajul arăta registration 100%; scoring-ul (ca la scriere) alege corect
    # car_insurance → pe COMODAT „Nu se deduce (0%)".
    Session, uid = _setup(tmp_path)
    _add_vehicul(Session, uid, tip="COMODAT")
    s = Session()
    msg = bot._build_confirm_message(
        _chelt("Asigurare auto", "RCA", brut=300.0),
        ACT, session=s, user_id=uid,
    )
    s.close()
    assert "Nu se deduce (0%)" in msg
    assert "(50% din" not in msg
    assert "(100%)" not in msg
    assert "🛡️" in msg                # icon car_insurance (NU 📋 registration)
    assert "📋" not in msg


# ── Fără vehicul + combustibil → linia 50% (neschimbat) ──────────────
def test_confirm_fuel_fara_vehicul_arata_50(tmp_path):
    Session, uid = _setup(tmp_path)
    s = Session()
    msg = bot._build_confirm_message(
        _chelt("Lukoil", "motorina"), ACT, session=s, user_id=uid
    )
    s.close()
    assert "(50% din" in msg        # linia „Deductibil: X RON (50% din …)"
    assert "(100%)" not in msg


# ── Fallback backward-compat: fără session → static (ignoră vehiculul) ─
def test_confirm_fara_session_ramane_static(tmp_path):
    # Chiar cu vehicul EXCLUSIV în DB, fără session pasat → procentul static (50).
    # Dovedește că I/O-ul e opt-in și fallback-ul (ex. lookup eșuat) e sigur.
    Session, uid = _setup(tmp_path)
    _add_vehicul(Session, uid, regim="EXCLUSIV")
    msg = bot._build_confirm_message(_chelt("Lukoil", "motorina"), ACT)
    assert "(50% din" in msg
    assert "(100%)" not in msg


# ── Coliziune cosmetică N2: „filtru combustibil" → car_service, NU fuel ─
def test_confirm_filtru_combustibil_e_car_service_nu_fuel(tmp_path):
    # „filtru combustibil" conține substring-ul „combustibil" (keyword fuel, listat
    # primul) → matcher-ul naiv arăta fuel ⛽; scoring-ul preferă keyword-ul COMPUS
    # „filtru combustibil" (car_service) → icon 🔧, ca la scriere.
    Session, uid = _setup(tmp_path)
    s = Session()
    msg = bot._build_confirm_message(
        _chelt("Auto Service", "filtru combustibil"), ACT, session=s, user_id=uid
    )
    s.close()
    assert "🔧" in msg                 # icon car_service
    assert "⛽" not in msg             # NU fuel
