"""
Felia 4b — APLICAREA gating-ului pe features + teaser-ul „armei secrete" (§1.7/§1.8).

Felia 4a a făcut tier-ul trial-aware; aici îl CONSUMĂM. Ce verificăm:
  · features gated (depunere D390/D301/D100/D207 → PRO, /bolt sync → START,
    D212 → START) — FREE primește invitația de upgrade, handler-ul NU rulează;
  · teaser-ul reconcilierii — FREE vede suma, NU cauzele/pașii (cârligul de aur);
  · TRIAL ACTIV = PRO peste tot (leagă 4a de 4b — testul crucial);
  · alertele de termene rămân FREE, NEatinse (ce trebuie să fie gratis, e gratis);
  · web: 403 upgrade_required pt FREE, trece pt PRO.

`now` nu se injectează aici — folosim trial_ends_at relativ la datetime.utcnow(),
ca în producție (determinist: ±zile mari, nu la limita secundei).
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import bot_contabil
from app.models import User
from app.services import gating
from app.services import subscription as sub
from app.integrations import bolt_sync
from app.integrations.imports import bolt_reconcile


# ══════════════════════════════════════════════════════════════
# Utilitare — DB in-memory + fake-uri Telegram (șablonul din test_sumar_test)
# ══════════════════════════════════════════════════════════════

def _db(tmp_path, nume="g.db", **user_kw):
    eng = create_engine(f"sqlite:///{(tmp_path / nume).as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=7, **user_kw); s.add(u); s.commit()
    uid = u.id; s.close()
    return S, uid


def _free():   return {}
def _pro():    return dict(stripe_status="active", stripe_tier="PRO")
def _start():  return dict(stripe_status="active", stripe_tier="START")
def _trial():  return dict(trial_ends_at=datetime.utcnow() + timedelta(days=30))
def _trial_expirat(): return dict(trial_ends_at=datetime.utcnow() - timedelta(days=1))


class _Query:
    """callback_query fals: reține ce s-a editat + expune message.chat_id."""
    def __init__(self, data):
        self.data = data
        self.edits = []
        self.message = SimpleNamespace(chat_id=42)
        self.from_user = SimpleNamespace(id=7)
    async def answer(self, *a, **kw): pass
    async def edit_message_text(self, text, **kw):
        self.edits.append((text, kw))


class _Msg:
    def __init__(self): self.replies = []
    async def reply_text(self, text, **kw): self.replies.append((text, kw))


class _Bot:
    def __init__(self): self.sent = []
    async def send_message(self, chat_id, text, **kw): self.sent.append((chat_id, text))


def _upd_cb(query):
    return SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=7),
                           effective_chat=SimpleNamespace(id=42))


def _wire(monkeypatch, S, uid):
    """Sesiunea + identitatea, pt bot_contabil ȘI gating."""
    monkeypatch.setattr(bot_contabil, "get_session", lambda: S())
    monkeypatch.setattr(gating, "get_session", lambda: S())
    monkeypatch.setattr(bot_contabil, "ensure_user", lambda update: uid)


# ══════════════════════════════════════════════════════════════
# 1. FREE apasă depunere D390 → upgrade, handler-ul NU rulează
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_free_d390_blocat_handlerul_nu_ruleaza(monkeypatch, tmp_path):
    S, uid = _db(tmp_path, **_free())
    _wire(monkeypatch, S, uid)
    apelat = []
    monkeypatch.setattr(bot_contabil, "execute_fisa_d390",
                        lambda *a, **kw: apelat.append(True))

    q = _Query("d390|2026|4")
    await bot_contabil.handle_callback_query(_upd_cb(q), SimpleNamespace(bot=_Bot()))

    assert apelat == []                                  # handler-ul NU s-a atins
    text, kw = q.edits[0]
    assert "planul PRO" in text and "Deschide Dashboard" in text
    assert kw.get("reply_markup") is not None            # butonul e acolo


@pytest.mark.asyncio
async def test_free_d301_d100_d207_du_toate_blocate(monkeypatch, tmp_path):
    """Toată maparea §1.8, nu doar D390 (d301/d100/d207 → PRO, du → START)."""
    S, uid = _db(tmp_path, **_free())
    _wire(monkeypatch, S, uid)
    for fn in ("execute_fisa_d301", "execute_fisa_d390",
               "execute_fisa_d100", "execute_fisa_d207"):
        monkeypatch.setattr(bot_contabil, fn, lambda *a, **kw: pytest.fail("a rulat!"))
    monkeypatch.setattr(bot_contabil.du_ui, "handle_callback",
                        lambda *a, **kw: pytest.fail("D212 a rulat!"))

    for data, tier in (("d301|2026|4", "PRO"), ("d100|2026|4", "PRO"),
                       ("d207|2026", "PRO"), ("du|an|2026", "START")):
        q = _Query(data)
        await bot_contabil.handle_callback_query(_upd_cb(q), SimpleNamespace(bot=_Bot()))
        assert q.edits, f"{data} n-a răspuns nimic"
        assert f"planul {tier}" in q.edits[0][0], f"{data} → tier greșit"


# ══════════════════════════════════════════════════════════════
# 2. PRO apasă depunere D390 → rulează normal
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_pro_d390_ruleaza(monkeypatch, tmp_path):
    S, uid = _db(tmp_path, **_pro())
    _wire(monkeypatch, S, uid)
    apelat = []

    async def _fake(query, context, user_id, year, month):
        apelat.append((user_id, year, month))
    monkeypatch.setattr(bot_contabil, "execute_fisa_d390", _fake)

    q = _Query("d390|2026|4")
    await bot_contabil.handle_callback_query(_upd_cb(q), SimpleNamespace(bot=_Bot()))

    assert apelat == [(uid, 2026, 4)]        # a rulat cu argumentele corecte
    assert q.edits == []                     # niciun mesaj de upgrade


# ══════════════════════════════════════════════════════════════
# 3. /bolt sync — FREE blocat (START+), START rulează
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_free_bolt_sync_blocat(monkeypatch, tmp_path):
    S, uid = _db(tmp_path, **_free())
    monkeypatch.setattr(gating, "get_session", lambda: S())
    monkeypatch.setattr(bolt_sync, "_resolve_user_id", lambda tg: uid)
    monkeypatch.setattr(bolt_sync, "get_month_summary",
                        lambda *a, **kw: pytest.fail("API-ul Bolt a fost apelat!"))
    msg = _Msg()
    upd = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=7))

    await bolt_sync.handle_bolt_command(upd, SimpleNamespace(args=["2026", "4"]))

    text, kw = msg.replies[0]
    assert "planul START" in text and "Deschide Dashboard" in text
    assert kw.get("reply_markup") is not None
    assert len(msg.replies) == 1             # NU a mai zis „Trag veniturile..."


@pytest.mark.asyncio
async def test_start_bolt_sync_ruleaza(monkeypatch, tmp_path):
    S, uid = _db(tmp_path, **_start())
    monkeypatch.setattr(gating, "get_session", lambda: S())
    monkeypatch.setattr(bolt_sync, "_resolve_user_id", lambda tg: uid)
    chemat = []
    monkeypatch.setattr(bolt_sync, "get_month_summary",
                        lambda *a, **kw: chemat.append(a) or {"n": 0})
    msg = _Msg()
    upd = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=7))

    await bolt_sync.handle_bolt_command(upd, SimpleNamespace(args=["2026", "4"]))

    assert chemat, "sync-ul n-a pornit pentru START"
    assert not any("planul" in t for t, _ in msg.replies)


@pytest.mark.asyncio
async def test_free_butonul_de_confirmare_bolt_blocat(monkeypatch, tmp_path):
    """Butonul rămas în istoric de dinainte de expirarea trialului NU mai scrie."""
    S, uid = _db(tmp_path, **_trial_expirat())
    monkeypatch.setattr(gating, "get_session", lambda: S())
    monkeypatch.setattr(bolt_sync, "_resolve_user_id", lambda tg: uid)
    monkeypatch.setattr(bolt_sync, "post_month",
                        lambda *a, **kw: pytest.fail("a scris în Registru!"))
    monkeypatch.setattr(bolt_sync, "get_month_summary",
                        lambda *a, **kw: pytest.fail("a chemat API-ul!"))

    q = _Query("bolt|confirm|2026|4")
    with pytest.raises(bolt_sync.ApplicationHandlerStop):
        await bolt_sync.handle_bolt_callback(_upd_cb(q), SimpleNamespace())
    assert "planul START" in q.edits[0][0]


def test_free_nu_primeste_sync_zilnic_automat(monkeypatch):
    """Sync-ul nocturn e ACELAȘI feature — altfel poarta de pe /bolt e cosmetică."""
    chemat = []
    monkeypatch.setattr(bolt_sync, "bolt_client_for_user",
                        lambda s, uid: chemat.append(uid))
    monkeypatch.setattr(bolt_sync, "get_session",
                        lambda: SimpleNamespace(close=lambda: None))

    free = SimpleNamespace(id=1, telegram_id=7, stripe_status=None,
                           stripe_tier=None, trial_ends_at=None)
    bolt_sync._daily_sync_one("token", free)
    assert chemat == [], "userul FREE a fost sincronizat automat"

    # START (și trial) trec mai departe — ajung la client
    platit = SimpleNamespace(id=2, telegram_id=8, stripe_status="active",
                             stripe_tier="START", trial_ends_at=None)
    bolt_sync._daily_sync_one("token", platit)
    assert chemat == [2]


# ══════════════════════════════════════════════════════════════
# 4. TEASER FREE — suma DA, cauzele/pașii NU (cârligul de aur)
# ══════════════════════════════════════════════════════════════

# Fraze care NU au voie să scape în teaser (sunt rezolvarea, adică PRO).
_DETALII_INTERZISE = ("Cauze normale", "sync mai vechi", "/bolt", "API-ul Bolt arată",
                      "adăugate manual", "rulează")


def test_teaser_free_arata_suma_dar_nu_detaliile():
    # declarat 1000, API 1200 → discrepanță de 200
    linie = bolt_reconcile.bolt_amount_confirm_line(1200.0, 1000.0, detailed=False)
    assert "200.00 lei" in linie                      # suma: DA
    assert "nepotrivire" in linie and "PRO" in linie
    for interzis in _DETALII_INTERZISE:
        assert interzis not in linie, f"a scăpat detaliul: {interzis}"
    # nici cifrele-sursă nu se dau (ar fi indiciu de cauză)
    assert "1200" not in linie and "1000" not in linie


def test_teaser_free_axa_bancara_nu_scapa_detaliile(monkeypatch):
    monkeypatch.setattr(bolt_reconcile, "bank_bolt_net_in_year", lambda c, an: 9000.0)
    monkeypatch.setattr("app.integrations.bolt_sync.net_bancabil_an",
                        lambda uid, an: 12000.0)
    nudge = bolt_reconcile.bank_reconcile_nudge(None, 1, [], 2026, detailed=False)
    assert "3000.00 lei" in nudge
    for interzis in _DETALII_INTERZISE:
        assert interzis not in nudge, f"a scăpat detaliul: {interzis}"
    assert "9000" not in nudge and "12000" not in nudge


def test_teaser_free_prezenta_nu_enumera_lunile(monkeypatch):
    """Axa de prezență: câte luni, dar fără enumerare și fără comanda de sync."""
    monkeypatch.setattr(bolt_reconcile, "bolt_months_in_statement",
                        lambda c: {(2026, 3), (2026, 4)})
    monkeypatch.setattr(bolt_reconcile, "has_bolt_income", lambda s, u, y, m: False)
    nudge = bolt_reconcile.bolt_reconcile_nudge(None, 1, [], detailed=False)
    assert "2 luni" in nudge and "START" in nudge
    assert "Martie" not in nudge and "Aprilie" not in nudge
    assert "/bolt" not in nudge


# ══════════════════════════════════════════════════════════════
# 5. TEASER PRO — verdictul COMPLET (cauze + pași), ca înainte
# ══════════════════════════════════════════════════════════════

def test_pro_primeste_verdictul_complet():
    linie = bolt_reconcile.bolt_amount_confirm_line(1200.0, 1000.0, detailed=True)
    assert "1200.00" in linie and "1000.00" in linie      # ambele cifre-sursă
    assert "Cauze normale" in linie and "/bolt" in linie  # cauzele + pasul
    assert "planul PRO" not in linie


def test_default_detailed_e_true_regresie():
    """Fără `detailed`, comportamentul e BIT-IDENTIC cu cel dinainte de 4b."""
    assert (bolt_reconcile.bolt_amount_confirm_line(1200.0, 1000.0)
            == bolt_reconcile.bolt_amount_confirm_line(1200.0, 1000.0, detailed=True))


def test_verdict_ok_neschimbat_pentru_toata_lumea():
    """✅ „API-ul confirmă X" e liniștire, nu armă secretă → rămâne și pt FREE."""
    ok_free = bolt_reconcile.bolt_amount_confirm_line(1000.0, 1000.0, detailed=False)
    ok_pro = bolt_reconcile.bolt_amount_confirm_line(1000.0, 1000.0, detailed=True)
    assert ok_free == ok_pro and "confirmă 1000.00 lei ✅" in ok_free


# ══════════════════════════════════════════════════════════════
# 6. CRUCIAL — TRIAL ACTIV = PRO peste tot (leagă 4a de 4b)
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_trial_activ_depunerea_ruleaza(monkeypatch, tmp_path):
    S, uid = _db(tmp_path, **_trial())          # user nou, 30 zile, FĂRĂ card
    _wire(monkeypatch, S, uid)
    apelat = []

    async def _fake(query, context, user_id, year, month):
        apelat.append(user_id)
    monkeypatch.setattr(bot_contabil, "execute_fisa_d390", _fake)

    q = _Query("d390|2026|4")
    await bot_contabil.handle_callback_query(_upd_cb(q), SimpleNamespace(bot=_Bot()))

    assert apelat == [uid], "userul în trial a fost blocat — 4a nu se leagă de 4b"
    assert q.edits == []


def test_trial_activ_are_toate_tier_urile(monkeypatch, tmp_path):
    """Trial → PRO: trece de START (bolt/D212) ȘI de PRO (declarații/reconciliere)."""
    S, uid = _db(tmp_path, **_trial())
    monkeypatch.setattr(gating, "get_session", lambda: S())
    s = S()
    assert gating.has_feature(s, uid, sub.START) is True
    assert gating.has_feature(s, uid, sub.PRO) is True
    assert gating.has_feature(s, uid, sub.MAX) is False    # trial = PRO, nu MAX
    s.close()
    ok, _, _ = gating.require_tier_bot(uid, sub.PRO, feature="declaratii")
    assert ok is True


def test_trial_activ_primeste_reconcilierea_completa(monkeypatch, tmp_path):
    """Reconcilierea în trial = verdict COMPLET (același drum ca PRO plătit)."""
    S, uid = _db(tmp_path, **_trial())
    monkeypatch.setattr(gating, "get_session", lambda: S())
    s = S()
    detailed = gating.has_feature(s, uid, sub.PRO)
    s.close()
    linie = bolt_reconcile.bolt_amount_confirm_line(1200.0, 1000.0, detailed=detailed)
    assert "Cauze normale" in linie and "1200.00" in linie


# ══════════════════════════════════════════════════════════════
# 7. Trial EXPIRAT → FREE peste tot
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_trial_expirat_depunerea_blocata(monkeypatch, tmp_path):
    S, uid = _db(tmp_path, **_trial_expirat())
    _wire(monkeypatch, S, uid)
    monkeypatch.setattr(bot_contabil, "execute_fisa_d390",
                        lambda *a, **kw: pytest.fail("a rulat după expirare!"))

    q = _Query("d390|2026|4")
    await bot_contabil.handle_callback_query(_upd_cb(q), SimpleNamespace(bot=_Bot()))
    assert "planul PRO" in q.edits[0][0]


def test_trial_expirat_primeste_teaser(monkeypatch, tmp_path):
    S, uid = _db(tmp_path, **_trial_expirat())
    monkeypatch.setattr(gating, "get_session", lambda: S())
    s = S()
    detailed = gating.has_feature(s, uid, sub.PRO)
    s.close()
    assert detailed is False
    linie = bolt_reconcile.bolt_amount_confirm_line(1200.0, 1000.0, detailed=detailed)
    assert "nepotrivire" in linie and "Cauze normale" not in linie


# ══════════════════════════════════════════════════════════════
# 8. CRUCIAL — alertele de termene rămân FREE, NEatinse
# ══════════════════════════════════════════════════════════════

def test_alertele_de_termene_nu_sunt_gated():
    """proactive_alerts + fiscal_calendar = FREE „Radar". Zero gating în ele."""
    from pathlib import Path
    rad = Path(__file__).resolve().parent.parent / "app"
    for rel in ("services/proactive_alerts.py", "domain/fiscal_calendar.py"):
        p = rad / rel
        if not p.exists():
            continue
        src = p.read_text(encoding="utf-8")
        assert "gating" not in src, f"{rel} a fost atins de gating"
        assert "has_tier_at_least" not in src and "require_tier" not in src


def test_namespace_urile_gratuite_trec_neatinse():
    """Doar declarațiile + D212 sunt în hartă; restul (raport, registru, ghid,
    alerte, export, plată, vehicul, bancă) rămân libere."""
    gated = set(gating.NAMESPACE_FEATURE)
    assert gated == {"d301", "d390", "d100", "d207", "du"}
    for liber in ("report", "registru", "registru_annual", "registru_monthly",
                  "alerts", "ghid", "export", "plata", "reminder", "vehicul",
                  "parcurs", "nav", "settings", "fiscal", "tvadecl", "confirm",
                  "onb", "coduri", "bankpost", "banktax"):
        assert liber not in gated, f"{liber} n-are voie să fie gated"


@pytest.mark.asyncio
async def test_free_poate_deschide_ecranul_tva_declaratii(monkeypatch, tmp_path):
    """Ecranul-poartă (unde VEZI ce ai de depus) e FREE — doar depunerea e PRO."""
    S, uid = _db(tmp_path, **_free())
    _wire(monkeypatch, S, uid)
    apelat = []

    async def _fake(query, context, user_id, year, month):
        apelat.append(user_id)
    monkeypatch.setattr(bot_contabil, "execute_tva_declaratii", _fake)

    q = _Query("tvadecl|2026|4")
    await bot_contabil.handle_callback_query(_upd_cb(q), SimpleNamespace(bot=_Bot()))
    assert apelat == [uid] and q.edits == []


# ══════════════════════════════════════════════════════════════
# 9. Web — _require_tier: FREE → 403 upgrade_required, PRO → trece
# ══════════════════════════════════════════════════════════════

def _web(monkeypatch, tmp_path, nume, **user_kw):
    from app.http import app as webapp
    S, uid = _db(tmp_path, nume, **user_kw)
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    monkeypatch.setattr(gating, "get_session", lambda: S())
    return webapp, webapp.flask_app.test_client(), uid


def test_web_free_403_upgrade_required(monkeypatch, tmp_path):
    webapp, client, uid = _web(monkeypatch, tmp_path, "w1.db", **_free())
    r = client.get("/api/v1/declaratie/D390/2026/4")
    assert r.status_code == 403
    d = r.get_json()
    assert d["error"] == "upgrade_required"
    assert d["tier_necesar"] == "PRO" and d["tier_curent"] == "FREE"
    assert "Deschide Dashboard" in d["message"]


def test_web_d207_free_403(monkeypatch, tmp_path):
    webapp, client, uid = _web(monkeypatch, tmp_path, "w2.db", **_free())
    r = client.get("/api/v1/declaratie-d207/2026")
    assert r.status_code == 403 and r.get_json()["error"] == "upgrade_required"


def test_web_pro_trece_de_gardian(monkeypatch, tmp_path):
    """PRO nu mai e oprit de tier — ajunge în logica rutei (aici: fără bază → 400,
    NU 403). Contează că gardianul l-a lăsat să treacă."""
    webapp, client, uid = _web(monkeypatch, tmp_path, "w3.db", **_pro())
    r = client.get("/api/v1/declaratie/D390/2026/4")
    assert r.status_code != 403


def test_web_trial_trece_de_gardian(monkeypatch, tmp_path):
    webapp, client, uid = _web(monkeypatch, tmp_path, "w4.db", **_trial())
    r = client.get("/api/v1/declaratie/D390/2026/4")
    assert r.status_code != 403


def test_web_require_tier_intoarce_none_cand_are_dreptul(monkeypatch, tmp_path):
    webapp, client, uid = _web(monkeypatch, tmp_path, "w5.db", **_pro())
    with webapp.flask_app.test_request_context():
        assert webapp._require_tier(uid, sub.PRO, feature="declaratii") is None


# ══════════════════════════════════════════════════════════════
# 10. Regresie — 4a neatinsă + copy-ul respectă tonul decis
# ══════════════════════════════════════════════════════════════

def test_regresie_subscription_4a_neatinsa():
    """Felia 4b doar CONSUMĂ 4a — semantica tier-ului rămâne exact cea de acolo."""
    u_trial = SimpleNamespace(stripe_status=None, stripe_tier=None,
                              trial_ends_at=datetime.utcnow() + timedelta(days=5))
    u_max = SimpleNamespace(stripe_status="active", stripe_tier="MAX",
                            trial_ends_at=datetime.utcnow() + timedelta(days=5))
    assert sub.user_tier(u_trial) == "PRO" and sub.is_in_trial(u_trial) is True
    assert sub.user_tier(u_max) == "MAX"      # plata primează, nu downgradăm
    assert sub.has_tier_at_least(u_trial, sub.PRO) is True
    assert sub.has_tier_at_least(u_trial, sub.MAX) is False


def test_user_inexistent_e_tratat_free_conservator(monkeypatch, tmp_path):
    S, _ = _db(tmp_path, "x.db", **_pro())
    monkeypatch.setattr(gating, "get_session", lambda: S())
    s = S()
    assert gating.has_feature(s, 99999, sub.PRO) is False   # user inexistent
    s.close()


def test_eroare_db_nu_deschide_poarta(monkeypatch):
    """Defensiv: dacă DB-ul crapă, poarta rămâne ÎNCHISĂ (nu deschidem din greșeală)."""
    def _boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(gating, "get_session", _boom)
    with pytest.raises(RuntimeError):
        gating.user_has_feature(1, sub.PRO)   # get_session însuși crapă
    # eroare ÎN interogare (sesiune ok) → False, nu excepție
    monkeypatch.setattr(gating, "get_session",
                        lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(gating.users_repo, "get_by_id",
                        lambda s, uid: (_ for _ in ()).throw(RuntimeError("boom")))
    assert gating.user_has_feature(1, sub.PRO) is False


def test_copy_upgrade_ton_si_continut():
    """Ton decis: liniștitor, adresare «tu», emoji prietenos. Fără alarmă."""
    t = gating.upgrade_text("declaratii")
    assert "planul PRO" in t and "Deschide Dashboard" in t
    assert "💡" in t
    assert "îți" in t or "tale" in t                  # adresare personală
    for alarmant in ("EROARE", "interzis", "nu ai voie", "blocat"):
        assert alarmant.lower() not in t.lower()
    # feature necunoscut → text generic, nu KeyError
    assert "Deschide Dashboard" in gating.upgrade_text("inexistent")


def test_linia_de_trial_apare_doar_in_trial():
    u = SimpleNamespace(stripe_status=None, stripe_tier=None,
                        trial_ends_at=datetime.utcnow() + timedelta(days=10))
    t = gating.upgrade_text("declaratii", user=u)
    assert "perioada PRO gratuită" in t and "10 zile" in t
    # fără trial → fără linie
    assert "perioada PRO gratuită" not in gating.upgrade_text("declaratii")
    assert gating.trial_line(None) is None


def test_teaser_nu_e_alarmant():
    """Frica de ANAF e menționată o dată, calm — nu strigăm la user."""
    t = gating.teaser_reconciliere(-237.5)
    assert "237.50 lei" in t                 # mărimea, nu semnul
    assert "-237" not in t
    assert "posibilă nepotrivire" in t and "Am observat" in t
    for alarmant in ("⚠️", "URGENT", "AMENDĂ", "RISCI"):
        assert alarmant not in t
