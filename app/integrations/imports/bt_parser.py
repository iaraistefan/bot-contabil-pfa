"""
Parser determinist pentru extrasul de cont Banca Transilvania (PDF).

Strategie — extracție pe COORDONATE (zona de bani, nu se ghicește):
- Sumele Debit/Credit sunt aliniate la dreapta în două coloane fixe; le
  clasific după coloana (header „Debit"/„Credit") cea mai apropiată de x1-ul
  sumei. Sumele de zgomot din descriere („valoare tranzactie: 6.05 EUR",
  „comision 0.00 RON") sunt la mijlocul paginii → în afara coloanelor → ignorate.
- Direcția vine din coloană: Debit → OUT (plată), Credit → IN (încasare).
  NU există semn pe sumă.
- Grupare multi-linie: o tranzacție începe pe linia cu o sumă într-o coloană;
  liniile următoare fără sumă în coloană = continuare de descriere.
- Data se propagă (carry-forward): apare o dată/zi; tranzacțiile 2+ din aceeași
  zi o moștenesc.
- Rândurile de control (SOLD/RULAJ/TOTAL/SUME BLOCATE/...) sunt sărite; parsarea
  se OPREȘTE la „RULAJ TOTAL CONT" (sfârșitul tranzacțiilor; restul = sumar).

AUTO-CHECKSUM: „RULAJ TOTAL CONT" conține totalul Debit/Credit al extrasului.
Comparăm sum(OUT)/sum(IN) cu el; la nepotrivire ridicăm BankStatementError
(NU întoarcem date parțiale).
"""
import io
import re
from datetime import date
from typing import List, Optional, Tuple

import pdfplumber

from .bank_statement import BankTxn, BankStatementError

# Linii de control de sărit (nu sunt tranzacții).
_SKIP = (
    "SOLD ANTERIOR", "RULAJ ZI", "SOLD FINAL ZI", "SOLD FINAL CONT",
    "SUME BLOCATE", "TOTAL DISPONIBIL", "Fonduri proprii", "Credit neutilizat",
    "din care",
)
_STOP = "RULAJ TOTAL CONT"           # marchează sfârșitul tranzacțiilor

_AMT = re.compile(r"^[0-9][0-9.,]*\.[0-9]{2}$")   # 31.81 / 1,019.45
_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_LINE_TOL = 3.5                      # toleranță grupare pe rând (y)
_BAND_TOL = 25.0                     # cât de aproape de header e o sumă din coloană
_CHECKSUM_TOL = 0.01


def _to_float(t: str) -> float:
    """„1,019.45" → 1019.45 (virgulă = mii, punct = zecimale)."""
    return float(t.replace(",", ""))


def _parse_date(tok: str) -> Optional[date]:
    m = _DATE.match(tok)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return date(y, mo, d)


def _cluster_lines(words: List[dict]) -> List[List[dict]]:
    """Grupează cuvintele în linii vizuale după `top` (toleranță _LINE_TOL).

    Clusterizare reală (nu rounding) — altfel eticheta și suma de pe același rând
    pot cădea în buckete diferite (ex. „SOLD FINAL ZI" rupt de valoarea lui).
    """
    ws = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines: List[List[dict]] = []
    for w in ws:
        if lines and abs(w["top"] - lines[-1][0]["top"]) <= _LINE_TOL:
            lines[-1].append(w)
        else:
            lines.append([w])
    for ln in lines:
        ln.sort(key=lambda w: w["x0"])
    return lines


def _column_amount(
    line: List[dict], deb_x: Optional[float], cre_x: Optional[float]
) -> Tuple[Optional[float], Optional[str]]:
    """Întoarce (sumă, direcție) dacă linia are o sumă în coloana Debit SAU Credit.

    Clasifică suma după header-ul (Debit/Credit) cel mai apropiat de x1-ul ei,
    dar numai dacă e în _BAND_TOL (altfel = zgomot din descriere → ignorat).
    """
    best: Tuple[Optional[float], Optional[str]] = (None, None)
    best_dist = _BAND_TOL
    for w in line:
        if not _AMT.match(w["text"]):
            continue
        x1 = w["x1"]
        if deb_x is not None and abs(x1 - deb_x) <= best_dist:
            best, best_dist = (_to_float(w["text"]), "OUT"), abs(x1 - deb_x)
        if cre_x is not None and abs(x1 - cre_x) <= best_dist:
            best, best_dist = (_to_float(w["text"]), "IN"), abs(x1 - cre_x)
    return best


def _both_columns(
    line: List[dict], deb_x: Optional[float], cre_x: Optional[float]
) -> Tuple[Optional[float], Optional[float]]:
    """Sumele din AMBELE coloane de pe o linie (pt. RULAJ TOTAL CONT = checksum)."""
    deb = cre = None
    for w in line:
        if not _AMT.match(w["text"]):
            continue
        if deb_x is not None and abs(w["x1"] - deb_x) <= _BAND_TOL:
            deb = _to_float(w["text"])
        elif cre_x is not None and abs(w["x1"] - cre_x) <= _BAND_TOL:
            cre = _to_float(w["text"])
    return deb, cre


def _clean_desc(text: str) -> str:
    """Curăță descrierea: scoate data din față și sumele din coloane din coadă."""
    parts = text.split()
    if parts and _DATE.match(parts[0]):     # data din față (dd/mm/yyyy)
        parts.pop(0)
    while parts and _AMT.match(parts[-1]):  # suma coloanei lipită în coadă
        parts.pop()
    return " ".join(parts).strip()


def parse_bt_pdf(content: bytes) -> List[BankTxn]:
    """Parsează un extras BT (PDF, bytes) → listă de BankTxn (neutru).

    Ridică BankStatementError dacă nu găsește „RULAJ TOTAL CONT" (nu poate
    verifica) sau dacă checksum-ul nu se potrivește (date posibil greșite).
    """
    txns: List[BankTxn] = []
    cur_date: Optional[date] = None
    deb_x: Optional[float] = None
    cre_x: Optional[float] = None
    control: Optional[Tuple[Optional[float], Optional[float]]] = None

    # tranzacția în curs de construit (pt. descriere multi-linie)
    cur: Optional[dict] = None

    def flush():
        nonlocal cur
        if cur is not None:
            txns.append(BankTxn(
                data=cur["data"], suma=cur["suma"],
                directie=cur["directie"], descriere=cur["desc"].strip(),
            ))
            cur = None

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for pg in pdf.pages:
            words = pg.extract_words()
            # header-ele se repetă pe fiecare pagină; reține ultima poziție știută
            for w in words:
                if w["text"] == "Debit":
                    deb_x = w["x1"]
                elif w["text"] == "Credit":
                    cre_x = w["x1"]
            for line in _cluster_lines(words):
                text = " ".join(w["text"] for w in line)

                if _STOP in text:
                    flush()
                    control = _both_columns(line, deb_x, cre_x)
                    return _finalize(txns, control)

                # data (carry-forward) — actualizează înainte de orice
                for w in line:
                    d = _parse_date(w["text"])
                    if d is not None and w["x0"] < 60:   # coloana Data (stânga)
                        cur_date = d
                        break

                if any(s in text for s in _SKIP):
                    flush()                              # rând de control → închide tranzacția
                    continue

                amt, direction = _column_amount(line, deb_x, cre_x)
                if amt is not None:
                    flush()                              # linie nouă cu sumă = tranzacție nouă
                    cur = {
                        "data": cur_date, "suma": amt, "directie": direction,
                        "desc": _clean_desc(text),
                    }
                elif cur is not None:
                    cur["desc"] += " " + text.strip()    # continuare descriere

    # nu am găsit RULAJ TOTAL CONT → nu pot verifica → nu întorc date nesigure
    raise BankStatementError(
        "RULAJ TOTAL CONT negăsit în extras — nu pot verifica corectitudinea."
    )


def _finalize(
    txns: List[BankTxn], control: Optional[Tuple[Optional[float], Optional[float]]]
) -> List[BankTxn]:
    """Verifică checksum-ul față de RULAJ TOTAL CONT; altfel ridică eroare."""
    if control is None or control[0] is None or control[1] is None:
        raise BankStatementError("RULAJ TOTAL CONT fără totaluri Debit/Credit valide.")
    ctrl_out, ctrl_in = control
    sum_out = round(sum(t.suma for t in txns if t.directie == "OUT"), 2)
    sum_in = round(sum(t.suma for t in txns if t.directie == "IN"), 2)
    if abs(sum_out - ctrl_out) > _CHECKSUM_TOL or abs(sum_in - ctrl_in) > _CHECKSUM_TOL:
        raise BankStatementError(
            "Checksum nepotrivit: extras OUT="
            f"{ctrl_out:.2f}/IN={ctrl_in:.2f}, parsat OUT={sum_out:.2f}/IN={sum_in:.2f}. "
            "Nu întorc date posibil greșite."
        )
    return txns
