"""
Calcul taxe PFA in sistem real pentru Declaratia Unica (D212).

Acopera impozitul pe venit (10%), CAS (pensie 25%) si CASS (sanatate 10%),
cu plafoanele raportate la salariul minim brut al anului.

Pentru anul de realizare a venitului 2025, Declaratia Unica se depune
pana la 25 mai 2026.

ATENTIE: valorile fiscale (salariu minim, plafoane, cote) se actualizeaza
anual. Parametrii pentru fiecare an sunt centralizati in PARAMETRI_FISCALI,
ca sa poata fi actualizati usor.
"""

# ============================================================
#                    PARAMETRI FISCALI PE AN
# ============================================================
# Pentru fiecare an: salariul minim brut + cotele + numarul de salarii
# minime care formeaza plafoanele. Plafoanele in lei se calculeaza din
# salariul minim, ca sa nu existe valori dublate care pot intra in conflict.

PARAMETRI_FISCALI = {
    2025: {
        "salariu_minim": 4050,
        "cota_impozit": 0.10,
        "cota_cas": 0.25,
        "cota_cass": 0.10,
        # praguri exprimate in numar de salarii minime
        "cas_prag_jos": 12,    # sub acest prag CAS e optional
        "cas_prag_sus": 24,    # peste acest prag baza CAS minima e 24 SMB
        "cass_prag_jos": 6,    # sub acest prag se datoreaza minim la 6 SMB
        "cass_prag_sus": 60,   # peste acest prag CASS se plafoneaza la 60 SMB
    },
    # 2026 este orientativ; salariul minim a fost majorat la 4.325 lei si
    # plafoanele se pot schimba. De reconfirmat la implementarea pentru 2026.
    2026: {
        "salariu_minim": 4325,
        "cota_impozit": 0.10,
        "cota_cas": 0.25,
        "cota_cass": 0.10,
        "cas_prag_jos": 12,
        "cas_prag_sus": 24,
        "cass_prag_jos": 6,
        "cass_prag_sus": 60,
    },
}


def _params(an: int) -> dict:
    if an not in PARAMETRI_FISCALI:
        ani = sorted(PARAMETRI_FISCALI.keys())
        an = ani[-1]
    return PARAMETRI_FISCALI[an]


def calcul_cass(venit_net: float, an: int = 2025,
                asigurat_salariat: bool = False) -> dict:
    """
    Contributia de asigurari sociale de sanatate (CASS), cota 10%.

    Reguli pentru sistem real:
      - venit net <= 0           -> nu se datoreaza (poate opta separat)
      - 0 < venit net < 6 SMB    -> se datoreaza la baza de 6 SMB
                                    (exceptie: asigurat ca salariat -> pe venit real)
      - 6 SMB <= venit <= 60 SMB -> 10% din venitul net real
      - venit net > 60 SMB       -> plafonat la 60 SMB
    """
    p = _params(an)
    sm = p["salariu_minim"]
    prag_jos = p["cass_prag_jos"] * sm
    prag_sus = p["cass_prag_sus"] * sm

    if venit_net <= 0:
        baza = 0.0
        nota = "Venit net zero sau pierdere - CASS nu se datoreaza."
    elif venit_net < prag_jos:
        if asigurat_salariat:
            baza = 0.0
            nota = "Sub 6 salarii minime, dar asigurat prin alta sursa (salariu/pensie) - CASS nu se datoreaza."
        else:
            baza = prag_jos
            nota = f"Sub 6 salarii minime - CASS la baza minima de {prag_jos:.0f} lei (6 SMB)."
    elif venit_net <= prag_sus:
        baza = venit_net
        nota = "CASS 10% din venitul net realizat."
    else:
        baza = prag_sus
        nota = f"Peste 60 salarii minime - CASS plafonat la {prag_sus:.0f} lei (60 SMB)."

    valoare = round(baza * p["cota_cass"], 0)
    return {"valoare": valoare, "baza": baza, "nota": nota}


def calcul_cas(venit_net: float, an: int = 2025,
               baza_aleasa: float = None, pensionar: bool = False) -> dict:
    """
    Contributia de asigurari sociale (CAS - pensie), cota 25%.

    Reguli pentru sistem real:
      - pensionar                  -> scutit
      - venit net < 12 SMB         -> optional (implicit 0)
      - 12 SMB <= venit < 24 SMB   -> baza minima 12 SMB
      - venit net >= 24 SMB        -> baza minima 24 SMB
    Contribuabilul poate alege o baza mai mare (baza_aleasa) - pensie mai mare.
    Implicit folosim baza minima aplicabila (contributie minima).
    """
    p = _params(an)
    sm = p["salariu_minim"]
    prag_jos = p["cas_prag_jos"] * sm
    prag_sus = p["cas_prag_sus"] * sm

    if pensionar:
        return {"valoare": 0.0, "baza": 0.0,
                "nota": "Pensionar - scutit de CAS."}

    if venit_net < prag_jos:
        baza_minima = 0.0
        nota = "Sub 12 salarii minime - CAS optional (implicit nu se datoreaza)."
    elif venit_net < prag_sus:
        baza_minima = prag_jos
        nota = f"Intre 12 si 24 salarii minime - baza CAS minima {prag_jos:.0f} lei (12 SMB)."
    else:
        baza_minima = prag_sus
        nota = f"Peste 24 salarii minime - baza CAS minima {prag_sus:.0f} lei (24 SMB)."

    baza = baza_minima
    if baza_aleasa is not None and baza_aleasa > baza_minima:
        baza = baza_aleasa
        nota += f" Baza aleasa: {baza_aleasa:.0f} lei."

    valoare = round(baza * p["cota_cas"], 0)
    return {"valoare": valoare, "baza": baza, "nota": nota}


def calcul_declaratie_unica(venit_brut: float, cheltuieli_deductibile: float,
                            an: int = 2025, baza_cas_aleasa: float = None,
                            asigurat_salariat: bool = False,
                            pensionar: bool = False) -> dict:
    """
    Calcul complet pentru Declaratia Unica (PFA sistem real).

    Pasi:
      1. venit net = venit brut incasat - cheltuieli deductibile platite
      2. CASS (10%), cu plafoane
      3. CAS (25%), cu baza minima sau aleasa
      4. baza impozabila = venit net - CAS - CASS
      5. impozit = 10% din baza impozabila
    """
    p = _params(an)
    venit_net = round(venit_brut - cheltuieli_deductibile, 2)

    cass = calcul_cass(venit_net, an=an, asigurat_salariat=asigurat_salariat)
    cas = calcul_cas(venit_net, an=an, baza_aleasa=baza_cas_aleasa, pensionar=pensionar)

    baza_impozabila = max(0.0, venit_net - cas["valoare"] - cass["valoare"])
    impozit = round(baza_impozabila * p["cota_impozit"], 0)

    total_taxe = cas["valoare"] + cass["valoare"] + impozit
    venit_dupa_taxe = round(venit_net - total_taxe, 2)
    rata_efectiva = round(total_taxe / venit_net * 100, 1) if venit_net > 0 else 0.0

    return {
        "an": an,
        "salariu_minim": p["salariu_minim"],
        "venit_brut": round(venit_brut, 2),
        "cheltuieli_deductibile": round(cheltuieli_deductibile, 2),
        "venit_net": venit_net,
        "cass": cass,
        "cas": cas,
        "baza_impozabila": round(baza_impozabila, 2),
        "impozit": impozit,
        "total_taxe": round(total_taxe, 2),
        "venit_dupa_taxe": venit_dupa_taxe,
        "rata_efectiva": rata_efectiva,
    }


def format_telegram(rez: dict) -> str:
    """Formateaza rezultatul pentru un mesaj Telegram (Markdown)."""
    linii = []
    linii.append(f"*Declaratia Unica {rez['an']} - estimare taxe*")
    linii.append("-----------------------------------")
    linii.append(f"Venit brut incasat: *{rez['venit_brut']:.2f}* lei")
    linii.append(f"Cheltuieli deductibile: *{rez['cheltuieli_deductibile']:.2f}* lei")
    linii.append(f"Venit net: *{rez['venit_net']:.2f}* lei")
    linii.append("")
    linii.append(f"CASS 10%: *{rez['cass']['valoare']:.0f}* lei")
    linii.append(f"  {rez['cass']['nota']}")
    linii.append(f"CAS 25%: *{rez['cas']['valoare']:.0f}* lei")
    linii.append(f"  {rez['cas']['nota']}")
    linii.append(f"Baza impozabila: {rez['baza_impozabila']:.2f} lei")
    linii.append(f"Impozit 10%: *{rez['impozit']:.0f}* lei")
    linii.append("")
    linii.append(f"TOTAL DE PLATA: *{rez['total_taxe']:.2f}* lei")
    linii.append(f"Venit dupa taxe: {rez['venit_dupa_taxe']:.2f} lei")
    if rez['venit_net'] <= 0:
        linii.append("Rata efectiva: nu se aplica (venit net zero sau pierdere)")
    elif rez['rata_efectiva'] > 100:
        linii.append("Rata efectiva: peste 100% - CASS minim obligatoriu "
                     "depaseste venitul net mic")
    else:
        linii.append(f"Rata efectiva de taxare: {rez['rata_efectiva']:.1f}%")
    linii.append("")
    linii.append("_Estimare orientativa. Baza CAS poate fi aleasa mai mare "
                 "pentru o pensie mai buna. Verificati cu un contabil inainte de depunere._")
    return "\n".join(linii)
