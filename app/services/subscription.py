"""
Abonament SaaS (§1.7) — logica de tier + gating primitiv.

FELIA 1: doar fundația de citire peste câmpurile Stripe de pe User (models.py).
ZERO Stripe API real aici — doar interpretează starea deja stocată. Funcțiile de
gating EXISTĂ dar NU sunt aplicate nicăieri încă (Felia 4 le va folosi ca să
condiționeze features). Până atunci: inert, comportament neschimbat pt toți userii.

Tier-uri (aliniate decizia #4 din PLAN-CONIAR.md §1, jurnal research):
  FREE  — neabonat (stripe_tier NULL). Tot ce e azi disponibil rămâne disponibil.
  START — ~99-149 lei (Bolt + D212 + estimare live + bot + rezervă taxe)
  PRO   — ~179-199 lei (+ depunere auto + feed bancar AI + reconciliere + garanție)
  MAX   — ~289-349 lei (+ plătitori TVA + optimizare predictivă + review uman)
"""

# Tier-uri (string, ca stripe_tier pe User). FREE = sentinela pt neabonat.
FREE = "FREE"
START = "START"
PRO = "PRO"
MAX = "MAX"

# Tier-urile plătite, în ordinea crescătoare a nivelului (pt comparații ≥).
PAID_TIERS = (START, PRO, MAX)
ALL_TIERS = (FREE,) + PAID_TIERS

# Rang numeric pt comparație „tier ≥ minim" (Felia 4 gating). FREE = 0.
_TIER_RANK = {FREE: 0, START: 1, PRO: 2, MAX: 3}

# Statusul Stripe care înseamnă abonament VALID (acces activ).
_ACTIVE_STATUS = "active"


def is_subscribed(user) -> bool:
    """
    True dacă userul are un abonament ACTIV (stripe_status == 'active').
    canceled / past_due / None → False. Sursă unică pt „e plătitor?".
    """
    return getattr(user, "stripe_status", None) == _ACTIVE_STATUS


def user_tier(user) -> str:
    """
    Tier-ul EFECTIV al userului: stripe_tier dacă abonat activ, altfel FREE.
    Un tier setat dar cu status ne-activ (ex. canceled) → FREE (nu mai are acces).
    Un tier necunoscut → FREE conservator (nu presupunem acces).
    """
    if not is_subscribed(user):
        return FREE
    tier = getattr(user, "stripe_tier", None)
    return tier if tier in _TIER_RANK else FREE


def has_tier_at_least(user, minim: str) -> bool:
    """
    Gating primitiv (Felia 4 îl va aplica): userul are cel puțin tier-ul `minim`?
    Ex. has_tier_at_least(u, PRO) → True pt PRO și MAX, False pt START/FREE.
    NEaplicat nicăieri încă — feature-urile nu-l cheamă până la Felia 4.
    """
    return _TIER_RANK.get(user_tier(user), 0) >= _TIER_RANK.get(minim, 99)
