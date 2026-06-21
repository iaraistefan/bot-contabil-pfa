"""
Proportionalizare mid-an pentru D212 — sursa UNICA a matematicii pro-rata.

Modul PUR (fara I/O, fara DB, fara import din aplicatie). Se cableaza in d212_calc.

CONTEXT LEGAL (sursa primara: ANAF Cluj „Completarea D212", 22 apr 2026; confirmat
pentru veniturile 2026):

- NORMA mid-an: norma se prorata pe ZILE / 365 (denominator FIX 365, NU anul
  calendaristic real). Confirmat ANAF/SOLO: 48.600 × 122 / 365 = 16.244.

- CAS la INCEPERE mid-an: plafonul inferior (12 SMB) se RECALCULEAZA proportional
  = 12 SMB × (luni_activitate / 12). Compari venitul net cu plafonul RECALCULAT:
  venit ≤ plafon recalculat → CAS 0; peste → CAS pe baza recalculata. Formula
  ANAF: „(plafon / 12 luni) × Numar luni". Prima luna = luna de inceput (luna
  depunerii D212).
  NU exista treapta distincta 12 vs 24 SMB la mid-an: plafonul recalculat pe 24
  SMB ar da aceeasi suma (36.000/12 = 72.000/24 = salariu_minim lunar; × aceleasi
  luni → identic). Confirmat de exemplul oficial portalpfa (start august 2023, 5
  luni → 15.000 pe ambele trepte). Deci baza recalculata = salariu_minim × luni.

- CAS la INCETARE mid-an: AMBIGUU legal — ANAF a recunoscut ca normele nu-s
  actualizate pentru acest caz. NU fortam o formula: motorul DOAR semnaleaza
  „verifica recalcularea CAS la incetare cu un contabil". Norma TOT se prorata
  (pe zilele de activitate pana la sfarsit).

- CASS: praguri INTREGI (neschimbate) — NU se proportionalizeaza aici.

⚠️ PRUDENTA CECCAR — SURSE CONTRADICTORII (onestitate maxima pe aceasta zona):
   Recalcularea CAS la INCEPERE mid-an e un teren cu surse oficiale in TENSIUNE:
     - Legea 296/2023 a ELIMINAT recalcularea CAS la incepere mid-an incepand cu 2024;
     - documentul ANAF Cluj „Completarea D212" (22 apr 2026) o descrie ca ACTIVA pentru
       venitul 2026.
   Implementam recalcularea (sursa ANAF 2026, cea mai recenta, o sustine), DAR e de
   RE-VALIDAT cu un contabil CECCAR inainte de a te baza pe recalcularea CAS mid-an.
   Pentru INCETARE nu inventam o formula (sursa primara lipseste) — doar semnalam.
   A presupune o cifra fara temei e exact bug-ul fiscal pe care il evitam sistematic.
"""

from datetime import date, datetime, timedelta

# Denominatorul FIX pentru prorata normei (confirmat ANAF/SOLO). NU folosim numarul
# real de zile al anului (365/366) — ar varia pe ani bisecti si ar diverge de cifra
# oficiala. 48.600 × 122 / 365 = 16.244.
ZILE_AN = 365
LUNI_AN = 12


def to_date(d):
    """
    Normalizeaza intrarea la `date` | None. Accepta `date`, `datetime` sau string
    ISO „YYYY-MM-DD" (profilul expune ISO; testele paseaza obiecte `date`). Orice
    valoare neparsabila → None (tratat ca „necompletat", fara cifra presupusa).

    Public: refolosit de gardianul activitatii mixte (PAS 4b) ca parser comun de date.
    """
    if d is None:
        return None
    if isinstance(d, datetime):     # datetime e subclasa de date → luam doar data
        return d.date()
    if isinstance(d, date):
        return d
    try:
        return date.fromisoformat(str(d)[:10])
    except (ValueError, TypeError):
        return None


def _margini_an(inceput, sfarsit, an):
    """
    Marginile EFECTIVE ale activitatii in interiorul anului `an` (inclusiv ambele
    capete). Datele din afara anului sunt clampate la 1 ianuarie / 31 decembrie.
    """
    jan1 = date(an, 1, 1)
    dec31 = date(an, 12, 31)
    i = to_date(inceput)
    s = to_date(sfarsit)
    start = i if (i is not None and i > jan1) else jan1
    end = s if (s is not None and s < dec31) else dec31
    return start, end


# ============================================================
#                       PREDICATE
# ============================================================

def este_incepere_mid_an(inceput, an) -> bool:
    """
    Activitatea a INCEPUT in cursul anului `an` (dupa 1 ianuarie)?

    Daca a inceput intr-un an anterior → an intreg pentru `an` (False). Sursa
    unica pentru decizia „aplic recalcularea CAS la incepere".
    """
    i = to_date(inceput)
    return i is not None and i.year == an and (i.month, i.day) > (1, 1)


def este_incetare(sfarsit, an) -> bool:
    """
    Activitatea a INCETAT in cursul anului `an` (inainte de 31 decembrie)?

    Sursa unica pentru semnalul de prudenta „verifica recalcularea CAS la incetare".
    """
    s = to_date(sfarsit)
    return s is not None and s.year == an and (s.month, s.day) < (12, 31)


def este_partial(inceput, sfarsit, an) -> bool:
    """Anul `an` e acoperit DOAR partial (incepere SAU incetare mid-an)?"""
    return este_incepere_mid_an(inceput, an) or este_incetare(sfarsit, an)


# ============================================================
#                    ZILE / LUNI DE ACTIVITATE
# ============================================================

def zile_activitate(inceput, sfarsit, an) -> int:
    """
    Numarul de ZILE de activitate in anul `an` (inclusiv ambele capete).

    An intreg (fara date sau date in afara anului) → 365 (1 ian → 31 dec inclusiv).
    Incepere 1 septembrie → 31 decembrie = 122 (exemplul ANAF/SOLO).

    >>> zile_activitate(date(2026, 9, 1), None, 2026)
    122
    >>> zile_activitate(None, None, 2026)
    365
    """
    start, end = _margini_an(inceput, sfarsit, an)
    if end < start:
        return 0
    return (end - start).days + 1


def zile_pe_norma_pana_la(inceput, data_split, an) -> int:
    """
    Zilele de activitate pe NORMA, de la inceput (sau 1 ian) pana in ziua DINAINTEA
    `data_split` (data adaugarii activitatii neeligibile, EXCLUSIV). Sub-perioada pe
    norma a activitatii mixte (PAS 4b): [start, data_split). Restul anului = real.

    Compunere cu PAS 4a: `inceput` poate fi data de incepere mid-an a activitatii —
    sub-intervalul normei e atunci [data_inceput, data_split). Refoloseste
    zile_activitate pe interval arbitrar (NU reimplementeaza nimic).

    >>> zile_pe_norma_pana_la(None, date(2026, 9, 1), 2026)   # 1 ian → 31 aug
    243
    """
    d = to_date(data_split)
    if d is None:
        return zile_activitate(inceput, None, an)   # fara split → tot anul pe norma
    return zile_activitate(inceput, d - timedelta(days=1), an)


def luni_activitate(inceput, sfarsit, an) -> int:
    """
    Numarul de LUNI de activitate in anul `an` (prima luna = luna de inceput;
    ultima = luna de sfarsit, altfel decembrie). Formula ANAF pentru recalculul
    plafonului CAS: prima luna = luna depunerii D212.

    >>> luni_activitate(date(2026, 9, 1), None, 2026)   # sept, oct, nov, dec
    4
    >>> luni_activitate(None, None, 2026)
    12
    """
    start, end = _margini_an(inceput, sfarsit, an)
    if end < start:
        return 0
    return end.month - start.month + 1


# ============================================================
#                    PRORATA (matematica oficiala)
# ============================================================

def prorata_norma(norma, zile, an=None) -> float:
    """
    Norma de venit prorata pe zile = norma × zile / 365 (denominator FIX 365).
    Confirmat ANAF/SOLO: 48.600 × 122 / 365 = 16.244 (rotunjit la leu).

    `an` e acceptat pentru simetrie cu celelalte helper-e (semnatura uniforma in
    cablare), dar NU schimba denominatorul — raman 365, nu zilele anului real.

    >>> round(prorata_norma(48_600, 122))
    16244
    """
    norma = max(0.0, float(norma or 0.0))
    zile = max(0, int(zile))
    return round(norma * zile / ZILE_AN, 2)


def plafon_cas_recalculat(plafon_anual, luni) -> float:
    """
    Plafonul CAS recalculat la INCEPERE mid-an = plafon × luni / 12.
    Formula ANAF: „(plafon / 12 luni) × Numar luni". Sub plafonul recalculat → CAS
    0; peste → baza CAS = plafonul recalculat.

    >>> plafon_cas_recalculat(48_600, 4)   # 4 luni active (sept..dec)
    16200.0
    """
    plafon_anual = max(0.0, float(plafon_anual or 0.0))
    luni = max(0, min(LUNI_AN, int(luni)))
    return round(plafon_anual * luni / LUNI_AN, 2)
