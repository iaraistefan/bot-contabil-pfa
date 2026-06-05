"""
Storage pentru fișierele primite de la useri — backend R2 cu fallback disk.

Strategie:
- Dacă cele 4 variabile R2 sunt setate (Render) → urcăm în Cloudflare R2
  (S3-compatible, boto3 cu endpoint custom). Cheia: user_<id>/<an>/<lună>/<sha>.<ext>
  (an/lună din data upload-ului — singura cunoscută la momentul salvării).
- Dacă R2 NU e configurat (local/test) → fallback pe disk (./storage/<sha>.<ext>),
  comportamentul istoric. Robust: nu crapă în dev/teste.

Dedup-ul rămâne în DB (înainte de save), deci save_bytes (și uploadul R2) se
cheamă DOAR pentru fișiere noi. Pe Render Free disk-ul e efemer — de aceea R2.
"""

import hashlib
import os
from datetime import datetime
from pathlib import Path

STORAGE_DIR = Path("./storage")

# Variabilele R2 sunt citite din os.environ (NU din config.Settings), ca să nu
# devină obligatorii — lipsa lor înseamnă fallback pe disk, nu crash.
_R2_ENV = ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT", "R2_BUCKET")


def compute_sha256(data: bytes) -> str:
    """SHA256 hex digest (64 caractere)."""
    return hashlib.sha256(data).hexdigest()


# ============================================================
#                          R2 (S3-compatible)
# ============================================================

def _r2_enabled() -> bool:
    """True dacă toate cele 4 variabile R2 sunt prezente în environment."""
    return all(os.environ.get(k) for k in _R2_ENV)


def _get_r2_client():
    """Client S3 pentru R2 (import boto3 lazy — doar când chiar urcăm în R2)."""
    import boto3  # lazy: nu e nevoie local/test (clientul e mock-uit acolo)
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def _r2_key(user_id: int, sha256: str, ext: str, dt: datetime) -> str:
    """Cheia R2: user_<id>/<an>/<lună zero-padded>/<sha>.<ext>."""
    return f"user_{user_id}/{dt.year}/{dt.month:02d}/{sha256}.{ext}"


# ============================================================
#                          DISK (fallback)
# ============================================================

def ensure_storage_dir() -> None:
    """Crează folderul storage dacă nu există. Idempotent."""
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def _save_disk(data: bytes, sha256: str, ext: str) -> str:
    """Salvează pe disk la ./storage/<sha>.<ext>. Dedup prin existență."""
    ensure_storage_dir()
    path = STORAGE_DIR / f"{sha256}.{ext}"
    if not path.exists():
        path.write_bytes(data)
    return str(path)


# ============================================================
#                          API PUBLICĂ
# ============================================================

def save_bytes(data: bytes, sha256: str, ext: str = "jpg", *,
               user_id: int = None, dt: datetime = None) -> str:
    """
    Salvează bytes și întoarce `storage_path` (cheie R2 sau cale disk).

    R2 (dacă _r2_enabled() ȘI user_id dat):
        urcă la cheia user_<id>/<an>/<lună>/<sha>.<ext> și întoarce cheia.
    Altfel (fallback):
        scrie pe disk la ./storage/<sha>.<ext> și întoarce calea.

    Args:
        data: conținutul fișierului.
        sha256: hash-ul (deja calculat de apelant pentru dedup).
        ext: extensia ("jpg" / "bin"...).
        user_id: necesar pentru cheia R2 (per-user). Lipsă -> fallback disk.
        dt: data upload-ului (default: acum) — dă an/lună în cheie.
    """
    if _r2_enabled() and user_id is not None:
        dt = dt or datetime.utcnow()
        key = _r2_key(user_id, sha256, ext, dt)
        _get_r2_client().put_object(
            Bucket=os.environ["R2_BUCKET"], Key=key, Body=data,
        )
        return key
    return _save_disk(data, sha256, ext)


def get_bytes(storage_path: str) -> bytes:
    """
    Citește înapoi conținutul după `storage_path`.

    Prefix "storage" -> disk; altfel (ex. "user_…") + R2 activ -> R2.
    Ridică FileNotFoundError dacă lipsește (ex. fișier istoric pierdut).
    """
    is_disk = str(storage_path).replace("\\", "/").startswith("storage")
    if not is_disk and _r2_enabled():
        resp = _get_r2_client().get_object(
            Bucket=os.environ["R2_BUCKET"], Key=storage_path,
        )
        return resp["Body"].read()
    # disk
    path = Path(storage_path)
    if not path.exists():
        raise FileNotFoundError(f"Fișier indisponibil: {storage_path}")
    return path.read_bytes()
