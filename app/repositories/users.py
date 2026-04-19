"""
Repository pentru User — acces la DB pentru users.

Convenție: orice funcție care atinge DB acceptă o SQLAlchemy Session ca prim argument.
Asta ține tranzacțiile sub controlul apelantului.
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.models import User


def get_by_telegram_id(session: Session, telegram_id: int) -> Optional[User]:
    """Returnează user-ul cu acest telegram_id, sau None."""
    return session.query(User).filter(User.telegram_id == telegram_id).one_or_none()


def get_or_create_by_telegram_id(
    session: Session,
    telegram_id: int,
    name: Optional[str] = None,
) -> User:
    """
    Returnează user-ul existent sau îl creează dacă nu există.
    Commit-ul rămâne în grija apelantului.
    """
    user = get_by_telegram_id(session, telegram_id)
    if user is not None:
        # Actualizăm numele dacă s-a schimbat (user-ul și-a schimbat numele în Telegram)
        if name and user.name != name:
            user.name = name
        return user

    user = User(telegram_id=telegram_id, name=name)
    session.add(user)
    session.flush()  # ca să avem user.id disponibil înainte de commit
    return user
