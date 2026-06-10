"""
Compensare plată↔returnare a taxelor (felia 5a PAS 2).

Pe extras, o plată de taxă poate fi RESPINSĂ și reîntoarsă (returnare). O astfel
de plată NU e reală (net 0) — a marca obligația ca achitată ar fi o eroare fiscală.
Înainte de orice match cu obligația (felia 5c), compensăm 1:1 plată↔returnare pe
grup și întoarcem DOAR plățile REALE.

Compensare 1:1 per grup `(tip, declarație, lună, an, sumă)`:
    plati_reale = max(0, n_plati - n_returnari)
- Cheia include SUMA: o returnare de 138 compensează doar o plată de 138, nu una
  de 40 (grupuri diferite).
- Doar COUNT-ul contează: plățile dintr-un grup sunt FUNGIBILE (identice pe cheie),
  deci nu contează CARE plată rămâne, ci CÂTE.
- Edge re-plată: 2 plăți + 1 returnare → 1 reală (NU „anulează tot").

Pur, DETERMINIST, zero scriere. Operează doar pe tranzacții cu `oblig` (hint
structurat); cele fără hint nu intră în compensare (5c oricum nu le poate match-ui
→ zero „achitat" fals).
"""
from collections import defaultdict
from typing import List

from app.integrations.imports.classify import PLATA_TAXA, RETURNARE_TAXA


def _key(r):
    o = r.oblig
    return (o.tip, o.declaratie, o.luna, o.an, round(r.txn.suma, 2))


def real_payment_indices(clasificate: List) -> List[int]:
    """INDICII (în `clasificate`) ai plăților de taxe REALE după compensarea 1:1.

    Pe indici (nu obiecte) → consumatorul (5c) poate lega fiecare plată reală de
    AMPRENTA ei (`compute_fingerprints` e aliniat pe index), fără `id()`/poziție
    fragilă. Determinist: ordinea = prima apariție în `clasificate`.
    """
    plati = defaultdict(list)
    returnari = defaultdict(list)
    for i, r in enumerate(clasificate):
        if r.oblig is None:
            continue
        if r.bucket == PLATA_TAXA:
            plati[_key(r)].append(i)
        elif r.bucket == RETURNARE_TAXA:
            returnari[_key(r)].append(i)

    real_idx: List[int] = []
    for key, idxs in plati.items():
        n_ret = len(returnari.get(key, ()))
        # indicii NEpereche rămân reali: idxs[n_ret:] are len = max(0, len(idxs) - n_ret)
        real_idx.extend(idxs[n_ret:])
    return real_idx


def compensate(clasificate: List) -> List:
    """Plățile de taxe REALE (obiecte) după compensarea 1:1 cu returnările.

    Wrapper subțire peste `real_payment_indices` (sursă unică a logicii).
    Determinist: aceeași intrare → același rezultat, în ordinea din clasificate.
    """
    return [clasificate[i] for i in real_payment_indices(clasificate)]
