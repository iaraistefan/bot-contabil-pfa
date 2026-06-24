"""
Migrare 021 — aliniază document.vat_id vechi (typo audit #2): EE102094445 → EE102090374.

Codul (PR #25) previne deja viitoarele scrieri greșite, dar documentele Bolt postate
ÎNAINTE de fix pot avea typo-ul stocat. Migrarea e VERSIONATĂ + IDEMPOTENTĂ (rulează la
deploy; 0 rânduri → nu face nimic; >0 → aliniază). Impact ZERO la ANAF (D390 nu citește
document.vat_id, generează din sursa unică BOLT_VAT_ID).

Testăm pe SQL-ul REAL din MIGRATIONS (nu o copie) → comportament, nu prezență.
"""

from sqlalchemy import create_engine, text

from app.migrations import MIGRATIONS
from app.domain.tax_rules import BOLT_VAT_ID

MIG_ID = "021_documents_fix_bolt_vat_id"
TYPO = "EE102094445"


def _get_migration():
    return next((m for m in MIGRATIONS if m["id"] == MIG_ID), None)


def test_migrarea_e_in_lista():
    m = _get_migration()
    assert m is not None, f"{MIG_ID} lipsește din MIGRATIONS"
    sql_joined = " ".join(m["sql"])
    assert TYPO in sql_joined                  # corectează typo-ul
    assert BOLT_VAT_ID in sql_joined           # → spre valoarea din sursa unică


def test_aliniaza_typo_lasa_restul_neatins_si_e_idempotenta():
    m = _get_migration()
    assert m is not None
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as cx:
        cx.execute(text("CREATE TABLE documents (id INTEGER PRIMARY KEY, vat_id VARCHAR(20))"))
        cx.execute(text(
            "INSERT INTO documents (id, vat_id) VALUES "
            f"(1, '{TYPO}'), (2, '{BOLT_VAT_ID}'), (3, 'NL852071589B01'), (4, NULL)"
        ))
        for sql in m["sql"]:
            cx.execute(text(sql))

    with eng.connect() as cx:
        # typo aliniat; rândul deja corect + cel migrat = 2 cu codul corect
        assert cx.execute(text(f"SELECT COUNT(*) FROM documents WHERE vat_id='{TYPO}'")).scalar() == 0
        assert cx.execute(text(f"SELECT COUNT(*) FROM documents WHERE vat_id='{BOLT_VAT_ID}'")).scalar() == 2
        # alte VAT-uri (Uber) + NULL neatinse
        assert cx.execute(text("SELECT vat_id FROM documents WHERE id=3")).scalar() == "NL852071589B01"
        assert cx.execute(text("SELECT vat_id FROM documents WHERE id=4")).scalar() is None

    # idempotență: a doua rulare nu mai schimbă nimic
    with eng.begin() as cx:
        for sql in m["sql"]:
            cx.execute(text(sql))
    with eng.connect() as cx:
        assert cx.execute(text(f"SELECT COUNT(*) FROM documents WHERE vat_id='{TYPO}'")).scalar() == 0
        assert cx.execute(text(f"SELECT COUNT(*) FROM documents WHERE vat_id='{BOLT_VAT_ID}'")).scalar() == 2
