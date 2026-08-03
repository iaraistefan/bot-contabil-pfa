"""
Configurarea Stripe Billing — maparea tier ↔ price ID (§1.7 Felia 2, Brick 2a).

Stripe Billing nu știe de „START/PRO/MAX" — știe de Price ID-uri (`price_...`), create
în dashboardul Stripe ca Products + Prices. Modulul ăsta e SINGURUL loc unde cele două
vocabulare se traduc:
  · la CHECKOUT (2b): tier ales de user → price_id de trimis la Stripe;
  · la WEBHOOK (2c):  price_id din event → tier de scris pe user.

De ce modul separat și nu în `subscription.py`: acela e PUR (interpretează starea
stocată, zero dependențe de config/mediu) și e testat ca atare. Aici depindem de env,
deci ținem granița curată.

ZERO Stripe API aici — doar citire de configurare. SDK-ul intră în 2b.

Degradare grațioasă (ca Bolt/Google): un price neconfigurat → tier-ul ăla nu se poate
cumpăra, restul aplicației merge. Nu aruncăm la import.
"""

from typing import Optional

from config import settings
from app.services import subscription as sub


def _price_map() -> dict:
    """
    Maparea tier → price_id, citită din `settings` LA APEL (nu la import): env-ul se
    poate schimba între teste/procese, iar o hartă înghețată la import ar minți.
    Tier-urile fără price configurat lipsesc din hartă (nu apar cu None).
    """
    brut = {
        sub.START: settings.stripe_price_start,
        sub.PRO: settings.stripe_price_pro,
        sub.MAX: settings.stripe_price_max,
    }
    return {tier: pid for tier, pid in brut.items() if pid}


def price_id_for_tier(tier: str) -> Optional[str]:
    """
    Price ID-ul Stripe pentru un tier plătit, sau None dacă nu e configurat.

    FREE → None întotdeauna (nu se cumpără — e ce rămâi când nu plătești).
    Tier necunoscut → None (nu ghicim).
    """
    return _price_map().get(tier)


def tier_for_price_id(price_id: str) -> Optional[str]:
    """
    Inversul: din price ID-ul venit într-un event Stripe (2c) → tier-ul cumpărat.
    None dacă price ID-ul nu e al niciunui tier configurat — caz în care webhook-ul
    NU trebuie să ghicească un tier, ci să logheze și să nu scrie nimic.
    """
    if not price_id:
        return None
    for tier, pid in _price_map().items():
        if pid == price_id:
            return tier
    return None


def tiers_configurate() -> tuple:
    """Tier-urile care AU price ID (deci se pot cumpăra), în ordinea START→PRO→MAX."""
    harta = _price_map()
    return tuple(t for t in (sub.START, sub.PRO, sub.MAX) if t in harta)


def is_payment_configured() -> bool:
    """
    Plata e utilizabilă? Are nevoie de cheia secretă ȘI de măcar un price cumpărabil.
    Fals → UI-ul de upgrade n-are ce oferi (2b decide cum arată asta).
    """
    return bool(settings.stripe_secret_key) and bool(_price_map())
