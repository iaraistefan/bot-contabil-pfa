"""
Teste integrare pentru register_source_file (Faza 2, PAS 2 — aprinderea R2).

DB sqlite IZOLAT in tmp (monkeypatch get_session) -> fara artefact in repo, fara
stare intre rulari. R2 MOCK-uit -> zero apeluri reale.

Verifica:
- upload nou -> SourceFile.storage_path = cheia R2 (user_<id>/<an>/<luna>/<sha>.jpg)
- al doilea upload identic -> dedup HIT, FARA al doilea put_object, intoarce existing
- regresie cu R2 dezactivat -> flux pe disk, dedup intact
"""

import io

import bot_contabil
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import storage
from app.models import User, SourceFile

R2_ENV = {
    "R2_ACCESS_KEY_ID": "test-key",
    "R2_SECRET_ACCESS_KEY": "test-secret",
    "R2_ENDPOINT": "https://test.r2.cloudflarestorage.com",
    "R2_BUCKET": "test-bucket",
}


class FakeR2:
    def __init__(self):
        self.store = {}
        self.put_calls = 0

    def put_object(self, Bucket, Key, Body):
        self.put_calls += 1
        self.store[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.store[(Bucket, Key)])}


def _setup_db(tmp_path, monkeypatch):
    """Engine sqlite izolat + user; redirecteaza get_session-ul bot-ului."""
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    monkeypatch.setattr(bot_contabil, "get_session", lambda: Session())
    # Auditul nu e obiectul testului; il izolam (BigInteger PK nu auto-incrementeaza
    # pe sqlite — pe Postgres in prod merge prin secventa).
    monkeypatch.setattr(bot_contabil.audit_repo, "write", lambda *a, **k: None)
    s = Session()
    u = User(telegram_id=12345)
    s.add(u)
    s.commit()
    uid = u.id
    s.close()
    return Session, uid


# ────────────────────────────────────────────────────────────
# R2 activ — cheie reala + dedup
# ────────────────────────────────────────────────────────────

def test_register_source_file_r2(monkeypatch, tmp_path):
    Session, uid = _setup_db(tmp_path, monkeypatch)
    for k, v in R2_ENV.items():
        monkeypatch.setenv(k, v)
    fake = FakeR2()
    monkeypatch.setattr(storage, "_get_r2_client", lambda: fake)

    data = b"poza-unica-r2-xyz"
    sha = storage.compute_sha256(data)

    r1 = bot_contabil.register_source_file(uid, data, telegram_file_id="tg1")
    assert r1["is_duplicate"] is False

    # storage_path persistat = cheia R2
    s = Session()
    sf = s.get(SourceFile, r1["id"])
    assert sf.storage_path.startswith(f"user_{uid}/")
    assert sf.storage_path.endswith(f"/{sha}.jpg")
    s.close()
    assert fake.put_calls == 1                 # un singur upload

    # al doilea upload identic -> dedup HIT, FARA al doilea put_object
    r2 = bot_contabil.register_source_file(uid, data, telegram_file_id="tg2")
    assert r2["is_duplicate"] is True
    assert r2["id"] == r1["id"]
    assert fake.put_calls == 1                 # tot 1 — R2 neatins a doua oara


# ────────────────────────────────────────────────────────────
# R2 dezactivat — regresie pe disk, dedup intact
# ────────────────────────────────────────────────────────────

def test_register_source_file_disk_fallback(monkeypatch, tmp_path):
    Session, uid = _setup_db(tmp_path, monkeypatch)
    for k in storage._R2_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path / "storage")

    data = b"poza-unica-disk-xyz"
    sha = storage.compute_sha256(data)

    r1 = bot_contabil.register_source_file(uid, data, telegram_file_id="tgd1")
    assert r1["is_duplicate"] is False

    s = Session()
    sf = s.get(SourceFile, r1["id"])
    assert "storage" in sf.storage_path        # cale disk, nu cheie R2
    assert sha in sf.storage_path
    s.close()

    # dedup pe disk
    r2 = bot_contabil.register_source_file(uid, data, telegram_file_id="tgd2")
    assert r2["is_duplicate"] is True
    assert r2["id"] == r1["id"]
