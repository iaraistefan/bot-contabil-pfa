"""
Wire-up UI D207 — ruta web anuala + handler bot (callback).

Generatorul genereaza_d207_anual e testat separat (test_d207_generator/anual).
Aici verificam DOAR expunerea: ruta /api/v1/declaratie-d207/<year> intoarce XML,
guard-urile (ValueError → 400, nu 500), callback-ul bot livreaza XML-ul, si ca
rutele lunare D390/D301/D100 raman inregistrate (regresie).
"""

import io
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User, Transaction
from app.repositories import users as users_repo

AN = 2026  # cota TVA 21% toate lunile


def _db(tmp_path, *, regim=True):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S()
    # Abonat PRO: din Felia 4b depunerea (inclusiv D207) e feature PRO. Aici testăm
    # LIVRAREA declarației, nu gating-ul — userul trebuie să aibă dreptul, altfel am
    # verifica poarta în loc de generator. Blocarea pt FREE e în test_gating_application.
    u = User(telegram_id=42, activity_code="ridesharing",
             stripe_status="active", stripe_tier="PRO")
    s.add(u); s.commit(); uid = u.id
    users_repo.update_profile(s, u, firma_cui="53067338",
                              firma_nume="TEST PFA")
    if regim:
        users_repo.update_profile(s, u, regim_nerezident_bolt="BOLT_CU_CRF",
                                  regim_nerezident_uber="UBER_CU_CRF")
    s.commit(); s.close()
    return S, uid


def _vat_out(uid, counterparty, amount, luna):
    return Transaction(
        user_id=uid, document_id=1, tx_type="VAT_OUT",
        category="REVERSE_CHARGE_VAT", amount_brut=amount, amount_vat=amount,
        amount_net=0.0, currency="RON", deductibility_pct=0, payment_method="CARD",
        counterparty=counterparty, vat_treatment="REVERSE_CHARGE",
        period_year=AN, period_month=luna, locked=False,
    )


def _seed_comisioane(S, uid):
    s = S()
    s.add_all([
        _vat_out(uid, "Bolt Operations OÜ", 21.0, 3),   # baza 100
        _vat_out(uid, "Uber B.V.", 21.0, 7),            # baza 100 (scutit)
    ])
    s.commit(); s.close()


# ════════════════════════════════════════════════════════
# 1. Ruta web → XML corect pentru user cu comision (Bolt+Uber)
# ════════════════════════════════════════════════════════
def test_ruta_d207_xml(tmp_path, monkeypatch):
    from app.http import app as webapp
    S, uid = _db(tmp_path)
    _seed_comisioane(S, uid)
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    from app.services import gating
    monkeypatch.setattr(gating, "get_session", lambda: S())

    r = webapp.flask_app.test_client().get(f"/api/v1/declaratie-d207/{AN}?format=xml")
    assert r.status_code == 200
    assert "application/xml" in r.headers["Content-Type"]
    assert f"D207_{AN}.xml" in r.headers["Content-Disposition"]
    xml = r.get_data(as_text=True)
    assert '<declaratie207 ' in xml
    assert 'Stat_R="EE"' in xml and 'Stat_R="NL"' in xml   # Bolt + Uber


def test_ruta_d207_json_default(tmp_path, monkeypatch):
    from app.http import app as webapp
    S, uid = _db(tmp_path)
    _seed_comisioane(S, uid)
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    from app.services import gating
    monkeypatch.setattr(gating, "get_session", lambda: S())

    d = webapp.flask_app.test_client().get(f"/api/v1/declaratie-d207/{AN}").get_json()
    assert d["tip"] == "D207" and d["year"] == AN
    assert d["are_plata"] is False                         # informativa
    assert d["xml_url"] == f"/api/v1/declaratie-d207/{AN}?format=xml"
    assert d["nume_fisier_xml"] == f"D207_{AN}.xml"


# ════════════════════════════════════════════════════════
# 2. Regim nesetat → ValueError gestionat (400, NU 500)
# ════════════════════════════════════════════════════════
def test_ruta_d207_regim_nesetat_400(tmp_path, monkeypatch):
    from app.http import app as webapp
    S, uid = _db(tmp_path, regim=False)   # comision dar fara regim nerezident
    _seed_comisioane(S, uid)
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    from app.services import gating
    monkeypatch.setattr(gating, "get_session", lambda: S())

    r = webapp.flask_app.test_client().get(f"/api/v1/declaratie-d207/{AN}")
    assert r.status_code == 400                            # gestionat, nu 500
    assert r.get_json()["error"] == "d207_indisponibil"


def test_ruta_d207_an_gol_negenerat(tmp_path, monkeypatch):
    from app.http import app as webapp
    S, uid = _db(tmp_path)                 # fara comisioane deloc
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    from app.services import gating
    monkeypatch.setattr(gating, "get_session", lambda: S())

    r = webapp.flask_app.test_client().get(f"/api/v1/declaratie-d207/{AN}")
    assert r.status_code == 400
    assert r.get_json()["error"] == "negenerat"


# ════════════════════════════════════════════════════════
# 3. Callback bot d207|{year} → livreaza XML (send_document, filename D207_{an})
# ════════════════════════════════════════════════════════
class _FakeBot:
    def __init__(self):
        self.messages = []
        self.documents = []
    async def send_message(self, **kw):
        self.messages.append(kw)
    async def send_document(self, **kw):
        self.documents.append(kw)


@pytest.mark.asyncio
async def test_callback_d207_livreaza_xml(tmp_path, monkeypatch):
    import bot_contabil
    S, uid = _db(tmp_path)
    _seed_comisioane(S, uid)
    monkeypatch.setattr(bot_contabil, "get_session", lambda: S())
    # gardianul de tier își deschide propria sesiune (Felia 4b) → o legăm la aceeași DB
    from app.services import gating
    monkeypatch.setattr(gating, "get_session", lambda: S())

    bot = _FakeBot()
    query = SimpleNamespace(message=SimpleNamespace(chat_id=999))
    context = SimpleNamespace(bot=bot)

    await bot_contabil.execute_fisa_d207(query, context, uid, AN)

    assert len(bot.documents) == 1                         # XML livrat
    doc = bot.documents[0]
    assert doc["filename"] == f"D207_{AN}.xml"
    assert isinstance(doc["document"], io.BytesIO)
    assert len(bot.messages) >= 1                          # ghidul trimis


@pytest.mark.asyncio
async def test_callback_d207_regim_nesetat_mesaj(tmp_path, monkeypatch):
    import bot_contabil
    S, uid = _db(tmp_path, regim=False)
    _seed_comisioane(S, uid)
    monkeypatch.setattr(bot_contabil, "get_session", lambda: S())
    # gardianul de tier își deschide propria sesiune (Felia 4b) → o legăm la aceeași DB
    from app.services import gating
    monkeypatch.setattr(gating, "get_session", lambda: S())

    bot = _FakeBot()
    query = SimpleNamespace(message=SimpleNamespace(chat_id=999))
    context = SimpleNamespace(bot=bot)

    await bot_contabil.execute_fisa_d207(query, context, uid, AN)
    assert len(bot.documents) == 0                         # niciun XML incomplet
    assert len(bot.messages) == 1                          # doar mesajul explicativ


# ════════════════════════════════════════════════════════
# 4. Regresie: rutele lunare D390/D301/D100 raman inregistrate
# ════════════════════════════════════════════════════════
def test_regresie_rute_lunare_neatinse():
    from app.http import app as webapp
    rules = {r.rule for r in webapp.flask_app.url_map.iter_rules()}
    assert "/api/v1/declaratie/<tip>/<int:year>/<int:month>" in rules   # lunar intact
    assert "/api/v1/declaratie-d207/<int:year>" in rules                # nou adaugat
    assert "/api/v1/declaratie-unica/<int:year>" in rules               # D212 intact
