"""
Format NEUTRU de tranzacție bancară — granița dintre parsere și conductă.

Orice parser de bancă (BT azi; ING/Revolut mâine) întoarce o listă de `BankTxn`.
Conducta (upload → SourceFile → preview → eventual postare) lucrează DOAR cu
`BankTxn`, fără să știe nimic specific despre o bancă anume. Așa, adăugarea unei
bănci noi = un parser nou care scoate același `BankTxn`, restul neschimbat.

TODO viitor (NU acum): detecție automată bancă + registru parsere + profil bancă
per user. Vezi PROGRES.md.
"""
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class BankTxn:
    """O tranzacție dintr-un extras, în format neutru de bancă.

    suma e MEREU pozitivă; sensul îl dă `directie` ("IN" = încasare / credit,
    "OUT" = plată / debit). `descriere` e textul brut (multi-linie concatenat),
    util pentru clasificare ulterioară (felie viitoare).
    """
    data: date
    suma: float
    directie: str          # "IN" | "OUT"
    descriere: str


class BankStatementError(Exception):
    """
    Parsare eșuată SAU checksum nepotrivit.

    Pe zona de bani preferăm „nu știu sigur" în loc de date parțiale tăcute:
    dacă suma tranzacțiilor extrase nu se potrivește cu totalul de control din
    extras, ridicăm asta — NU întoarcem o listă posibil greșită.
    """
