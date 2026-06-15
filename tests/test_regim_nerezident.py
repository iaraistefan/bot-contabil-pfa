"""
Fiscal #3 — SUB-PAS A: fundația de date pentru regimul nerezident D100.

Acoperă DOAR maparea (regim → cotă) + None-safety. NU atinge calculul D100
sau afișarea — acelea vin în sub-pașii B-E. După sub-pas A comportamentul
vizibil e neschimbat (D100 încă pe 2% vechi); aici blocăm doar fundația:

  - cele 4 regimuri (Bolt 2%/16%, Uber 0%/16%) → cotă corectă;
  - NULL (neconfigurat) → None, NU o rată presupusă;
  - valoare invalidă → None, NU o rată presupusă (a presupune = bug-ul #3);
  - migrarea 013 e idempotentă (formă ADD COLUMN IF NOT EXISTS + tracking).
"""

import pytest

from app.domain.fiscal_profile import (
    from_user_dict,
    RegimNerezident,
    COTA_NEREZIDENT,
)


def _profile(regim_nerezident):
    """Profil minimal PFA cu regimul nerezident dat (sau cheia absentă)."""
    d = {"firma_forma_juridica": "PFA"}
    if regim_nerezident is not _ABSENT:
        d["regim_nerezident"] = regim_nerezident
    return from_user_dict(d)


_ABSENT = object()  # marcaj „cheia lipsește complet din dict"


# ── Sursa unică acoperă exact cele 3 regimuri ───────────────────────

def test_cota_mapping_acopera_toate_regimurile():
    assert set(COTA_NEREZIDENT) == set(RegimNerezident)
    # Bolt (Estonia, Art. 12): 2% cu certificat / 16% fără — NU există 0%.
    assert COTA_NEREZIDENT[RegimNerezident.BOLT_CU_CRF] == 0.02
    assert COTA_NEREZIDENT[RegimNerezident.BOLT_FARA_CRF] == 0.16
    # Uber (Olanda, art. 7): 0% cu certificat / 16% fără (extensie engine).
    assert COTA_NEREZIDENT[RegimNerezident.UBER_CU_CRF] == 0.0
    assert COTA_NEREZIDENT[RegimNerezident.UBER_FARA_CRF] == 0.16


# ── from_user_dict: fiecare cod → cotă corectă (engine acceptă toate) ─

@pytest.mark.parametrize("regim,cota_asteptata", [
    ("BOLT_CU_CRF", 0.02),
    ("BOLT_FARA_CRF", 0.16),
    ("UBER_CU_CRF", 0.0),
    ("UBER_FARA_CRF", 0.16),
])
def test_from_user_dict_mapeaza_cota(regim, cota_asteptata):
    p = _profile(regim)
    assert p.regim_nerezident == RegimNerezident(regim)
    assert p.cota_nerezident == cota_asteptata


# ── Neconfigurat → None, NU o rată presupusă (miezul #3) ────────────

def test_null_da_none_nu_rata():
    # cheia lipsește complet din profil (cazul userilor existenți, NULL în DB)
    p = _profile(_ABSENT)
    assert p.regim_nerezident is None
    assert p.cota_nerezident is None          # NU 0.02, NU 0.0 — neconfigurat


def test_none_explicit_da_none():
    p = _profile(None)
    assert p.regim_nerezident is None
    assert p.cota_nerezident is None


def test_empty_string_da_none():
    p = _profile("")
    assert p.regim_nerezident is None
    assert p.cota_nerezident is None


def test_valoare_invalida_da_none_nu_rata():
    # un string necunoscut NU trebuie să devină o rată — rămâne neconfigurat
    p = _profile("CEVA_GRESIT")
    assert p.regim_nerezident is None
    assert p.cota_nerezident is None


# ── to_summary expune ambele câmpuri (pt /anafdebug) ────────────────

def test_to_summary_include_nerezident():
    s = _profile("BOLT_CU_CRF").to_summary()
    assert s["regim_nerezident"] == "BOLT_CU_CRF"
    assert s["cota_nerezident"] == 0.02

    s_null = _profile(_ABSENT).to_summary()
    assert s_null["regim_nerezident"] is None
    assert s_null["cota_nerezident"] is None


# ── Migrarea 013: idempotentă prin construcție ──────────────────────
# Migrările folosesc DDL Postgres (ADD COLUMN IF NOT EXISTS) + tracking în
# schema_migrations; nu se execută pe SQLite-ul testelor. Verificăm deci
# garanțiile STRUCTURALE de idempotență, nu execuția propriu-zisă.

def test_migrare_013_idempotenta_prin_constructie():
    from app.migrations import MIGRATIONS

    by_id = {m["id"]: m for m in MIGRATIONS}
    # id unic (rulat de 2× → _is_applied sare a doua oară)
    assert len(by_id) == len(MIGRATIONS), "ID-uri de migrare duplicate"

    m = by_id["013_user_regim_nerezident"]
    assert len(m["sql"]) == 1
    sql = m["sql"][0].upper()
    # forma idempotentă la nivel SQL (chiar dacă tracking-ul ar fi ocolit)
    assert "ADD COLUMN IF NOT EXISTS" in sql
    assert "REGIM_NEREZIDENT" in sql
    # nullable fără default — NULL = neconfigurat, nu o rată presupusă
    assert "NOT NULL" not in sql
    assert "DEFAULT" not in sql
