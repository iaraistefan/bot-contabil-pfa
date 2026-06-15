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
D100_NS_VERSION = "v2"  # CONFIRMAT empiric cu DUKIntegrator (01.06.2026)
D100_NAMESPACE = f"mfp:anaf:dgti:d100:declaratie:{D100_NS_VERSION}"
D100_XSD = "D100.xsd"

# Cota impozit nerezidenti NU se mai defineste aici. Sursa UNICA e
# app.domain.fiscal_profile.COTA_NEREZIDENT (depinde de certificatul de
# rezidenta fiscala, per platforma: Bolt 2%/16%, Uber 0%/16%). `cota` se
# paseaza explicit in fiecare functie — a presupune 2% pentru toti era bug #3.

# Codul de creanta (pozitia din nomenclatorul ANAF) pentru impozit nerezidenti
COD_CREANTA_NEREZIDENTI = "634"
DENUMIRE_CREANTA = "Impozit pe veniturile obtinute din Romania de nerezidenti - persoane juridice nerezidente"
# Cod bugetar pentru obligatia 634 — CONFIRMAT cu DUKIntegrator (cont unic)
COD_BUGETAR_634 = "20470101"

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


def calcul_impozit_nerezident(baza_comision_lei: float, cota: float) -> float:
    """
    Impozit nerezident = cota × baza comision, rotunjit la intreg (lei).

    `cota` vine din profilul user-ului (sursa unica fiscal_profile.COTA_NEREZIDENT:
    0.0 / 0.02 / 0.16 dupa CRF). NU exista cota hardcodata aici.

    Ridica ValueError la cota None/<=0: impozitul nu se calculeaza pentru
    cota 0 (scutit, ex. Uber cu certificat → D207) sau regim neconfigurat.
    """
    if cota is None or cota <= 0:
        raise ValueError(
            f"Cota nerezident invalida ({cota}). D100 nu se calculeaza la cota "
            f"0/neconfigurat — scutit (CRF) se declara in D207; neconfigurat "
            f"necesita setarea regimului nerezident."
        )
    return round(baza_comision_lei * cota, 0)


def calcul_scadenta(an: int, luna: int) -> str:
    """Scadenta D100 = 25 a lunii urmatoare perioadei de raportare (ZZ.LL.AAAA)."""
    luna_urm = luna + 1
    an_urm = an
    if luna_urm > 12:
        luna_urm = 1
        an_urm = an + 1
    return f"25.{luna_urm:02d}.{an_urm}"


def calcul_nr_evid_d100(an: int, luna: int, cod_oblig: str) -> str:
    """
    Numarul de evidenta a platii (23 cifre) pentru D100.
    Structura ANAF:
      Poz.1-2  : 10
      Poz.3-5  : cod obligatie (3 cifre)
      Poz.6-7  : 01
      Poz.8-11 : LLAA (sfarsit perioada raportare)
      Poz.12-17: ZZLLAA (scadenta platii)
      Poz.18   : 0
      Poz.19   : 0
      Poz.20-21: 00
      Poz.22-23: suma de control = ultimele 2 cifre din suma primelor 21 cifre
    """
    cod = str(cod_oblig).zfill(3)[-3:]
    ll = f"{luna:02d}"
    aa = f"{an % 100:02d}"
    # scadenta = 25 a lunii urmatoare
    luna_urm = luna + 1
    an_urm = an
    if luna_urm > 12:
        luna_urm = 1
        an_urm = an + 1
    scad = f"25{luna_urm:02d}{an_urm % 100:02d}"  # ZZLLAA
    primele21 = f"10{cod}01{ll}{aa}{scad}0000"  # 2+3+2+2+2+6+1+1+2 = 21
    suma = sum(int(c) for c in primele21)
    control = f"{suma % 100:02d}"
    return primele21 + control


# ============================================================
#                    GENERATOR XML D100 (Drumul B)
# ============================================================

def genereaza_d100(
    an: int,
    luna: int,
    identitate: IdentitateD100,
    baza_comision_lei: float,
    *,
    cota: float,
    d_rec: int = 0,
    suportat_de_bolt: bool = False,
) -> str:
    """
    Genereaza XML-ul D100 pentru impozitul nerezidenti (poz. 634).

    Args:
        baza_comision_lei: baza (comisionul Bolt) pe care se aplica `cota`
        cota: cota nerezident din profil (0.02 / 0.16). OBLIGATORIE si > 0.
        suportat_de_bolt: DEPRECATED — fara efect. Cu certificat de rezidenta,
                          impozitul se plateste de PFA din buzunar; deci
                          suma_de_plata = suma_datorata intotdeauna.

    ⚠️ GARDA (Strat 2 — date la ANAF): la cota None/<=0 ridica ValueError, deci
    e IMPOSIBIL sa iasa un XML D100 cu suma 0 sau cu o cota presupusa. Scutit
    (CRF→0%) se declara in D207; neconfigurat necesita setarea regimului.

    ⚠️ Verifica D100_NS_VERSION inainte de productie.
    """
    if not (2013 <= an <= 2099):
        raise ValueError(f"An invalid: {an}")
    if not (1 <= luna <= 12):
        raise ValueError(f"Luna invalida: {luna}")
    if cota is None or cota <= 0:
        raise ValueError(
            f"genereaza_d100: cota {cota} → niciun XML. D100 se genereaza doar "
            f"la cota > 0 (ex. Bolt 2%/16%). Scutit (0%)/neconfigurat NU produc XML."
        )

    cui = _curata_cui(identitate.cui)
    suma_datorata = int(calcul_impozit_nerezident(baza_comision_lei, cota))
    # Regula ANAF R17-20.1 (model 1): suma_plata = suma_dat - suma_redu.
    # Fara reducere, suma_plata = suma_dat. suma_ded si suma_rest NU se completeaza.
    suma_de_plata = suma_datorata

    den = _curata_text(identitate.denumire)
    adresa = _curata_text(identitate.adresa)
    nume = _curata_text(identitate.nume_declarant)
    prenume = _curata_text(identitate.prenume_declarant)
    functie = _curata_text(identitate.functie_declarant)

    # totalPlata_A = suma(suma_dat + suma_plata) [suma_ded/rest necompletate]
    total_plata_a = suma_datorata + suma_de_plata

    cod_bugetar = COD_BUGETAR_634
    scadenta = calcul_scadenta(an, luna)
    nr_evid = calcul_nr_evid_d100(an, luna, COD_CREANTA_NEREZIDENTI)

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    root_attrs = " ".join(a for a in [
        _attr("xmlns", D100_NAMESPACE),
        _attr("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance"),
        _attr("xsi:schemaLocation", f"{D100_NAMESPACE} {D100_XSD}"),
        _attr("luna", f"{luna:02d}"),
        _attr("an", an),
        _attr("d_anulare", d_rec),  # 0 = declaratie normala
        _attr("nume_declar", nume),
        _attr("prenume_declar", prenume),
        _attr("functie_declar", functie),
        _attr("cui", cui),
        _attr("den", den),
        _attr("adresa", adresa),
        _attr("totalPlata_A", total_plata_a),
    ] if a)
    lines.append(f"<declaratie100 {root_attrs}>")

    # suma_ded si suma_rest NU se completeaza pentru modelul 1 (regula R17-20.1)
    oblig_attrs = " ".join([
        _attr("cod_oblig", COD_CREANTA_NEREZIDENTI),
        _attr("cod_bugetar", cod_bugetar),
        _attr("scadenta", scadenta),
        _attr("nr_evid", nr_evid),
        _attr("suma_dat", suma_datorata),
        _attr("suma_plata", suma_de_plata),
    ])
    lines.append(f"  <obligatie {oblig_attrs}/>")
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
    *,
    cota: float,
    d_rec: int = 0,
    suportat_de_bolt: bool = False,
    plain: bool = False,
) -> str:
    """Ghid de completare D100 — valorile exacte pentru formular.

    `cota` (din profil) e folosita atat la suma cat si la afisarea cotei.
    Chemat doar pe calea generata (cota > 0); calcul_impozit_nerezident ridica
    ValueError la cota 0/None.
    """
    cui = _curata_cui(identitate.cui)
    luna_nume = _LUNI.get(luna, str(luna))
    suma_datorata = int(calcul_impozit_nerezident(baza_comision_lei, cota))
    # suportat_de_bolt e DEPRECATED si nu mai are efect: cu certificat de
    # rezidenta, impozitul 2% se plateste de PFA -> suma_de_plata = suma_datorata.
    suma_de_plata = suma_datorata

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
    L.append(f"   Cota: {cota * 100:.0f}% (CDI Romania-Estonia)")
    L.append(f"   Suma datorata: {b(suma_datorata)} lei")
    L.append(f"   {b(f'SUMA DE PLATA: {suma_de_plata} lei')}")
    L.append("")
    warn = (f"D100 e OBLIGATORIU lunar pentru comisionul Bolt "
            f"(impozit nerezident {cota * 100:.0f}%). Se depune pana pe 25 a "
            f"lunii urmatoare. Impozitul se plateste din buzunar, suplimentar "
            f"fata de comisionul Bolt.")
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

    # Ianuarie 2026: comision Bolt 657 lei. Cota din profil (ex. BOLT_CU_CRF → 2%).
    print("=" * 60)
    print("DRUMUL B — XML D100 (cota 2% = BOLT_CU_CRF, suma datorata):")
    print("=" * 60)
    print(genereaza_d100(an=2026, luna=1, identitate=identitate,
                         baza_comision_lei=657, cota=0.02))
    print()
    print("=" * 60)
    print("DRUMUL A — GHID D100 (cota 16% = BOLT_FARA_CRF):")
    print("=" * 60)
    print(genereaza_ghid_d100(an=2026, luna=1, identitate=identitate,
                              baza_comision_lei=657, cota=0.16,
                              plain=True))
