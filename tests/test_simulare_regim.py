"""
A1 — simulare regim NORMĂ vs SISTEM REAL (funcție pură, fundația simulatorului).

Orchestrează `calculeaza_d212` (chemat de 2 ori) + contextul legal din `norma_venit`
(gardian tranziție + plafon). Întoarce DOAR date + coduri de avertisment (zero
formatare — aia vine în UI/A3). NU atinge motorul.
"""

import pytest

from app.integrations.anaf.simulare_regim import simulare_regim, SimulareRegim
from app.integrations.anaf.d212_calc import calculeaza_d212

AN, SMB = 2026, 4050
NORMA = 50_000.0   # ∈ [12 SMB, 24 SMB) → CAS pe 48.600, CASS pe 50.000


def _real(vb, ch, an=AN):
    return calculeaza_d212(vb, ch, an=an, salariu_minim=SMB)


def _norma(an=AN):
    return calculeaza_d212(0, 0, an=an, salariu_minim=SMB,
                           regim="NORMA_VENIT", norma_anuala=NORMA)


# ════════════════════════════════════════════════════════════
#   Recomandare normă vs real (orchestrare prin motor)
# ════════════════════════════════════════════════════════════

def test_recomanda_norma_cand_mai_ieftina():
    # venit mare, cheltuieli mici → real scump; normă fixă 50k mai ieftină
    s = simulare_regim(200_000, 20_000, NORMA, AN, "ridesharing", "SISTEM_REAL")
    assert isinstance(s, SimulareRegim)
    assert s.recomandat == "NORMA_VENIT"
    assert s.norma is not None
    # cifrele trec corect prin motor (sursă unică)
    assert s.real["total_taxe"] == _real(200_000, 20_000).total_plata
    assert s.norma["total_taxe"] == _norma().total_plata
    assert s.diferenta == round(s.real["total_taxe"] - s.norma["total_taxe"], 2)
    assert s.diferenta > 0
    # recomandat ≠ curent → SCHIMBARE_ANUL_URMATOR; curent real + recomandat normă → REVENIRE
    assert "SCHIMBARE_ANUL_URMATOR" in s.avertismente_legale
    assert "REVENIRE_NORMA_2ANI" in s.avertismente_legale


def test_recomanda_real_cand_mai_ieftin():
    # venit mic → real ieftin (CAS 0); normă fixă 50k mai scumpă
    s = simulare_regim(40_000, 10_000, NORMA, AN, "ridesharing", "NORMA_VENIT")
    assert s.recomandat == "SISTEM_REAL"
    assert s.real["total_taxe"] < s.norma["total_taxe"]
    assert "SCHIMBARE_ANUL_URMATOR" in s.avertismente_legale   # recomandat real ≠ curent normă
    assert "REVENIRE_NORMA_2ANI" not in s.avertismente_legale  # nu recomandăm normă


def test_recomandat_egal_curent_fara_schimbare():
    # normă mai ieftină ȘI user deja pe normă → fără SCHIMBARE/REVENIRE
    s = simulare_regim(200_000, 20_000, NORMA, AN, "ridesharing", "NORMA_VENIT")
    assert s.recomandat == "NORMA_VENIT"
    assert "SCHIMBARE_ANUL_URMATOR" not in s.avertismente_legale
    assert "REVENIRE_NORMA_2ANI" not in s.avertismente_legale  # nu e pe real


# ════════════════════════════════════════════════════════════
#   Normă indisponibilă / nepermisă → fără recomandare
# ════════════════════════════════════════════════════════════

def test_norma_indisponibila():
    # normă necunoscută (CAEN/județ neacoperit) → NU inventăm valoarea
    s = simulare_regim(90_000, 30_000, None, AN, "ridesharing", "SISTEM_REAL")
    assert s.norma is None
    assert s.recomandat is None
    assert s.diferenta == 0.0
    assert "NORMA_INDISPONIBILA" in s.avertismente_legale
    assert "SCHIMBARE_ANUL_URMATOR" not in s.avertismente_legale
    # real se calculează oricum (sursă unică)
    assert s.real["total_taxe"] == _real(90_000, 30_000).total_plata


def test_norma_doar_din_2026():
    # ridesharing în 2025 → gardian tranziție: normă nepermisă (deși valoarea există)
    s = simulare_regim(200_000, 20_000, NORMA, 2025, "ridesharing", "SISTEM_REAL")
    assert s.norma is None
    assert s.recomandat is None
    assert "NORMA_DOAR_DIN_2026" in s.avertismente_legale
    assert "NORMA_INDISPONIBILA" not in s.avertismente_legale   # valoarea normei E dată
    assert s.real["total_taxe"] == _real(200_000, 20_000, an=2025).total_plata


# ════════════════════════════════════════════════════════════
#   Plafon depășit — alături de comparație validă
# ════════════════════════════════════════════════════════════

def test_plafon_depasit_nu_anuleaza_norma():
    # venit brut 130.000 > plafon 126.038 → PLAFON_DEPASIT, dar normă tot calculabilă anul ăsta
    s = simulare_regim(130_000, 10_000, NORMA, AN, "ridesharing", "SISTEM_REAL")
    assert s.norma is not None                                 # comparație validă
    assert s.recomandat is not None
    assert "PLAFON_DEPASIT" in s.avertismente_legale


def test_sub_plafon_fara_avertisment():
    s = simulare_regim(40_000, 10_000, NORMA, AN, "ridesharing", "NORMA_VENIT")
    assert "PLAFON_DEPASIT" not in s.avertismente_legale       # 40k sub plafon


# ════════════════════════════════════════════════════════════
#   Structura returnată
# ════════════════════════════════════════════════════════════

def test_structura_real_si_norma():
    s = simulare_regim(90_000, 30_000, NORMA, AN, "ridesharing", "SISTEM_REAL")
    r = _real(90_000, 30_000)
    assert s.real == {"total_taxe": r.total_plata, "impozit": r.impozit,
                      "cas": r.cas, "cass": r.cass, "venit_net": r.venit_net}
    n = _norma()
    assert s.norma == {"total_taxe": n.total_plata, "impozit": n.impozit,
                       "cas": n.cas, "cass": n.cass, "venit_net": n.venit_net,
                       "norma": NORMA}
