"""
Suport Uber — SUB-PAS A: regim nerezident PER-PLATFORMĂ (fundație de date).

ZERO schimbare de comportament: D100 single (pre-Uber) consumă `cota_nerezident`,
care rămâne ALIAS = Bolt → identic înainte/după A. Uber se stochează, dar nu intră
încă în D100 (sub-pas B). Testul-cheie: backward-compat (userii #3 nu-și pierd D100).
"""

from app.domain.fiscal_profile import from_user_dict, RegimNerezident
from app.repositories.users import (
    is_valid_regim_nerezident_bolt, is_valid_regim_nerezident_uber,
    VALID_REGIMURI_NEREZIDENT_BOLT, VALID_REGIMURI_NEREZIDENT_UBER,
)


def _p(**kw):
    return from_user_dict({"firma_forma_juridica": "PFA", **kw})


# ── citire per-platformă ────────────────────────────────────────────

def test_bolt_si_uber_citite_separat():
    p = _p(regim_nerezident_bolt="BOLT_CU_CRF", regim_nerezident_uber="UBER_CU_CRF")
    assert p.regim_nerezident_bolt == RegimNerezident.BOLT_CU_CRF
    assert p.regim_nerezident_uber == RegimNerezident.UBER_CU_CRF
    assert p.cota_nerezident_bolt == 0.02
    assert p.cota_nerezident_uber == 0.0


def test_cota_nerezident_for_brand():
    p = _p(regim_nerezident_bolt="BOLT_FARA_CRF", regim_nerezident_uber="UBER_CU_CRF")
    assert p.cota_nerezident_for("Bolt") == 0.16
    assert p.cota_nerezident_for("Uber") == 0.0
    assert p.cota_nerezident_for("Uber Eats") == 0.0    # startswith „uber"
    assert p.cota_nerezident_for("AWS") is None          # necunoscut → fără cotă
    assert p.cota_nerezident_for(None) is None


# ── alias backward-compat (cota_nerezident = Bolt) — D100 NESCHIMBAT ─

def test_alias_cota_nerezident_e_bolt():
    p = _p(regim_nerezident_bolt="BOLT_CU_CRF")
    assert p.cota_nerezident == p.cota_nerezident_bolt == 0.02
    assert p.regim_nerezident == p.regim_nerezident_bolt == RegimNerezident.BOLT_CU_CRF


# ── ESENȚIAL: fallback la vechiul regim_nerezident (userii #3) ──────

def test_backward_compat_fallback_vechiul_camp():
    # user #3: a setat DOAR vechiul `regim_nerezident` (pre-backfill / capturat pe
    # câmpul vechi) → D100 (cota_nerezident) trebuie să se rezolve, NU să se piardă.
    p = _p(regim_nerezident="BOLT_CU_CRF")               # doar vechiul, NU _bolt
    assert p.regim_nerezident_bolt == RegimNerezident.BOLT_CU_CRF   # fallback
    assert p.cota_nerezident == 0.02                     # D100 IDENTIC


def test_bolt_nou_are_prioritate_peste_vechiul():
    # dacă _bolt e setat, are prioritate peste vechiul (nu se amestecă)
    p = _p(regim_nerezident_bolt="BOLT_FARA_CRF", regim_nerezident="BOLT_CU_CRF")
    assert p.cota_nerezident == 0.16                     # _bolt (16%), nu vechiul (2%)


def test_neconfigurat_ramane_none():
    p = _p()
    assert p.cota_nerezident is None
    assert p.cota_nerezident_bolt is None and p.cota_nerezident_uber is None


# ── VALID per-platformă (anti-cross-contaminare) ────────────────────

def test_valid_seturi_separate():
    assert VALID_REGIMURI_NEREZIDENT_BOLT == {"BOLT_CU_CRF", "BOLT_FARA_CRF"}
    assert VALID_REGIMURI_NEREZIDENT_UBER == {"UBER_CU_CRF", "UBER_FARA_CRF"}


def test_cod_uber_respins_pe_bolt_si_invers():
    assert is_valid_regim_nerezident_bolt("BOLT_CU_CRF") is True
    assert is_valid_regim_nerezident_bolt("UBER_CU_CRF") is False    # Uber NU pe Bolt
    assert is_valid_regim_nerezident_uber("UBER_FARA_CRF") is True
    assert is_valid_regim_nerezident_uber("BOLT_FARA_CRF") is False  # Bolt NU pe Uber


# ── Migrare 014: idempotentă + NE-DISTRUCTIVĂ (structural) ──────────

def test_migrare_014_idempotenta_si_ne_distructiva():
    from app.migrations import MIGRATIONS
    by_id = {m["id"]: m for m in MIGRATIONS}
    assert len(by_id) == len(MIGRATIONS)                 # id-uri unice
    m = by_id["014_regim_nerezident_per_platforma"]
    sql = " ".join(m["sql"]).upper()
    assert "ADD COLUMN IF NOT EXISTS REGIM_NEREZIDENT_BOLT" in sql
    assert "ADD COLUMN IF NOT EXISTS REGIM_NEREZIDENT_UBER" in sql
    # backfill idempotent (doar unde _bolt NULL) + ne-distructiv (nu atinge vechiul)
    assert "WHERE REGIM_NEREZIDENT_BOLT IS NULL" in sql
    assert "DROP" not in sql and "DELETE" not in sql
