"""
Brick 2c — webhook-ul Stripe: ULTIMA verigă a lanțului de plată (§1.7 Felia 2).

Aici se acordă abonamentul — singura scriere din tot pipeline-ul. Deci aici testăm
cel mai apăsat DOUĂ lucruri opuse:
  · plata reală CHIAR activează abonamentul (altfel omul plătește degeaba);
  · nimic nefirmat nu scrie NIMIC (altfel planul PRO se ia cu un curl).

Semnăturile sunt REALE, nu mockuite: le calculăm cu același HMAC pe care-l face
Stripe, ca testul să treacă prin `construct_event` adevărat. Un mock peste
verificare ar fi testat că mockul merge, nu că apărarea ține.

ZERO apeluri de rețea: evenimentele sunt payload-uri construite de mână.
"""

import hashlib
import hmac
import json
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.services import stripe_config
from app.services import stripe_webhook
from app.services import subscription as sub

SECRET = "whsec_test_secret"


# ══════════════════════════════════════════════════════════════
# Unelte: semnătură reală + evenimente de mână
# ══════════════════════════════════════════════════════════════

def _semneaza(payload: bytes, secret: str = SECRET, ts: int = None) -> str:
    """
    Antetul `Stripe-Signature`, calculat exact ca la Stripe: HMAC-SHA256 peste
    „{timestamp}.{corp brut}". Timestampul e ACUM — `construct_event` respinge
    semnăturile vechi (toleranță 5 min), la fel ca `auth_date` la Telegram.
    """
    ts = ts if ts is not None else int(time.time())
    semnat = f"{ts}.".encode("utf-8") + payload
    v1 = hmac.new(secret.encode("utf-8"), semnat, hashlib.sha256).hexdigest()
    return f"t={ts},v1={v1}"


def _event(tip: str, obiect: dict) -> bytes:
    return json.dumps({
        "id": "evt_test_1",
        "object": "event",          # SDK-ul îl citește ca să distingă v1 de v2
        "type": tip,
        "created": int(time.time()),
        "data": {"object": obiect},
    }).encode("utf-8")


def _checkout(user_id, tier="PRO", payment_status="paid",
              customer="cus_1", subscription="sub_1") -> dict:
    return {
        "id": "cs_test_1",
        "object": "checkout.session",
        "mode": "subscription",
        "status": "complete",
        "payment_status": payment_status,
        "client_reference_id": str(user_id) if user_id is not None else None,
        "customer": customer,
        "subscription": subscription,
        "metadata": {"user_id": str(user_id), "tier": tier},
    }


def _abonament(user_id, status="active", price="price_PRO",
               cancel_at_period_end=False) -> dict:
    return {
        "id": "sub_1",
        "object": "subscription",
        "customer": "cus_1",
        "status": status,
        "cancel_at_period_end": cancel_at_period_end,
        "metadata": {"user_id": str(user_id), "tier": "PRO"},
        "items": {"data": [{"price": {"id": price}}]},
    }


@pytest.fixture
def web(monkeypatch, tmp_path):
    """Client Flask + DB de test + configurare Stripe completă."""
    from app.http import app as webapp

    eng = create_engine(f"sqlite:///{(tmp_path / 'w.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=1); s.add(u); s.commit(); uid = u.id; s.close()

    monkeypatch.setattr(webapp, "get_session", lambda: S())
    monkeypatch.setattr(stripe_webhook.settings, "stripe_webhook_secret", SECRET)
    monkeypatch.setattr(stripe_config.settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(stripe_config.settings, "stripe_price_start", "price_START")
    monkeypatch.setattr(stripe_config.settings, "stripe_price_pro", "price_PRO")
    monkeypatch.setattr(stripe_config.settings, "stripe_price_max", "price_MAX")

    return webapp.flask_app.test_client(), S, uid


def _trimite(client, payload: bytes, semnatura=True, secret=SECRET):
    antete = {"Content-Type": "application/json"}
    if semnatura:
        antete["Stripe-Signature"] = _semneaza(payload, secret)
    return client.post("/stripe/webhook", data=payload, headers=antete)


def _citeste(S, uid):
    """Userul, recitit din sesiune NOUĂ — dovada că s-a comis, nu doar s-a scris."""
    s = S()
    try:
        return s.query(User).filter_by(id=uid).one()
    finally:
        s.close()


# ══════════════════════════════════════════════════════════════
# 1. Plata reală activează abonamentul — MIEZUL brick-ului
# ══════════════════════════════════════════════════════════════

def test_checkout_completed_activeaza_abonamentul(web):
    """CRUCIAL: omul a plătit → devine PRO. Capătul lanțului 2a→2b→2c."""
    client, S, uid = web

    r = _trimite(client, _event("checkout.session.completed", _checkout(uid, tier="PRO")))

    assert r.status_code == 200 and r.get_json()["rezultat"] == "procesat"

    u = _citeste(S, uid)
    assert u.stripe_status == "active"
    assert u.stripe_tier == "PRO"
    assert u.stripe_customer_id == "cus_1"          # legătura pt reabonare (2b)
    assert u.stripe_subscription_id == "sub_1"
    assert sub.user_tier(u) == "PRO"                # citit prin 4a: chiar are planul


def test_checkout_completed_respecta_tierul_cumparat(web):
    client, S, uid = web
    _trimite(client, _event("checkout.session.completed", _checkout(uid, tier="MAX")))
    assert _citeste(S, uid).stripe_tier == "MAX"


def test_checkout_neplatit_nu_activeaza(web):
    """payment_status != 'paid' → nu acordăm nimic."""
    client, S, uid = web

    r = _trimite(client, _event("checkout.session.completed",
                                _checkout(uid, payment_status="unpaid")))

    assert r.status_code == 200 and r.get_json()["rezultat"] == "ignorat"
    assert _citeste(S, uid).stripe_status is None
    assert sub.user_tier(_citeste(S, uid)) == "FREE"


def test_tier_necunoscut_in_metadata_nu_acorda_nimic(web):
    client, S, uid = web
    r = _trimite(client, _event("checkout.session.completed",
                                _checkout(uid, tier="VIP_INVENTAT")))
    assert r.status_code == 200 and r.get_json()["rezultat"] == "ignorat"
    assert _citeste(S, uid).stripe_tier is None


# ══════════════════════════════════════════════════════════════
# 2. Apărarea: fără semnătură validă nu se scrie NIMIC
# ══════════════════════════════════════════════════════════════

def test_semnatura_invalida_400_si_zero_scriere(web):
    """CRUCIAL: cu alt secret → 400 și DB neatins. Altfel PRO s-ar lua cu un curl."""
    client, S, uid = web

    r = _trimite(client, _event("checkout.session.completed", _checkout(uid)),
                 secret="whsec_alt_secret")

    assert r.status_code == 400
    u = _citeste(S, uid)
    assert u.stripe_status is None and u.stripe_tier is None


def test_fara_antet_semnatura_400(web):
    client, S, uid = web
    r = _trimite(client, _event("checkout.session.completed", _checkout(uid)),
                 semnatura=False)
    assert r.status_code == 400
    assert _citeste(S, uid).stripe_status is None


def test_corp_modificat_dupa_semnare_400(web):
    """Semnătura e pe OCTEȚII BRUȚI: schimbi o cifră în corp → cade."""
    client, S, uid = web
    payload = _event("checkout.session.completed", _checkout(uid))
    antete = {"Stripe-Signature": _semneaza(payload), "Content-Type": "application/json"}

    stricat = payload.replace(b'"PRO"', b'"MAX"')          # upgrade pe furiș
    r = client.post("/stripe/webhook", data=stricat, headers=antete)

    assert r.status_code == 400
    assert _citeste(S, uid).stripe_tier is None


def test_semnatura_veche_respinsa(web):
    """Toleranța de timp: o semnătură valabilă la nesfârșit = credential exfiltrabil."""
    client, S, uid = web
    payload = _event("checkout.session.completed", _checkout(uid))
    vechi = _semneaza(payload, ts=int(time.time()) - 3600)   # acum o oră

    r = client.post("/stripe/webhook", data=payload,
                    headers={"Stripe-Signature": vechi})

    assert r.status_code == 400
    assert _citeste(S, uid).stripe_status is None


def test_fara_whsec_configurat_400(web, monkeypatch):
    """Secret neconfigurat → respingem, nu crăpăm (și nu acceptăm orbește)."""
    client, S, uid = web
    monkeypatch.setattr(stripe_webhook.settings, "stripe_webhook_secret", None)

    r = _trimite(client, _event("checkout.session.completed", _checkout(uid)))

    assert r.status_code == 400
    assert _citeste(S, uid).stripe_status is None


# ══════════════════════════════════════════════════════════════
# 3. customer.subscription.updated — capcana cancel_at_period_end
# ══════════════════════════════════════════════════════════════

def test_subscription_updated_activ_scrie_tierul(web):
    client, S, uid = web
    r = _trimite(client, _event("customer.subscription.updated",
                                _abonament(uid, status="active", price="price_PRO")))

    assert r.status_code == 200 and r.get_json()["rezultat"] == "procesat"
    u = _citeste(S, uid)
    assert u.stripe_status == "active" and u.stripe_tier == "PRO"


def test_upgrade_de_tier_prin_updated(web):
    """Schimbarea de plan vine ca updated cu alt price → tier nou."""
    client, S, uid = web
    _trimite(client, _event("checkout.session.completed", _checkout(uid, tier="START")))
    assert _citeste(S, uid).stripe_tier == "START"

    _trimite(client, _event("customer.subscription.updated",
                            _abonament(uid, price="price_MAX")))
    assert _citeste(S, uid).stripe_tier == "MAX"


def test_cancel_at_period_end_NU_taie_accesul(web):
    """
    CRUCIAL (capcana reconului): userul a anulat, dar a PLĂTIT până la finalul
    perioadei. Stripe trimite updated cu cancel_at_period_end=true și status ÎNCĂ
    active. Dacă am comuta pe flag în loc de status, i-am tăia accesul plătit.
    """
    client, S, uid = web
    _trimite(client, _event("checkout.session.completed", _checkout(uid, tier="PRO")))

    r = _trimite(client, _event("customer.subscription.updated",
                                _abonament(uid, status="active",
                                           cancel_at_period_end=True)))

    assert r.status_code == 200
    u = _citeste(S, uid)
    assert u.stripe_status == "active"                  # NEATINS
    assert sub.user_tier(u) == "PRO"                    # are în continuare planul


def test_past_due_nu_lasa_abonament_activ_fals(web):
    """Consecvent cu 4a: `is_subscribed` cere exact 'active' → past_due nu dă tier."""
    client, S, uid = web
    _trimite(client, _event("checkout.session.completed", _checkout(uid, tier="PRO")))

    _trimite(client, _event("customer.subscription.updated",
                            _abonament(uid, status="past_due")))

    u = _citeste(S, uid)
    assert u.stripe_status == "past_due"
    assert sub.is_subscribed(u) is False
    assert sub.user_tier(u) == "FREE"                   # fără trial valid → FREE


def test_status_incheiat_prin_updated_curata_abonamentul(web):
    client, S, uid = web
    _trimite(client, _event("checkout.session.completed", _checkout(uid)))

    _trimite(client, _event("customer.subscription.updated",
                            _abonament(uid, status="unpaid")))

    u = _citeste(S, uid)
    assert u.stripe_status == "canceled"
    assert sub.user_tier(u) == "FREE"


def test_price_strain_nu_ghiceste_tierul(web):
    """Price necunoscut → scriem statusul, NU inventăm un tier."""
    client, S, uid = web
    _trimite(client, _event("checkout.session.completed", _checkout(uid, tier="START")))

    r = _trimite(client, _event("customer.subscription.updated",
                                _abonament(uid, price="price_DIN_ALT_CONT")))

    assert r.status_code == 200
    u = _citeste(S, uid)
    assert u.stripe_status == "active"
    assert u.stripe_tier == "START"                     # neschimbat, nu ghicit


# ══════════════════════════════════════════════════════════════
# 4. customer.subscription.deleted — anularea reală
# ══════════════════════════════════════════════════════════════

def test_subscription_deleted_cade_pe_free(web):
    client, S, uid = web
    _trimite(client, _event("checkout.session.completed", _checkout(uid, tier="PRO")))

    r = _trimite(client, _event("customer.subscription.deleted",
                                _abonament(uid, status="canceled")))

    assert r.status_code == 200 and r.get_json()["rezultat"] == "procesat"
    u = _citeste(S, uid)
    assert u.stripe_status == "canceled"
    assert sub.user_tier(u) == "FREE"
    # istoricul rămâne (reabonare fără client Stripe duplicat — regula 2a)
    assert u.stripe_customer_id == "cus_1" and u.stripe_tier == "PRO"


def test_deleted_lasa_trialul_valabil_sa_decida(web, monkeypatch):
    """Anulare + trial încă valabil → 4a decide: PRO din trial, nu FREE."""
    from datetime import datetime, timedelta

    client, S, uid = web
    s = S(); u = s.query(User).filter_by(id=uid).one()
    u.trial_ends_at = datetime.utcnow() + timedelta(days=10)
    s.commit(); s.close()

    _trimite(client, _event("checkout.session.completed", _checkout(uid, tier="MAX")))
    _trimite(client, _event("customer.subscription.deleted", _abonament(uid)))

    assert sub.user_tier(_citeste(S, uid)) == "PRO"     # trial-ul intern, nu FREE


# ══════════════════════════════════════════════════════════════
# 5. Ce ignorăm intenționat — mereu 200, ca Stripe să nu reîncerce
# ══════════════════════════════════════════════════════════════

def test_invoice_paid_ignorat_dar_confirmat(web):
    """Fără client_reference_id/metadata n-am ști A CUI e — updated acoperă reînnoirile."""
    client, S, uid = web

    r = _trimite(client, _event("invoice.paid", {
        "id": "in_1", "customer": "cus_1", "billing_reason": "subscription_cycle",
    }))

    assert r.status_code == 200 and r.get_json()["rezultat"] == "ignorat"
    assert _citeste(S, uid).stripe_status is None


def test_event_necunoscut_200_fara_scriere(web):
    client, S, uid = web
    r = _trimite(client, _event("customer.created", {"id": "cus_9"}))
    assert r.status_code == 200 and r.get_json()["rezultat"] == "ignorat"
    assert _citeste(S, uid).stripe_status is None


def test_user_inexistent_200_nu_500(web):
    """
    CRUCIAL pt deploy: un 500 aici ar pune Stripe pe retry ~3 zile pentru o stare
    care nu se repară niciodată (userul nu apare din senin).
    """
    client, S, uid = web
    r = _trimite(client, _event("checkout.session.completed", _checkout(999999)))

    assert r.status_code == 200 and r.get_json()["rezultat"] == "ignorat"
    assert _citeste(S, uid).stripe_status is None


def test_fara_id_de_user_200_fara_scriere(web):
    client, S, uid = web
    obiect = _checkout(uid)
    obiect["client_reference_id"] = None
    r = _trimite(client, _event("checkout.session.completed", obiect))
    assert r.status_code == 200 and r.get_json()["rezultat"] == "ignorat"
    assert _citeste(S, uid).stripe_status is None


def test_metadata_lipsa_pe_abonament_200(web):
    client, S, uid = web
    obiect = _abonament(uid)
    obiect["metadata"] = {}
    r = _trimite(client, _event("customer.subscription.updated", obiect))
    assert r.status_code == 200 and r.get_json()["rezultat"] == "ignorat"


def test_eroare_tranzitorie_da_500_ca_stripe_sa_reincerce(monkeypatch, web):
    """Singurul caz în care retry-ul ajută: ceva neașteptat (ex. DB picat)."""
    client, S, uid = web

    def _crapa(session, event):
        raise RuntimeError("DB picat")

    from app.http import app as webapp
    monkeypatch.setattr(webapp._stripe_wh, "proceseaza", _crapa)

    r = _trimite(client, _event("checkout.session.completed", _checkout(uid)))
    assert r.status_code == 500


# ══════════════════════════════════════════════════════════════
# 6. Idempotență — Stripe poate livra același eveniment de mai multe ori
# ══════════════════════════════════════════════════════════════

def test_acelasi_event_de_doua_ori_da_acelasi_rezultat(web):
    client, S, uid = web
    payload = _event("checkout.session.completed", _checkout(uid, tier="PRO"))

    r1 = _trimite(client, payload)
    dupa_prima = (_citeste(S, uid).stripe_status, _citeste(S, uid).stripe_tier)
    r2 = _trimite(client, payload)

    assert r1.status_code == r2.status_code == 200
    u = _citeste(S, uid)
    assert (u.stripe_status, u.stripe_tier) == dupa_prima == ("active", "PRO")


# ══════════════════════════════════════════════════════════════
# 7. Regresie — ce NU trebuie să atingă 2c
# ══════════════════════════════════════════════════════════════

def _sursa(rel):
    from pathlib import Path
    return (Path(__file__).resolve().parent.parent / rel).read_text(encoding="utf-8")


def test_ruta_citeste_corpul_brut_nu_json():
    """`get_json` ar re-serializa corpul și ar invalida semnătura Stripe."""
    src = _sursa("app/http/app.py")
    bloc = src[src.index("def stripe_webhook"):src.index("def run_flask")]
    assert "request.get_data()" in bloc
    assert "request.get_json" not in bloc


def test_webhookul_e_singura_ruta_fara_require_user_care_scrie():
    """Paginile 2b rămân fără scriere; webhook-ul scrie, dar cere semnătură."""
    src = _sursa("app/http/app.py")
    bloc_pagini = src[src.index("def stripe_success"):src.index("def stripe_webhook")]
    assert "set_subscription" not in bloc_pagini and "get_session" not in bloc_pagini

    bloc_webhook = src[src.index("def stripe_webhook"):src.index("def run_flask")]
    assert "verifica_semnatura" in bloc_webhook
    assert "session.commit()" in bloc_webhook


def test_setterele_2a_neatinse():
    import inspect
    from app.repositories import users as users_repo

    assert list(inspect.signature(users_repo.set_subscription).parameters) == [
        "session", "user", "customer_id", "subscription_id", "status", "tier",
    ]
    assert list(inspect.signature(users_repo.clear_subscription).parameters) == [
        "session", "user",
    ]


def test_checkout_2b_neatins():
    """2b rămâne fără DB (garanția structurală) — 2c n-a mutat scrierea acolo."""
    import ast
    arbore = ast.parse(_sursa("app/services/stripe_checkout.py"))
    apelate = {n.attr for n in ast.walk(arbore) if isinstance(n, ast.Attribute)}
    assert "set_subscription" not in apelate and "commit" not in apelate


def test_subscription_si_migrarile_neatinse():
    from app import migrations
    ids = [m["id"] for m in migrations.MIGRATIONS]
    assert ids[-1] == "024_trial_ends_at"
    assert ids[-2] == "023_subscription_fields"


def test_rutele_existente_folosesc_in_continuare_get_json():
    """Doar ruta nouă citește brut; restul API-ului rămâne pe get_json."""
    src = _sursa("app/http/app.py")
    assert src.count("request.get_json(silent=True)") >= 4
