"""
Brick 2b — inițierea plății: Stripe Checkout Session (§1.7 Felia 2).

MIEZUL testat aici: `client_reference_id` ajunge la Stripe. Fără el, webhook-ul din
2c primește o plată fără să știe A CUI e — abonamentul n-ar putea fi acordat nimănui.

Al doilea miez, în oglindă: 2b NU scrie în DB. Nici la „succes". `success_url` e
ocolibil (oricine îl poate deschide fără să plătească), deci sursa de adevăr rămâne
webhook-ul semnat. Testăm asta STRUCTURAL, nu doar pe comportament.

ZERO apeluri reale la Stripe: SDK-ul e înlocuit cu un dublu care înregistrează
parametrii primiți.
"""

from types import SimpleNamespace

import pytest

from app.services import gating
from app.services import stripe_checkout
from app.services import stripe_config
from app.services import subscription as sub


# ══════════════════════════════════════════════════════════════
# Dublu de test pentru SDK-ul Stripe
# ══════════════════════════════════════════════════════════════

class _FakeSDK:
    """
    Imită exact cât folosim: `sdk.checkout.Session.create(**params)`.
    Reține parametrii în `.captured` ca să putem verifica CE i-am trimis lui Stripe.
    """

    URL = "https://checkout.stripe.com/c/pay/cs_test_123"

    def __init__(self, crapa=False, raspuns=None):
        self.captured = None
        eu = self

        class _Session:
            @staticmethod
            def create(**kw):
                eu.captured = kw
                if crapa:
                    raise RuntimeError("Stripe indisponibil")
                return raspuns if raspuns is not None else SimpleNamespace(url=_FakeSDK.URL)

        class _Checkout:
            Session = _Session

        self.checkout = _Checkout


def _fake_sdk(monkeypatch, **kw):
    sdk = _FakeSDK(**kw)
    monkeypatch.setattr(stripe_checkout, "_stripe", lambda: sdk)
    return sdk


def _preturi(monkeypatch, start=None, pro=None, max_=None, secret="sk_test_x"):
    """Configurarea Stripe din env (aceleași câmpuri ca în 2a)."""
    monkeypatch.setattr(stripe_config.settings, "stripe_price_start", start)
    monkeypatch.setattr(stripe_config.settings, "stripe_price_pro", pro)
    monkeypatch.setattr(stripe_config.settings, "stripe_price_max", max_)
    monkeypatch.setattr(stripe_config.settings, "stripe_secret_key", secret)


def _user(id=7, customer_id=None):
    return SimpleNamespace(id=id, stripe_customer_id=customer_id)


# ══════════════════════════════════════════════════════════════
# 1. Sesiunea de checkout — client_reference_id e miezul
# ══════════════════════════════════════════════════════════════

def test_checkout_trimite_client_reference_id(monkeypatch):
    """CRUCIAL pt 2c: plata trebuie să poarte id-ul userului nostru."""
    _preturi(monkeypatch, pro="price_PRO")
    sdk = _fake_sdk(monkeypatch)

    url = stripe_checkout.create_checkout_session(_user(id=42), sub.PRO)

    assert url == _FakeSDK.URL
    assert sdk.captured["client_reference_id"] == "42"      # STRING, cum cere Stripe
    # redundanța pt evenimentele de reînnoire (nu poartă client_reference_id)
    assert sdk.captured["metadata"]["user_id"] == "42"
    assert sdk.captured["subscription_data"]["metadata"]["user_id"] == "42"
    assert sdk.captured["subscription_data"]["metadata"]["tier"] == "PRO"


def test_checkout_trimite_price_id_ul_tierului(monkeypatch):
    _preturi(monkeypatch, start="price_S", pro="price_P", max_="price_M")
    sdk = _fake_sdk(monkeypatch)

    stripe_checkout.create_checkout_session(_user(), sub.MAX)
    assert sdk.captured["line_items"] == [{"price": "price_M", "quantity": 1}]

    stripe_checkout.create_checkout_session(_user(), sub.START)
    assert sdk.captured["line_items"] == [{"price": "price_S", "quantity": 1}]


def test_checkout_e_abonament_cu_pagini_de_intoarcere(monkeypatch):
    _preturi(monkeypatch, pro="price_P")
    sdk = _fake_sdk(monkeypatch)

    stripe_checkout.create_checkout_session(_user(), sub.PRO)

    assert sdk.captured["mode"] == "subscription"           # recurent, nu plată unică
    assert sdk.captured["success_url"].endswith("/stripe/success")
    assert sdk.captured["cancel_url"].endswith("/stripe/cancel")
    assert sdk.captured["success_url"].startswith("https://")


def test_checkout_base_url_injectabil(monkeypatch):
    """Domeniul e injectabil (teste / eventual staging), default = producția."""
    _preturi(monkeypatch, pro="price_P")
    sdk = _fake_sdk(monkeypatch)

    stripe_checkout.create_checkout_session(_user(), sub.PRO, base_url="https://x.test/")
    assert sdk.captured["success_url"] == "https://x.test/stripe/success"
    assert sdk.captured["cancel_url"] == "https://x.test/stripe/cancel"


# ══════════════════════════════════════════════════════════════
# 2. Degradare grațioasă — niciodată excepție în fața userului
# ══════════════════════════════════════════════════════════════

def test_fara_chei_intoarce_none_nu_crapa(monkeypatch):
    """Plata neconfigurată (fără secret key) → None, aplicația merge mai departe."""
    _preturi(monkeypatch, pro="price_P", secret=None)
    # NU mockăm _stripe: vrem calea reală prin `is_payment_configured`.
    assert stripe_checkout.create_checkout_session(_user(), sub.PRO) is None


def test_fara_price_pentru_tier_intoarce_none(monkeypatch):
    """Cheie da, price pt tier-ul cerut nu → None (nu ghicim alt price)."""
    _preturi(monkeypatch, pro="price_P")                    # START/MAX neconfigurate
    assert stripe_checkout.create_checkout_session(_user(), sub.START) is None
    assert stripe_checkout.create_checkout_session(_user(), sub.MAX) is None


def test_free_nu_se_cumpara(monkeypatch):
    _preturi(monkeypatch, start="price_S", pro="price_P", max_="price_M")
    assert stripe_checkout.create_checkout_session(_user(), sub.FREE) is None
    assert stripe_checkout.create_checkout_session(_user(), "INVENTAT") is None


def test_stripe_picat_intoarce_none(monkeypatch):
    """Excepție din SDK → None + log, NU propagăm în handler-ul de bot."""
    _preturi(monkeypatch, pro="price_P")
    _fake_sdk(monkeypatch, crapa=True)
    assert stripe_checkout.create_checkout_session(_user(), sub.PRO) is None


def test_raspuns_fara_url_intoarce_none(monkeypatch):
    _preturi(monkeypatch, pro="price_P")
    _fake_sdk(monkeypatch, raspuns=SimpleNamespace())        # fără .url
    assert stripe_checkout.create_checkout_session(_user(), sub.PRO) is None


def test_user_fara_id_e_refuzat(monkeypatch):
    """Fără id nu există punte spre 2c → refuzăm, nu creăm o plată orfană."""
    _preturi(monkeypatch, pro="price_P")
    sdk = _fake_sdk(monkeypatch)
    assert stripe_checkout.create_checkout_session(SimpleNamespace(id=None), sub.PRO) is None
    assert sdk.captured is None                             # nici n-am sunat Stripe


# ══════════════════════════════════════════════════════════════
# 3. Reabonare — refolosim clientul Stripe existent
# ══════════════════════════════════════════════════════════════

def test_refoloseste_stripe_customer_id_daca_exista(monkeypatch):
    _preturi(monkeypatch, pro="price_P")
    sdk = _fake_sdk(monkeypatch)

    stripe_checkout.create_checkout_session(_user(customer_id="cus_vechi"), sub.PRO)
    assert sdk.captured["customer"] == "cus_vechi"


def test_fara_customer_id_lasa_stripe_sa_creeze_unul(monkeypatch):
    """User nou → NU trimitem `customer` gol; Stripe creează clientul, 2c îl salvează."""
    _preturi(monkeypatch, pro="price_P")
    sdk = _fake_sdk(monkeypatch)

    stripe_checkout.create_checkout_session(_user(customer_id=None), sub.PRO)
    assert "customer" not in sdk.captured


# ══════════════════════════════════════════════════════════════
# 4. Butonul de upgrade duce la tier-ul CERUT
# ══════════════════════════════════════════════════════════════

def _callback_data(markup):
    return markup.inline_keyboard[0][0].callback_data


def test_butonul_duce_la_checkout_ul_tierului(monkeypatch):
    _preturi(monkeypatch, start="price_S", pro="price_P", max_="price_M")

    assert _callback_data(gating.upgrade_markup(sub.PRO)) == "upgrade|PRO"
    assert _callback_data(gating.upgrade_markup(sub.MAX)) == "upgrade|MAX"
    assert _callback_data(gating.upgrade_markup(sub.START)) == "upgrade|START"


def test_butonul_e_etichetat_cu_tierul(monkeypatch):
    _preturi(monkeypatch, pro="price_P")
    buton = gating.upgrade_markup(sub.PRO).inline_keyboard[0][0]
    assert "PRO" in buton.text
    assert buton.web_app is None                            # buton de callback, nu WebApp


def test_gating_pro_da_buton_pro_iar_start_da_buton_start(monkeypatch, tmp_path):
    """Capătul real: feature-ul decide tier-ul, tier-ul decide butonul."""
    _preturi(monkeypatch, start="price_S", pro="price_P", max_="price_M")
    monkeypatch.setattr(gating, "user_has_feature", lambda uid, t: False)
    monkeypatch.setattr(gating, "_load_user", lambda uid: None)

    ok, text, markup = gating.require_tier_bot(1, sub.PRO, feature="declaratii")
    assert ok is False and _callback_data(markup) == "upgrade|PRO"
    assert "planul PRO" in text

    ok, text, markup = gating.require_tier_bot(1, sub.START, feature="bolt_sync")
    assert ok is False and _callback_data(markup) == "upgrade|START"
    assert "planul START" in text


def test_textul_numeste_exact_butonul(monkeypatch):
    """Mesajul nu voie să trimită la un buton care nu există (afișaj == realitate)."""
    _preturi(monkeypatch, pro="price_P")
    monkeypatch.setattr(gating, "_load_user", lambda uid: None)

    text = gating.upgrade_text("declaratii")
    eticheta = gating.upgrade_markup(sub.PRO).inline_keyboard[0][0].text
    assert eticheta in text
    assert "Deschide Dashboard" not in text                 # butonul ăla nu mai e acolo


def test_fara_plata_configurata_ramane_butonul_vechi(monkeypatch):
    """Degradare grațioasă: fără chei/price, comportamentul din 4b, neschimbat."""
    _preturi(monkeypatch, secret=None)                      # nimic configurat
    markup = gating.upgrade_markup(sub.PRO)
    buton = markup.inline_keyboard[0][0]

    assert buton.callback_data is None
    assert buton.web_app is not None                        # WebApp spre dashboard
    assert "Deschide Dashboard" in buton.text
    assert "Deschide Dashboard" in gating.upgrade_text("declaratii")


def test_fara_tier_ramane_butonul_vechi(monkeypatch):
    """Apel fără tier (compatibilitate) → dashboard, nu buton mort."""
    _preturi(monkeypatch, pro="price_P")
    buton = gating.upgrade_markup().inline_keyboard[0][0]
    assert buton.web_app is not None and buton.callback_data is None


def test_tier_fara_price_cade_pe_dashboard(monkeypatch):
    """PRO configurat, MAX nu → butonul pt MAX nu duce într-un checkout inexistent."""
    _preturi(monkeypatch, pro="price_P")
    assert _callback_data(gating.upgrade_markup(sub.PRO)) == "upgrade|PRO"
    assert gating.upgrade_markup(sub.MAX).inline_keyboard[0][0].web_app is not None


# ══════════════════════════════════════════════════════════════
# 5. Paginile de întoarcere — cosmetice, fără auth, fără DB
# ══════════════════════════════════════════════════════════════

def _client():
    from app.http import app as webapp
    return webapp.flask_app.test_client()


def test_pagina_succes_200_fara_auth():
    r = _client().get("/stripe/success")
    assert r.status_code == 200
    assert "text/html" in r.headers["Content-Type"]
    assert "Mulțumim" in r.get_data(as_text=True)


def test_pagina_cancel_200_fara_auth():
    r = _client().get("/stripe/cancel")
    assert r.status_code == 200
    assert "anulat" in r.get_data(as_text=True).lower()


def test_paginile_nu_cer_identitate(monkeypatch):
    """
    Gardian: dacă cineva le pune `_require_user`, testul cade. Redirectul de la Stripe
    NU are initData Telegram — o pagină cu auth ar arăta 401 exact după o plată reușită.
    """
    from app.http import app as webapp

    def _explodeaza():
        raise AssertionError("paginile Stripe NU trebuie să ceară identitate")

    monkeypatch.setattr(webapp, "_resolve_user_id", _explodeaza)
    assert _client().get("/stripe/success").status_code == 200
    assert _client().get("/stripe/cancel").status_code == 200


def test_paginile_nu_promit_activarea_instantanee():
    """Copy onest: activarea vine din webhook (2c), nu din pagina asta."""
    text = _client().get("/stripe/success").get_data(as_text=True)
    assert "se procesează" in text


# ══════════════════════════════════════════════════════════════
# 6. Regresie — ce NU trebuie să atingă 2b
# ══════════════════════════════════════════════════════════════

def _sursa(rel):
    from pathlib import Path
    return (Path(__file__).resolve().parent.parent / rel).read_text(encoding="utf-8")


def test_2b_nu_scrie_in_db():
    """
    STRUCTURAL, nu pe comportament: modulul de checkout nu are cum să scrie, fiindcă
    nu importă nici repository-ul, nici sesiunea de DB. Scrierea = 2c (webhook semnat).

    Verificat pe AST, nu pe text — altfel comentariile care EXPLICĂ regula ar declanșa-o.
    """
    import ast

    arbore = ast.parse(_sursa("app/services/stripe_checkout.py"))

    module_importate = set()
    for nod in ast.walk(arbore):
        if isinstance(nod, ast.Import):
            module_importate |= {a.name for a in nod.names}
        elif isinstance(nod, ast.ImportFrom):
            module_importate.add(nod.module or "")
    for m in module_importate:
        assert not m.startswith("app.repositories"), f"2b importă repository-ul: {m}"
        assert m != "db", "2b importă sesiunea de DB"
        assert not m.startswith("app.models"), f"2b importă modelele: {m}"

    apelate = {n.attr for n in ast.walk(arbore) if isinstance(n, ast.Attribute)}
    for interzis in ("set_subscription", "clear_subscription", "commit", "flush", "add"):
        assert interzis not in apelate, f"2b atinge DB-ul prin .{interzis}()"


def test_paginile_de_intoarcere_nu_ating_db_ul():
    """Nici rutele cosmetice nu acordă abonamente (success_url e ocolibil)."""
    src = _sursa("app/http/app.py")
    start = src.index("def stripe_success")
    bloc = src[start:src.index("def run_flask")]
    for interzis in ("get_session", "set_subscription", "_require_user", "users_repo"):
        assert interzis not in bloc, f"pagina de întoarcere atinge {interzis!r}"


def test_set_subscription_neatins_de_2b():
    """Semnătura din 2a rămâne exact cum a lăsat-o 2a (2c o va folosi)."""
    import inspect
    from app.repositories import users as users_repo

    sig = inspect.signature(users_repo.set_subscription)
    assert list(sig.parameters) == [
        "session", "user", "customer_id", "subscription_id", "status", "tier",
    ]


def test_subscription_si_migrarile_neatinse():
    """user_tier (4a) și migrările rămân cum erau — 2b n-are treabă cu ele."""
    from app import migrations

    ids = [m["id"] for m in migrations.MIGRATIONS]
    assert ids[-1] == "024_trial_ends_at"
    assert ids[-2] == "023_subscription_fields"

    u = SimpleNamespace(stripe_status="active", stripe_tier="MAX", trial_ends_at=None)
    assert sub.user_tier(u) == "MAX"


def test_gating_logica_neatinsa():
    """Harta feature→tier și gardianul rămân cele din 4b; 2b a schimbat doar CTA-ul."""
    assert gating.FEATURES["declaratii"]["tier"] == sub.PRO
    assert gating.FEATURES["bolt_sync"]["tier"] == sub.START
    assert gating.NAMESPACE_FEATURE["d390"] == "declaratii"
    assert "upgrade" not in gating.NAMESPACE_FEATURE       # butonul de ieșire nu e gated


def test_botul_ruteaza_namespace_ul_upgrade():
    src = _sursa("bot_contabil.py")
    assert 'namespace == "upgrade"' in src
    assert "execute_upgrade_checkout" in src


def test_handlerul_de_bot_nu_scrie_abonamentul():
    """Butonul de plată nu acordă tier — doar deschide checkout-ul."""
    src = _sursa("bot_contabil.py")
    start = src.index("async def execute_upgrade_checkout")
    bloc = src[start:src.index("async def execute_show_profil")]
    assert "set_subscription" not in bloc
    assert "create_checkout_session" in bloc


def test_gardianul_2a_ramane_valabil():
    """2b importă SDK-ul legitim — dar NU în fișierele pe care 2a le-a înghețat."""
    for rel in ("app/services/stripe_config.py", "app/repositories/users.py"):
        assert "import stripe" not in _sursa(rel)
    assert "import stripe" in _sursa("app/services/stripe_checkout.py")
