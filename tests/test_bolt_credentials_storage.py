"""
#2-A — stocare credențiale Bolt per-user (coloane User + migrare 015).

Inert (storage): coloanele există, nullable (NULL = neconectat → neschimbat).
client_id în clar, client_secret CRIPTAT (numele coloanei _enc semnalează). Conectarea
efectivă = #2-B. Migrarea 015 = Postgres `ADD COLUMN IF NOT EXISTS` (idempotentă);
testele rulează pe schema din models (create_all), deci verificăm modelul + intrarea 015.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.migrations import MIGRATIONS
from app.domain import crypto


def test_coloanele_bolt_exista_nullable():
    cols = User.__table__.columns
    for name in ("bolt_client_id", "bolt_client_secret_enc", "bolt_connected_at"):
        assert name in cols, f"lipsește coloana {name}"
        assert cols[name].nullable is True, f"{name} trebuie nullable (NULL=neconectat)"


def test_secretul_se_stocheaza_criptat(tmp_path):
    # round-trip pe un user real: scriem secret criptat, citim din DB → token ≠ plaintext.
    eng = create_engine(f"sqlite:///{(tmp_path / 'b.db').as_posix()}")
    User.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    secret = "bolt_client_secret_ABC123"
    u = User(telegram_id=1, bolt_client_id="CLIENT_ID_public",
             bolt_client_secret_enc=crypto.encrypt(secret))
    s.add(u); s.commit()

    row = s.query(User).filter_by(telegram_id=1).one()
    assert row.bolt_client_id == "CLIENT_ID_public"        # ID în clar
    assert secret not in row.bolt_client_secret_enc        # secretul NU e în clar în DB
    assert crypto.decrypt(row.bolt_client_secret_enc) == secret  # dar se decriptează corect
    s.close()


def test_migrarea_015_idempotenta_si_nedistructiva():
    m = next((x for x in MIGRATIONS if x["id"] == "015_bolt_credentials_per_user"), None)
    assert m is not None, "migrarea 015 lipsește"
    sql = " ".join(m["sql"])
    assert "ADD COLUMN IF NOT EXISTS bolt_client_id" in sql
    assert "ADD COLUMN IF NOT EXISTS bolt_client_secret_enc" in sql
    assert "ADD COLUMN IF NOT EXISTS bolt_connected_at" in sql
    # idempotent (IF NOT EXISTS) + non-distructiv (doar ADD, fără DROP)
    assert "DROP" not in sql.upper()


def test_user_existent_neconectat_default(tmp_path):
    # user fără credențiale Bolt → coloanele NULL (comportament neschimbat)
    eng = create_engine(f"sqlite:///{(tmp_path / 'n.db').as_posix()}")
    User.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    s.add(User(telegram_id=2)); s.commit()
    u = s.query(User).filter_by(telegram_id=2).one()
    assert u.bolt_client_id is None and u.bolt_client_secret_enc is None and u.bolt_connected_at is None
    s.close()
