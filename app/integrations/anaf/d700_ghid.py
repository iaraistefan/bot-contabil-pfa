"""
Ghid D700 — inregistrarea in scopuri TVA pentru achizitii intracomunitare (art. 317).

D700 NU e un generator XML (spre deosebire de D100/D207/D301/D390): e o CERERE de
inregistrare depusa prin SPV, fara fisier de depus si fara plata. Rezultatul e un
COD SPECIAL de TVA (RO...) — poarta catre tot lantul intracomunitar (D301/D390).

Aici oferim DOAR "Drumul A" (ghid pas-cu-pas), refolosind conventia genereaza_ghid_*
din familia de generatoare. Se afiseaza userului care inca NU are cod (neplatitor,
fara cod special) — cel care ARE cod deja e comutat pe SPECIAL_INTRACOM si nu mai
vede D700 (vezi users._comuta_regim_intracom).
"""


def should_show_d700_ghid(regim_tva, cod_special_tva) -> bool:
    """
    True cand ghidul D700 e relevant: userul e NEPLATITOR si NU are inca cod special.

    - PLATITOR_21 → False (plątitor complet, art. 317 irelevant).
    - SPECIAL_INTRACOM → False (are deja cod → D700 facut).
    - NEPLATITOR + cod prezent → False (are cod, doar n-a fost comutat inca).
    - NEPLATITOR + fara cod → True (poarta catre intracom, inca neinregistrat).
    """
    regim = (regim_tva or "").strip().upper()
    are_cod = bool((cod_special_tva or "").strip())
    return regim == "NEPLATITOR" and not are_cod


def genereaza_ghid_d700(*, plain: bool = False) -> str:
    """Ghid pas-cu-pas D700 (Telegram/dashboard). `plain=True` = fara markdown."""
    def b(txt):
        return txt if plain else f"*{txt}*"

    L = []
    L.append(b("D700 — cum iti iei codul special de TVA (art. 317)"))
    L.append("")
    L.append("E o inregistrare O SINGURA DATA, INAINTE de prima cursa/comision de la o "
             "platforma UE (Bolt EE / Uber NL). Fara plata. Fara ea nu poti depune legal "
             "D301/D390. Nu exista prag — pragul de 10.000 € e doar pentru BUNURI, nu "
             "pentru servicii (comisionul platformei e serviciu).")
    L.append("")
    L.append(b("Pasii:"))
    L.append("1. Ai nevoie de o semnatura electronica calificata + inrolare in SPV pe "
             "CUI-ul PFA.")
    L.append("2. Completeaza Formularul 700, Subsectiunea B.VI, punctul 1.23.1, bifa "
             "nr. 3 — \"primirea de servicii de la un prestator din UE\" (art. 317 "
             "alin. (1) lit. c).")
    L.append("3. Semneaza electronic si urca fisierul in SPV / e-guvernare → "
             "\"Depunere declaratii\".")
    L.append("4. Pastreaza recipisa de depunere.")
    L.append("5. Ridica certificatul de inregistrare de la sediul ANAF (3-10 zile) — "
             "titular sau imputernicit.")
    L.append("6. Confirma ca apare codul RO in VIES (verificare online).")
    L.append("7. Introdu codul in Coniar → activeaza automat D301/D390.")
    L.append("")
    L.append(b("Termen:") + " inainte de prima cursa/comision. Cat mai devreme — e "
             "primul pas din tot lantul intracomunitar.")
    return "\n".join(L)
