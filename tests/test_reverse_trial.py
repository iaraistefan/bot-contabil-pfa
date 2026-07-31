"""
Felia 4a — mecanismul de reverse trial (trial-aware tier). §1.8.

30 zile PRO complet la onboarding (fără card) → apoi FREE „Radar". DOAR mecanismul:
câmp + logică + setare la onboarding. ZERO gating aplicat pe features (Felia 4b).

Cazuri-cheie: trial valid→PRO, expirat→FREE, abonat MAX în trial→MAX (respectă plata,
nu downgradăm), onboarding setează +30 zile idempotent. `now` injectat pt determinism.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.services import subscription as sub
from app.repositories import users as users_repo
from app import migrations

NOW = datetime(2026, 7, 31, 12, 0, 0)   # moment fix de referință


def _u(**kw):
    """User fals cu câmpurile relevante (default: neabonat, fără trial)."""
    base = dict(stripe_status=None, stripe_tier=None, trial_ends_at=None)
    base.update(kw)
    return SimpleNamespace(**base)


# ══════════════════════════════════════════════════════════════
# 1. Migrarea 024 — structură + idempotență + câmp nullable
# ══════════════════════════════════════════════════════════════
def test_migrarea_024_structura():
    m = next((x for x in migrations.MIGRATIONS if x["id"] == "024_trial_ends_at"), None)
    assert m is not None
    assert len(m["sql"]) == 1
    assert "ADD COLUMN IF NOT EXISTS trial_ends_at" in m["sql"][0]
    assert "users" in m["sql"][0]


def test_migrarea_024_e_ultima():
    ids = [m["id"] for m in migrations.MIGRATIONS]
    assert ids[-1] == "024_trial_ends_at"
    assert ids[-2] == "023_subscription_fields"


def test_camp_trial_nullable_default_none(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    cols = {c["name"]: c for c in inspect(eng).get_columns("users")}
    assert "trial_ends_at" in cols and cols["trial_ends_at"]["nullable"] is True
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=1); s.add(u); s.commit()
    assert u.trial_ends_at is None
    s.close()


# ══════════════════════════════════════════════════════════════
# 2-5. user_tier trial-aware (prioritatea corectă)
# ══════════════════════════════════════════════════════════════
def test_trial_valid_neabonat_pro():
    u = _u(trial_ends_at=NOW + timedelta(days=10))    # trial încă valid
    assert sub.user_tier(u, now=NOW) == "PRO"


def test_trial_expirat_neabonat_free():
    u = _u(trial_ends_at=NOW - timedelta(days=1))     # trial expirat
    assert sub.user_tier(u, now=NOW) == "FREE"


def test_abonat_max_in_trial_ramane_max():
    # CRUCIAL: userul a PLĂTIT MAX în timpul trial-ului → respectăm MAX, NU downgrade la PRO.
    u = _u(stripe_status="active", stripe_tier="MAX",
           trial_ends_at=NOW + timedelta(days=10))
    assert sub.user_tier(u, now=NOW) == "MAX"


def test_abonat_start_in_trial_ramane_start():
    # Chiar dacă START < PRO, plata primează asupra trial-ului (userul a ales conștient).
    u = _u(stripe_status="active", stripe_tier="START",
           trial_ends_at=NOW + timedelta(days=10))
    assert sub.user_tier(u, now=NOW) == "START"


def test_fara_trial_neabonat_free():
    assert sub.user_tier(_u(), now=NOW) == "FREE"


# ══════════════════════════════════════════════════════════════
# 6. is_in_trial
# ══════════════════════════════════════════════════════════════
def test_is_in_trial():
    assert sub.is_in_trial(_u(trial_ends_at=NOW + timedelta(days=5)), now=NOW) is True
    assert sub.is_in_trial(_u(trial_ends_at=NOW - timedelta(days=1)), now=NOW) is False
    assert sub.is_in_trial(_u(trial_ends_at=None), now=NOW) is False
    # abonat activ → NU e „în trial" (e client), chiar dacă trial_ends_at încă viitor
    u = _u(stripe_status="active", stripe_tier="MAX", trial_ends_at=NOW + timedelta(days=5))
    assert sub.is_in_trial(u, now=NOW) is False


# ══════════════════════════════════════════════════════════════
# 7. trial_days_left
# ══════════════════════════════════════════════════════════════
def test_trial_days_left():
    # exact 10 zile → 10
    assert sub.trial_days_left(_u(trial_ends_at=NOW + timedelta(days=10)), now=NOW) == 10
    # fracție de zi (10 zile + 5h) → rotunjit în sus la 11 („încă o zi rămasă")
    assert sub.trial_days_left(
        _u(trial_ends_at=NOW + timedelta(days=10, hours=5)), now=NOW) == 11
    # expirat / fără trial → 0
    assert sub.trial_days_left(_u(trial_ends_at=NOW - timedelta(days=1)), now=NOW) == 0
    assert sub.trial_days_left(_u(trial_ends_at=None), now=NOW) == 0


# ══════════════════════════════════════════════════════════════
# 8. Onboarding setează trial +30 zile, idempotent
# ══════════════════════════════════════════════════════════════
def _db(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=7); s.add(u); s.commit()
    return s, u


def test_complete_onboarding_seteaza_trial(tmp_path):
    s, u = _db(tmp_path)
    assert u.trial_ends_at is None
    before = datetime.utcnow()
    users_repo.complete_onboarding(s, u); s.commit()
    after = datetime.utcnow()
    assert u.trial_ends_at is not None
    # ~30 zile în viitor (toleranță pt execuția testului)
    assert before + timedelta(days=30) - timedelta(seconds=5) <= u.trial_ends_at
    assert u.trial_ends_at <= after + timedelta(days=30) + timedelta(seconds=5)
    # user nou în trial → PRO
    assert sub.user_tier(u) == "PRO" and sub.is_in_trial(u) is True
    s.close()


def test_reonboarding_nu_reseteaza_trial(tmp_path):
    s, u = _db(tmp_path)
    users_repo.complete_onboarding(s, u); s.commit()
    primul = u.trial_ends_at
    # a doua completare (re-onboarding) → NU resetează (idempotent)
    users_repo.complete_onboarding(s, u); s.commit()
    assert u.trial_ends_at == primul
    s.close()


def test_set_onboarding_step_completed_seteaza_trial(tmp_path):
    # cealaltă cale de completare (set_onboarding_step cu COMPLETED) → tot trial
    s, u = _db(tmp_path)
    completed = users_repo.ONBOARDING_STEPS["COMPLETED"]
    users_repo.set_onboarding_step(s, u, completed); s.commit()
    assert u.trial_ends_at is not None
    s.close()


# ══════════════════════════════════════════════════════════════
# 9. REGRESIE — Felia 1 neatinsă
# ══════════════════════════════════════════════════════════════
def test_regresie_is_subscribed_neatins():
    assert sub.is_subscribed(_u(stripe_status="active")) is True
    assert sub.is_subscribed(_u(stripe_status="canceled")) is False
    assert sub.is_subscribed(_u()) is False


def test_regresie_has_tier_at_least_neatins():
    pro = _u(stripe_status="active", stripe_tier="PRO")
    assert sub.has_tier_at_least(pro, sub.PRO) is True
    assert sub.has_tier_at_least(pro, sub.MAX) is False
    assert sub.has_tier_at_least(_u(), sub.START) is False


def test_regresie_migrari_stripe_neatinse():
    ids = [m["id"] for m in migrations.MIGRATIONS]
    assert "023_subscription_fields" in ids
    assert "015_bolt_credentials_per_user" in ids
    assert ids.count("024_trial_ends_at") == 1


def test_regresie_campuri_stripe_neatinse(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    cols = {c["name"] for c in inspect(eng).get_columns("users")}
    for name in ("stripe_customer_id", "stripe_subscription_id",
                 "stripe_status", "stripe_tier", "bolt_client_id"):
        assert name in cols
