"""
Numele declarantului (nume de familie + prenume), din denumirea de la ANAF.

De ce exista: declaratiile cer nume si prenume SEPARAT (D390 `nume_declar` /
`prenume_declar`, D212 `nume_c` / `prenume_c` cu use="required"), iar in profil
aveam un singur sir liber, `firma_nume`. Un camp liber poate purta ambele
ordini — si chiar le poarta: pe acelasi CUI, ANAF intoarce
„IARAI ŞTEFAN PERSOANĂ FIZICĂ AUTORIZATĂ" (nume intai), dar in baza noastra
statea „ȘTEFAN IARAI PFA" (prenume intai), tastat de mana. Cine sparge sirul
NU are cum sa stie ca perechea a fost intoarsa inainte sa ajunga la el.

Solutia e la SURSA: se sparge `denumire` PROASPAT de la ANAF, unde ordinea e
stabila (verificata pe doua PFA-uri reale, nume de familie intai), si se
stocheaza cele doua bucati separat. Modulul asta e taietorul; nu ghiceste
nimic despre ce nu recunoaste.

Doua capcane pe care le evita, ambele prezente in varianta veche
(`declaratii_service._split_nume_prenume`):

  DIACRITICE. Lista de sufixe era scrisa fara diacritice
  („PERSOANA FIZICA AUTORIZATA"), dar ANAF scrie CU („PERSOANĂ FIZICĂ
  AUTORIZATĂ") — deci sufixul nu se taia niciodata. Scapa doar din noroc,
  fiindca se luau primele doua cuvinte oricum.

  POTRIVIRE PE SUBSIR. `den.replace("II", "")` lovea orice nume care contine
  „II" — „ILIIESCU" devenea „ILESCU". Aici potrivirea e pe CUVANT INTREG, in
  secventa, deci „II" taie doar cuvantul „II".
"""

import re
import unicodedata
from typing import List, Optional, Tuple

# Sufixele de forma juridica, ca SECVENTE DE CUVINTE normalizate. Prezenta unuia
# e si dovada ca denumirea e a unei persoane fizice: un SRL („I-SHTEF SRL") n-are
# nume de om in denumire, deci acolo nu avem ce sparge si nu inventam.
_SUFIXE_PERSOANA_FIZICA: List[List[str]] = [
    ["PERSOANA", "FIZICA", "AUTORIZATA"],
    ["INTREPRINDERE", "INDIVIDUALA"],
    ["INTREPRINDERE", "FAMILIALA"],
    ["CABINET", "MEDICAL", "INDIVIDUAL"],
    ["CABINET", "INDIVIDUAL"],
    ["CABINET", "MEDICAL"],
    ["BIROU", "INDIVIDUAL"],
    ["PFA"],
    ["II"],
    ["IF"],
]


def _norm(cuvant: str) -> str:
    """Un cuvant → forma de potrivire: fara diacritice, fara punctuatie, MAJUSCULE.

    „PERSOANĂ" → „PERSOANA", „P.F.A." → „PFA", „NICOLETA-ILEANA" →
    „NICOLETAILEANA" (nu se potriveste cu niciun sufix — exact ce vrem).
    """
    fara = "".join(
        c for c in unicodedata.normalize("NFKD", cuvant)
        if not unicodedata.combining(c)
    )
    return re.sub(r"[^A-Za-z0-9]", "", fara).upper()


def split_denumire(denumire: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Denumire ANAF → (nume de familie, prenume), sau (None, None) daca nu se poate.

    Se intoarce (None, None) — nu o ghicitura — cand:
      · denumirea n-are sufix de persoana fizica (SRL/SA: n-are nume de om);
      · inaintea sufixului raman sub doua cuvinte (n-avem ce imperechea).

    Cuvintele se intorc ASA CUM LE-A SCRIS ANAF, cu diacritice: curatarea pentru
    XML o fac generatoarele (`_curata_text`), nu noi.
    """
    if not denumire:
        return None, None
    cuvinte = str(denumire).split()
    normalizate = [_norm(c) for c in cuvinte]

    taietura = None
    for i in range(len(normalizate)):
        for suf in _SUFIXE_PERSOANA_FIZICA:
            if normalizate[i:i + len(suf)] == suf:
                taietura = i
                break
        if taietura is not None:
            break

    if taietura is None:          # fara sufix → nu stim ca e persoana fizica
        return None, None

    persoana = [c for c in cuvinte[:taietura] if _norm(c)]
    if len(persoana) < 2:         # un singur cuvant → nu avem pereche
        return None, None

    # Ordinea la ANAF: NUME de familie intai, restul e prenume (compus inclusiv:
    # „POPESCU ION VASILE" → „POPESCU" / „ION VASILE").
    return persoana[0], " ".join(persoana[1:])
