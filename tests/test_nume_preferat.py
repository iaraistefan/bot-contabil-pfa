"""
Numele ALES de user, separat de oglinda Telegram.

BUG-UL, in doua propozitii: `users.name` e capturat automat la primul mesaj SI
rescris la fiecare mesaj urmator (`get_or_create_by_telegram_id`, users.py:42-43).
Onboarding-ul scria raspunsul userului tot in `name` — deci ce tasta el traia
pana scria orice altceva botului. Conflatarea celor doua ERA bug-ul.

`nume_preferat` e raspunsul lui; `name` ramane oglinda Telegram, utila la
identificare in loguri. Afisajele conversationale trec prin `nume_de_adresare`:
ce a ales, altfel oglinda, altfel implicitul.

Numele nu mai e nici obligatoriu, nici primul: nu configureaza nimic (pe
declaratii merge nume_declarant din ANAF, PR #141), deci n-are ce sta in calea
tuturor. Prima intrebare e CUI-ul.
"""

import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.repositories import users as users_repo

_ROOT = Path(__file__).resolve().parent.parent
_HTML = (_ROOT / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")


def _db(tmp_path, nume="np.db"):
    eng = create_engine(f"sqlite:///{(tmp_path / nume).as_posix()}")
    User.metadata.create_all(eng)
    return sessionmaker(bind=eng)


# ── 1. MIEZUL: raspunsul supravietuieste unui mesaj ulterior ──

def test_numele_ales_supravietuieste_unui_mesaj_in_bot(tmp_path):
    S = _db(tmp_path, "supravietuire.db")
    s = S()
    u = users_repo.get_or_create_by_telegram_id(s, telegram_id=42, name="Wn rain")
    s.commit()

    # userul raspunde la „Cum sa-ti spun?"
    users_repo.update_profile(s, u, nume_preferat="Ștefan")
    s.commit()

    # ...si apoi mai scrie botului orice — Telegram isi impune numele de afisare
    users_repo.get_or_create_by_telegram_id(s, telegram_id=42, name="Wn rain")
    s.commit()

    u2 = users_repo.get_by_telegram_id(s, telegram_id=42)
    assert u2.nume_preferat == "Ștefan", "raspunsul userului a fost pierdut"
    assert u2.name == "Wn rain"          # oglinda Telegram, neatinsa
    s.close()


def test_injectare_pe_name_se_pierde(tmp_path):
    """Contraexemplu PINUIT: exact ce facea codul vechi (scriere in `name`)."""
    S = _db(tmp_path, "injectare.db")
    s = S()
    u = users_repo.get_or_create_by_telegram_id(s, telegram_id=43, name="Wn rain")
    s.commit()
    users_repo.update_profile(s, u, name="Ștefan")          # comportamentul VECHI
    s.commit()
    users_repo.get_or_create_by_telegram_id(s, telegram_id=43, name="Wn rain")
    s.commit()
    assert users_repo.get_by_telegram_id(s, telegram_id=43).name == "Wn rain", (
        "daca asta trece, Telegram NU mai suprascrie si bug-ul original n-a existat"
    )
    s.close()


def test_ambele_drumuri_scriu_in_coloana_noua():
    import inspect
    from app.services import onboarding
    src = inspect.getsource(onboarding.handle_onboarding_text)
    assert '"nume_preferat": text[:200]' in src, "botul inca scrie in `name`"
    assert "wizSave({nume_preferat:" in _HTML, "web-ul inca scrie in `name`"


# ── 2. Afisajele conversationale ──

@pytest.mark.parametrize("profil,asteptat", [
    ({"nume_preferat": "Ștefan", "name": "Wn rain"}, "Ștefan"),   # ce a ales
    ({"nume_preferat": None, "name": "Wn rain"}, "Wn rain"),      # oglinda Telegram
    ({"nume_preferat": None, "name": None}, "implicit"),          # nimic
    ({}, "implicit"),
])
def test_nume_de_adresare(profil, asteptat):
    assert users_repo.nume_de_adresare(profil, "implicit") == asteptat


def test_afisajele_folosesc_sursa_unica():
    import inspect
    from app.services import onboarding
    import bot_contabil
    for sursa in (inspect.getsource(onboarding), inspect.getsource(bot_contabil)):
        assert 'profile.get("name") or "' not in sursa, (
            "un afisaj citeste direct `name` — raspunsul userului n-ar avea efect acolo"
        )
    assert inspect.getsource(onboarding).count("nume_de_adresare") >= 2
    assert "nume_de_adresare" in inspect.getsource(bot_contabil)


# ── 3. get_pfa_display_name ramane corect ──

@pytest.mark.parametrize("kw,asteptat", [
    ({"firma_nume": "IARAI ŞTEFAN PFA", "nume_preferat": "Ștefan"}, "IARAI ŞTEFAN PFA"),
    ({"nume_preferat": "Ștefan", "name": "Wn rain"}, "Ștefan"),
    ({"name": "Wn rain"}, "Wn rain"),
    ({}, "PFA"),
])
def test_get_pfa_display_name(tmp_path, kw, asteptat):
    S = _db(tmp_path, f"disp{abs(hash(str(kw)))}.db")
    s = S()
    u = User(telegram_id=1, **kw)
    s.add(u); s.commit()
    assert users_repo.get_pfa_display_name(s, u.id) == asteptat
    s.close()


# ── 4. Nu mai blocheaza finalizarea, nu mai e primul ──

def test_numele_nu_mai_blocheaza_finalizarea():
    from app.http import app as webapp
    profil = {"firma_cui": "53067338", "regim_impunere": "SISTEM_REAL"}   # fara `name`
    assert webapp._onboarding_missing(profil, has_vehicul=True) == []


def test_scoaterea_e_documentata_ca_no_op():
    """Fara nota, cineva il pune la loc crezand ca repara o omisiune."""
    import inspect
    from app.http import app as webapp
    src = inspect.getsource(webapp._onboarding_missing)
    assert "NO-OP" in src.upper() and "oglinda Telegram" in src


def test_cui_e_prima_intrebare_iar_numele_ultimul():
    m = re.search(r"function wizSteps\(\)\s*\{[\s\S]*?\n  \}", _HTML)
    corp = m.group(0)
    assert 'const s=["cui"' in corp, "CUI-ul nu e prima întrebare"
    assert 's.push("nume")' in corp, "numele nu e împins la final"
    assert '["nume","cui"' not in corp


def test_numele_e_optional_in_wizard():
    assert 'wizMsg("Scrie numele.",true)' not in _HTML, "numele inca blocheaza pasul"
    assert "Poți sări peste" in _HTML


# ── 5. Cei doi useri reali aterizeaza tot la „cui" (gardianul din #147) ──

def test_reordonarea_nu_muta_userii_parcati(tmp_path, monkeypatch):
    """CONFIRMAT, nu presupus: profilul lor exact, prin endpoint-ul real."""
    from app.http import app as webapp
    S = _db(tmp_path, "parcati.db")
    s = S()
    s.add(User(telegram_id=2, name="Wn rain", onboarding_step=1,
               onboarding_completed=False, eligibilitate_pfa="DA"))
    s.commit()
    uid = s.query(User).one().id
    s.close()
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    d = webapp.flask_app.test_client().get("/api/v1/onboarding/status").get_json()
    # „name" nu mai apare ca lipsa (nici nu mai e verificat), „firma" da →
    # derivarea din #147 ii duce la pasul „cui", oriunde ar sta el in lista
    assert "name" not in d["lipsa"]
    assert "firma" in d["lipsa"]
