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
                                    exceptie asigurat_salariat (salariat/pensionar):
                                    10% pe VENITUL NET REAL (NU urca la 6 SMB, NU 0)
    6 SMB <= venit net <= cass_sus SMB -> 10% pe venit net real
    venit net > cass_sus SMB     -> plafon cass_sus SMB
                                    (cass_sus = 60 pt. 2025, 72 pt. 2026+ — Legea 141/2025)

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
        "cass_sus": 60,          # venituri 2025 -> CASS plafonat la 60 SMB = 243.000
    },
    2026: {
        "salariu_minim": 4050,   # ⚠️ 4050, NU 4325 (vezi nota din docstring)
        "cota_cas": 25,
        "cota_cass": 10,
        "cas_jos": 12,
        "cas_sus": 24,
        "cass_jos": 6,
        # Legea 141/2025: plafonul superior CASS urca 60->72 SMB DOAR pentru
        # veniturile realizate incepand cu 01.01.2026 (D212 depusa in 2027).
        # 72 × 4050 = 291.600 baza -> CASS max 29.160. Pentru 2025 ramane 60 (vezi sus).
        "cass_sus": 72,
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


def plafon_cas_jos(an: int, salariu_minim: int = None) -> float:
    """
    Plafonul CAS INFERIOR in lei (12 SMB) — pragul sub care CAS e optional si baza
    minima cand devine obligatoriu. Expus ca sursa unica pentru proportionalizarea
    mid-an (d212_calc recalculeaza acest plafon × luni/12 la incepere de activitate).
    """
    p = _params(an)
    sm = salariu_minim if salariu_minim is not None else p["salariu_minim"]
    return float(p["cas_jos"] * sm)


# ============================================================
#                       CAS (pensie 25%)
# ============================================================

def calcul_cas(venit_net: float, an: int, *,
               baza_aleasa: float = None,
               pensionar: bool = False,
               salariu_minim: int = None,
               plafon_recalculat: float = None) -> dict:
    """
    CAS (contributia la pensie), cota 25%, pentru PFA sistem real.

    Vezi regulile in docstring-ul modulului.

    Args:
        salariu_minim: override optional al SMB pe an (default: valoarea din
            PARAMETRI_CONTRIBUTII). Folosit de d212_calc pentru compatibilitate
            cu apeluri care pasau explicit salariul minim.
        plafon_recalculat: la INCEPERE de activitate mid-an, plafonul CAS de 12 SMB
            se recalculeaza proportional (12 SMB × luni/12, sursa ANAF Cluj). Cand e
            setat, INLOCUIESTE logica standard pe doua trepte (12/24 SMB): venit ≤
            plafon recalculat → CAS 0; peste → baza CAS = plafonul recalculat. None
            (default) → comportament standard neschimbat (regresie 0).

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

    if plafon_recalculat is not None:
        # INCEPERE mid-an: plafonul de 12 SMB e prorata-recalculat (ANAF Cluj,
        # „(plafon/12) × nr luni"). Treapta de 24 SMB NU se aplica la incepere —
        # baza, cand venitul depaseste plafonul, ESTE plafonul recalculat.
        prag = float(plafon_recalculat)
        if venit_net <= prag:
            return {"valoare": 0.0, "baza": 0.0, "cota_pct": cota,
                    "aplicabil": False,
                    "nota": (f"Incepere activitate mid-an: venit net sub plafonul CAS "
                             f"recalculat proportional ({prag:.0f} lei = 12 SMB × luni/12) "
                             f"— CAS optional (implicit 0).")}
        baza = prag
        if baza_aleasa is not None and baza_aleasa > baza:
            baza = float(baza_aleasa)
        valoare = round(baza * cota / 100, 2)
        return {"valoare": valoare, "baza": baza, "cota_pct": cota,
                "aplicabil": True,
                "nota": (f"Incepere activitate mid-an: baza CAS = plafonul recalculat "
                         f"proportional ({prag:.0f} lei = 12 SMB × luni/12).")}

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
    MINIMA 6 SMB (nu 0) pentru NEASIGURATI; pentru asigurati prin alta sursa
    (salariat/pensionar) = 10% pe venitul net REAL (nu urca la 6 SMB, nu 0).

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
            # CORECTIE (varianta b): asigurat prin alta sursa (salariat SAU pensionar)
            # NU urca la baza minima de 6 SMB — plateste 10% pe VENITUL NET REAL (nu 0,
            # nu 2.430). Confirmare numerica: net 13.950 -> CASS 1.395 (= 10% × 13.950).
            # Regula PFA difera de veniturile pasive: podeaua de 6 SMB se aplica DOAR
            # neasiguratilor altfel; cei deja asigurati platesc pe net real efectiv.
            # ⚠️ Zona "CASS asigurat sub prag" — surse secundare convergente (ContApp /
            # declaratie-unica.ro / Red Moonlight), NU text primar Cod Fiscal. De
            # RE-VALIDAT cu un contabil CECCAR daca apare ambiguitate.
            baza = float(venit_net)
            nota = (f"Sub {p['cass_jos']} salarii minime, dar asigurat prin alta sursa "
                    f"(salariu/pensie) — CASS 10% pe venitul net real (fara urcare la "
                    f"baza minima de {p['cass_jos']} SMB).")
        else:
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


# ============================================================
#           PRAGURI — STATUS pentru alerte „aproape de plafon"
# ============================================================

def prag_core(value: float, threshold: float) -> dict:
    """
    Partea NUMERICĂ comună a tuturor statusurilor de prag (CAS 12, CAS 24,
    CASS 60, plafon normă): status + utilized_pct + remaining_ron + threshold_ron.

    PUBLIC (DRY) — refolosit și de `norma_venit.prag_norma_status` (plafonul de
    normă, PAS trackere). Mesajul NU se construiește aici — îl adaugă fiecare funcție
    publică, pentru că semantica diferă (12 = CAS obligatoriu, 24 = baza se dublează
    „rău", 60 = CASS plafonat „bine", normă = trecere la sistem real). Matematica e o
    singură dată; mesajele, separate. status: OK (<80%) / APROAPE_PLAFON (≥80%) /
    DEPASIT_PLAFON (≥100%).
    """
    utilized_pct = (value / threshold * 100) if threshold else 0.0
    remaining = max(0.0, round(threshold - value, 2))
    if value >= threshold:
        status = "DEPASIT_PLAFON"
    elif utilized_pct >= 80:
        status = "APROAPE_PLAFON"
    else:
        status = "OK"
    return {
        "status": status,
        "threshold_ron": float(threshold),
        "utilized_pct": utilized_pct,
        "remaining_ron": remaining,
    }


def prag_cas_status(venit_net: float, an: int) -> dict:
    """
    Status față de pragul CAS de 12 SMB (peste care CAS devine OBLIGATORIU).
    Aceeași formă ca FiscalProfile.vat_threshold_status (consecvent), + remaining.

    threshold = 12 SMB; status: OK (<80%) / APROAPE_PLAFON (≥80%) /
    DEPASIT_PLAFON (≥100%). remaining_ron = cât a mai rămas până la prag.
    Toate cifrele din sursa unică (PARAMETRI_CONTRIBUTII).
    """
    p = _params(an)
    sm = p["salariu_minim"]
    threshold = float(p["cas_jos"] * sm)                 # 12 × 4050 = 48.600
    cas_obligatoriu = round(threshold * p["cota_cas"] / 100, 2)  # 12.150 la 4050
    core = prag_core(venit_net, threshold)
    status = core["status"]
    utilized_pct = core["utilized_pct"]
    remaining = core["remaining_ron"]

    if status == "DEPASIT_PLAFON":
        message = (
            f"🔴 Ai depășit pragul de {threshold:.0f} RON "
            f"({p['cas_jos']} salarii minime). CAS devine obligatoriu "
            f"(~{cas_obligatoriu:.0f} lei/an)."
        )
    elif status == "APROAPE_PLAFON":
        message = (
            f"🟡 Aproape de pragul CAS: {utilized_pct:.0f}% "
            f"({venit_net:.0f} / {threshold:.0f} RON). Mai ai ~{remaining:.0f} lei "
            f"până la {threshold:.0f} → CAS obligatoriu (~{cas_obligatoriu:.0f} lei/an)."
        )
    else:
        message = (
            f"✅ Sub pragul CAS: {utilized_pct:.0f}% "
            f"({venit_net:.0f} / {threshold:.0f} RON)."
        )

    return {**core, "message": message}


def prag_cas24_status(venit_net: float, an: int) -> dict:
    """
    Status față de pragul CAS de 24 SMB (peste care BAZA CAS se DUBLEAZĂ).

    Sub 24 SMB baza CAS = 12 SMB; la/peste 24 SMB baza = 24 SMB → CAS ~dublu.
    Eveniment fiscal DISTINCT de pragul de 12 SMB (în alerte sunt independente:
    12 = CAS devine obligatoriu; 24 = baza se dublează). Ton „rău" (plătești mai
    mult). Toate cifrele din sursa unică (PARAMETRI_CONTRIBUTII).
    """
    p = _params(an)
    sm = p["salariu_minim"]
    threshold = float(p["cas_sus"] * sm)                       # 24 × 4050 = 97.200
    cas_jos_val = round(p["cas_jos"] * sm * p["cota_cas"] / 100, 2)   # ~12.150
    cas_sus_val = round(threshold * p["cota_cas"] / 100, 2)          # ~24.300
    core = prag_core(venit_net, threshold)
    status = core["status"]
    utilized_pct = core["utilized_pct"]
    remaining = core["remaining_ron"]

    if status == "DEPASIT_PLAFON":
        message = (
            f"🔴 Ai depășit pragul de {threshold:.0f} RON "
            f"({p['cas_sus']} salarii minime). Baza CAS se DUBLEAZĂ: "
            f"CAS ~{cas_sus_val:.0f} lei/an (față de ~{cas_jos_val:.0f} la pragul minim)."
        )
    elif status == "APROAPE_PLAFON":
        message = (
            f"🟡 Aproape de pragul CAS de {p['cas_sus']} salarii minime: "
            f"{utilized_pct:.0f}% ({venit_net:.0f} / {threshold:.0f} RON). Mai ai "
            f"~{remaining:.0f} lei până când baza CAS se dublează (~{cas_sus_val:.0f} lei/an)."
        )
    else:
        message = (
            f"✅ Sub pragul CAS de {p['cas_sus']} salarii minime: {utilized_pct:.0f}% "
            f"({venit_net:.0f} / {threshold:.0f} RON)."
        )

    return {**core, "message": message}


def prag_cass6_status(venit_net: float, an: int) -> dict:
    """
    Status față de PODEAUA CASS de 6 SMB (sub care CASS se calculează pe baza
    MINIMĂ 6 SMB, NU pe venitul real).

    Relevant pentru venituri MICI: sub 6 SMB plătești CASS pe 6 SMB (24.300 ×
    10% = 2.430) chiar dacă ai câștigat mai puțin — bara arată „de ce" plătești
    minimul. La/peste 6 SMB, CASS = 10% pe venitul net real. Ton informativ.
    Toate cifrele din sursa unică (PARAMETRI_CONTRIBUTII).
    """
    p = _params(an)
    sm = p["salariu_minim"]
    threshold = float(p["cass_jos"] * sm)                  # 6 × 4050 = 24.300
    cass_min = round(threshold * p["cota_cass"] / 100, 2)  # ~2.430
    core = prag_core(venit_net, threshold)
    status = core["status"]
    utilized_pct = core["utilized_pct"]

    if status == "DEPASIT_PLAFON":
        message = (
            f"✅ Peste podeaua CASS de {p['cass_jos']} salarii minime "
            f"({threshold:.0f} RON). CASS se calculează pe venitul net real."
        )
    elif status == "APROAPE_PLAFON":
        message = (
            f"ℹ️ Aproape de podeaua CASS de {p['cass_jos']} salarii minime: "
            f"{utilized_pct:.0f}% ({venit_net:.0f} / {threshold:.0f} RON). Sub "
            f"{threshold:.0f} RON, CASS se calculează pe baza minimă (~{cass_min:.0f} lei/an)."
        )
    else:
        message = (
            f"ℹ️ Sub podeaua CASS de {p['cass_jos']} salarii minime: {utilized_pct:.0f}% "
            f"({venit_net:.0f} / {threshold:.0f} RON). CASS se plătește pe baza minimă "
            f"(~{cass_min:.0f} lei/an), nu pe venitul tău."
        )

    return {**core, "message": message}


def prag_cass60_status(venit_net: float, an: int) -> dict:
    """
    Status față de plafonul SUPERIOR CASS (peste care CASS se PLAFONEAZĂ).

    NUME ISTORIC: „60” reflectă plafonul din 2025; valoarea depinde de an —
    60 SMB pentru venituri 2025 (243.000), 72 SMB pentru venituri 2026+
    (291.600, Legea 141/2025). Funcția citește mereu PARAMETRI_CONTRIBUTII[an],
    deci e corectă pe orice an; doar identificatorul a rămas pe vechea valoare.

    La/peste plafon, CASS nu mai crește proporțional — rămâne la cass_sus × SMB × 10%.
    Informație neutru-favorabilă: NU e o felicitare (CASS rămâne de plată
    integral), doar nu mai crește. Ton ℹ️. Toate cifrele din sursa unică.
    """
    p = _params(an)
    sm = p["salariu_minim"]
    threshold = float(p["cass_sus"] * sm)                  # 2025: 60×4050=243.000 | 2026: 72×4050=291.600
    cass_max = round(threshold * p["cota_cass"] / 100, 2)  # 2025: ~24.300 | 2026: ~29.160
    core = prag_core(venit_net, threshold)
    status = core["status"]
    utilized_pct = core["utilized_pct"]

    if status == "DEPASIT_PLAFON":
        message = (
            f"ℹ️ Ai atins plafonul CASS ({p['cass_sus']} salarii minime, "
            f"{threshold:.0f} RON). CASS-ul tău e plafonat la ~{cass_max:.0f} lei/an "
            f"— peste acest venit NU mai crește (rămâne de plată integral)."
        )
    elif status == "APROAPE_PLAFON":
        message = (
            f"ℹ️ Aproape de plafonul CASS de {p['cass_sus']} salarii minime: "
            f"{utilized_pct:.0f}% ({venit_net:.0f} / {threshold:.0f} RON). Peste "
            f"{threshold:.0f} RON CASS se plafonează la ~{cass_max:.0f} lei/an (nu mai crește)."
        )
    else:
        message = (
            f"✅ Sub plafonul CASS de {p['cass_sus']} salarii minime: {utilized_pct:.0f}% "
            f"({venit_net:.0f} / {threshold:.0f} RON)."
        )

    return {**core, "message": message}
