"""
Generator pentru Declaratia 100 — Declaratie privind obligatiile de plata
la bugetul de stat.

CAZUL DE UTILIZARE (PFA ridesharing Bolt):
  - impozit pe veniturile nerezidentilor (poz. 634), cota 2%
  - conform Conventiei de evitare a dublei impuneri Romania-Estonia (art. 12),
    comisionul platit catre Bolt Operations OU se impoziteaza in Romania cu 2%
  - beneficiarul (PFA) retine si vireaza acest impozit

  ⚠️ ATENTIE FISCALA IMPORTANTA:
    Din 2023, in practica Bolt suporta singur acesti 2% (ii retine din
    comision si ii vireaza). De aceea suma de plata efectiva poate fi 0
    pentru tine. VERIFICA in SPV / cu un contabil daca mai ai de depus D100
    si cu ce valoare. Botul calculeaza 2% × baza, dar tu confirmi daca se
    aplica sau e suportat de Bolt.

  - D100 se depune pe CUI-ul PFA (53067338), NU pe codul special TVA!
    (D100 = impozit pe venit nerezidenti, nu are legatura cu TVA / D301)
  - se depune LUNAR (pana pe 25), pentru lunile cu factura Bolt

DOUA DRUMURI (ca la D301/D390):
  - genereaza_d100()      -> XML pentru DUKIntegrator (Drumul B)
  - genereaza_ghid_d100() -> ghid de completare (Drumul A)

⚠️ NAMESPACE DE CONFIRMAT (ca la D301): 'mfp:anaf:dgti:d100:declaratie:vN'.
   Pentru ghidul de completare (Drumul A) nu conteaza. Pentru XML, verifica
   empiric in DUKIntegrator si modifica D100_NS_VERSION mai jos.
"""

from dataclasses import dataclass
from datetime import date
from typing import List, Optional
from xml.sax.saxutils import escape
import unicodedata
import re


# ============================================================
#                    CONSTANTE
# ============================================================

# ⚠️ DE CONFIRMAT EMPIRIC
D100_NS_VERSION = "v6"
D100_NAMESPACE = f"mfp:anaf:dgti:d100:declaratie:{D100_NS_VERSION}"
D100_XSD = "D100.xsd"

# Cota impozit nerezidenti pentru comisioane (CDI Romania-Estonia)
COTA_NEREZIDENT_EE = 0.02  # 2%

# Codul de creanta (pozitia din nomenclatorul ANAF) pentru impozit nerezidenti
COD_CREANTA_NEREZIDENTI = "634"
DENUMIRE_CREANTA = "Impozit pe veniturile obtinute din Romania de nerezidenti - persoane juridice nerezidente"

_LUNI = {
    1: "Ianuarie", 2: "Februarie", 3: "Martie", 4: "Aprilie",
    5: "Mai", 6: "Iunie", 7: "Iulie", 8: "August",
    9: "Septembrie", 10: "Octombrie", 11: "Noiembrie", 12: "Decembrie",
}


# ============================================================
#                    DATACLASSES
# ============================================================

@dataclass
class IdentitateD100:
    """Datele de identificare pentru D100 (pe CUI-ul PFA, nu codul special)."""
    cui: str               # CUI PFA (ex. "53067338"), NU codul special TVA!
    denumire: str
    adresa: str
    nume_declarant: str
    prenume_declarant: str
    functie_declarant: str = "TITULAR"


# ============================================================
#                    HELPERS
# ============================================================

def _curata_text(text: str) -> str:
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    fara = "".join(c for c in nfkd if not unicodedata.combining(c))
    curatat = re.sub(r"[^A-Za-z0-9 +\-.@/]", " ", fara)
    return re.sub(r"\s+", " ", curatat).strip()


def _curata_cui(cui: str) -> str:
    return re.sub(r"\D", "", str(cui))


def _attr(name: str, value) -> str:
    return f'{name}="{escape(str(value), {chr(34): "&quot;"})}"'


def _attr_opt(name: str, value) -> str:
    """Atribut optional: omis complet daca valoarea e goala (ANAF respinge atribute vide)."""
    if value is None or str(value).strip() == "":
        return ""
    return _attr(name, value)


def calcul_impozit_nerezident(baza_comision_lei: float) -> float:
    """Impozit nerezident = 2% × baza comision, rotunjit la intreg (lei)."""
    return round(baza_comision_lei * COTA_NEREZIDENT_EE, 0)


# ============================================================
#                    GENERATOR XML D100 (Drumul B)
# ============================================================

def genereaza_d100(
    an: int,
    luna: int,
    identitate: IdentitateD100,
    baza_comision_lei: float,
    d_rec: int = 0,
    suportat_de_bolt: bool = False,
) -> str:
    """
    Genereaza XML-ul D100 pentru impozitul nerezidenti (poz. 634).

    Args:
        baza_comision_lei: baza (comisionul Bolt) pe care se aplica 2%
        suportat_de_bolt: daca True, suma_de_plata = 0 (Bolt a retinut deja),
                          dar suma_datorata ramane calculata informativ

    ⚠️ Verifica D100_NS_VERSION inainte de productie.
    """
    if not (2013 <= an <= 2099):
        raise ValueError(f"An invalid: {an}")
    if not (1 <= luna <= 12):
        raise ValueError(f"Luna invalida: {luna}")

    cui = _curata_cui(identitate.cui)
    suma_datorata = int(calcul_impozit_nerezident(baza_comision_lei))
    suma_de_plata = 0 if suportat_de_bolt else suma_datorata

    den = _curata_text(identitate.denumire)
    adresa = _curata_text(identitate.adresa)
    nume = _curata_text(identitate.nume_declarant)
    prenume = _curata_text(identitate.prenume_declarant)
    functie = _curata_text(identitate.functie_declarant)

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    root_attrs = " ".join([
        _attr("xmlns", D100_NAMESPACE),
        _attr("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance"),
        _attr("xsi:schemaLocation", f"{D100_NAMESPACE} {D100_XSD}"),
        _attr("luna", f"{luna:02d}"),
        _attr("an", an),
        _attr("d_rec", d_rec),
        _attr("cui", cui),
        _attr("den", den),
        _attr("adresa", adresa),
        _attr("nume_declar", nume),
        _attr("prenume_declar", prenume),
        _attr("functie_declar", functie),
        _attr("totalPlata_A", suma_de_plata),
    ])
    lines.append(f"<declaratie100 {root_attrs}>")

    creanta_attrs = " ".join([
        _attr("nr_rand", 1),
        _attr("atribut_id", COD_CREANTA_NEREZIDENTI),
        _attr("denumire_creanta", DENUMIRE_CREANTA),
        _attr("suma_datorata", suma_datorata),
        _attr("suma_deductibila", 0),
        _attr("suma_de_plata", suma_de_plata),
    ])
    lines.append(f"  <creanta {creanta_attrs}/>")
    lines.append("</declaratie100>")
    return "\n".join(lines)


# ============================================================
#       GHID DE COMPLETARE D100 (Drumul A)
# ============================================================

def genereaza_ghid_d100(
    an: int,
    luna: int,
    identitate: IdentitateD100,
    baza_comision_lei: float,
    d_rec: int = 0,
    suportat_de_bolt: bool = False,
    plain: bool = False,
) -> str:
    """Ghid de completare D100 — valorile exacte pentru formular."""
    cui = _curata_cui(identitate.cui)
    luna_nume = _LUNI.get(luna, str(luna))
    suma_datorata = int(calcul_impozit_nerezident(baza_comision_lei))
    suma_de_plata = 0 if suportat_de_bolt else suma_datorata

    b = (lambda s: s) if plain else (lambda s: f"*{s}*")
    h = "" if plain else "📋 "
    sep = "──────────────────────────"

    L = []
    L.append(f"{h}{b(f'D100 — Obligatii de plata — {luna_nume} {an}')}")
    L.append("Declaratie initiala" if d_rec == 0 else "Declaratie RECTIFICATIVA")
    L.append(sep)
    L.append("Perioada de raportare")
    L.append(f"   Anul: {b(an)}    Luna: {b(f'{luna:02d}')}")
    L.append("")
    L.append(f"{'' if plain else '🧾 '}{b('Date de identificare')}")
    L.append(f"   Cod fiscal (dupa RO): {b(cui)}   "
             + ("(CUI PFA — NU codul special!)" if plain else "_(CUI PFA — NU codul special!)_"))
    L.append(f"   Denumire: {_curata_text(identitate.denumire)}")
    L.append(f"   Adresa: {_curata_text(identitate.adresa)}")
    L.append("")
    L.append(f"{'' if plain else '📝 '}{b('Creanta (poz. 634 — impozit nerezidenti)')}")
    L.append(f"   Baza (comision Bolt): {baza_comision_lei:.0f} lei")
    L.append(f"   Cota: 2% (CDI Romania-Estonia)")
    L.append(f"   Suma datorata: {b(suma_datorata)} lei")
    L.append(f"   {b(f'SUMA DE PLATA: {suma_de_plata} lei')}")
    L.append("")
    if suportat_de_bolt or suma_de_plata == 0:
        warn = ("ATENTIE: din 2023 Bolt suporta singur cei 2%. "
                "Verifica in SPV daca mai ai de depus/platit D100. "
                "Suma de plata poate fi 0.")
        L.append(warn if plain else f"⚠️ _{warn}_")
    else:
        warn = ("VERIFICA in SPV daca Bolt nu a retinut deja cei 2% "
                "(din 2023 ii suporta de obicei).")
        L.append(warn if plain else f"⚠️ _{warn}_")
    L.append("")
    L.append(f"{'' if plain else '✍️ '}Declarant: {_curata_text(identitate.nume_declarant)} "
             f"{_curata_text(identitate.prenume_declarant)} — "
             f"{_curata_text(identitate.functie_declarant)}")
    L.append(sep)
    if not plain:
        L.append("_D100 se depune pe CUI-ul PFA. Dupa completare: "
                 "VALIDARE -> eToken -> SPV._")
    else:
        L.append("D100 pe CUI PFA. Validare -> eToken -> SPV.")
    return "\n".join(L)


# ============================================================
#                    TEST / DEMO
# ============================================================

if __name__ == "__main__":
    identitate = IdentitateD100(
        cui="53067338",  # CUI PFA (NU codul special TVA 53148882!)
        denumire="IARAI STEFAN PERSOANA FIZICA AUTORIZATA",
        adresa="JUD BISTRITA NASAUD MUN BISTRITA STR MESTEACANULUI NR15 ET 2 AP 2",
        nume_declarant="IARAI",
        prenume_declarant="STEFAN",
        functie_declarant="TITULAR",
    )

    # Ianuarie 2026: comision Bolt 657 lei. Impozit 2% = 13 lei.
    print("=" * 60)
    print("DRUMUL B — XML D100 (suma datorata, daca NU e suportat de Bolt):")
    print("=" * 60)
    print(genereaza_d100(an=2026, luna=1, identitate=identitate,
                         baza_comision_lei=657, suportat_de_bolt=False))
    print()
    print("=" * 60)
    print("DRUMUL A — GHID D100 (cazul real: suportat de Bolt -> 0):")
    print("=" * 60)
    print(genereaza_ghid_d100(an=2026, luna=1, identitate=identitate,
                              baza_comision_lei=657, suportat_de_bolt=True,
                              plain=True))
