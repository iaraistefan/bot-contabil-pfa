"""
app/ro_dates.py — formatare datelor/lunilor în ROMÂNĂ (sursă unică).

NU folosi `strftime("%b"/"%B")` — depinde de locale-ul sistemului (dă "May"/"June"
pe servere fără locale RO). Aici e determinist, în română. Folosit de bannere
(`contai_banners`) + UI (Declarația Unică, Raport, …).
"""

LUNI_RO = {
    1: "Ianuarie", 2: "Februarie", 3: "Martie", 4: "Aprilie",
    5: "Mai", 6: "Iunie", 7: "Iulie", 8: "August",
    9: "Septembrie", 10: "Octombrie", 11: "Noiembrie", 12: "Decembrie",
}
LUNI_RO_SCURT = {
    1: "Ian", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Mai", 6: "Iun",
    7: "Iul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Noi", 12: "Dec",
}


def luna_ro(month: int) -> str:
    """Numele întreg al lunii: 5 → 'Mai'."""
    return LUNI_RO.get(month, str(month))


def luna_ro_scurt(month: int) -> str:
    """Numele abreviat al lunii: 2 → 'Feb'."""
    return LUNI_RO_SCURT.get(month, str(month))


def zi_luna_ro(d) -> str:
    """Data cu lună întreagă: 25 Mai 2027."""
    return f"{d.day} {luna_ro(d.month)} {d.year}"


def zi_luna_ro_scurt(d) -> str:
    """Data cu lună abreviată: 28 Feb 2027."""
    return f"{d.day} {luna_ro_scurt(d.month)} {d.year}"
