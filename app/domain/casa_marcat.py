"""
Casă de marcat (AMEF) — LOGICA „ai nevoie de casă", modul PUR (fără I/O, fără DB).

AMEF (Aparat de Marcat Electronic Fiscal) e obligatorie când prestatorul încasează DIRECT
de la client — NUMERAR sau card la propriul POS, la livrarea serviciului (OUG 28/1999
republicată + OUG 49/2019 art. 21 — sancțiuni). Plățile prin aplicație (card via Bolt/Uber)
NU declanșează AMEF (banii vin de la platformă, nu direct de la pasager).

La ridesharing, semnalul practic = NUMERAR:
  - Bolt permite DEZACTIVAREA plății cash → fără numerar → fără casă.
  - Uber permite mereu cash → în practică ai nevoie de casă dacă accepți curse cash.

Hardware-ul (integrarea fizică a casei) e SEPARAT (research tehnic) — aici DOAR logica
semnalului „ai nevoie / nu ai nevoie".

⚠️ ORIENTATIV — AMEF are nuanțe (excepții, praguri). Semnalul e INFORMATIV + trimitere la
ghid, NU verdict categoric. De verificat cu un contabil / ANAF.
"""

from typing import Tuple


def necesita_amef(income_cash: float, declarat: bool = False) -> Tuple[bool, str]:
    """
    Semnal „ai nevoie de casă de marcat (AMEF)?" — sursă UNICĂ.

    Combină DATELE reale cu DECLARAȚIA, cu prioritate pe date (protejează userul de
    omisiune): dacă apar încasări în numerar chiar dacă a declarat „nu" → semnalăm oricum.

    Args:
        income_cash: total încasări în numerar (lei) din date (tranzacții CASH / curse cash).
        declarat: userul a declarat la onboarding că încasează numerar.

    Returns:
        (necesita: bool, motiv: str) — motivul explică DE CE (date vs declarație).

    >>> necesita_amef(150.0)[0]
    True
    >>> necesita_amef(0.0, declarat=True)[0]
    True
    >>> necesita_amef(0.0, declarat=False)
    (False, ...)
    """
    cash = float(income_cash or 0.0)
    if cash > 0:
        return True, (
            "Ai încasări în numerar în date (curse cash) — numerarul direct de la "
            "pasager declanșează obligația de casă de marcat."
        )
    if declarat:
        return True, (
            "Ai declarat că încasezi numerar de la pasageri — numerarul direct "
            "declanșează obligația de casă de marcat."
        )
    return False, (
        "Nu detectăm încasări în numerar — dacă toate plățile sunt prin aplicație "
        "(card Bolt/Uber), casa de marcat nu e necesară."
    )


# Conținut pedagogic AMEF (ce/când/de ce/cum) — sursă UNICĂ, surfațat în ghid + dashboard.
# Ton „profesor", ca restul ghidului de obligații.
AMEF_INFO = {
    "titlu": "Casă de marcat (AMEF)",
    "ce_e": (
        "AMEF = Aparatul de Marcat Electronic Fiscal (casa de marcat). Emite bon fiscal "
        "pentru încasările în numerar de la clienți și le raportează automat la ANAF."
    ),
    "cand": (
        "Obligatorie când încasezi DIRECT de la pasager — numerar (cash) sau card la un POS "
        "al tău, la finalul cursei. Plățile prin aplicație (card via Bolt/Uber) NU intră: "
        "acolo banii vin de la platformă, nu direct de la client."
    ),
    "de_ce": (
        "Legea cere bon fiscal pentru orice încasare în numerar de la populație "
        "(OUG 28/1999 republicată; OUG 49/2019 art. 21 stabilește sancțiunile). Fără casă "
        "la încasări cash → amendă + risc de suspendare a activității."
    ),
    "cum": (
        "Bolt: poți DEZACTIVA plata cash în aplicație → dacă accepți doar card prin app, nu "
        "ai nevoie de casă. Uber: permite mereu cash → dacă accepți curse cash, ai nevoie de "
        "casă. Dacă încasezi numerar: cumperi o AMEF, o fiscalizezi la ANAF și emiți bon la "
        "fiecare cursă plătită cash."
    ),
}
