"""
Calcul taxe PFA in sistem real pentru Declaratia Unica (D212).

Acopera impozitul pe venit (10%), CAS (pensie 25%) si CASS (sanatate 10%),
cu plafoanele raportate la salariul minim brut al anului.

Pentru anul de realizare a venitului 2025, Declaratia Unica se depune
pana la 25 mai 2026.

ATENTIE: valorile fiscale (salariu minim, plafoane, cote) se actualizeaza
anual. Parametrii pentru fiecare an sunt centralizati in PARAMETRI_FISCALI,
ca sa poata fi actualizati usor.

CAS/CASS NU se mai calculeaza aici — sursa unica: app.domain.contributii.
Acest modul pastreaza doar impozitul + orchestrarea (calcul_declaratie_unica)
si formatarea Telegram. Estimarea e DOAR pentru afisare (flux /declaratie_unica),
NU produce declaratie depozabila.
"""

from app.domain import contributii

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
    # 2026: plafoanele PFA folosesc salariul minim de la 1 IANUARIE = 4050
    # (NU 4325 — acela e minimul salariati din iulie). Vezi app.domain.contributii.
    2026: {
        "salariu_minim": 4050,
        "cota_impozit": 0.10,
        "cota_cas": 0.25,
        "cota_cass": 0.10,
        "cas_prag_jos": 12,
        "cas_prag_sus": 24,
        "cass_prag_jos": 6,
        "cass_prag_sus": 72,   # Legea 141/2025: plafon CASS 60→72 SMB pt. venituri 2026+
    },
}


def _params(an: int) -> dict:
    if an not in PARAMETRI_FISCALI:
        ani = sorted(PARAMETRI_FISCALI.keys())
        an = ani[-1]
    return PARAMETRI_FISCALI[an]


def calcul_cass(venit_net: float, an: int = 2025,
                asigurat_salariat: bool = False) -> dict:
    """CASS (10%) — delegat la sursa unica app.domain.contributii."""
    return contributii.calcul_cass(venit_net, an, asigurat_salariat=asigurat_salariat)


def calcul_cas(venit_net: float, an: int = 2025,
               baza_aleasa: float = None, pensionar: bool = False) -> dict:
    """CAS (25%) — delegat la sursa unica app.domain.contributii."""
    return contributii.calcul_cas(venit_net, an,
                                  baza_aleasa=baza_aleasa, pensionar=pensionar)


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
