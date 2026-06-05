"""
Teste pentru storage cu backend R2 + fallback disk (Faza 2, PAS 1).

R2 e MOCK-UIT (fake client) — zero apeluri reale. Verifică:
- cheia R2 exactă (user_<id>/<an>/<lună zero-padded>/<sha>.<ext>)
- round-trip save/get prin R2
- fallback pe disk când R2 nu e configurat
- backward-compat: apelul vechi (fără user_id) rămâne pe disk
"""

import io
from datetime import datetime

import pytest

from app import storage

R2_ENV = {
    "R2_ACCESS_KEY_ID": "test-key",
    "R2_SECRET_ACCESS_KEY": "test-secret",
    "R2_ENDPOINT": "https://test.r2.cloudflarestorage.com",
    "R2_BUCKET": "test-bucket",
}


class FakeR2:
    """Client S3 fals: ține obiectele într-un dict, fără rețea."""
    def __init__(self):
        self.store = {}
        self.put_calls = 0

    def put_object(self, Bucket, Key, Body):
        self.put_calls += 1
        self.store[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.store[(Bucket, Key)])}


def _enable_r2(monkeypatch):
    for k, v in R2_ENV.items():
        monkeypatch.setenv(k, v)
    fake = FakeR2()
    monkeypatch.setattr(storage, "_get_r2_client", lambda: fake)
    return fake


def _disable_r2(monkeypatch):
    for k in storage._R2_ENV:
        monkeypatch.delenv(k, raising=False)


# ────────────────────────────────────────────────────────────
# R2 activ — cheie exactă + round-trip
# ────────────────────────────────────────────────────────────

def test_save_bytes_r2_cheie_exacta(monkeypatch):
    fake = _enable_r2(monkeypatch)
    data = b"hello-r2"
    sha = storage.compute_sha256(data)
    key = storage.save_bytes(data, sha, ext="jpg", user_id=1,
                             dt=datetime(2026, 6, 5))
    assert key == f"user_1/2026/06/{sha}.jpg"          # zero-padding lună (06)
    assert fake.store[("test-bucket", key)] == data    # urcat în R2
    assert fake.put_calls == 1


def test_get_bytes_r2_roundtrip(monkeypatch):
    _enable_r2(monkeypatch)
    data = b"continut-document"
    sha = storage.compute_sha256(data)
    key = storage.save_bytes(data, sha, ext="jpg", user_id=7,
                             dt=datetime(2026, 1, 9))
    assert key == f"user_7/2026/01/{sha}.jpg"          # luna 01, nu 1
    assert storage.get_bytes(key) == data


def test_zero_padding_luna(monkeypatch):
    _enable_r2(monkeypatch)
    sha = storage.compute_sha256(b"x")
    for luna, asteptat in [(1, "01"), (6, "06"), (12, "12")]:
        key = storage.save_bytes(b"x", sha, ext="bin", user_id=3,
                                 dt=datetime(2026, luna, 15))
        assert key == f"user_3/2026/{asteptat}/{sha}.bin"


# ────────────────────────────────────────────────────────────
# Fallback disk — R2 dezactivat
# ────────────────────────────────────────────────────────────

def test_fallback_disk_cand_r2_dezactivat(monkeypatch, tmp_path):
    _disable_r2(monkeypatch)
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path / "storage")
    data = b"pe-disk"
    sha = storage.compute_sha256(data)
    path = storage.save_bytes(data, sha, ext="jpg", user_id=1)
    assert "storage" in path
    assert sha in path
    assert storage.get_bytes(path) == data             # citit înapoi de pe disk


def test_backward_compat_apel_vechi(monkeypatch, tmp_path):
    # apelul vechi (fără user_id) rămâne pe disk, chiar dacă R2 ar fi activ
    fake = _enable_r2(monkeypatch)
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path / "storage")
    sha = storage.compute_sha256(b"vechi")
    path = storage.save_bytes(b"vechi", sha, ext="jpg")  # fără user_id
    assert "storage" in path
    assert fake.put_calls == 0                            # NU s-a atins R2


# ────────────────────────────────────────────────────────────
# Detecție _r2_enabled
# ────────────────────────────────────────────────────────────

def test_r2_enabled_detection(monkeypatch):
    for k, v in R2_ENV.items():
        monkeypatch.setenv(k, v)
    assert storage._r2_enabled() is True
    monkeypatch.delenv("R2_BUCKET")
    assert storage._r2_enabled() is False


def test_get_bytes_disk_lipsa_ridica_eroare(monkeypatch, tmp_path):
    _disable_r2(monkeypatch)
    with pytest.raises(FileNotFoundError):
        storage.get_bytes(str(tmp_path / "storage" / "inexistent.jpg"))
