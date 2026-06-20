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

from typing import Optional

# Tipurile de localitate din deciziile AJFP (norma diferă pe nivel administrativ).
TIPURI_LOCALITATE = ("municipiu", "oras", "comuna")

# Anul de la care ridesharing (CAEN 4933) e eligibil pentru normă de venit.
AN_START_NORMA_RIDESHARING = 2026

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
