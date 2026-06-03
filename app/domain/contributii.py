"""
Sursa UNICA de adevar pentru contributiile sociale PFA: CAS si CASS.

Modul PUR — fara I/O, fara DB, fara imports din aplicatie. Toate motoarele de
calcul (tax_calculator, d212_calc, declaratie_unica) deleaga aici, ca sa nu mai
existe logica duplicata care poate diverge.

CONTEXT LEGAL (PFA sistem real):
- CAS (pensie) = 25%; CASS (sanatate) = 10%.
- Plafoanele anuale se raporteaza la SALARIUL MINIM BRUT de la 1 IANUARIE al
  anului, valoare FIXA pe tot anul pentru plafoanele PFA.

⚠️ SALARIU MINIM PENTRU PLAFOANE PFA 2026 = 4050 lei, NU 4325!
   4325 e minimul brut pentru SALARIATI introdus din iulie 2025; plafoanele
   anuale CAS/CASS ale PFA folosesc valoarea de la 1 ianuarie (4050).
   A nu se "corecta" la 4325 — ar supraestima contributiile.

REGULI:
- CAS (25%):
    venit net < 12 SMB           -> 0 (optional; poate plati voluntar)
    12 SMB <= venit net < 24 SMB -> baza 12 SMB
    venit net >= 24 SMB          -> baza 24 SMB
    pensionar                    -> scutit (0)
    baza_aleasa > baza minima    -> contribuabilul poate alege o baza mai mare
- CASS (10%):
    venit net <= 0               -> 0
    0 < venit net < 6 SMB        -> baza MINIMA 6 SMB (NU 0!)
                                    exceptie: asigurat_salariat -> 0
    6 SMB <= venit net <= 60 SMB -> 10% pe venit net real
    venit net > 60 SMB           -> plafon 60 SMB

Rotunjire: 2 zecimale (pastreaza D212 bit-identic cu d212_calc actual).
Retur: dict {"valoare", "baza", "cota_pct", "nota", "aplicabil"}.
"""

# ============================================================
#                 PARAMETRI FISCALI PE AN
# ============================================================
# salariu_minim = valoarea de la 1 IANUARIE (fixa pe an, pentru plafoane PFA).
# Pragurile sunt in numar de salarii minime; valorile in lei se deriva din
# salariu_minim ca sa nu existe cifre dublate care pot intra in conflict.

PARAMETRI_CONTRIBUTII = {
    2025: {
        "salariu_minim": 4050,   # HG 1506/2024
        "cota_cas": 25,
        "cota_cass": 10,
        "cas_jos": 12,           # sub 12 SMB -> CAS optional
        "cas_sus": 24,           # >= 24 SMB -> baza CAS = 24 SMB
        "cass_jos": 6,           # sub 6 SMB -> baza CASS minima = 6 SMB
        "cass_sus": 60,          # > 60 SMB -> CASS plafonat la 60 SMB
    },
    2026: {
        "salariu_minim": 4050,   # ⚠️ 4050, NU 4325 (vezi nota din docstring)
        "cota_cas": 25,
        "cota_cass": 10,
        "cas_jos": 12,
        "cas_sus": 24,
        "cass_jos": 6,
        "cass_sus": 60,
    },
}


def _params(an: int) -> dict:
    """Parametrii anului; fallback la ultimul an cunoscut daca an lipseste."""
    if an not in PARAMETRI_CONTRIBUTII:
        an = sorted(PARAMETRI_CONTRIBUTII.keys())[-1]
    return PARAMETRI_CONTRIBUTII[an]


def salariu_minim(an: int) -> int:
    """Salariul minim brut de plafoane pentru anul dat (1 ianuarie)."""
    return _params(an)["salariu_minim"]


# ============================================================
#                       CAS (pensie 25%)
# ============================================================

def calcul_cas(venit_net: float, an: int, *,
               baza_aleasa: float = None,
               pensionar: bool = False,
               salariu_minim: int = None) -> dict:
    """
    CAS (contributia la pensie), cota 25%, pentru PFA sistem real.

    Vezi regulile in docstring-ul modulului.

    Args:
        salariu_minim: override optional al SMB pe an (default: valoarea din
            PARAMETRI_CONTRIBUTII). Folosit de d212_calc pentru compatibilitate
            cu apeluri care pasau explicit salariul minim.

    Returns:
        dict cu: valoare, baza, cota_pct, nota, aplicabil.
    """
    p = _params(an)
    sm = salariu_minim if salariu_minim is not None else p["salariu_minim"]
    cota = p["cota_cas"]
    prag_jos = p["cas_jos"] * sm
    prag_sus = p["cas_sus"] * sm

    if pensionar:
        return {"valoare": 0.0, "baza": 0.0, "cota_pct": cota,
                "aplicabil": False, "nota": "Pensionar — scutit de CAS."}

    if venit_net < prag_jos:
        return {"valoare": 0.0, "baza": 0.0, "cota_pct": cota,
                "aplicabil": False,
                "nota": (f"Venit net sub {p['cas_jos']} salarii minime "
                         f"({prag_jos:.0f} lei) — CAS optional (implicit 0).")}

    if venit_net < prag_sus:
        baza_minima = float(prag_jos)
        nota = (f"Venit net intre {p['cas_jos']} si {p['cas_sus']} salarii "
                f"minime — baza CAS {baza_minima:.0f} lei ({p['cas_jos']} SMB).")
    else:
        baza_minima = float(prag_sus)
        nota = (f"Venit net peste {p['cas_sus']} salarii minime — baza CAS "
                f"plafonata {baza_minima:.0f} lei ({p['cas_sus']} SMB).")

    baza = baza_minima
    if baza_aleasa is not None and baza_aleasa > baza_minima:
        baza = float(baza_aleasa)
        nota += f" Baza aleasa: {baza:.0f} lei."

    valoare = round(baza * cota / 100, 2)
    return {"valoare": valoare, "baza": baza, "cota_pct": cota,
            "aplicabil": True, "nota": nota}


# ============================================================
#                       CASS (sanatate 10%)
# ============================================================

def calcul_cass(venit_net: float, an: int, *,
                asigurat_salariat: bool = False,
                salariu_minim: int = None) -> dict:
    """
    CASS (contributia la sanatate), cota 10%, pentru PFA sistem real.

    Vezi regulile in docstring-ul modulului. Punct critic: sub 6 SMB baza e
    MINIMA 6 SMB (nu 0), exceptand cazul asigurat prin alta sursa (salariu).

    Args:
        salariu_minim: override optional al SMB pe an (vezi calcul_cas).

    Returns:
        dict cu: valoare, baza, cota_pct, nota, aplicabil.
    """
    p = _params(an)
    sm = salariu_minim if salariu_minim is not None else p["salariu_minim"]
    cota = p["cota_cass"]
    prag_jos = p["cass_jos"] * sm
    prag_sus = p["cass_sus"] * sm

    if venit_net <= 0:
        return {"valoare": 0.0, "baza": 0.0, "cota_pct": cota,
                "aplicabil": False,
                "nota": "Venit net zero sau pierdere — CASS nu se datoreaza."}

    if venit_net < prag_jos:
        if asigurat_salariat:
            return {"valoare": 0.0, "baza": 0.0, "cota_pct": cota,
                    "aplicabil": False,
                    "nota": (f"Sub {p['cass_jos']} salarii minime, dar asigurat "
                             f"prin alta sursa (salariu/pensie) — CASS 0.")}
        baza = float(prag_jos)
        nota = (f"Venit net sub {p['cass_jos']} salarii minime — baza CASS "
                f"minima {baza:.0f} lei ({p['cass_jos']} SMB).")
    elif venit_net <= prag_sus:
        baza = float(venit_net)
        nota = "CASS 10% din venitul net realizat."
    else:
        baza = float(prag_sus)
        nota = (f"Venit net peste {p['cass_sus']} salarii minime — CASS "
                f"plafonat la {baza:.0f} lei ({p['cass_sus']} SMB).")

    valoare = round(baza * cota / 100, 2)
    return {"valoare": valoare, "baza": baza, "cota_pct": cota,
            "aplicabil": True, "nota": nota}
