"""
Storage local pentru fișierele primite de la useri.

Pe Render Free, filesystem-ul e efemer (se șterge la redeploy).
Hash-urile rămân în DB → dedup-ul funcționează în continuare.
Pentru persistență reală, vom muta la S3/R2 într-un pas viitor.
"""

import hashlib
import os
from pathlib import Path

STORAGE_DIR = Path("./storage")


def compute_sha256(data: bytes) -> str:
    """SHA256 hex digest (64 caractere)."""
    return hashlib.sha256(data).hexdigest()


def ensure_storage_dir() -> None:
    """Crează folderul storage dacă nu există. Idempotent."""
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def save_bytes(data: bytes, sha256: str, ext: str = "jpg") -> str:
    """
    Salvează bytes pe disk la ./storage/<sha>.<ext>
    Dacă fișierul există deja (same hash), nu-l rescrie.
    Întoarce calea relativă (string).
    """
    ensure_storage_dir()
    path = STORAGE_DIR / f"{sha256}.{ext}"
    if not path.exists():
        path.write_bytes(data)
    return str(path)
