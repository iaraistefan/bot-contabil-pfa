"""
Brick 2a — fundația de plată Stripe (§1.7 Felia 2).

DOAR fundația: setter dedicat pt câmpurile Stripe + maparea tier↔price_id.
ZERO Stripe API (checkout = 2b, webhook = 2c) → totul testabil fără chei.

Miezul: `set_subscription` CHIAR SCRIE. `update_profile` are allowlist explicit de
kwargs fără câmpurile Stripe — de-aia avem setter dedicat, nu extindem allowlist-ul.
Testăm capcana în ambele sensuri: setter-ul scrie ȘI update_profile a rămas neatins.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.repositories import users as users_repo
from app.services import subscription as sub
from app.services import stripe_config


def _db(tmp_path, nume="s.db", **user_kw):
    eng = create_engine(f"sqlite:///{(tmp_path / nume).as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=3, **user_kw); s.add(u); s.commit()
    return S, s, u


# ══════════════════════════════════════════════════════════════
# 1. set_subscription CHIAR SCRIE (nu silent no-op) — miezul brick-ului
# ══════════════════════════════════════════════════════════════

def test_set_subscription_scrie_toate_campurile(tmp_path):
    S, s, u = _db(tmp_path)
    assert u.stripe_customer_id is None and u.stripe_status is None   # start curat

    users_repo.set_subscription(
        s, u,
        customer_id="cus_123", subscription_id="sub_456",
        status="active", tier=sub.PRO,
    )

    # a) vizibil imediat pe obiect
    assert u.stripe_customer_id == "cus_123"
    assert u.stripe_subscription_id == "sub_456"
    assert u.stripe_status == "active"
    assert u.stripe_tier == "PRO"
    s.commit(); s.close()

    # b) CHIAR a ajuns în DB — recitire din sesiune nouă (dovada anti-no-op)
    s2 = S(); u2 = s2.query(User).filter_by(telegram_id=3).one()
    assert (u2.stripe_customer_id, u2.stripe_subscription_id,
            u2.stripe_status, u2.stripe_tier) == ("cus_123", "sub_456", "active", "PRO")
    s2.close()


def test_set_subscription_partial_lasa_restul_neschimbat(tmp_path):
    """None = «lasă neschimbat» (ca update_profile), nu «șterge»."""
    S, s, u = _db(tmp_path)
    users_repo.set_subscription(s, u, customer_id="cus_1", subscription_id="sub_1",
                                status="active", tier=sub.START)
    users_repo.set_subscription(s, u, status="past_due")      # DOAR statusul

    assert u.stripe_status == "past_due"
    assert u.stripe_customer_id == "cus_1"       # neatins
    assert u.stripe_subscription_id == "sub_1"   # neatins
    assert u.stripe_tier == "START"              # neatins
    s.close()


def test_set_subscription_intoarce_userul_si_flush(tmp_path):
    S, s, u = _db(tmp_path)
    ret = users_repo.set_subscription(s, u, status="active", tier=sub.MAX)
    assert ret is u                              # întoarce userul, ca update_profile
    # flush → modificarea e vizibilă în sesiune ÎNAINTE de commit
    gasit = s.query(User).filter_by(stripe_tier="MAX").one_or_none()
    assert gasit is not None
    s.close()


# ══════════════════════════════════════════════════════════════
# 2. set_subscription + user_tier (se leagă de Felia 1/4a)
# ══════════════════════════════════════════════════════════════

def test_set_subscription_active_pro_da_tier_pro(tmp_path):
    S, s, u = _db(tmp_path)
    assert sub.user_tier(u) == "FREE"                     # înainte
    users_repo.set_subscription(s, u, customer_id="cus_x", status="active", tier=sub.PRO)
    assert sub.is_subscribed(u) is True
    assert sub.user_tier(u) == "PRO"                      # după
    assert sub.has_tier_at_least(u, sub.PRO) is True
    s.close()


def test_abonat_max_in_trial_ramane_max(tmp_path):
    """Plata primează (regula 4a): cine cumpără MAX în trial NU cade la PRO."""
    S, s, u = _db(tmp_path, trial_ends_at=datetime.utcnow() + timedelta(days=20))
    assert sub.user_tier(u) == "PRO"                      # doar trial
    users_repo.set_subscription(s, u, status="active", tier=sub.MAX)
    assert sub.user_tier(u) == "MAX"
    assert sub.is_in_trial(u) is False                    # abonat ⇒ nu mai e „în trial"
    s.close()


def test_status_neactiv_nu_da_tier(tmp_path):
    """past_due/incomplete NU sunt abonament valid, chiar cu tier scris."""
    S, s, u = _db(tmp_path)
    users_repo.set_subscription(s, u, status="past_due", tier=sub.MAX)
    assert sub.is_subscribed(u) is False
    assert sub.user_tier(u) == "FREE"
    s.close()


# ══════════════════════════════════════════════════════════════
# 3. clear_subscription
# ══════════════════════════════════════════════════════════════

def test_clear_subscription_cade_pe_free(tmp_path):
    S, s, u = _db(tmp_path)
    users_repo.set_subscription(s, u, customer_id="cus_9", subscription_id="sub_9",
                                status="active", tier=sub.PRO)
    users_repo.clear_subscription(s, u)

    assert u.stripe_status == "canceled"
    assert sub.is_subscribed(u) is False
    assert sub.user_tier(u) == "FREE"
    # istoricul rămâne (reabonare fără client duplicat + trasabilitate)
    assert u.stripe_customer_id == "cus_9"
    assert u.stripe_subscription_id == "sub_9"
    assert u.stripe_tier == "PRO"
    s.close()


def test_clear_subscription_cu_trial_valid_cade_pe_trial_nu_pe_free(tmp_path):
    """Prioritatea 4a decide, nu clear_subscription: trial încă valabil → PRO."""
    S, s, u = _db(tmp_path, trial_ends_at=datetime.utcnow() + timedelta(days=10))
    users_repo.set_subscription(s, u, status="active", tier=sub.MAX)
    assert sub.user_tier(u) == "MAX"
    users_repo.clear_subscription(s, u)
    assert sub.user_tier(u) == "PRO"                      # trialul îl prinde
    assert sub.is_in_trial(u) is True
    s.close()


# ══════════════════════════════════════════════════════════════
# 4-5. Maparea tier ↔ price_id
# ══════════════════════════════════════════════════════════════

def _preturi(monkeypatch, start=None, pro=None, max_=None):
    monkeypatch.setattr(stripe_config.settings, "stripe_price_start", start)
    monkeypatch.setattr(stripe_config.settings, "stripe_price_pro", pro)
    monkeypatch.setattr(stripe_config.settings, "stripe_price_max", max_)


def test_price_id_for_tier_mapare_corecta(monkeypatch):
    _preturi(monkeypatch, start="price_S", pro="price_P", max_="price_M")
    assert stripe_config.price_id_for_tier(sub.START) == "price_S"
    assert stripe_config.price_id_for_tier(sub.PRO) == "price_P"
    assert stripe_config.price_id_for_tier(sub.MAX) == "price_M"


def test_price_id_none_cand_neconfigurat(monkeypatch):
    _preturi(monkeypatch)                                  # niciun price
    for tier in (sub.START, sub.PRO, sub.MAX):
        assert stripe_config.price_id_for_tier(tier) is None
    # configurat parțial: doar PRO
    _preturi(monkeypatch, pro="price_P")
    assert stripe_config.price_id_for_tier(sub.PRO) == "price_P"
    assert stripe_config.price_id_for_tier(sub.START) is None


def test_free_nu_are_price_niciodata(monkeypatch):
    """FREE nu se cumpără — e ce rămâi când nu plătești."""
    _preturi(monkeypatch, start="price_S", pro="price_P", max_="price_M")
    assert stripe_config.price_id_for_tier(sub.FREE) is None
    assert stripe_config.price_id_for_tier("INEXISTENT") is None


def test_tier_for_price_id_e_inversul(monkeypatch):
    _preturi(monkeypatch, start="price_S", pro="price_P", max_="price_M")
    assert stripe_config.tier_for_price_id("price_S") == sub.START
    assert stripe_config.tier_for_price_id("price_P") == sub.PRO
    assert stripe_config.tier_for_price_id("price_M") == sub.MAX
    # dus-întors pe toate tier-urile plătite
    for tier in (sub.START, sub.PRO, sub.MAX):
        assert stripe_config.tier_for_price_id(stripe_config.price_id_for_tier(tier)) == tier


def test_tier_for_price_id_necunoscut_e_none(monkeypatch):
    """Price străin (alt cont / alt produs) → None, ca webhook-ul 2c să NU ghicească."""
    _preturi(monkeypatch, pro="price_P")
    assert stripe_config.tier_for_price_id("price_ALTCEVA") is None
    assert stripe_config.tier_for_price_id("") is None
    assert stripe_config.tier_for_price_id(None) is None


def test_tiers_configurate_si_is_payment_configured(monkeypatch):
    _preturi(monkeypatch)
    monkeypatch.setattr(stripe_config.settings, "stripe_secret_key", None)
    assert stripe_config.tiers_configurate() == ()
    assert stripe_config.is_payment_configured() is False

    # cheie fără preț → tot indisponibil (n-ai ce vinde)
    monkeypatch.setattr(stripe_config.settings, "stripe_secret_key", "sk_test_x")
    assert stripe_config.is_payment_configured() is False

    _preturi(monkeypatch, start="price_S", max_="price_M")
    assert stripe_config.tiers_configurate() == (sub.START, sub.MAX)   # ordine START→MAX
    assert stripe_config.is_payment_configured() is True


# ══════════════════════════════════════════════════════════════
# 6. REGRESIE — ce trebuia să rămână neatins
# ══════════════════════════════════════════════════════════════

def test_update_profile_nu_a_fost_extins_cu_stripe():
    """
    Allowlist-ul lui update_profile NU trebuie să conțină câmpuri Stripe — de-aia
    există setter dedicat. Dacă cineva le adaugă aici, testul cade (intenționat).
    """
    import inspect
    params = set(inspect.signature(users_repo.update_profile).parameters)
    for camp in ("stripe_customer_id", "stripe_subscription_id",
                 "stripe_status", "stripe_tier", "trial_ends_at"):
        assert camp not in params, f"{camp} n-are ce căuta în update_profile"
    # și n-a pierdut nimic din ce avea (eșantion din allowlist-ul existent)
    for camp in ("firma_cui", "regim_tva", "bolt_client_id", "iban"):
        assert camp in params


def test_update_profile_inca_functioneaza(tmp_path):
    """Regresie de comportament, nu doar de semnătură."""
    S, s, u = _db(tmp_path)
    users_repo.update_profile(s, u, firma_nume="TEST PFA", firma_cui="53067338")
    s.commit()
    assert u.firma_nume == "TEST PFA" and u.firma_cui == "53067338"
    s.close()


def test_ensure_trial_started_neatins(tmp_path):
    """4a: trial 30 zile, idempotent (a doua chemare NU resetează)."""
    S, s, u = _db(tmp_path)
    users_repo._ensure_trial_started(u)
    primul = u.trial_ends_at
    assert primul is not None
    assert users_repo.TRIAL_DAYS == 30
    users_repo._ensure_trial_started(u)
    assert u.trial_ends_at == primul              # idempotent
    s.close()


def test_subscription_4a_neatinsa(tmp_path):
    """user_tier/is_subscribed/is_in_trial — semantica din 4a, nemodificată."""
    S, s, u = _db(tmp_path)
    assert sub.user_tier(u) == "FREE" and sub.is_subscribed(u) is False
    u.trial_ends_at = datetime.utcnow() + timedelta(days=5)
    assert sub.user_tier(u) == "PRO" and sub.is_in_trial(u) is True
    assert sub._TIER_RANK == {"FREE": 0, "START": 1, "PRO": 2, "MAX": 3}
    s.close()


def test_migrarile_neatinse():
    """
    Câmpurile Stripe există din 023/024 — 2a NU adaugă migrări.

    Gardianul e pe ORDINE (024 imediat după 023), nu pe „ultima": feliile ulterioare
    adaugă legitim migrări noi (025 facturare), fără ca asta să spună ceva despre 2a.
    """
    from app import migrations
    ids = [m["id"] for m in migrations.MIGRATIONS]
    assert ids.index("024_trial_ends_at") == ids.index("023_subscription_fields") + 1


def test_zero_stripe_api_in_2a():
    """Brick 2a nu importă SDK-ul Stripe nicăieri (checkout=2b, webhook=2c)."""
    from pathlib import Path
    rad = Path(__file__).resolve().parent.parent
    for rel in ("app/services/stripe_config.py", "app/repositories/users.py"):
        src = (rad / rel).read_text(encoding="utf-8")
        assert "import stripe" not in src, f"{rel} importă SDK-ul prea devreme"


def test_stripe_in_requirements():
    from pathlib import Path
    req = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text(encoding="utf-8")
    assert "stripe>=" in req


def test_config_are_price_ids():
    """Câmpurile noi sunt Optional (lipsa lor NU oprește aplicația)."""
    from config import Settings
    campuri = Settings.model_fields
    for c in ("stripe_price_start", "stripe_price_pro", "stripe_price_max"):
        assert c in campuri
        assert campuri[c].default is None          # degradare grațioasă
