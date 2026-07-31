"""
Abonament SaaS (§1.7) — logica de tier + gating primitiv.

FELIA 1: fundația de citire peste câmpurile Stripe de pe User (models.py).
FELIA 4a: user_tier() e acum TRIAL-AWARE (reverse trial §1.8). ZERO Stripe API real
aici — doar interpretează starea stocată. Gating-ul efectiv (blocarea features) =
Felia 4b; până atunci: inert, comportament neschimbat pt toți userii.

Tier-uri (aliniate decizia #4 din PLAN-CONIAR.md §1, jurnal research):
  FREE  — neabonat, fără trial activ (stripe_tier NULL + trial expirat/absent)
  START — ~99-149 lei (Bolt + D212 + estimare live + bot + rezervă taxe)
  PRO   — ~179-199 lei (+ depunere auto + feed bancar AI + reconciliere + garanție)
  MAX   — ~289-349 lei (+ plătitori TVA + optimizare predictivă + review uman)

Reverse trial (§1.8): la onboarding, userul nou primește 30 zile PRO complet (fără
card, trial_ends_at = now+30). Cât timp trial_ends_at > acum ȘI nu e abonat activ →
tratat ca PRO. După expirare → FREE „Radar". Un user care PLĂTEȘTE în trial (ex. MAX)
e respectat la tier-ul plătit — NU downgradăm la PRO.
"""

from datetime import datetime

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


def is_in_trial(user, now=None) -> bool:
    """
    True dacă userul e în reverse trial ACTIV: trial_ends_at > acum ȘI NU e abonat
    activ (un abonat plătitor nu mai e „în trial", e client). `now` injectabil pt teste.
    """
    if is_subscribed(user):
        return False
    ends = getattr(user, "trial_ends_at", None)
    if ends is None:
        return False
    return ends > (now or datetime.utcnow())


def trial_days_left(user, now=None) -> int:
    """
    Câte zile ÎNTREGI au rămas din trial (rotunjit în sus la ziua curentă), sau 0
    dacă nu e în trial. Pt mesaje „îți mai rămân X zile" (Felia 4b). `now` injectabil.
    """
    if not is_in_trial(user, now=now):
        return 0
    ends = getattr(user, "trial_ends_at", None)
    delta = ends - (now or datetime.utcnow())
    # secunde → zile, rotunjit în sus (o fracție de zi = încă „o zi rămasă").
    return max(0, -(-delta.total_seconds() // 86400).__int__())


def user_tier(user, now=None) -> str:
    """
    Tier-ul EFECTIV al userului. Ordine de prioritate (TRIAL-AWARE, Felia 4a):
      1. abonat activ (stripe_status=active) → stripe_tier (respectă plata; dacă a luat
         MAX în trial, rămâne MAX — NU downgradăm). Tier necunoscut → FREE conservator.
      2. altfel, în trial (trial_ends_at > acum) → PRO (reverse trial §1.8).
      3. altfel → FREE.
    `now` injectabil pt teste (default: datetime.utcnow()).
    """
    if is_subscribed(user):
        tier = getattr(user, "stripe_tier", None)
        return tier if tier in _TIER_RANK else FREE
    if is_in_trial(user, now=now):
        return PRO
    return FREE


def has_tier_at_least(user, minim: str) -> bool:
    """
    Gating primitiv (Felia 4 îl va aplica): userul are cel puțin tier-ul `minim`?
    Ex. has_tier_at_least(u, PRO) → True pt PRO și MAX, False pt START/FREE.
    NEaplicat nicăieri încă — feature-urile nu-l cheamă până la Felia 4.
    """
    return _TIER_RANK.get(user_tier(user), 0) >= _TIER_RANK.get(minim, 99)
