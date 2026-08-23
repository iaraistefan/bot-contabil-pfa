"""
Certificatul ONRC ca DATE FISCALE: nr_doc_autoriz + data_doc_autoriz din D212.

De ce exista modulul asta: ANAF ne da deja `nrRegCom` si `data_inregistrare` in
raspunsul V9 (anaf_lookup le extrage), dar D212 nu le cere ca „date de la ONRC" —
le cere ca documentul care ATESTA dreptul de a desfasura activitatea:
BR-D212-0095 pretinde nr_doc_autoriz pentru categ_venit=1016, iar BR-D212-0096
cere numarul si data impreuna sau deloc. De aceea campurile se numesc dupa rolul
lor fiscal (doc_autorizare), nu dupa sursa (reg_com).

Doua asimetrii deliberate intre numar si data:

  NUMARUL se ia automat CAND ANAF IL ARE, si se poate tasta cand nu-l are.
  Aici a stat scris, pana in august 2026, ca numarul „se ia automat, fara sa
  intrebam — verificat pe un CUI real: ANAF a intors «J2018000137062», identic
  caracter cu caracter cu certificatul". Fraza era adevarata despre acel CUI si
  FALSA ca regula. Din ea a crescut o asumptie care a mers mai departe in cod
  („singurul camp al perechii care poate lipsi e data") si a lasat numarul fara
  cale de intrare manuala. Pe productie, CUI-ul userului 1 a intors nr_reg_com
  GOL: campul a ramas gol, D212 a refuzat sa se genereze, si niciun ecran din
  produs nu putea repara — pentru un user care platise planul care include D212.
  Un esantion nu e o regula. Automatizarea a ramas; langa ea exista acum si o
  cale de mana, si o stare care spune DE CE lipseste (vezi motivele mai jos).

  DATA se pre-completeaza, dar o confirma userul. ANAF se contrazice singur pe
  PFA — pe acelasi CUI, `data_inregistrare` = 2025-12-05, iar
  `stare_inregistrare` = „INREGISTRAT din data 04.12.2025". In plus, „Data
  eliberarii" tiparita pe certificat nu apare in niciunul dintre cele 18 campuri
  ale raspunsului. Deci cifra pe care i-o aratam e cea mai buna ipoteza pe care o
  avem, nu un fapt — si o spunem asa.
"""

import re
from datetime import date
from typing import Optional

# nr_doc_autoriz e C15Type in d212_schema.xsd (maxLength 15).
MAX_LEN_NR_DOC_AUTORIZARE = 15

# data_doc_autoriz e D10Type: lungime FIXA 10, format zz.ll.aaaa.
LEN_DATA_DOC_AUTORIZARE = 10


class NrDocAutorizarePreaLung(ValueError):
    """Numarul de la ONRC nu incape in C15Type.

    Se ridica in loc sa se trunchieze. Un numar de registru taiat („J2018000137"
    in loc de „J2018000137062") trece de XSD fara sa clipeasca si ajunge in
    declaratie ca numar de certificat FALS — exact gaura pe care campul asta ar
    trebui s-o inchida. Mai bine gol si reclamat, decat plin si gresit.
    """


# ============================================================
#     DE CE LIPSESTE NUMARUL — starea, nu doar absenta
# ============================================================
# Un camp gol nu spune nimic: „n-a intrebat nimeni niciodata" arata identic cu
# „am intrebat ANAF si n-a avut ce sa-mi dea". Distinctia nu e academica — pe
# productie, userul 1 avea nr_doc_autorizare NULL desi lookup-ul ANAF ii scrisese
# numele in ACEEASI rulare (onboarding.py, acelasi dict `updates`). Cauza s-a
# pierdut intr-un logger.warning, si nimeni n-a aflat pana la generarea D212, luni
# mai tarziu, cand userul a primit un refuz fara iesire.
#
# De aceea esecul se STOCHEAZA. Cele doua cauze cer raspunsuri DIFERITE de la user:
# pe ANAF_GOL numarul trebuie tastat de pe certificat (reimprospatarea nu ajuta,
# ANAF chiar n-are ce da); pe PREA_LUNG avem un numar, dar nu incape in formatul
# ANAF si trebuie sa ne uitam impreuna la el. Un singur „nesetat" le-ar confunda.
#
# NULL = n-am incercat niciodata (sau numarul e completat — vezi campul insusi).
MOTIV_NR_ANAF_GOL = "ANAF_GOL"
MOTIV_NR_PREA_LUNG = "PREA_LUNG"

# Lungimea coloanei din migrarea 031. Codurile sunt scurte si stabile.
MAX_LEN_MOTIV_NR_DOC = 30


def motiv_nr_doc_text(motiv: Optional[str]) -> Optional[str]:
    """Codul de motiv → ce citeste OMUL. Cod necunoscut / None → None.

    Sursa UNICA pentru toate cele patru suprafete (coduri fiscale in bot, Setari
    web, rezultatul reimprospatarii, sumarul de configurare). Un motiv explicat
    diferit in doua locuri e acelasi bug ca un motiv neexplicat deloc.
    """
    return {
        MOTIV_NR_ANAF_GOL: (
            "ANAF nu are numărul certificatului pentru CUI-ul tău — "
            "l-am cerut și a venit gol. Scrie-l tu de pe certificat."
        ),
        MOTIV_NR_PREA_LUNG: (
            f"ANAF a întors un număr mai lung de {MAX_LEN_NR_DOC_AUTORIZARE} "
            "caractere, cât acceptă Declarația Unică. Nu-l tai — un număr de "
            "certificat trunchiat e un număr fals. Scrie-l tu de pe certificat."
        ),
    }.get(motiv or "")


def normalizeaza_nr_doc_autorizare(val: Optional[str]) -> Optional[str]:
    """Curata numarul si REFUZA ce nu incape in 15 caractere.

    Formatul nou (ONRC din 2023) da 14 caractere fix — „J2018000137062" — dar
    pe doua esantioane nu se construieste o regula. Un PFA vechi poate avea
    forma cu bare, „F06/123456/2018", care e exact 15; iar un judet cu numar
    mai lung ar depasi. De aceea limita se verifica, nu se presupune.
    """
    if val is None:
        return None
    curat = re.sub(r"\s+", "", str(val)).upper()
    if not curat:
        return None
    if len(curat) > MAX_LEN_NR_DOC_AUTORIZARE:
        raise NrDocAutorizarePreaLung(
            f"numar de autorizare de {len(curat)} caractere ({curat!r}), dar D212 "
            f"accepta cel mult {MAX_LEN_NR_DOC_AUTORIZARE} (C15Type). "
            f"Nu il trunchiem — un numar de certificat taiat e un numar fals."
        )
    return curat


def nr_doc_din_anaf(val: Optional[str]) -> tuple:
    """Raspunsul ANAF → `(numar, motiv)`. NICIODATA nu arunca, niciodata nu tace.

    Inlocuieste tiparul care a produs bug-ul: apelantii chemau
    `normalizeaza_nr_doc_autorizare` intr-un try/except care inghitea exceptia cu
    un logger.warning, iar valoarea goala trecea prin `if nr_doc:` fara urma.
    Aici cele doua esecuri sunt VALORI de intors, nu evenimente de pierdut:

        („J2018000137062", None)   -> avem numarul
        (None, MOTIV_NR_ANAF_GOL)  -> ANAF n-a dat nimic
        (None, MOTIV_NR_PREA_LUNG) -> a dat, dar nu incape

    Apelantul nu mai poate ignora cauza din greseala: ca s-o piarda, trebuie sa
    arunce explicit al doilea element.
    """
    try:
        nr = normalizeaza_nr_doc_autorizare(val)
    except NrDocAutorizarePreaLung:
        return None, MOTIV_NR_PREA_LUNG
    if not nr:
        return None, MOTIV_NR_ANAF_GOL
    return nr, None


def parseaza_data_anaf(val: Optional[str]) -> Optional[date]:
    """ANAF „YYYY-MM-DD" → obiect `date`. Ce nu se potriveste → None.

    Conversie, nu copiere: stocam un `date` ca formatul cerut de D212 sa se
    produca dintr-o data reala, nu dintr-un sir plimbat de colo-colo.
    """
    if not val:
        return None
    s = str(val).strip()[:10]
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parseaza_data_utilizator(val: Optional[str]) -> Optional[date]:
    """Ce scrie userul („zz.ll.aaaa") → `date`. Ce nu se potriveste → None.

    Acceptam si `-` sau `/` ca separator, pentru ca omul copiaza de pe certificat
    cum vede. Nu acceptam luni/zile imposibile — mai bine reintrebam.
    """
    if not val:
        return None
    m = re.fullmatch(r"\s*(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\s*", str(val))
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def formateaza_data_d212(d: Optional[date]) -> str:
    """`date` → „zz.ll.aaaa" (D10Type, lungime fixa 10)."""
    if d is None:
        return ""
    s = d.strftime("%d.%m.%Y")
    assert len(s) == LEN_DATA_DOC_AUTORIZARE, s
    return s


# Refuzul unei date pe care n-o intelegem. UNA singura, pentru toate cele patru
# locuri unde se poate scrie o data de certificat (configurare bot, configurare
# web, Setari bot, Setari web) — daca cere acelasi lucru, sa ceara la fel.
MESAJ_DATA_INVALIDA = (
    "Nu recunosc data asta. Scrie-o ca pe certificat, în formatul "
    "zz.ll.aaaa (de exemplu 05.12.2025)."
)


# ============================================================
#          TEXTUL DE CONFIRMARE A DATEI (profesorul rabdator)
# ============================================================

def text_confirmare_data(
    data_propusa: Optional[date],
    nr_doc: Optional[str] = None,
) -> str:
    """Ce-i aratam userului cand ii cerem sa confirme data certificatului.

    Trei lucruri, in ordinea asta: ce e campul, de unde vine cifra pe care i-o
    aratam, si ce face daca pe certificatul lui scrie altceva.
    """
    linii = [
        "📜 *Data certificatului de la Registrul Comerțului*",
        "",
        "Declarația Unică cere, pe lângă numărul certificatului tău, și data lui. "
        "Sunt datele documentului care atestă că ai dreptul să desfășori "
        "activitatea — ANAF le vrea pereche, număr fără dată nu se poate.",
    ]
    if nr_doc:
        linii += ["", f"Numărul l-am luat din ANAF: `{nr_doc}`."]
    if data_propusa:
        linii += [
            "",
            f"Data pe care ți-o propun este *{formateaza_data_d212(data_propusa)}* — "
            "e data înregistrării fiscale la ANAF. Ți-o arăt în loc s-o trec "
            "tăcut, pentru că nu e chiar același lucru cu „Data eliberării” "
            "tipărită pe certificat: aceasta din urmă nu apare nicăieri în "
            "răspunsul ANAF, așa că e cea mai bună potrivire pe care o am, nu o "
            "certitudine.",
        ]
    else:
        linii += [
            "",
            # Neutru DELIBERAT: aceeasi fraza serveste si configurarea (ANAF n-a
            # dat data) si Setarile (userul a amanat-o). „N-am gasit-o in ANAF"
            # ar fi fost fals pe al doilea drum.
            "Data nu e completată încă, așa că pe asta trebuie să mi-o dai tu.",
        ]
    linii += [
        "",
        "*Uită-te pe certificat.* Dacă acolo scrie altă dată, pe a ta o folosim — "
        "scrie-mi-o în formatul zz.ll.aaaa și o schimb. Documentul tău are "
        "dreptate, nu registrul meu.",
    ]
    return "\n".join(linii)
