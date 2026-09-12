"""
Poarta formei juridice pe drumul BOTULUI (onboarding, pasul CUI).

Perechea celor din tests/test_forma_neservita_poarta_anaf.py (web + reîmprospătare).
Aici se măsoară ce contează cel mai mult: că nu se scrie NIMIC în profil și că
pasul NU avansează. O poartă care afișează mesajul corect dar lasă
`firma_forma_juridica=SRL_MICRO` în urmă n-ar fi o poartă, ci o notificare.

Schela (fake bot / update / sqlite) e cea din tests/test_onboarding_nerezident.py.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.services import onboarding as onb


class _FakeBot:
    def __init__(self):
        self.mesaje = []

    async def send_message(self, *a, **kw):
        self.mesaje.append(kw.get("text", ""))


def _ctx():
    return SimpleNamespace(user_data={}, bot=_FakeBot())


def _update(tg_id, text, chat_id=999):
    return SimpleNamespace(
        message=SimpleNamespace(text=text),
        effective_user=SimpleNamespace(id=tg_id),
        effective_chat=SimpleNamespace(id=chat_id),
    )


def _db(monkeypatch, tmp_path, tg_id):
    eng = create_engine(f"sqlite:///{(tmp_path / 'onb.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    monkeypatch.setattr(onb, "get_session", lambda: Session())
    s = Session()
    s.add(User(telegram_id=tg_id, onboarding_step=onb.STEP_CUI))
    s.commit(); s.close()
    return Session


def _anaf(denumire, forma):
    return {
        "found": True, "cui": "12345678", "denumire": denumire,
        "forma_juridica_detectata": forma, "cod_caen": "4932",
        "regim_tva": "NEPLATITOR", "is_platitor_tva": False, "is_inactiv": False,
        "judet": "BN", "localitate": "Bistrița", "nr_reg_com": "F06/123/2020",
        "data_inregistrare": "2020-01-15",
    }


@pytest.mark.asyncio
async def test_botul_nu_scrie_nimic_pentru_un_srl(monkeypatch, tmp_path):
    Session = _db(monkeypatch, tmp_path, tg_id=601)
    monkeypatch.setattr(onb, "lookup_cui",
                        lambda cui: _anaf("I-SHTEF BUSINESS SRL", "SRL_MICRO"))
    ctx = _ctx()

    tratat = await onb.handle_onboarding_text(_update(601, "12345678"), ctx)
    assert tratat is True

    s = Session()
    u = s.query(User).filter_by(telegram_id=601).one()
    # NIMIC scris — nici forma, nici CUI-ul, nici denumirea, nici regimul.
    assert u.firma_forma_juridica is None
    assert u.firma_cui is None
    assert u.firma_nume is None
    assert u.regim_impunere is None
    # Și pasul NU a avansat: userul poate da imediat alt CUI.
    assert (u.onboarding_step or 0) == onb.STEP_CUI
    s.close()


@pytest.mark.asyncio
async def test_botul_explica_si_ofera_calea_pfa(monkeypatch, tmp_path):
    _db(monkeypatch, tmp_path, tg_id=602)
    monkeypatch.setattr(onb, "lookup_cui",
                        lambda cui: _anaf("I-SHTEF BUSINESS SRL", "SRL_MICRO"))
    ctx = _ctx()
    await onb.handle_onboarding_text(_update(602, "12345678"), ctx)

    tot = "\n".join(ctx.bot.mesaje)
    assert "I-SHTEF BUSINESS SRL" in tot                  # ce s-a întâmplat
    assert "altă bază decât la un PFA" in tot              # DE CE
    assert "Ai și un PFA?" in tot                         # ce să facă
    # ...și întrebarea despre CUI e pusă din nou, ca drumul să nu se înfunde.
    assert sum("CUI" in m for m in ctx.bot.mesaje) >= 2


@pytest.mark.asyncio
async def test_botul_lasa_un_pfa_sa_treaca(monkeypatch, tmp_path):
    """Contra-proba: poarta nu blochează pe cine servim."""
    Session = _db(monkeypatch, tmp_path, tg_id=603)
    monkeypatch.setattr(onb, "lookup_cui",
                        lambda cui: _anaf("POPESCU ION PFA", "PFA"))
    ctx = _ctx()
    await onb.handle_onboarding_text(_update(603, "12345678"), ctx)

    s = Session()
    u = s.query(User).filter_by(telegram_id=603).one()
    assert u.firma_forma_juridica == "PFA"
    assert u.firma_cui == "12345678"
    assert (u.onboarding_step or 0) > onb.STEP_CUI
    s.close()


@pytest.mark.asyncio
async def test_botul_lasa_sa_treaca_forma_goala(monkeypatch, tmp_path):
    """Cazul des: ANAF nu declară forma la persoane fizice. NU e o respingere."""
    Session = _db(monkeypatch, tmp_path, tg_id=604)
    monkeypatch.setattr(onb, "lookup_cui",
                        lambda cui: _anaf("CEVA NEIDENTIFICABIL", None))
    ctx = _ctx()
    await onb.handle_onboarding_text(_update(604, "12345678"), ctx)

    s = Session()
    u = s.query(User).filter_by(telegram_id=604).one()
    assert u.firma_cui == "12345678", "un PFA fără formă declarată a fost blocat"
    s.close()
