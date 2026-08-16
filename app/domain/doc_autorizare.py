"""
Certificatul ONRC ca DATE FISCALE: nr_doc_autoriz + data_doc_autoriz din D212.

De ce exista modulul asta: ANAF ne da deja `nrRegCom` si `data_inregistrare` in
raspunsul V9 (anaf_lookup le extrage), dar D212 nu le cere ca „date de la ONRC" —
le cere ca documentul care ATESTA dreptul de a desfasura activitatea:
BR-D212-0095 pretinde nr_doc_autoriz pentru categ_venit=1016, iar BR-D212-0096
cere numarul si data impreuna sau deloc. De aceea campurile se numesc dupa rolul
lor fiscal (doc_autorizare), nu dupa sursa (reg_com).

Doua asimetrii deliberate intre numar si data:

  NUMARUL se ia automat, fara sa intrebam. Verificat pe un CUI real: ANAF a
  intors „J2018000137062", identic caracter cu caracter cu certificatul.

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
            "Data n-am găsit-o în ANAF, așa că pe asta trebuie să mi-o dai tu.",
        ]
    linii += [
        "",
        "*Uită-te pe certificat.* Dacă acolo scrie altă dată, pe a ta o folosim — "
        "scrie-mi-o în formatul zz.ll.aaaa și o schimb. Documentul tău are "
        "dreptate, nu registrul meu.",
    ]
    return "\n".join(linii)
