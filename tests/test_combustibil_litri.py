"""
Fiscal #5 — verdict combustibil pe LITRI (nu pe lei).

Bug: `mai_poti_lei = plafon_lei - total_bonuri_lei` amestecă banii TUTUROR
bonurilor cu un pret derivat doar din bonurile CU litri → fals „depășit" când
unele bonuri n-au litri. Fix: verdict pe `total_litri` vs `plafon_litri`.

+ linia 138: norma fallback = NORMA_CONSUM_FALLBACK (L/100km), NU
  PRET_MOTORINA_FALLBACK (RON/L) — un preț nu poate fi o normă de consum.
"""

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import combustibil as C
from app.models import User


def _sum(km_business, norma, total_bonuri_lei, total_litri, lei_cu_litri,
         nr_bonuri, nr_bonuri_cu_litri):
    return C._summarize(
        km_business=km_business, norma=norma,
        total_bonuri_lei=total_bonuri_lei, total_litri=total_litri,
        lei_cu_litri=lei_cu_litri, nr_bonuri=nr_bonuri,
        nr_bonuri_cu_litri=nr_bonuri_cu_litri, year=2026, month=5,
    )


# ── DOVADA BUG → FIX (bonuri mixte: unele fără litri) ───────────────

def test_bonuri_mixte_lei_fals_depasit_litri_corect():
    # km 1000, normă 7,5 → plafon 75 L. Un bon cu 50 L (350 lei), unul FĂRĂ
    # litri (500 lei). Verificat: 50 L < 75 L plafon → NU e depășit.
    r = _sum(km_business=1000, norma=7.5, total_bonuri_lei=850.0,
             total_litri=50.0, lei_cu_litri=350.0,
             nr_bonuri=2, nr_bonuri_cu_litri=1)
    # BUG: verdictul vechi pe lei ar fi „depășit" (mai_poti_lei negativ)
    assert r["mai_poti_lei"] < 0
    # FIX: verdictul pe litri spune corect — NU depășit, mai poate 25 L
    assert r["depasit"] is False
    assert r["mai_poti_litri"] == 25.0


# ── Demonstrația matematică: toate bonurile cu litri → lei ⟺ litri ──

def test_toate_cu_litri_lei_si_litri_coincid_depasit():
    # 80 L (560 lei, preț 7) vs plafon 75 L → depășit pe AMBELE.
    r = _sum(1000, 7.5, 560.0, 80.0, 560.0, 1, 1)
    assert r["depasit"] is True
    assert r["mai_poti_lei"] < 0           # același semn ca verdictul pe litri


def test_toate_cu_litri_sub_plafon_coincid():
    # 60 L (420 lei) vs plafon 75 L → sub plafon pe AMBELE.
    r = _sum(1000, 7.5, 420.0, 60.0, 420.0, 1, 1)
    assert r["depasit"] is False
    assert r["mai_poti_lei"] > 0
    assert r["mai_poti_litri"] == 15.0


# ── Fără niciun litru → verdict NECUNOSCUT (None), nu fals „OK" ─────

def test_fara_litri_verdict_necunoscut():
    r = _sum(1000, 7.5, 500.0, 0.0, 0.0, 1, 0)
    assert r["depasit"] is None            # nu dăm verdict pe date nepuse
    assert r["pret_din_bonuri"] is False


# ── Render: verdictul afișat e pe LITRI + caveat bonuri fără litri ──

def test_render_depasit_pe_litri():
    r = _sum(1000, 7.5, 700.0, 90.0, 700.0, 1, 1)   # 90 L > 75 → depășit 15 L
    txt = C.format_fuel_section(r)
    assert "depășit" in txt and "L" in txt
    assert "lei" not in txt.split("depășit")[1][:20]   # verdictul e în L, nu lei


def test_render_caveat_bonuri_fara_litri():
    r = _sum(1000, 7.5, 850.0, 50.0, 350.0, 2, 1)   # 1 bon fără litri
    txt = C.format_fuel_section(r)
    assert "fără litri" in txt                       # nudge de completare


def test_render_fara_litri_cere_litri():
    r = _sum(1000, 7.5, 500.0, 0.0, 0.0, 1, 0)
    txt = C.format_fuel_section(r)
    assert "Scrie litrii" in txt


# ── Linia 138: norma fallback e CONSUM (7,5), nu PREȚ ──────────────

def test_norma_fallback_e_consum_nu_pret(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    monkeypatch.setattr(C, "get_session", lambda: Session())
    monkeypatch.setattr(C.vehicule_repo, "get_default", lambda s, u: None)  # fără vehicul
    monkeypatch.setattr(C.trip_repo, "list_closed_for_month",
                        lambda s, u, y, m: [SimpleNamespace(km=1000.0)])
    # DOVADA fix: chiar dacă prețul fallback ar fi 999, norma rămâne 7,5 (consum)
    monkeypatch.setattr(C, "PRET_MOTORINA_FALLBACK", 999.0)
    res = C.get_fuel_summary(1, 2026, 5)
    assert res["norma_consum"] == 7.5                # NORMA, nu prețul (999)
    assert res["plafon_litri"] == 1000 * 7.5 / 100   # = 75 L
