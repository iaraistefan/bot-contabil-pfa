"""
Repository pentru SourceFile — dedup bazat pe SHA256.
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.models import SourceFile


def get_by_sha256(session: Session, user_id: int, sha256: str) -> Optional[SourceFile]:
    """
    Caută un fișier deja înregistrat pentru acest user cu acest hash.
    Întoarce None dacă e prima dată.
    """
    return (
        session.query(SourceFile)
        .filter(SourceFile.user_id == user_id, SourceFile.sha256 == sha256)
        .one_or_none()
    )


def create(
    session: Session,
    *,
    user_id: Optional[int],
    kind: str,
    sha256: str,
    telegram_file_id: Optional[str] = None,
    mime: Optional[str] = None,
    bytes_size: Optional[int] = None,
    storage_path: Optional[str] = None,
) -> SourceFile:
    """Înregistrează un fișier nou. Commit-ul rămâne la apelant."""
    sf = SourceFile(
        user_id=user_id,
        kind=kind,
        sha256=sha256,
        telegram_file_id=telegram_file_id,
        mime=mime,
        bytes_size=bytes_size,
        storage_path=storage_path,
    )
    session.add(sf)
    session.flush()
    return sf
