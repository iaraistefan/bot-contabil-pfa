"""
F1 pas 2 — WIRING: cele patru call-site-uri cu artefact scriu in arhiva.

  bot_contabil.py  _trimite_declaratie_noua  (D100/D301/D390)
  bot_contabil.py  execute_fisa_d207         (D207)
  app/http/app.py  /api/v1/declaratie/...    (D100/D301/D390)
  app/http/app.py  /api/v1/d207/...          (D207)

D212 NU e legat aici — n-are artefact, deci n-are moment de generare (vezi
blocantul de PRODUS „D212 nu produce niciun artefact").

CE APARA TESTELE
  1. fiecare din cele patru produce un RAND;
  2. o generare ESUATA (generat=False, ex. D100 scutit) produce si ea rand —
     „am incercat si n-a iesit" e informatie fiscala;
  3. LIVRAREA REUSESTE chiar daca arhivarea cade (esec injectat). Ordinea e
     genereaza → arhiveaza → livreaza, iar arhivarea NU are drept de veto.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import bot_contabil
from app.models import User, DeclaratieGenerata
from app.services import declaratii_arhiva as arh

AN, LUNA = 2026, 3


# ════════════════════════════════════════════════════════════
#   Fixture comuna: DB in tmp + arhiva legata la ea
# ════════════════════════════════════════════════════════════

def _db(monkeypatch, tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 'a.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S()
    u = User(telegram_id=99, activity_code="ridesharing", onboarding_completed=True)
    s.add(u); s.commit(); uid = u.id; s.close()
    # Arhiva isi deschide sesiune PROPRIE -> o legam la baza de test.
    monkeypatch.setattr(arh, "get_session", lambda: S())
    return S, uid


def _randuri(S, tip=None):
    s = S()
    q = s.query(DeclaratieGenerata)
    if tip:
        q = q.filter(DeclaratieGenerata.tip == tip)
    out = q.all()
    s.close()
    return out


_PROFIL = {
    "firma_cui": "12345678", "cod_special_tva": "RO12345678",
    "firma_nume": "IARAI STEFAN PFA", "regim_nerezident_bolt": "BOLT_CU_CRF",
    "activity_code": "ridesharing",
}


# ════════════════════════════════════════════════════════════
#   BOT — D100/D301/D390 si D207
# ════════════════════════════════════════════════════════════

class _Q:
    def __init__(self):
        self.message = SimpleNamespace(chat_id=99)


class _Bot:
    def __init__(self):
        self.mesaje = []
        self.documente = []

    async def send_message(self, **kw):
        self.mesaje.append(kw)

    async def send_document(self, **kw):
        self.documente.append(kw)


def _ctx():
    return SimpleNamespace(bot=_Bot())


def _bot_env(monkeypatch, S, tip_totals=None):
    """Monkeypatch minimul ca handlerele bot sa ajunga la generator."""
    monkeypatch.setattr(bot_contabil, "get_session", lambda: S())
    monkeypatch.setattr(bot_contabil.gating, "require_tier_bot",
                        lambda *a, **k: (True, "", None))
    monkeypatch.setattr(bot_contabil.users_repo, "get_profile_dict",
                        lambda s, uid: dict(_PROFIL))
    monkeypatch.setattr(bot_contabil.tax_engine, "compute_period",
                        lambda s, **k: tip_totals or {"vat_out_total": 2100.0,
                                                      "cota_tva": 0.21})


@pytest.mark.asyncio
async def test_bot_d390_produce_rand(monkeypatch, tmp_path):
    S, uid = _db(monkeypatch, tmp_path)
    _bot_env(monkeypatch, S)
    ctx = _ctx()
    await bot_contabil._trimite_declaratie_noua(_Q(), ctx, uid, AN, LUNA, "D390")

    r = _randuri(S, "D390")
    assert len(r) == 1
    assert r[0].an == AN and r[0].luna == LUNA and r[0].generat is True
    assert r[0].xml and r[0].nume_fisier_xml
    assert r[0].inputuri_json["firma"]["cui_pfa"]        # serializat pe lista explicita
    assert "ghid_plain" in r[0].rezultat_json
    assert ctx.bot.documente, "XML-ul trebuie livrat"


@pytest.mark.asyncio
async def test_bot_d207_produce_rand(monkeypatch, tmp_path):
    S, uid = _db(monkeypatch, tmp_path)
    _bot_env(monkeypatch, S)
    monkeypatch.setattr(bot_contabil.tax_engine, "nerezident_anual_by_brand",
                        lambda s, **k: {"bolt": 10_000.0})
    ctx = _ctx()
    await bot_contabil.execute_fisa_d207(_Q(), ctx, uid, AN)

    r = _randuri(S, "D207")
    assert len(r) == 1
    assert r[0].an == AN and r[0].luna is None      # ANUALA -> fara luna
    assert r[0].inputuri_json["by_brand"] == {"bolt": 10_000.0}


# ════════════════════════════════════════════════════════════
#   WEB — aceleasi doua drumuri, prin endpoint
# ════════════════════════════════════════════════════════════

def _web(monkeypatch, S, uid):
    from app.http import app as webapp
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "_require_tier", lambda *a, **k: None)  # gating PRO
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    monkeypatch.setattr(webapp.users_repo, "get_profile_dict",
                        lambda s, u: dict(_PROFIL))
    monkeypatch.setattr(webapp.tax_engine, "compute_period",
                        lambda s, **k: {"vat_out_total": 2100.0, "cota_tva": 0.21})
    monkeypatch.setattr(webapp.tax_engine, "nerezident_anual_by_brand",
                        lambda s, **k: {"bolt": 10_000.0})
    return webapp.flask_app.test_client()


def test_web_d390_produce_rand(monkeypatch, tmp_path):
    S, uid = _db(monkeypatch, tmp_path)
    c = _web(monkeypatch, S, uid)
    resp = c.get(f"/api/v1/declaratie/D390/{AN}/{LUNA}")
    assert resp.status_code == 200

    r = _randuri(S, "D390")
    assert len(r) == 1 and r[0].luna == LUNA and r[0].xml


def test_web_d207_produce_rand(monkeypatch, tmp_path):
    S, uid = _db(monkeypatch, tmp_path)
    c = _web(monkeypatch, S, uid)
    resp = c.get(f"/api/v1/declaratie-d207/{AN}")
    assert resp.status_code == 200

    r = _randuri(S, "D207")
    assert len(r) == 1 and r[0].luna is None


# ════════════════════════════════════════════════════════════
#   ESECURILE se arhiveaza (generat=False)
# ════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_generare_esuata_produce_si_ea_rand(monkeypatch, tmp_path):
    """
    D100 la cota nerezident 0/None: `rez.generat=False`, fara XML. „Am incercat si
    n-a iesit" e informatie fiscala — trebuie sa ramana urma.
    """
    S, uid = _db(monkeypatch, tmp_path)
    _bot_env(monkeypatch, S)
    # profil FARA regim nerezident -> D100 nu se genereaza
    monkeypatch.setattr(bot_contabil.users_repo, "get_profile_dict",
                        lambda s, uid_: {k: v for k, v in _PROFIL.items()
                                         if k != "regim_nerezident_bolt"})
    await bot_contabil._trimite_declaratie_noua(_Q(), _ctx(), uid, AN, LUNA, "D100")

    r = _randuri(S, "D100")
    assert len(r) == 1
    assert r[0].generat is False
    assert r[0].motiv_negenerat                      # „scutit" / „neconfigurat"
    assert r[0].xml is None


# ════════════════════════════════════════════════════════════
#   ARHIVAREA N-ARE DREPT DE VETO
# ════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_livrarea_reuseste_chiar_daca_arhivarea_cade(monkeypatch, tmp_path, caplog):
    """
    Esec de arhivare INJECTAT: userul isi primeste declaratia oricum, iar esecul
    tipa in log. Ordinea genereaza → arhiveaza → livreaza nu da arhivarii drept
    de veto asupra livrarii.
    """
    S, uid = _db(monkeypatch, tmp_path)
    _bot_env(monkeypatch, S)

    def _boom():
        raise RuntimeError("DB indisponibil")
    monkeypatch.setattr(arh, "get_session", _boom)

    ctx = _ctx()
    with caplog.at_level("ERROR"):
        await bot_contabil._trimite_declaratie_noua(_Q(), ctx, uid, AN, LUNA, "D390")

    assert ctx.bot.documente, "XML-ul TREBUIE livrat chiar daca arhivarea a cazut"
    assert "ARHIVARE DECLARATIE ESUATA" in caplog.text
    for fragment in ("tip=D390", f"an={AN}", f"luna={LUNA}"):
        assert fragment in caplog.text


# ════════════════════════════════════════════════════════════
#   GARDIAN — call-site-urile nu au voie sa revina la generatorul brut
# ════════════════════════════════════════════════════════════

def test_call_siteurile_folosesc_arhiva():
    """
    Cade daca un call-site revine la `decl.genereaza(...)` direct: declaratia ar
    pleca la user fara sa lase urma, tacit.
    """
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    bot = (root / "bot_contabil.py").read_text(encoding="utf-8")
    web = (root / "app" / "http" / "app.py").read_text(encoding="utf-8")

    assert "arhiva.genereaza_si_arhiveaza(" in bot
    assert "arhiva.genereaza_si_arhiveaza_d207(" in bot
    assert "arhiva.genereaza_si_arhiveaza(" in web
    assert "arhiva.genereaza_si_arhiveaza_d207(" in web
    # generatorul brut nu mai are voie sa fie chemat direct din call-site-uri
    assert "decl_nou.genereaza(" not in bot
    assert "decl_nou.genereaza_d207_anual(" not in bot
    assert "decl.genereaza(" not in web
    assert "decl.genereaza_d207_anual(" not in web
