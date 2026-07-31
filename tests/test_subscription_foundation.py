"""
Felia 1 — fundația abonament SaaS (§1.7). DOAR date, ZERO Stripe API.

Verifică: câmpurile Stripe pe User (nullable), migrarea 023 (structură + idempotență
prin construcție + mecanism de skip), logica de tier (is_subscribed/user_tier/
has_tier_at_least). Regresie: migrările 019-022 + triada Bolt neatinse.
"""

from types import SimpleNamespace

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.services import subscription as sub
from app import migrations


# ══════════════════════════════════════════════════════════════
# 2. Câmpuri noi pe User — nullable, default None
# ══════════════════════════════════════════════════════════════
def _db(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    return eng, sessionmaker(bind=eng)


def test_user_are_campuri_stripe_nullable(tmp_path):
    eng, S = _db(tmp_path)
    cols = {c["name"]: c for c in inspect(eng).get_columns("users")}
    for name in ("stripe_customer_id", "stripe_subscription_id",
                 "stripe_status", "stripe_tier"):
        assert name in cols, f"lipsește coloana {name}"
        assert cols[name]["nullable"] is True

    # default None la inserare (fără valori)
    s = S()
    u = User(telegram_id=1)
    s.add(u); s.commit()
    assert u.stripe_customer_id is None and u.stripe_subscription_id is None
    assert u.stripe_status is None and u.stripe_tier is None
    s.close()


# ══════════════════════════════════════════════════════════════
# 1. Migrarea 023 — structură + idempotență prin construcție + mecanism skip
# ══════════════════════════════════════════════════════════════
def _mig(mid):
    return next((m for m in migrations.MIGRATIONS if m["id"] == mid), None)


def test_migrarea_023_structura():
    m = _mig("023_subscription_fields")
    assert m is not None, "migrarea 023 lipsește"
    # 4 coloane, toate ADD COLUMN IF NOT EXISTS (idempotent prin construcție, ca 019)
    assert len(m["sql"]) == 4
    for sql in m["sql"]:
        assert "ADD COLUMN IF NOT EXISTS" in sql
        assert "users" in sql
    coloane = " ".join(m["sql"])
    for c in ("stripe_customer_id", "stripe_subscription_id",
              "stripe_status", "stripe_tier"):
        assert c in coloane


def test_migrarea_023_dupa_022():
    # Regula: adaugă mereu la sfârșit. 023 vine imediat după 022 (poziția „ultima"
    # s-a mutat pe 024 în Felia 4a — verificăm relația de ordonare, care rămâne).
    ids = [m["id"] for m in migrations.MIGRATIONS]
    i23 = ids.index("023_subscription_fields")
    assert ids[i23 - 1] == "022_vehicule_regim_utilizare"


def test_migrarea_023_idempotenta_prin_mecanism(tmp_path, monkeypatch):
    # Mecanismul de skip (schema_migrations tracking): după _mark_applied, migrarea
    # e considerată aplicată → a doua rulare o sare. SQLite-compatibil (CREATE TABLE
    # IF NOT EXISTS + ON CONFLICT DO NOTHING). Demonstrează „rulează de 2x, nu crapă".
    eng = create_engine(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    S = sessionmaker(bind=eng)
    monkeypatch.setattr(migrations, "get_session", lambda: S())

    migrations._ensure_migrations_table()
    migrations._ensure_migrations_table()          # a doua oară → IF NOT EXISTS, nu crapă
    assert migrations._is_applied("023_subscription_fields") is False

    migrations._mark_applied("023_subscription_fields", "test")
    assert migrations._is_applied("023_subscription_fields") is True
    migrations._mark_applied("023_subscription_fields", "test")  # ON CONFLICT DO NOTHING
    assert migrations._is_applied("023_subscription_fields") is True  # tot o singură dată


# ══════════════════════════════════════════════════════════════
# 3. is_subscribed — active→True, restul→False
# ══════════════════════════════════════════════════════════════
def test_is_subscribed():
    assert sub.is_subscribed(SimpleNamespace(stripe_status="active")) is True
    assert sub.is_subscribed(SimpleNamespace(stripe_status="canceled")) is False
    assert sub.is_subscribed(SimpleNamespace(stripe_status="past_due")) is False
    assert sub.is_subscribed(SimpleNamespace(stripe_status=None)) is False


# ══════════════════════════════════════════════════════════════
# 4. user_tier — cu tier activ→tier, fără/inactiv→FREE
# ══════════════════════════════════════════════════════════════
def test_user_tier():
    assert sub.user_tier(SimpleNamespace(stripe_status="active", stripe_tier="PRO")) == "PRO"
    assert sub.user_tier(SimpleNamespace(stripe_status="active", stripe_tier="MAX")) == "MAX"
    # neabonat → FREE
    assert sub.user_tier(SimpleNamespace(stripe_status=None, stripe_tier=None)) == "FREE"
    # tier setat DAR status ne-activ → FREE (nu mai are acces)
    assert sub.user_tier(SimpleNamespace(stripe_status="canceled", stripe_tier="PRO")) == "FREE"
    # tier necunoscut, chiar activ → FREE conservator
    assert sub.user_tier(SimpleNamespace(stripe_status="active", stripe_tier="ENTERPRISE")) == "FREE"


def test_has_tier_at_least():
    pro = SimpleNamespace(stripe_status="active", stripe_tier="PRO")
    start = SimpleNamespace(stripe_status="active", stripe_tier="START")
    free = SimpleNamespace(stripe_status=None, stripe_tier=None)
    assert sub.has_tier_at_least(pro, sub.PRO) is True
    assert sub.has_tier_at_least(pro, sub.MAX) is False    # PRO < MAX
    assert sub.has_tier_at_least(pro, sub.START) is True   # PRO ≥ START
    assert sub.has_tier_at_least(start, sub.PRO) is False
    assert sub.has_tier_at_least(free, sub.START) is False


def test_tiere_aliniate_decizia_4():
    # Decizia #4: 3 tiere plătite START/PRO/MAX + FREE (neabonat).
    assert sub.PAID_TIERS == ("START", "PRO", "MAX")
    assert sub.ALL_TIERS == ("FREE", "START", "PRO", "MAX")


# ══════════════════════════════════════════════════════════════
# 5. REGRESIE — migrările 019-022 + triada Bolt neatinse
# ══════════════════════════════════════════════════════════════
def test_regresie_migrari_existente_neatinse():
    ids = [m["id"] for m in migrations.MIGRATIONS]
    # migrarea Bolt (triada) + regim_utilizare rămân, în ordine
    assert "015_bolt_credentials_per_user" in ids
    assert "022_vehicule_regim_utilizare" in ids
    # 023 e ADIȚIONALĂ (nu înlocuiește nimic): exact una nouă față de câte erau
    assert ids.count("023_subscription_fields") == 1


def test_regresie_triada_bolt_neatinsa(tmp_path):
    eng, _ = _db(tmp_path)
    cols = {c["name"] for c in inspect(eng).get_columns("users")}
    # triada Bolt intactă, alături de câmpurile noi Stripe
    for name in ("bolt_client_id", "bolt_client_secret_enc", "bolt_connected_at"):
        assert name in cols
