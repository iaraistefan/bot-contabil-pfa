"""
Nomenclator NORMĂ DE VENIT + gardian de tranziție — PFA pe normă (CAEN 4933).

Modul PUR (fără I/O, fără DB). Două responsabilități:

1. NOMENCLATOR (valori OMF 1960/2025): norma anuală de venit, pe JUDEȚ × TIP
   LOCALITATE, pentru CAEN 4933 (transport rutier de pasageri — ridesharing).
   Sursa fiecărei valori e trasabilă (județ + decizia AJFP + an), ca matricea
   fiscală. Populat DOAR cu valori CONFIRMATE — niciodată inventate (o cifră la
   ANAF presupusă greșit = exact bug-ul fiscal #3). Județ lipsă → None → userul
   introduce manual valoarea din decizia județului lui (fallback ne-blocant).

2. GARDIAN DE TRANZIȚIE: CAEN 4933 e eligibil pentru normă DOAR de la venitul
   2026 (OMF 1960/2025, Art. III). Pentru 2025, ridesharing era sistem-real
   OBLIGATORIU. `norma_permisa(an, activity)` = sursa unică a regulii, consumată
   atât la selecție (onboarding/Setări), cât și la calcul (motorul D212).
"""

from datetime import date
from typing import Optional

from app.domain import proportionalizare
from app.domain import contributii

# Tipurile de localitate din deciziile AJFP (norma diferă pe nivel administrativ).
TIPURI_LOCALITATE = ("municipiu", "oras", "comuna")

# Anul de la care ridesharing (CAEN 4933) e eligibil pentru normă de venit.
AN_START_NORMA_RIDESHARING = 2026


# ============================================================
#   PLAFON NORMĂ DE VENIT — trecere OBLIGATORIE la sistem real (art. 69 CF)
# ============================================================
# Plafon de venit BRUT încasat (lei): peste el, din ANUL URMĂTOR impunerea e
# OBLIGATORIU în sistem real (nu mai poți rămâne pe normă). 25.000 EUR convertit la
# cursul mediu BNR al anului ANTERIOR. Structură PE AN (cursul se schimbă anual, ca
# nomenclatorul normei) — NU constantă universală. An lipsă → None (fără alertă, NU
# presupunem o cifră — filosofia PAS 1).
PLAFON_NORMA_VENIT = {
    2026: 126_038.0,   # 25.000 EUR × 5,0415 (curs mediu BNR 2025). Sursă: art. 69 Cod Fiscal.
}

# Activitățile pentru care se aplică gardianul de tranziție (normă doar din 2026).
_ACTIVITATI_TRANZITIE_2026 = {"ridesharing"}


# ============================================================
#   NOMENCLATOR NORMĂ ANUALĂ — CAEN 4933 (lei/an), per județ × tip localitate
# ============================================================
# Cheie județ = cod ANAF (uppercase). Valori CONFIRMATE din research; `_sursa`
# = trasabilitate. Județele neacoperite → fallback manual (vezi norma_anuala).
#
# ⚠️ NU adăuga valori neconfirmate. O normă greșită = impozit greșit la ANAF.
NORMA_VENIT_4933 = {
    2026: {
        "SJ": {
            "municipiu": 54_300.0,   # Zalău
            "oras": 51_300.0,
            "comuna": 48_600.0,
            "_sursa": "Decizia AJFP Sălaj 2026 (OMF 1960/2025)",
        },
        # BN (Bistrița-Năsăud — județul lui Stefan): valoare exactă din Decizia
        # AJFP BN 2026 — DE COMPLETAT când o avem confirmată. Până atunci → fallback
        # manual (userul o introduce din decizia județului). NU inventăm cifra.
        # Sibiu / Mureș: idem — se adaugă cu valorile exacte + sursă.
    },
}

# Aliasuri nume județ → cod, ca să acceptăm și `judet` salvat ca nume (din ANAF
# unele profile au „Bistrița", altele „BN"). Doar județele din nomenclator.
_JUDET_ALIAS = {
    "SALAJ": "SJ", "SĂLAJ": "SJ",
    "BISTRITA-NASAUD": "BN", "BISTRIȚA-NĂSĂUD": "BN", "BISTRITA": "BN", "BISTRIȚA": "BN",
}


def _normalize_judet(judet: Optional[str]) -> Optional[str]:
    """Normalizează `judet` (cod sau nume) la codul ANAF uppercase. None → None."""
    if not judet:
        return None
    j = judet.strip().upper()
    if not j:
        return None
    if len(j) <= 3:            # deja cod (SJ, BN, B, CJ…)
        return j
    return _JUDET_ALIAS.get(j, j)


def norma_anuala(
    judet: Optional[str],
    tip_localitate: Optional[str],
    an: int = AN_START_NORMA_RIDESHARING,
    caen: str = "4933",
) -> Optional[float]:
    """
    Norma anuală de venit (lei) pentru un județ + tip localitate, dat anul + CAEN.

    Returnează None dacă nu avem valoarea confirmată (județ/tip/an neacoperit) —
    apelantul cade pe valoarea introdusă manual de user (NU presupunem o cifră).

    >>> norma_anuala("SJ", "municipiu", 2026)
    54300.0
    >>> norma_anuala("SJ", "comuna", 2026)
    48600.0
    >>> norma_anuala("BN", "municipiu", 2026) is None
    True
    """
    if caen != "4933":
        return None
    cod = _normalize_judet(judet)
    tip = (tip_localitate or "").strip().lower()
    if not cod or tip not in TIPURI_LOCALITATE:
        return None
    val = NORMA_VENIT_4933.get(an, {}).get(cod, {}).get(tip)
    return float(val) if val is not None else None


def norma_permisa(an: int, activity_code: Optional[str]) -> bool:
    """
    Gardian de tranziție: e permisă NORMA DE VENIT pentru (an, activitate)?

    Regula OMF 1960/2025: ridesharing (CAEN 4933) e eligibil normă DOAR din 2026.
    Pentru 2025 → sistem real obligatoriu. Alte activități: neafectate (True).

    Sursă UNICĂ — folosită la selecție (onboarding) ȘI la calcul (motor D212).

    >>> norma_permisa(2025, "ridesharing")
    False
    >>> norma_permisa(2026, "ridesharing")
    True
    >>> norma_permisa(2025, "it_freelance")
    True
    """
    if activity_code in _ACTIVITATI_TRANZITIE_2026:
        return an >= AN_START_NORMA_RIDESHARING
    return True


def activitate_mixta_split_de_la(
    regim: Optional[str],
    are_activitate_neeligibila: Optional[bool],
    data_adaugare,
    an: int,
) -> Optional[date]:
    """
    Gardian ACTIVITATE MIXTĂ (PAS 4b) — sursă UNICĂ a regulii de split temporal.

    Regula OPANAF (formular D212, pct. 3.5.11): un contribuabil pe NORMĂ care își
    completează obiectul de activitate în cursul anului cu o activitate NEeligibilă
    pentru normă (neinclusă în nomenclator) → impunere în SISTEM REAL **de la data
    respectivă**. Venitul net anual = fracțiunea din normă (perioada pe normă, până
    la data adăugării) + venitul net real (perioada de după). NU retroactiv tot anul.

    Returnează DATA de la care impunerea trece pe sistem real (granița split-ului),
    sau None dacă split-ul NU se aplică:
      - regim ≠ NORMA_VENIT (pe real deja → fără split);
      - flag neactivat (nu a declarat activitate neeligibilă);
      - data lipsă / neparsabilă / în alt an (fără dată nu putem face split exact —
        apelantul afișează un avertisment „treci pe sistem real", fără cifră presupusă);
      - data = 1 ianuarie (real pe tot anul, nu există fracțiune de normă → nu e split).

    Variantă a gardianului de tranziție (`norma_permisa`): aceeași formă (predicat →
    decizie regim), dar întoarce o DATĂ (split), nu un bool.

    >>> activitate_mixta_split_de_la("NORMA_VENIT", True, "2026-09-01", 2026)
    datetime.date(2026, 9, 1)
    >>> activitate_mixta_split_de_la("SISTEM_REAL", True, "2026-09-01", 2026) is None
    True
    >>> activitate_mixta_split_de_la("NORMA_VENIT", False, "2026-09-01", 2026) is None
    True
    >>> activitate_mixta_split_de_la("NORMA_VENIT", True, None, 2026) is None
    True
    """
    if str(regim) != "NORMA_VENIT":
        return None
    if not are_activitate_neeligibila:
        return None
    d = proportionalizare.to_date(data_adaugare)
    if d is None or d.year != an:
        return None
    if (d.month, d.day) <= (1, 1):     # adăugare de la 1 ian → real tot anul, fără fracțiune normă
        return None
    return d


def plafon_norma_venit(an: int) -> Optional[float]:
    """
    Plafonul de venit BRUT (lei) peste care, din anul URMĂTOR, impunerea pe normă
    nu mai e permisă (sistem real obligatoriu, art. 69 Cod Fiscal). An necunoscut →
    None (fără cifră presupusă — cursul EUR se schimbă anual).
    """
    val = PLAFON_NORMA_VENIT.get(an)
    return float(val) if val is not None else None


def prag_norma_status(venit_brut: float, an: int) -> Optional[dict]:
    """
    Status față de plafonul de NORMĂ (venit BRUT încasat vs 25.000 EUR în lei).

    Aceeași formă ca `contributii.prag_cas_status` (status + utilized_pct +
    remaining_ron + threshold_ron + message), refolosind `contributii.prag_core`
    (DRY). Comparația e pe venitul BRUT (nu net — plafonul normei e pe brut încasat).

    status: OK (<80%) / APROAPE_PLAFON (≥80%) / DEPASIT_PLAFON (≥100%).
    Plafon necunoscut pe `an` → None (apelantul nu trimite alertă — fără cifră presupusă).
    """
    threshold = plafon_norma_venit(an)
    if threshold is None:
        return None
    core = contributii.prag_core(venit_brut, threshold)
    status = core["status"]
    pct = core["utilized_pct"]
    remaining = core["remaining_ron"]

    if status == "DEPASIT_PLAFON":
        message = (
            f"🔴 Ai depășit plafonul de normă de {threshold:.0f} RON venit brut "
            f"(ai {venit_brut:.0f} RON). Din anul viitor treci OBLIGATORIU la sistem "
            f"real (art. 69 Cod Fiscal)."
        )
    elif status == "APROAPE_PLAFON":
        message = (
            f"🟡 Te apropii de plafonul de normă: {pct:.0f}% "
            f"({venit_brut:.0f} / {threshold:.0f} RON venit brut). Dacă-l depășești "
            f"anul acesta, din anul viitor treci OBLIGATORIU la sistem real "
            f"(art. 69 Cod Fiscal). Mai ai ~{remaining:.0f} lei."
        )
    else:
        message = (
            f"✅ Sub plafonul de normă: {pct:.0f}% "
            f"({venit_brut:.0f} / {threshold:.0f} RON venit brut)."
        )

    return {**core, "message": message}
