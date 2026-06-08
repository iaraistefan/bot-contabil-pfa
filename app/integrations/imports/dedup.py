"""
Dedup determinist pentru tranzacții de extras bancar (felia 3 PAS 2).

Amprentă STABILĂ per linie de extras, ca să nu postăm aceeași tranzacție de două
ori (re-upload al aceluiași extras, eventual re-descărcat cu alt fișier/sha).

Cheia: `(occurred_on, amount, directie, descriere_normalizată, ocurență)`.
- `descriere_normalizată` scoate părțile VOLATILE (REF/RRN/TID, runuri lungi de
  cifre, data embedded) → același extras re-descărcat dă același hash, chiar dacă
  banca pune alt REF de sesiune. SAFE-BY-DEFAULT: REF/RRN NU intră în hash (nu am
  putut verifica empiric că-s stabile la re-descărcare — fixture anonimizat).
- `ocurență` = tiebreaker pentru linii LEGITIM identice în același extras (ex. 8
  comisioane de 0,51 în aceeași zi) → fingerprint-uri distincte → ambele se postează.

⚠️ NORMALIZARE FROZEN: pattern-urile de mai jos sunt INTENȚIONAT independente de
`classify._denoise`. Fingerprint-urile se stochează în DB și trebuie să rămână
reproductibile; cuplarea la clasificator ar invalida tăcut amprentele salvate dacă
denoise-ul se schimbă vreodată. NU refactoriza spre import din classify.
"""
import hashlib
import re
from typing import List

# Zgomot constant din descrierile BT de card (sumă lipită de monedă: „0.00RON").
_RE_NOISE = [
    re.compile(r"comision tranzactie\s+[\d.,]+\s*ron", re.I),
    re.compile(r"valoare tranzactie:?\s*[\d.,]+\s*eur", re.I),
]
# Token-uri ID volatile (valoare după REF:/RRN:/TID:, cu sau fără spațiu/`:`).
_RE_IDTOKEN = re.compile(r"\b(?:ref|rrn|tid)\s*:?\s*\S+", re.I)
# Runuri lungi de cifre: RRN neprefixat, măști card, numere de telefon (+1000…).
_RE_LONGDIGITS = re.compile(r"\d{10,}")
# Dată embedded (dd/mm/yyyy) — redundantă cu occurred_on, variabilă ca format.
_RE_DATE = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
_RE_WS = re.compile(r"\s+")


def normalize_descriere(s: str) -> str:
    """Forma canonică STABILĂ a descrierii (scoate părțile volatile)."""
    s = s or ""
    for pat in _RE_NOISE:
        s = pat.sub(" ", s)
    s = _RE_IDTOKEN.sub(" ", s)      # REF:/RRN:/TID: + valoarea lor
    s = _RE_LONGDIGITS.sub(" ", s)   # RRN-like / măști card / telefon
    s = _RE_DATE.sub(" ", s)         # data embedded
    s = s.lower()
    s = _RE_WS.sub(" ", s).strip()
    return s


def _hash(date_iso: str, amount_str: str, directie: str,
          norm: str, ocurenta: int) -> str:
    raw = f"{date_iso}|{amount_str}|{directie}|{norm}|{ocurenta}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def fingerprint(txn, ocurenta: int = 0) -> str:
    """Amprenta unei singure tranzacții (cu ocurența dată).

    `txn` = orice obiect cu `.data` (date), `.suma` (float), `.directie` (str),
    `.descriere` (str) — ex. `BankTxn`.
    """
    norm = normalize_descriere(txn.descriere)
    return _hash(txn.data.isoformat(), f"{txn.suma:.2f}", txn.directie, norm, ocurenta)


def compute_fingerprints(txns) -> List[str]:
    """Amprentele unei liste de tranzacții, cu `ocurența` atribuită pe grupuri de
    linii identice (tiebreaker). `out[i]` == `fingerprint(txns[i], ocurența_i)`.

    Determinist: aceeași listă (parse stabil) → aceleași amprente → re-upload skip.
    """
    seen = {}
    out: List[str] = []
    for t in txns:
        norm = normalize_descriere(t.descriere)
        key = (t.data.isoformat(), f"{t.suma:.2f}", t.directie, norm)
        oc = seen.get(key, 0)
        seen[key] = oc + 1
        out.append(_hash(key[0], key[1], key[2], key[3], oc))
    return out


def exists_fingerprint(session, user_id: int, fp: str) -> bool:
    """True dacă există deja o tranzacție a user-ului cu acest fingerprint."""
    from app.models import Transaction  # lazy: modul pur, fără lanț config la import
    return (
        session.query(Transaction)
        .filter(
            Transaction.user_id == user_id,
            Transaction.import_fingerprint == fp,
        )
        .first()
        is not None
    )
