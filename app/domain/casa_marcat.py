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
            "În date ai curse plătite cash — iar numerarul primit direct de la "
            "pasager cere casă de marcat."
        )
    if declarat:
        return True, (
            "Ai declarat că iei numerar de la pasageri — iar banii cash direct "
            "de la client cer casă de marcat."
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
        "AMEF = Aparatul de Marcat Electronic Fiscal — adică, pe scurt, casa de marcat. "
        "Emite bon fiscal pentru banii primiți cash de la clienți și îi raportează automat la ANAF."
    ),
    "cand": (
        "Ai nevoie de ea când iei banii direct de la pasager — cash sau card pe un POS "
        "al tău, la finalul cursei. Plățile prin aplicație (card prin Bolt/Uber) nu intră: "
        "acolo banii vin de la platformă, nu direct de la client."
    ),
    "de_ce": (
        "Legea cere bon fiscal pentru orice sumă primită cash de la populație "
        "(OUG 28/1999 republicată; OUG 49/2019 art. 21 stabilește amenzile). Fără casă de marcat "
        "la încasări cash rișți amendă și chiar suspendarea activității."
    ),
    "cum": (
        "Bolt: poți dezactiva plata cash în aplicație — dacă accepți doar card prin app, "
        "nu-ți trebuie casă. Uber: permite mereu cash — dacă accepți curse cash, îți trebuie "
        "casă. Dacă iei numerar: cumperi o casă de marcat, o fiscalizezi la ANAF și emiți bon la "
        "fiecare cursă plătită cash."
    ),
}
