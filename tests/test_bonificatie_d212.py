"""
Fiscal #2 — LOCK pe baza bonificației D212 (OUG 8/2026, validă în 2026).

Bonificația de 3% se aplică DOAR pe impozitul pe venit, NU pe total (CAS/CASS
nu se reduc). Calculul e corect (d212_calc:132 — `impozit * COTA_BONIFICATIE`);
aceste teste BLOCHEAZĂ baza ca să prindă orice regresie viitoare care ar muta-o
pe `total_plata`. (Microcopy-ul condiției — plată integrală + termen 15 apr —
a fost completat separat, nu se testează aici.)
"""

from app.integrations.anaf.d212_calc import calculeaza_d212, COTA_BONIFICATIE


def test_bonificatie_DOAR_pe_impozit_nu_pe_total():
    # venit_net 60.000 → CAS ȘI CASS AMBELE > 0 (ca "nu pe total" să fie real)
    r = calculeaza_d212(venit_brut=90000, cheltuieli_deductibile=30000, an=2026)
    assert r.cas > 0 and r.cass > 0                                  # ambele nenule

    # BAZA CORECTĂ: 3% × impozit
    assert r.bonificatie == round(r.impozit * COTA_BONIFICATIE, 2)
    # NU pe total: 3% × total ar fi alt număr (mai mare, total > impozit)
    assert r.bonificatie != round(r.total_plata * COTA_BONIFICATIE, 2)
    assert round(r.total_plata * COTA_BONIFICATIE, 2) > r.bonificatie

    # total cu bonificație = total − bonificație; DOAR impozitul se reduce
    assert r.total_cu_bonificatie == round(r.total_plata - r.bonificatie, 2)
    assert round(r.total_plata - r.total_cu_bonificatie, 2) == r.bonificatie
    # reducerea e mică (doar pe impozit) — sub CAS și sub CASS
    assert r.bonificatie < r.cas and r.bonificatie < r.cass


def test_bonificatie_exact_30_la_impozit_1000():
    # caz controlat: venit_net 12.430 → CASS pe baza minimă (2.430), CAS=0,
    # venit_impozabil = 12.430 − 0 − 2.430 = 10.000 → impozit 1.000 → bonif 30.
    r = calculeaza_d212(venit_brut=14430, cheltuieli_deductibile=2000, an=2026)
    assert r.impozit == 1000.0
    assert r.bonificatie == 30.0
    assert r.bonificatie == round(r.impozit * COTA_BONIFICATIE, 2)
