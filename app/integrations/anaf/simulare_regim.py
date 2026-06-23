"""
Simulare regim fiscal — comparatie NORMA vs SISTEM REAL pentru acelasi user (A1).

Functie PURA (fara I/O, fara DB, fara UI). Orchestreaza motorul existent
`calculeaza_d212` (chemat de 2 ori, cate o data pe regim) + contextul legal din
`norma_venit` (gardian tranzitie + plafon). NU atinge motorul si NU formateaza
mesaje pentru user — intoarce DOAR date + coduri de avertisment. Formatarea
(mesaje lizibile) vine in stratul UI (A3).

Coduri de avertisment legal (`avertismente_legale`):
- NORMA_INDISPONIBILA    : norma_anuala necunoscuta (CAEN/judet neacoperit) — NU
                           inventam valoarea normei; doar real se calculeaza.
- NORMA_DOAR_DIN_2026    : activitatea nu e eligibila norma in anul cerut (gardian
                           tranzitie, ex. ridesharing inainte de 2026).
- PLAFON_DEPASIT         : venit brut peste plafonul de norma (126.038 in 2026) —
                           trecere OBLIGATORIE pe real anul URMATOR (nu optional).
                           Apare ALATURI de o comparatie valida (norma calculabila
                           anul asta, dar forteaza real anul viitor).
- REVENIRE_NORMA_2ANI    : recomandata norma, dar userul e pe real — revenirea la
                           norma e posibila doar dupa min. 2 ani fiscali pe real.
- SCHIMBARE_ANUL_URMATOR : recomandarea difera de regimul curent — schimbarea se
                           aplica de anul URMATOR prin Declaratia Unica (25 mai),
                           NU in cursul anului.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.integrations.anaf.d212_calc import calculeaza_d212, SALARIU_MINIM_2025
from app.domain import norma_venit


@dataclass
class SimulareRegim:
    """Rezultat structurat al comparatiei de regim (doar date + coduri, fara mesaje)."""
    real: Dict[str, float]                       # mereu prezent
    norma: Optional[Dict[str, float]]            # None daca norma indisponibila/nepermisa
    recomandat: Optional[str]                    # "SISTEM_REAL" / "NORMA_VENIT" / None
    diferenta: float                             # economia pe regimul recomandat (lei)
    avertismente_legale: List[str] = field(default_factory=list)


def _rezumat(r) -> Dict[str, float]:
    """Cifrele relevante dintr-un RezultatD212 (total_taxe = total_plata = CAS+CASS+impozit)."""
    return {
        "total_taxe": r.total_plata,
        "impozit": r.impozit,
        "cas": r.cas,
        "cass": r.cass,
        "venit_net": r.venit_net,
    }


def simulare_regim(
    venit_brut: float,
    cheltuieli: float,
    norma_anuala: Optional[float],
    an: int,
    activity_code: str,
    regim_curent: str,
    *,
    salariu_minim: int = SALARIU_MINIM_2025,
    pensionar: bool = False,
    asigurat_salariat: bool = False,
) -> SimulareRegim:
    """
    Compara impozitarea pe NORMA vs SISTEM REAL pentru aceleasi date, pentru a raspunde
    la „ce regim e mai avantajos?". Pur — cheama `calculeaza_d212` de doua ori.

    Args:
        venit_brut: venit brut incasat (YTD) — baza pentru real + comparatia cu plafonul.
        cheltuieli: cheltuieli deductibile (folosite DOAR pe sistem real).
        norma_anuala: valoarea normei (lei/an) pentru CAEN+judet; None daca necunoscuta.
        an: anul fiscal.
        activity_code: ex. "ridesharing" (pentru gardianul de tranzitie).
        regim_curent: regimul ACTUAL al userului ("NORMA_VENIT" / "SISTEM_REAL").
        salariu_minim/pensionar/asigurat_salariat: pasate identic catre motor.

    Returns:
        SimulareRegim — real (mereu), norma (sau None), recomandat, diferenta, avertismente.
    """
    avert: List[str] = []

    # --- SISTEM REAL — se calculeaza MEREU ---
    r_real = calculeaza_d212(
        venit_brut, cheltuieli, an=an, salariu_minim=salariu_minim,
        regim="SISTEM_REAL", pensionar=pensionar, asigurat_salariat=asigurat_salariat,
    )
    real = _rezumat(r_real)

    # --- NORMA — doar daca avem valoarea SI e permisa in anul cerut ---
    norma_rez: Optional[Dict[str, float]] = None
    if norma_anuala is None or float(norma_anuala) <= 0:
        avert.append("NORMA_INDISPONIBILA")           # nu inventam cifra
    elif not norma_venit.norma_permisa(an, activity_code):
        avert.append("NORMA_DOAR_DIN_2026")           # gardian tranzitie
    else:
        r_norma = calculeaza_d212(
            0.0, 0.0, an=an, salariu_minim=salariu_minim,
            regim="NORMA_VENIT", norma_anuala=float(norma_anuala),
            pensionar=pensionar, asigurat_salariat=asigurat_salariat,
        )
        norma_rez = {**_rezumat(r_norma), "norma": round(float(norma_anuala), 2)}

    # --- Recomandare + diferenta + context legal (doar cand exista AMBELE regimuri) ---
    recomandat: Optional[str] = None
    diferenta = 0.0
    if norma_rez is not None:
        recomandat = ("NORMA_VENIT" if norma_rez["total_taxe"] < real["total_taxe"]
                      else "SISTEM_REAL")
        diferenta = round(abs(real["total_taxe"] - norma_rez["total_taxe"]), 2)

        # PLAFON_DEPASIT — norma calculabila anul asta, dar peste plafon → real obligatoriu
        # anul URMATOR. Nu anuleaza comparatia, doar avertizeaza.
        st = norma_venit.prag_norma_status(venit_brut, an)
        if st is not None and st["status"] == "DEPASIT_PLAFON":
            avert.append("PLAFON_DEPASIT")

        # REVENIRE_NORMA_2ANI — recomandata norma, dar userul e pe real (revenire ≥ 2 ani).
        if recomandat == "NORMA_VENIT" and str(regim_curent) == "SISTEM_REAL":
            avert.append("REVENIRE_NORMA_2ANI")

        # SCHIMBARE_ANUL_URMATOR — recomandarea difera de regimul curent (se aplica de
        # anul viitor prin D212, NU in cursul anului).
        if recomandat != str(regim_curent):
            avert.append("SCHIMBARE_ANUL_URMATOR")

    return SimulareRegim(
        real=real,
        norma=norma_rez,
        recomandat=recomandat,
        diferenta=diferenta,
        avertismente_legale=avert,
    )
