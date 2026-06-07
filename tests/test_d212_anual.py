"""
Teste pentru compute_d212_anual (Faza 1 — suma D212 pe card).

Disciplina Faza 0 (calcul de bani):
- ECHIVALENTA: helper-ul produce EXACT acelasi rezultat ca vechea logica inline
  din /api/v1/declaratie-unica (Σ compute_period + genereaza_d212). Diff 0.
- An corect: D212 pe martie 2026 -> agrega 2025; iunie 2026 -> agrega 2026
  (via termen.year - 1).
- Cele 3 cazuri la venit: an gol (0), pierdere (>0 dar total 0), venit pozitiv.

compute_period e mock-uit (fara DB).
"""

from datetime import date

from app.services import tax_engine
from app.integrations.anaf import declaratii_service as decl
from app.domain.fiscal_calendar import get_obligations_for_user


def _mock_period(monkeypatch, per_month):
    """per_month: {luna: (income_total, expense_deductible_total)}."""
    def fake(session, *, user_id, year, month):
        inc, exp = per_month.get(month, (0.0, 0.0))
        return {"income_total": float(inc), "expense_deductible_total": float(exp)}
    monkeypatch.setattr(tax_engine, "compute_period", fake)


# ────────────────────────────────────────────────────────────
# ECHIVALENTA — helper == vechea cale inline (diff 0)
# ────────────────────────────────────────────────────────────

def test_echivalenta_helper_vs_old_path(monkeypatch):
    monthly = {1: (1000, 200), 2: (1500, 300), 3: (2000, 0),
               4: (2500, 450.55), 5: (1800, 120), 6: (3000, 600)}
    _mock_period(monkeypatch, monthly)

    # vechea cale (replica logicii inline din endpoint-ul actual)
    vb = sum(v[0] for v in monthly.values())
    ch = sum(v[1] for v in monthly.values())
    baseline = decl.genereaza_d212(2026, round(vb, 2), round(ch, 2))

    # noua cale
    r = tax_engine._compute_d212_anual_uncached(None, user_id=1, an=2026)

    assert (r.venit_brut, r.cheltuieli, r.venit_net, r.cas, r.cass,
            r.impozit, r.total_plata, r.bonificatie) == \
           (baseline.venit_brut, baseline.cheltuieli, baseline.venit_net,
            baseline.cas, baseline.cass, baseline.impozit,
            baseline.total_plata, baseline.bonificatie)


# ────────────────────────────────────────────────────────────
# AN CORECT — agregare pe anul potrivit + termen.year - 1
# ────────────────────────────────────────────────────────────

def test_helper_agrega_anul_cerut(monkeypatch):
    # venit diferit pe 2025 vs 2026 -> helper agrega anul cerut
    def fake(session, *, user_id, year, month):
        inc = {2025: 1000.0, 2026: 2000.0}.get(year, 0.0)
        return {"income_total": inc, "expense_deductible_total": 0.0}
    monkeypatch.setattr(tax_engine, "compute_period", fake)

    assert tax_engine._compute_d212_anual_uncached(None, user_id=1, an=2025).venit_brut == 12_000
    assert tax_engine._compute_d212_anual_uncached(None, user_id=1, an=2026).venit_brut == 24_000


def test_termen_an_minus_1():
    # martie 2026 -> D212 termen in 2026 -> venit anul 2025
    obl_mar = get_obligations_for_user(
        2026, 3, "PFA", "ridesharing",
        today=date(2026, 3, 15), has_cod_special_tva=True,
    )
    d212_mar = next(o for o in obl_mar if o.definitie.cod == "D212")
    assert d212_mar.termen.year == 2026
    assert d212_mar.termen.year - 1 == 2025

    # iunie 2026 -> D212 termen in 2027 -> venit anul 2026
    obl_iun = get_obligations_for_user(
        2026, 6, "PFA", "ridesharing",
        today=date(2026, 6, 5), has_cod_special_tva=True,
    )
    d212_iun = next(o for o in obl_iun if o.definitie.cod == "D212")
    assert d212_iun.termen.year == 2027
    assert d212_iun.termen.year - 1 == 2026


# ────────────────────────────────────────────────────────────
# CELE 3 CAZURI LA VENIT
# ────────────────────────────────────────────────────────────

def test_caz_an_gol(monkeypatch):
    _mock_period(monkeypatch, {})  # nicio luna cu date
    r = tax_engine._compute_d212_anual_uncached(None, user_id=1, an=2026)
    assert r.venit_brut == 0
    assert r.total_plata == 0
    # regula card: venit_brut == 0 -> estimare_in_curs (NU afisam "0 lei" sec)
    assert (r.venit_brut > 0) is False


def test_caz_pierdere(monkeypatch):
    _mock_period(monkeypatch, {1: (3000, 5000)})  # cheltuieli > venit
    r = tax_engine._compute_d212_anual_uncached(None, user_id=1, an=2026)
    assert r.venit_brut == 3000
    assert r.venit_net == -2000
    assert r.total_plata == 0          # pierdere -> fara plata
    assert r.venit_brut > 0            # -> "de depus, fara plata" (declarativa)


def test_caz_venit_pozitiv_mic(monkeypatch):
    _mock_period(monkeypatch, {1: (5000, 0)})  # venit net 5000, sub 6 SMB
    r = tax_engine._compute_d212_anual_uncached(None, user_id=1, an=2026)
    assert r.venit_brut == 5000
    assert r.cass == 2430.0             # CASS minim pe 6 SMB (fix Faza 0)
    assert r.total_plata == 2687.0      # suma reala -> intra in plati
