"""
Migrare idempotenta: adauga in tabela users coloanele pentru
codurile fiscale suplimentare (cod special TVA art. 317 + CNP).

Se ruleaza la pornirea botului, dupa run_migrations(). Foloseste
ADD COLUMN IF NOT EXISTS (suportat de Postgres), deci e sigur sa
ruleze de oricate ori - nu strica nimic daca au fost deja adaugate.
"""

import logging
from sqlalchemy import text

from db import get_session

logger = logging.getLogger(__name__)

_COLOANE = [
    ("cod_special_tva", "VARCHAR(20)"),
    ("cnp", "VARCHAR(13)"),
]


def ensure_coduri_fiscale_columns():
    """Adauga coloanele cod_special_tva si cnp daca lipsesc."""
    session = get_session()
    try:
        for nume, tip in _COLOANE:
            session.execute(text(
                f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {nume} {tip}"
            ))
        session.commit()
        logger.info("Migrare coduri fiscale OK (cod_special_tva, cnp)")
    except Exception as e:
        session.rollback()
        logger.error(f"Migrare coduri fiscale a esuat: {e}")
        raise
    finally:
        session.close()
