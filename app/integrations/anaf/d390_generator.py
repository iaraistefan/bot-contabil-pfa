"""
Generator XML pentru Declaratia 390 VIES (Declaratie recapitulativa privind
livrarile/achizitiile/prestarile intracomunitare).

Structura conforma cu schema oficiala ANAF:
  - OPANAF 705/11.03.2020, versiunea v3
  - radacina <declaratie390>, namespace mfp:anaf:dgti:d390:declaratie:v3
  - structura confirmata din structura_D390_2020_180320.pdf + PDF real depus

CAZUL DE UTILIZARE (PFA ridesharing Bolt, cod special TVA art. 317):
  - PFA neplatitor TVA cu cod special (art. 317)
  - achizitie intracomunitara de SERVICII (comision Bolt) -> tip operatiune "S"
  - furnizor: BOLT OPERATIONS OU, Estonia (EE), VAT 102090374
  - se depune LUNAR (pana pe 25), DOAR in lunile cu factura Bolt

IMPORTANT:
  - cui = codul special de TVA (53148882), FARA prefixul "RO", camp numeric N(10)
  - se admit DOAR caractere din alfabetul latin, FARA diacritice / caractere speciale
  - baza se exprima in LEI (intreg), la cursul BNR din data facturii, FARA TVA

Fluxul complet: acest XML -> validare DUKIntegrator (-p) -> PDF inteligent
-> utilizatorul semneaza cu eToken (local) -> incarca in SPV.

NOTA: D390 este DOAR declarativa (raportare), NU se plateste nimic prin ea.
Plata TVA se face prin D301 (taxare inversa 21%).
"""

from dataclasses import dataclass, field
from typing import List, Optional
from xml.sax.saxutils import escape
import unicodedata
import re


# ============================================================
#                    CONSTANTE
# ============================================================

D390_NAMESPACE = "mfp:anaf:dgti:d390:declaratie:v3"
D390_XSD = "D390.xsd"

# Tipuri de operatiuni VIES valide
TIPURI_OPERATIUNE = {"L", "T", "A", "P", "S", "R"}
# L = livrari intracom. bunuri
# T = livrari operatiune triunghiulara
# A = achizitii intracom. bunuri
# P = prestari intracom. servicii
# S = achizitii intracom. servicii  <-- cazul Bolt
# R = livrari regim special agricultori


# ============================================================
#                    DATACLASSES
# ============================================================

@dataclass
class OperatorIntracom:
    """O operatiune intracomunitara (un rand din anexa D390)."""
    tip: str               # L/T/A/P/S/R  (Bolt = "S")
    tara: str              # cod tara 2 litere (Bolt = "EE")
    cod_operator: str      # cod TVA partener, fara prefix tara (Bolt = "102090374")
    denumire: str          # denumire partener (Bolt = "BOLT OPERATIONS OU")
    baza: int              # baza impozabila in LEI, intreg, fara TVA


@dataclass
class IdentitateDeclarant:
    """Datele de identificare ale declarantului si firmei."""
    cui: str               # cod special TVA, FARA "RO" (ex. "53148882")
    denumire: str          # ex. "IARAI STEFAN PERSOANA FIZICA AUTORIZATA"
    adresa: str            # domiciliu fiscal complet
    nume_declarant: str    # ex. "IARAI"
    prenume_declarant: str # ex. "STEFAN"
    functie_declarant: str = "TITULAR"
    telefon: str = ""
    fax: str = ""
    email: str = ""


# ============================================================
#                    HELPERS
# ============================================================

def _curata_text(text: str) -> str:
    """
    Elimina diacriticele si caracterele nepermise.
    ANAF: se admit doar caractere din alfabetul latin, fara diacritice.
    Caractere permise in text: litere, cifre, spatiu si + - . @
    """
    if not text:
        return ""
    # transforma diacriticele in echivalentul latin (ă->a, ț->t, etc.)
    nfkd = unicodedata.normalize("NFKD", text)
    fara_diacritice = "".join(c for c in nfkd if not unicodedata.combining(c))
    # pastreaza doar caracterele permise
    curatat = re.sub(r"[^A-Za-z0-9 +\-.@]", " ", fara_diacritice)
    # normalizeaza spatiile multiple
    curatat = re.sub(r"\s+", " ", curatat).strip()
    return curatat


def _curata_cui(cui: str) -> str:
    """Scoate prefixul RO si orice non-cifra din CUI (camp numeric N(10))."""
    return re.sub(r"\D", "", str(cui))


def _attr(name: str, value) -> str:
    """Construieste un atribut XML escaped."""
    return f'{name}="{escape(str(value), {chr(34): "&quot;"})}"'


# ============================================================
#                    GENERATOR D390
# ============================================================

def genereaza_d390(
    an: int,
    luna: int,
    identitate: IdentitateDeclarant,
    operatori: List[OperatorIntracom],
    d_rec: int = 0,
) -> str:
    """
    Genereaza XML-ul D390 conform schemei oficiale ANAF v3.

    Args:
        an: anul de raportare (>= 2020)
        luna: luna de raportare (1-12; pentru an=2020+ trebuie >= 2)
        identitate: datele declarantului (cu cod special TVA)
        operatori: lista operatiunilor intracomunitare (pentru Bolt: 1 op. tip "S")
        d_rec: 0 = declaratie initiala, 1 = rectificativa

    Returns:
        XML-ul D390 ca string (UTF-8, gata de scris in fisier .xml)

    Raises:
        ValueError: daca datele sunt invalide
    """
    # --- validari ---
    if not (2020 <= an <= 2099):
        raise ValueError(f"An invalid: {an}")
    if not (1 <= luna <= 12):
        raise ValueError(f"Luna invalida: {luna}")
    if not operatori:
        raise ValueError(
            "D390 nu se depune pe zero. Daca nu ai operatiuni intracom "
            "in aceasta luna, NU depui D390."
        )
    for op in operatori:
        if op.tip not in TIPURI_OPERATIUNE:
            raise ValueError(f"Tip operatiune invalid: {op.tip}")
        if len(op.tara) != 2:
            raise ValueError(f"Cod tara invalid: {op.tara}")
        if op.baza <= 0:
            raise ValueError(f"Baza invalida pentru {op.denumire}: {op.baza}")

    cui = _curata_cui(identitate.cui)

    # --- calcul rezumat (totaluri pe tip) ---
    baze = {"L": 0, "T": 0, "A": 0, "P": 0, "S": 0, "R": 0}
    for op in operatori:
        baze[op.tip] += int(round(op.baza))
    total_baza = sum(baze.values())
    nr_opi = len(operatori)

    # suma de control: nrOPI + bazaL + bazaT + bazaA + bazaP + bazaS + bazaR
    total_plata_a = nr_opi + baze["L"] + baze["T"] + baze["A"] + baze["P"] + baze["S"] + baze["R"]

    # --- construire XML ---
    den = _curata_text(identitate.denumire)
    adresa = _curata_text(identitate.adresa)
    nume = _curata_text(identitate.nume_declarant)
    prenume = _curata_text(identitate.prenume_declarant)
    functie = _curata_text(identitate.functie_declarant)
    telefon = _curata_text(identitate.telefon)
    fax = _curata_text(identitate.fax)
    mail = identitate.email.strip()  # email-ul poate contine @ si .

    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')

    # atributele radacinii
    root_attrs = " ".join([
        _attr("xmlns", D390_NAMESPACE),
        _attr("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance"),
        _attr("xsi:schemaLocation", f"{D390_NAMESPACE} {D390_XSD}"),
        _attr("luna", f"{luna:02d}"),
        _attr("an", an),
        _attr("d_rec", d_rec),
        _attr("nume_declar", nume),
        _attr("prenume_declar", prenume),
        _attr("functie_declar", functie),
        _attr("cui", cui),
        _attr("den", den),
        _attr("adresa", adresa),
        _attr("telefon", telefon),
        _attr("fax", fax),
        _attr("mail", mail),
        _attr("totalPlata_A", total_plata_a),
    ])
    lines.append(f"<declaratie390 {root_attrs}>")

    # rezumat
    rezumat_attrs = " ".join([
        _attr("nr_pag", 1),
        _attr("nrOPI", nr_opi),
        _attr("bazaL", baze["L"]),
        _attr("bazaT", baze["T"]),
        _attr("bazaA", baze["A"]),
        _attr("bazaP", baze["P"]),
        _attr("bazaS", baze["S"]),
        _attr("bazaR", baze["R"]),
        _attr("total_baza", total_baza),
    ])
    lines.append(f"  <rezumat {rezumat_attrs}/>")

    # operatiuni
    for op in operatori:
        op_attrs = " ".join([
            _attr("tip", op.tip),
            _attr("tara", op.tara.upper()),
            _attr("codO", _curata_text(op.cod_operator).replace(" ", "")),
            _attr("denO", _curata_text(op.denumire)),
            _attr("baza", int(round(op.baza))),
        ])
        lines.append(f"  <operatie {op_attrs}/>")

    lines.append("</declaratie390>")

    return "\n".join(lines)


# ============================================================
#       HELPER: construieste operatorul Bolt dintr-o baza
# ============================================================

def operator_bolt(baza_lei: int) -> OperatorIntracom:
    """
    Construieste rapid operatorul Bolt pentru D390 (achizitie servicii).

    Args:
        baza_lei: baza impozabila in lei (comisionul Bolt, fara TVA, intreg)
    """
    return OperatorIntracom(
        tip="S",                       # achizitie intracomunitara de servicii
        tara="EE",                     # Estonia
        cod_operator="102090374",      # VAT Bolt Operations OU
        denumire="BOLT OPERATIONS OU",
        baza=int(round(baza_lei)),
    )


# ============================================================
#       GHID DE COMPLETARE (Drumul A — copiezi in formular)
# ============================================================

# nume luni pentru afisare
_LUNI = {
    1: "Ianuarie", 2: "Februarie", 3: "Martie", 4: "Aprilie",
    5: "Mai", 6: "Iunie", 7: "Iulie", 8: "August",
    9: "Septembrie", 10: "Octombrie", 11: "Noiembrie", 12: "Decembrie",
}

_TIP_NUME = {
    "L": "Livrare intracom. bunuri",
    "T": "Livrare op. triunghiulara",
    "A": "Achizitie intracom. bunuri",
    "P": "Prestare intracom. servicii",
    "S": "Achizitie intracom. servicii",
    "R": "Livrare regim special agricultori",
}


def genereaza_ghid_d390(
    an: int,
    luna: int,
    identitate: IdentitateDeclarant,
    operatori: List[OperatorIntracom],
    d_rec: int = 0,
    plain: bool = False,
) -> str:
    """
    Genereaza un GHID DE COMPLETARE D390 — valorile exacte de pus in
    formularul PDF ANAF, casuta cu casuta.

    Pentru Drumul A: utilizatorul deschide formularul gol, copiaza aceste
    valori, da Validare, semneaza, depune.

    Args:
        plain: daca True, fara emoji/markdown (pentru loguri / text simplu).
               Daca False, format placut pentru Telegram/dashboard.
    """
    cui = _curata_cui(identitate.cui)
    den = _curata_text(identitate.denumire)
    adresa = _curata_text(identitate.adresa)
    luna_nume = _LUNI.get(luna, str(luna))

    # totaluri pe tip + suma de control (ca in XML)
    baze = {"L": 0, "T": 0, "A": 0, "P": 0, "S": 0, "R": 0}
    for op in operatori:
        baze[op.tip] += int(round(op.baza))
    total_baza = sum(baze.values())
    nr_opi = len(operatori)
    suma_control = nr_opi + sum(baze.values())

    b = (lambda s: s) if plain else (lambda s: f"*{s}*")
    h = "" if plain else "📋 "
    sep = "──────────────────────────"

    L = []
    L.append(f"{h}{b(f'D390 — {luna_nume} {an}')}")
    L.append(f"_{'Declaratie initiala' if d_rec == 0 else 'Declaratie RECTIFICATIVA'}_" if not plain
             else ("Declaratie initiala" if d_rec == 0 else "Declaratie RECTIFICATIVA"))
    L.append(sep)
    L.append(f"{'' if plain else '🗓️ '}Perioada de raportare")
    L.append(f"   Anul: {b(an)}    Luna: {b(f'{luna:02d}')}")
    L.append("")
    L.append(f"{'' if plain else '🧾 '}{b('I. Date de identificare')}")
    L.append(f"   Cod fiscal (dupa RO): {b(cui)}")
    L.append(f"   Denumire: {den}")
    L.append(f"   Domiciliu fiscal: {adresa}")
    if identitate.telefon:
        L.append(f"   Telefon: {_curata_text(identitate.telefon)}")
    if identitate.email:
        L.append(f"   E-mail: {identitate.email.strip()}")
    L.append("")
    L.append(f"{'' if plain else '📊 '}{b('II. Rezumat (se completeaza automat in formular)')}")
    L.append(f"   Nr. total operatori: {b(nr_opi)}")
    L.append(f"   Suma de control: {b(suma_control)}")
    L.append("")
    L.append(f"{'' if plain else '📝 '}{b('III. Lista operatiuni')} — completeaza randurile:")
    for i, op in enumerate(operatori, 1):
        tipnum = _TIP_NUME.get(op.tip, op.tip)
        L.append(f"   {b(f'Rand {i}')}")
        L.append(f"      TIP: {b(op.tip)}  ({tipnum})")
        L.append(f"      TARA: {b(op.tara.upper())}")
        L.append(f"      COD OPERATOR: {b(op.cod_operator)}")
        L.append(f"      DENUMIRE: {op.denumire}")
        L.append(f"      BAZA IMPOZABILA: {b(int(round(op.baza)))}")
    L.append("")
    L.append(f"{'' if plain else '✍️ '}Declarant")
    L.append(f"   Nume: {b(_curata_text(identitate.nume_declarant))}   "
             f"Prenume: {b(_curata_text(identitate.prenume_declarant))}")
    L.append(f"   Functia: {b(_curata_text(identitate.functie_declarant))}")
    L.append(sep)
    if not plain:
        L.append("_Dupa completare: apasa VALIDARE, semneaza cu eToken, "
                 "incarca in SPV. D390 e doar declarativa — fara plata._")
    else:
        L.append("Dupa completare: Validare -> semnatura eToken -> depunere SPV. "
                 "D390 nu se plateste.")
    return "\n".join(L)


# ============================================================
#                    TEST / DEMO
# ============================================================

if __name__ == "__main__":
    # Reproduce exact D390-ul real al lui Stefan din Ianuarie 2026
    # (baza Bolt = 657 lei, conform PDF depus)
    identitate = IdentitateDeclarant(
        cui="53148882",  # codul special de TVA (NU CUI-ul PFA 53067338!)
        denumire="IARAI STEFAN PERSOANA FIZICA AUTORIZATA",
        adresa="JUD BISTRITA NASAUD MUN BISTRITA STR MESTEACANULUI NR15 ET 2 AP 2",
        nume_declarant="IARAI",
        prenume_declarant="STEFAN",
        functie_declarant="TITULAR",
        telefon="0756284346",
        email="iaraistefan@gmail.com",
    )

    operatori = [operator_bolt(baza_lei=657)]

    print("=" * 60)
    print("DRUMUL B — XML (pentru DUKIntegrator):")
    print("=" * 60)
    xml = genereaza_d390(an=2026, luna=1, identitate=identitate,
                         operatori=operatori, d_rec=0)
    print(xml)

    print()
    print("=" * 60)
    print("DRUMUL A — GHID DE COMPLETARE (pentru dashboard/Telegram):")
    print("=" * 60)
    ghid = genereaza_ghid_d390(an=2026, luna=1, identitate=identitate,
                               operatori=operatori, d_rec=0, plain=True)
    print(ghid)
