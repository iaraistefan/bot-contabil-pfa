"""
Brick 2b — INIȚIEREA plății: Stripe Checkout Session (§1.7 Felia 2).

Un singur lucru face modulul ăsta: transformă „userul X vrea tier-ul Y" într-un URL
de plată găzduit de Stripe. Atât. NU scrie nimic în baza de date — nici măcar la
succes.

DE CE NU SCRIE (decizie arhitecturală 2b):
`success_url` e o simplă redirecționare de browser, pe care oricine o poate deschide
direct fără să fi plătit. Dacă am acorda abonamentul acolo, planul PRO s-ar lua cu
un link. Sursa de adevăr e webhook-ul semnat (Brick 2c) — el cheamă
`users_repo.set_subscription`. Aici, deliberat, nu importăm nici repository-ul, nici
sesiunea de DB: garanția „2b nu scrie" e structurală, nu doar o promisiune.

LEGĂTURA CU 2c (cea mai importantă linie din fișier):
`client_reference_id = str(user.id)` — Stripe îl întoarce neatins în evenimentul
`checkout.session.completed`. Fără el, webhook-ul primește o plată fără să știe A CUI
e. Punem în plus `metadata` și pe abonament, pentru că evenimentele ulterioare
(reînnoiri, anulări) NU mai poartă `client_reference_id`, doar metadata abonamentului.

Degradare grațioasă peste tot (ca Bolt/Google): fără chei, fără price, sau cu Stripe
picat → `None` + log, niciodată excepție în fața userului.
"""

import logging
from typing import Optional

from config import settings
from app.services import stripe_config

logger = logging.getLogger(__name__)

# Domeniul public al aplicației (același host ca dashboard-ul din gating.py).
BASE_URL = "https://bot-contabil-pfa.onrender.com"
SUCCESS_PATH = "/stripe/success"
CANCEL_PATH = "/stripe/cancel"


def _stripe():
    """
    SDK-ul Stripe cu cheia setată, sau None dacă plata nu e configurată.

    Import LAZY și cheie setată LA APEL (nu la import), din două motive: aplicația
    trebuie să pornească și fără chei Stripe, iar env-ul se poate schimba între
    procese/teste — o cheie înghețată la import ar minți (același raționament ca
    `_price_map()` din 2a).
    """
    if not stripe_config.is_payment_configured():
        return None
    import stripe
    stripe.api_key = settings.stripe_secret_key
    return stripe


def create_checkout_session(user, tier: str, base_url: str = None) -> Optional[str]:
    """
    Creează o sesiune Stripe Checkout pentru abonamentul `tier` și întoarce URL-ul
    de plată (sau None dacă nu se poate — apelantul afișează un mesaj blând).

    Args:
        user: userul care plătește; citim doar `id` și `stripe_customer_id`.
        tier: START / PRO / MAX (FREE nu se cumpără → None).
        base_url: domeniul pt success/cancel (default BASE_URL; injectabil în teste).

    Returns:
        URL-ul de checkout, sau None dacă: tier-ul n-are price configurat, plata nu e
        configurată (lipsă cheie), userul n-are id, sau apelul la Stripe a eșuat.
    """
    price_id = stripe_config.price_id_for_tier(tier)
    if not price_id:
        logger.warning(f"Checkout cerut pt tier fără price configurat: {tier!r}")
        return None

    sdk = _stripe()
    if sdk is None:
        logger.warning("Checkout cerut dar plata nu e configurată (lipsă STRIPE_SECRET_KEY).")
        return None

    user_id = getattr(user, "id", None)
    if not user_id:
        logger.error("Checkout cerut fără user identificabil — refuz (2c n-ar ști a cui e plata).")
        return None

    baza = (base_url or BASE_URL).rstrip("/")
    params = {
        "mode": "subscription",              # abonament recurent, nu plată unică
        "line_items": [{"price": price_id, "quantity": 1}],
        # CRUCIAL pt 2c: singura punte între plata de la Stripe și userul nostru.
        "client_reference_id": str(user_id),
        # Redundanță utilă: evenimentele de reînnoire/anulare nu mai poartă
        # client_reference_id, dar poartă metadata abonamentului.
        "metadata": {"user_id": str(user_id), "tier": tier},
        "subscription_data": {"metadata": {"user_id": str(user_id), "tier": tier}},
        "success_url": f"{baza}{SUCCESS_PATH}",
        "cancel_url": f"{baza}{CANCEL_PATH}",
        # Felia 3: factura fiscală cere adresa clientului (stradă + nr), pe care
        # onboarding-ul n-o colectează (avem doar județ/localitate). O cerem aici,
        # unde userul oricum completează datele de plată, și o salvăm la webhook.
        "billing_address_collection": "required",
    }

    # Reabonare: refolosim clientul Stripe existent, ca să nu-i facem userului al
    # doilea „customer" în dashboardul Stripe (de-asta `clear_subscription` din 2a
    # păstrează `stripe_customer_id` la anulare, nu-l șterge).
    customer_id = getattr(user, "stripe_customer_id", None)
    if customer_id:
        params["customer"] = customer_id

    try:
        sesiune = sdk.checkout.Session.create(**params)
    except Exception as e:
        logger.error(f"Stripe checkout.Session.create a eșuat user={user_id} tier={tier}: {e}")
        return None

    url = getattr(sesiune, "url", None)
    if not url and isinstance(sesiune, dict):
        url = sesiune.get("url")
    if not url:
        logger.error(f"Stripe a răspuns fără URL de checkout (user={user_id} tier={tier}).")
        return None
    return url
