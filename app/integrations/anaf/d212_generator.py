"""
Generator XML pentru Declaratia Unica (D212) — PFA activitate independenta,
impusa in SISTEM REAL.

CAZUL DE UTILIZARE (PFA ridesharing Bolt/Uber):
  D212 e declaratia PERSONALA anuala: venitul net din activitate + CAS + CASS +
  impozit. Se depune pana pe 25 mai a anului urmator.

DE CE EXISTA ACEST GENERATOR — golul pe care il umple:
  Din 2026 ANAF precompleteaza D212 in SPV din declaratiile depuse de terti
  (D205, D112, C168). Ghidul oficial ANAF de precompletare spune explicit ca
  precompletarea NU acopera "veniturile din activitati independente". Pentru un
  PFA de ridesharing platit de platforme NEREZIDENTE (Bolt/Uber, care nu depun
  D205 in Romania), precompletarea vine GOALA exact pe partea grea. Aia e partea
  pe care o avem noi calculata, din bonuri si extrase reale.

CUM SE FOLOSESTE XML-UL (traseul confirmat pe surse ANAF, august 2026):
  Formularul D212 conform OpANAF 2736/2025 NU mai are PDF inteligent (Soft A) si
  nici validator Java (Soft J) — coloanele sunt goale pe pagina oficiala. In loc,
  ANAF publica un formular WEB (anaf.ro/declaratii/duf) care are buton
  "Importa fisier salvat" (accepta .xml) si "Salveaza datele in D212.xml".
  Deci: generam XML → userul il importa in formularul web → verifica si
  completeaza → "Genereaza fisier PDF pentru depunere" → depune prin SPV.
  ⚠️ DUKIntegrator NU poate valida acest XML: ultimul plugin D212 publicat de
  ANAF e J13.0.1 / 01.08.2025, pentru formularul VECHI (OpANAF 1929/2025).
  Validarea noastra e locala: XSD + Schematron oficial (vezi tests/).

CE COMPLETAM (partea de CALCUL, cea pe care o avem):
  - cap11: venit brut, cheltuieli deductibile, venit net, venit net recalculat
  - Sectiunea 3.1 CAS: baza + CAS datorat
  - Sectiunea 3.2 CASS: total venituri, baza, CASS anuala/datorata
  - Sectiunea 4: CAS/CASS deductibile, venit net impozabil, impozit datorat
  - Obligatii: impozit, diferenta de plata
  - Bifele: DERIVATE din starea reala (CAS > 0 → bifa131=1 etc.). Singura
    exceptie e bifa18, fixa pe 0 — motivul e in NOTA-BONIFICATIE (d212_calc.py).

CE LASAM GOL, DELIBERAT — si de ce:
  Formularul web ANAF e EDITABIL dupa import. Ce nu putem sti cu certitudine
  lasam userul sa completeze, in loc sa inventam:
    - initiala tatalui (initiala_c)          — nu o avem in profil
    - nr. + data certificatului ONRC         — nu le colectam nicaieri
      (nr_doc_autoriz / data_doc_autoriz)
    - statutul contribuabilului (statut)     — avem semnalele (is_salariat,
      is_pensionar) dar nu codul din nomenclatorul ANAF
    - pierderi reportate din anii precedenti — nu tinem evidenta multi-an
      (pierdere_precedenta / pierdere_compensata)
  Nu ne trebuie acoperire totala ca sa fim utili. Ne trebuie partea grea.

  EXCEPTIE de la "lasam gol": nume_c si prenume_c sunt use="required" in XSD,
  iar Schematron-ul ANAF (SN-D212-002) respinge atributele vide. Un fisier fara
  ele nu e doar incomplet, e INVALID — deci inutil. Le cerem apelantului ca
  parametri OBLIGATORII; nu le ghicim spargand firma_nume.

STRUCTURA XML (confirmata contra XSD-ului oficial d212_schema.xsd,
namespace mfp:anaf:dgti:d212:declaratie:v11, vendorizat in scheme/d212/):
  <d212 d_rec rectif1 rectif2 luna_r=12 an_r bifa* nume_c prenume_c cif
        nerezident totalPlata_A ...>
    <oblig_realizat .../>   ← Sectiunile 3 + 4 + obligatii (CAS/CASS/impozit)
    <cap11 .../>            ← Cap. I Sect. 1 Subsect. 1 (sistem real)
  </d212>
  ⚠️ ORDINEA CONTEAZA: oblig_realizat INAINTEA lui cap11 (secventa din XSD).

Toate sumele sunt INTREGI (lei) — N15Type in XSD e decimal cu fractionDigits=0.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional
from xml.sax.saxutils import escape
import os
import re
import unicodedata
import xml.etree.ElementTree as ET


# ============================================================
#                    CONSTANTE
# ============================================================

# Namespace v11 = formularul conform OpANAF 2736/2025 (cel cu formular web).
D212_NS_VERSION = "v11"
D212_NAMESPACE = f"mfp:anaf:dgti:d212:declaratie:{D212_NS_VERSION}"

# Luna raportarii: BR-D212-0005 cere FIX 12 (declaratie anuala).
D212_LUNA = 12

# Categoria de venit din Nomenclator_venituri_RO: 1016 = activitati independente.
# (CD-D212-015 valideaza contra listei; 1003 = drepturi de proprietate intelectuala.)
CATEG_VENIT_ACTIVITATI_INDEPENDENTE = "1016"

# Determinarea venitului net: 1 = sistem real, 2 = cote forfetare.
# BR: pentru categ_venit 1016 det_ven_net TREBUIE sa fie 1.
DET_VEN_NET_SISTEM_REAL = "1"

# Forma de organizare: 1 = individual (PFA), 2 = asociere fara personalitate juridica.
FORMA_ORG_INDIVIDUAL = "1"


# ============================================================
#         AN_R — CE INSEAMNA, SI DE UNDE IL LUAM
# ============================================================
#
# LANTUL DE DOVEZI (nu reface rationamentul, e facut si verificat):
#
# 1. Eticheta din documentatia de structura e ambigua. `an_r` e descris drept
#    "Anul de raportare", dar instructiunile oficiale folosesc EXACT aceeasi
#    expresie pentru anul veniturilor ("in anul de raportare, s-a inregistrat
#    pierdere fiscala"). Eticheta singura nu decide nimic.
#
# 2. Formularul are DOUA casete de an, nu una. Din instructiunile OpANAF
#    2736/2025: capitolul I "Date privind impozitul pe veniturile realizate si
#    contributiile sociale datorate pentru anul ........" si capitolul II
#    "Date privind contributia de asigurari sociale de sanatate datorata de
#    catre persoanele fizice care opteaza pentru plata contributiei pentru
#    anul .......".
#
# 3. XML-ul are UN SINGUR atribut de an (`an_r`, pe radacina). Deci nu poate fi
#    anul ambelor capitole — unul dintre ele ramane implicit.
#
# 4. BR-D212-0023 decide care: cere ca `data_incep`, `data_sf`, `data_suspendare`
#    (si perechile lor de la norma/strainatate) sa aiba anul egal cu `an_r - 1`.
#    Alea sunt datele de desfasurare a activitatii din Capitolul I, adica
#    perioada in care s-a produs venitul declarat.
#
# CONCLUZIE: `an_r` = anul Capitolului II (optiunea CASS) = anul DEPUNERII.
# Anul veniturilor din Capitolul I e `an_r - 1` si NU are camp propriu in XML.
# De aceea generatorul primeste `an_venituri` si scrie `an_r = an_venituri + 1`.
#
# ⚠️ Anul NU vine niciodata din ceasul sistemului. Vine din anul de calcul,
#    pasat explicit. O declaratie pe 2025 depusa cu intarziere in 2027 tot
#    an_r=2026 trebuie sa poarte.

# Fisierul din care citim anul acoperit. Modul de esec conteaza: daca ANAF
# reformuleaza regula, vrem sa ne oprim, nu sa ghicim (vezi _extrage_an_r_impus).
CALE_REGULI_BUSINESS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "scheme", "d212", "business", "d212-business.sch")

_SCHEMATRON_NS = "{http://purl.oclc.org/dsdl/schematron}"
_an_impus_cache = {}


def _extrage_an_r_impus(cale: str) -> int:
    """Citeste din BR-D212-0006 anul de raportare pe care il impune pachetul ANAF.

    Regula, in `business/d212-business.sch`, arata asa:

        <rule context="//@*[name(.) = 'an_r']">
          <let name="an" value="number(normalize-space(.))"/>
          <let name="isValid" value="$an = 2026"/>
          <assert test="$isValid" flag="fatal" id="BR-D212-0006"> ... </assert>
        </rule>

    Il DERIVAM in loc sa-l hardcodam: cand ANAF publica pachetul pentru anul
    urmator si cineva inlocuieste fisierele din scheme/d212/, generatorul se
    adapteaza fara nicio schimbare de cod. Sursa unica pe valoare, aplicata si
    pe justificare.

    Raises:
        RuntimeError: daca anul NU poate fi extras. Deliberat NU exista implicit:
            un fallback tacit ar reface exact problema pe care o reparam —
            generatorul ar pretinde iar un domeniu pe care nu-l poate onora.
            Mai bine ne oprim zgomotos decat sa emitem fisiere nevalidabile.
    """
    if cale in _an_impus_cache:
        return _an_impus_cache[cale]

    def opreste(motiv: str):
        raise RuntimeError(
            f"Nu pot citi anul de raportare impus de BR-D212-0006 din {cale}: "
            f"{motiv}. Probabil ANAF a reformulat regula in pachetul nou. "
            f"Verifica fisierul si actualizeaza _extrage_an_r_impus — pana atunci "
            f"NU generam D212, ca sa nu producem fisiere pe care nu le putem valida."
        )

    try:
        radacina = ET.parse(cale).getroot()
    except (OSError, ET.ParseError) as e:
        opreste(f"fisierul nu poate fi citit sau parsat ({e})")

    for regula in radacina.iter(_SCHEMATRON_NS + "rule"):
        if not any(a.get("id") == "BR-D212-0006"
                   for a in regula.iter(_SCHEMATRON_NS + "assert")):
            continue
        for let in regula.iter(_SCHEMATRON_NS + "let"):
            potrivire = re.search(r"\$an\s*=\s*(\d{4})", let.get("value") or "")
            if potrivire:
                an = int(potrivire.group(1))
                _an_impus_cache[cale] = an
                return an
        opreste("am gasit regula BR-D212-0006 dar nu si comparatia `$an = <an>`")

    opreste("nu am gasit regula BR-D212-0006")


def anul_de_raportare_acoperit() -> int:
    """Anul `an_r` pe care il accepta pachetul de scheme vendorizat acum."""
    return _extrage_an_r_impus(CALE_REGULI_BUSINESS)


# ============================================================
#                    DATACLASSES
# ============================================================

@dataclass
class IdentitateD212:
    """Datele de identificare ale contribuabilului (persoana fizica, nu firma).

    nume/prenume sunt OBLIGATORII: XSD le cere, iar Schematron respinge valorile
    vide. Le primim de la apelant — nu le derivam din firma_nume.
    """
    cnp: str
    nume: str
    prenume: str
    sediu: str                 # descriere_sediu_bun — BR-D212-0094 il cere pt 1016
    email: str = ""
    telefon: str = ""
    iban: str = ""


@dataclass
class ActivitateD212:
    """Activitatea declarata in cap11 (o singura sursa in v1).

    Certificatul ONRC (numar + data) e OBLIGATORIU, desi initial il pusesem pe
    lista "lasam gol": BR-D212-0095 cere nr_doc_autoriz pentru categ_venit 1016,
    iar BR-D212-0096 cere ca numarul si data sa existe impreuna sau deloc. Le
    primim de la apelant — nu inventam un numar de autorizatie.
    """
    caen: str
    den_caen: str
    nr_doc_autorizare: str
    data_doc_autorizare: date
    denumire_venit: str = "Venituri din activitati independente"
    # Datele se emit DOAR daca sunt in anul de raportare (BR-D212-0023 cere
    # anul = an_r - 1). Activitate inceputa in anii trecuti → se omit.
    data_incepere: Optional[date] = None
    data_incetare: Optional[date] = None


# ============================================================
#                    HELPERS (oglinda d207_generator)
# ============================================================

def _curata_text(text: str) -> str:
    """Diacritice → ASCII, caractere exotice → spatiu (ca la D100/D207)."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    fara = "".join(c for c in nfkd if not unicodedata.combining(c))
    curatat = re.sub(r"[^A-Za-z0-9 +\-.,@/]", " ", fara)
    return re.sub(r"\s+", " ", curatat).strip()


def _curata_cnp(cnp: str) -> str:
    return re.sub(r"\D", "", str(cnp or ""))


def _lei(valoare) -> int:
    """N15Type = decimal, fractionDigits=0, minInclusive=0 → intreg nenegativ."""
    return max(0, int(round(float(valoare or 0))))


def _attr(nume: str, valoare) -> str:
    return f'{nume}="{escape(str(valoare), {chr(34): "&quot;"})}"'


def _attr_opt(nume: str, valoare) -> str:
    """Atribut optional: OMIS complet daca e gol.

    Schematron-ul ANAF (SN-D212-002) respinge atributele prezente-dar-vide, deci
    'nu stim' se scrie ca absenta, niciodata ca "".
    """
    if valoare is None or str(valoare).strip() == "":
        return ""
    return _attr(nume, valoare)


def _data_ro(d: Optional[date], an_venituri: int) -> str:
    """Data in format zz.ll.aaaa, DOAR daca e in anul de raportare.

    BR-D212-0023: anul oricarei date din declaratie trebuie sa fie an_r - 1.
    O activitate inceputa in 2019 nu se poate declara intr-un D212 pe 2025 —
    se omite, nu se falsifica.
    """
    if d is None or d.year != an_venituri:
        return ""
    return d.strftime("%d.%m.%Y")


def _suma_cifrelor(text: str) -> int:
    """BR-D212-0004: totalPlata_A = suma cifrelor din CNP. Suma de control ciudata,
    dar asta e regula."""
    return sum(int(c) for c in text if c.isdigit())


# ============================================================
#              GENERATOR XML D212
# ============================================================

def genereaza_d212(
    an_venituri: int,
    identitate: IdentitateD212,
    activitate: ActivitateD212,
    rezultat,
    *,
    d_rec: int = 0,
) -> str:
    """
    Genereaza XML-ul D212 conform XSD-ului oficial ANAF (namespace v11).

    Args:
        an_venituri: anul in care s-au realizat veniturile (ex. 2025).
            an_r din declaratie = an_venituri + 1 (BR-D212-0006/0023).
        identitate: datele persoanei fizice (CNP, nume, prenume, sediu)
        activitate: CAEN + denumire + eventuale date de incepere/incetare
        rezultat: RezultatD212 din app.integrations.anaf.d212_calc — sursa UNICA
            a cifrelor. Generatorul NU recalculeaza nimic, doar transcrie.
        d_rec: 0 = declaratie initiala, 1 = rectificativa

    Returns:
        XML-ul D212 ca string UTF-8, gata de scris in D212.xml pentru importul
        in formularul web ANAF.

    Raises:
        ValueError: date invalide (an, CNP, regim neacoperit de v1)
    """
    # Domeniul NU e un interval inventat de noi: e exact anul pe care il valideaza
    # pachetul de scheme din scheme/d212/. Inainte acceptam 2018-2100 si produceam
    # pentru orice alt an fisiere pe care propriul nostru Schematron le respingea —
    # adica promiteam un domeniu pe care nu-l puteam onora.
    an_r_acoperit = anul_de_raportare_acoperit()
    an_r = an_venituri + 1
    if an_r != an_r_acoperit:
        raise ValueError(
            f"Pot genera fisierul D212 doar pentru veniturile din "
            f"{an_r_acoperit - 1} — pachetul de scheme oficiale ANAF pe care il "
            f"avem vendorizat (scheme/d212/) valideaza exclusiv declaratia cu "
            f"an_r={an_r_acoperit}. Ai cerut veniturile din {an_venituri} "
            f"(ar da an_r={an_r}), pentru care n-am schema. "
            f"Pentru alt an descarca pachetul corespunzator de la ANAF "
            f"(www.anaf.ro/declaratii/doc/d212.zip) — vezi PROVENIENTA.md."
        )

    regim = getattr(rezultat, "regim", "SISTEM_REAL")
    if regim != "SISTEM_REAL":
        raise ValueError(
            f"v1 genereaza D212 doar pentru SISTEM_REAL (primit: {regim}). "
            "Norma de venit se declara in cap12, cu alta structura — nu o "
            "aproximam cu cap11."
        )

    cnp = _curata_cnp(identitate.cnp)
    if len(cnp) != 13:
        raise ValueError(
            f"CNP invalid pentru D212: {len(cnp)} cifre (asteptate 13). "
            "Fara CNP corect, declaratia nu se poate depune."
        )
    if not _curata_text(identitate.nume) or not _curata_text(identitate.prenume):
        raise ValueError(
            "Nume si prenume sunt obligatorii in D212 (XSD: use=required). "
            "Nu le derivam din denumirea PFA — le cerem explicit."
        )
    if not _curata_text(activitate.nr_doc_autorizare):
        raise ValueError(
            "Nr. certificatului de inregistrare ONRC e obligatoriu pentru "
            "activitati independente (BR-D212-0095). Nu inventam un numar."
        )
    if activitate.data_doc_autorizare is None:
        # Lipsa asta e ASTEPTATA: data certificatului se confirma de user la
        # configurare si se poate sari peste. Cand se sare, aici trebuie sa se
        # vada ce lipseste si de unde se completeaza — nu un AttributeError pe
        # strftime(None).
        raise ValueError(
            "Data certificatului ONRC lipseste. BR-D212-0096 o cere impreuna cu "
            "numarul (iar numarul e obligatoriu prin BR-D212-0095), deci fara ea "
            "declaratia nu se poate genera. O completezi in profil — ti-o "
            "pre-completam din ANAF, tu doar confirmi ce scrie pe certificat."
        )

    # ---- cifrele, transcrise din motorul de calcul (nu recalculate) ----
    venit_brut = _lei(rezultat.venit_brut)
    cheltuieli = _lei(rezultat.cheltuieli)
    venit_net = _lei(rezultat.venit_net)
    cas = _lei(rezultat.cas)
    cas_baza = _lei(rezultat.cas_baza)
    cass = _lei(rezultat.cass)
    cass_baza = _lei(rezultat.cass_baza)
    venit_impozabil = _lei(rezultat.venit_impozabil)
    impozit = _lei(rezultat.impozit)

    # ---- bifele: DERIVATE din starea reala, nu fixate ----
    # (in fisierul de test initial erau hardcodate pe 0, ceea ce pentru un venit
    #  real inseamna "nu datorez CAS/CASS" — fals fiscal.)
    bifa131 = 1 if cas > 0 else 0                    # Sectiunea 3.1 — CAS
    bifa132 = 1 if cass > 0 else 0                   # Sectiunea 3.2 — CASS
    bifa14 = 1 if impozit > 0 else 0                 # Sectiunea 4 — impozit anual

    # bifa_cas_real: 1 = venit intre 12 si 24 salarii minime, 2 = peste 24.
    # BR-D212-0047 leaga bifa de pragul bazei; derivam din baza aleasa de motor.
    bifa_cas_real = ""
    if bifa131:
        salariu_minim = int(getattr(rezultat, "salariu_minim", 0) or 0)
        bifa_cas_real = 2 if (salariu_minim and cas_baza >= 24 * salariu_minim) else 1

    # ---- Sectiunea 4: ponderea venitului din sistem real in total venituri ----
    # O singura sursa de venit din activitati independente → ponderea e 1 si
    # CAS/CASS deductibile = CAS/CASS integral. Cand vor exista mai multe surse,
    # ponderea trebuie calculata, nu presupusa.
    pondere = 1
    cas_deductibil = cas
    cass_deductibil = cass

    # ---- antet ----
    atribute_radacina = [
        _attr("xmlns", D212_NAMESPACE),
        _attr("d_rec", 1 if d_rec else 0),
        _attr("rectif1", 0),
        _attr("rectif2", 0),
        _attr("luna_r", D212_LUNA),
        _attr("an_r", an_r),
        _attr("anulare_litA", 0),
        _attr("anulare_litB", 0),
        _attr("bifa_conformare", 0),
        _attr("bifa111", 1),          # avem cap11 (sistem real) — BR-D212-0007
        _attr("bifa112", 0),
        _attr("bifa113", 0),
        _attr("bifa121", 0),
        _attr("bifa122", 0),
        _attr("bifa131", bifa131),
        _attr("bifa132", bifa132),
        _attr("bifa14", bifa14),
        _attr("bifa15", 0),
        # FIX 0, deliberat — nu derivata ca bifa131/132/14. XSD cere atributul
        # (use="required"), dar sectiunea pe care o comanda nu are temei legal
        # pentru niciun an pe care il servim: vezi NOTA-BONIFICATIE in
        # d212_calc.py. Starea reala e "nu se datoreaza nimic aici", pe orice an,
        # deci 0 NU e o valoare implicita lenesa — e cifra corecta.
        _attr("bifa18", 0),
        _attr("bifa19", 0),
        _attr("bifa23", 0),
        _attr("nume_c", _curata_text(identitate.nume)),
        # initiala_c: LASAT GOL deliberat — nu o avem in profil.
        _attr("prenume_c", _curata_text(identitate.prenume)),
        _attr("cif", cnp),
        _attr("nerezident", 0),
        _attr_opt("telefon_c", _curata_text(identitate.telefon)),
        _attr_opt("email_c", identitate.email.strip()),
        _attr_opt("cont_bancar", _curata_text(identitate.iban).upper()),
        # statut: LASAT GOL deliberat — avem semnalele, nu codul ANAF.
        _attr("totalPlata_A", _suma_cifrelor(cnp)),
    ]

    linii = ['<?xml version="1.0" encoding="UTF-8"?>']
    linii.append("<d212 " + " ".join(a for a in atribute_radacina if a) + ">")

    # ---- oblig_realizat: Sectiunile 3 + 4 + obligatii (INAINTEA lui cap11) ----
    #
    # ⚠️ REQUIRED-BY-SCHEMA / IGNORED-BY-FORM. Nu incerca sa scoti elementul asta
    #    "ca optimizare" — pare balast, dar schema il impune. Ambele jumatati sunt
    #    masurate, nu presupuse (probe pe formularul public, 11-12 august 2026):
    #
    #    REQUIRED: un fisier identic dar FARA <oblig_realizat>, cu aceleasi bife,
    #    e respins de Schematron cu 11 esecuri — BR-D212-0041/0042/0043/0045/0046/
    #    0048/0049/0052/0053 (toate de forma "daca bifa131=1 atunci <camp> trebuie
    #    completat") plus BR-D212-0054/0055 pe CASS. Deci cat timp bifele sunt pe 1,
    #    elementul nu e optional.
    #
    #    IGNORED: la import, formularul a afisat CAS 0 si impozit 6750, desi
    #    fisierul continea cas_datorat=12150 si real_impozit_datorat_ai=5535.
    #    Formularul recalculeaza din cap11 + bife: 75000 - 0 - 7500 = 67500, x10%.
    #    Cifrele noastre de aici nu ajung in declaratie.
    #
    #    Consecinta practica: valorile trebuie sa fie COERENTE INTRE ELE (ca sa
    #    treaca de Schematron), nu neaparat sa fie citite de cineva. Iar CAS-ul
    #    userul trebuie sa-l introduca manual in formular — vezi ghidul.
    atribute_oblig = []
    if bifa131:
        atribute_oblig += [
            _attr("bifa_cas_real", bifa_cas_real),
            # BR-D212-0042/0043: ambele bife trebuie completate cand bifa131=1.
            # Cazul standard (venit peste plafonul intreg, an complet) → 0 la ambele.
            _attr("bifa_cas_recalculat", 0),
            _attr("bifa_cas_sub_plafon", 0),
            _attr("cas_total_ven", venit_net),   # total venituri din activ. independente
            _attr("cas_baza", cas_baza),         # venitul ALES pentru CAS (vezi ghid)
            _attr("cas_datorat", cas),
            # BR-D212-0052/0053: cas_dif_plus = cas_datorat - cas_retinut_platitor.
            # Platformele nerezidente nu retin CAS la sursa → retinut 0 → dif = CAS.
            #
            # ⚠️ cas_retinut_platitor="0" pare redundant (regula zice "daca lipseste
            # se considera 0") dar e OBLIGATORIU: implementarea ANAF calculeaza
            #   number(exists(@cas_retinut_platitor)) * number(@cas_retinut_platitor)
            # iar cand atributul lipseste asta devine 0 * NaN = NaN, nu 0, si regula
            # pica. Scriem 0 explicit — e si adevarat (nimeni nu ne-a retinut CAS).
            _attr("cas_retinut_platitor", 0),
            _attr("cas_dif_plus", cas),
        ]
    if bifa132:
        atribute_oblig += [
            _attr("bifa_cass_datorat_ai", 1),
            # BR-D212-0055: bifa_cass_datorat_dpi trebuie sa existe cand bifa132=1.
            # 0 = nu avem venituri din DPI/chirii/investitii, doar activitate independenta.
            _attr("bifa_cass_datorat_dpi", 0),
            _attr("cass_total_ven_ai", venit_net),
            _attr("baza_cass_datorat_ai", cass_baza),
            _attr("cass_anuala_ai", cass),
            # BR-D212-0060: cass_datorat_ai = cass_anuala_ai - cass_datorat_art180_ai.
            # art.180 = optiunea de plata CASS a celor NEobligati; noi suntem obligati → 0.
            _attr("cass_datorat_art180_ai", 0),
            _attr("cass_datorat_ai", cass),
        ]
    if bifa14:
        atribute_oblig += [
            # Sectiunea 4 — stabilirea impozitului anual
            _attr("real_venit_net_recalculat_ai", venit_net),
            _attr("real_cas-deduc_ai", cas_deductibil),
            _attr("real_cass-deductibil_ai", cass_deductibil),
            _attr("real_venit_net_impozabil_ai", venit_impozabil),
            _attr("real_impozit_datorat_ai", impozit),
            # Subsectiunea 4.1 — CAS deductibila (pondere)
            _attr("real_cas_venit_net_ai", venit_net),
            _attr("real_cas_total_ven_ai", venit_net),
            _attr("real_cas_pondere_ai", pondere),
            _attr("real_cas_datorata_ai", cas),
            _attr("real_cas_deductibila_ai", cas_deductibil),
            # Subsectiunea 4.2 — CASS deductibila (pondere)
            _attr("real_cass_venit_net_ai", venit_net),
            _attr("real_cass_total_ven_ai", venit_net),
            _attr("real_cass_pondere_ai", pondere),
            _attr("real_cass_datorata_ai", cass),
            _attr("real_cass_calculata_ai", cass),
            _attr("real_cass_deductibila_ai", cass_deductibil),
            # Obligatii de plata
            _attr("oblimpoz_real_total", impozit),
        ]
    # oblimpozit_real_bonif NU se emite niciodata (XSD: use="optional", deci
    # absenta lui e valida). Declaratia spune ce se datoreaza.

    if atribute_oblig:
        linii.append("  <oblig_realizat " + " ".join(a for a in atribute_oblig if a) + "/>")

    # ---- cap11: Cap. I, Sectiunea 1, Subsectiunea 1 (sistem real) ----
    atribute_cap11 = [
        _attr("categ_venit", CATEG_VENIT_ACTIVITATI_INDEPENDENTE),
        _attr("den_venit", _curata_text(activitate.denumire_venit)),
        _attr("det_ven_net", DET_VEN_NET_SISTEM_REAL),
        _attr("forma_org", FORMA_ORG_INDIVIDUAL),
        _attr("caen", _curata_text(activitate.caen)),
        _attr_opt("den_caen", _curata_text(activitate.den_caen)),
        _attr("descriere_sediu_bun", _curata_text(identitate.sediu)),
        # nr_doc_autoriz: OBLIGATORIU prin BR-D212-0095 pentru categ_venit 1016.
        # data_doc_autoriz: obligatorie prin BR-D212-0096 (pereche cu numarul).
        # Nu intra sub BR-D212-0023 (anul = an_r-1), deci un certificat din 2019 e ok.
        _attr("nr_doc_autoriz", _curata_text(activitate.nr_doc_autorizare)),
        _attr("data_doc_autoriz", activitate.data_doc_autorizare.strftime("%d.%m.%Y")),
        _attr_opt("data_incep", _data_ro(activitate.data_incepere, an_venituri)),
        _attr_opt("data_sf", _data_ro(activitate.data_incetare, an_venituri)),
        _attr("venit_brut", venit_brut),
        _attr("chelt_deduc", cheltuieli),
        _attr("venit_net_anual", venit_net),
        # pierdere_precedenta / pierdere_compensata: LASATE GOALE (fara evidenta multi-an).
        # BR-D212-0107: venit_recalculat = venit_net_anual - pierdere_compensata.
        _attr("venit_recalculat", venit_net),
    ]
    linii.append("  <cap11 " + " ".join(a for a in atribute_cap11 if a) + "/>")

    linii.append("</d212>")
    return "\n".join(linii)


# ============================================================
#              GHID DE COMPLETARE D212
# ============================================================

def genereaza_ghid_d212(
    an_venituri: int,
    rezultat,
    *,
    plain: bool = False,
) -> str:
    """Ghid pentru user: ce am completat, ce trebuie sa completeze el, ce e o alegere."""
    def b(txt):
        return txt if plain else f"*{txt}*"

    salariu_minim = int(getattr(rezultat, "salariu_minim", 0) or 0)
    cas_baza = _lei(rezultat.cas_baza)
    cas = _lei(rezultat.cas)

    L = []
    L.append(b(f"D212 — Declaratia Unica pentru veniturile din {an_venituri}"))
    L.append("")
    L.append(f"Termen: 25 mai {an_venituri + 1}.")
    L.append("")
    L.append(b("Ce ti-am completat (cifrele tale, din bonuri si extrase):"))
    L.append(f"  • Venit brut: {_lei(rezultat.venit_brut)} lei")
    L.append(f"  • Cheltuieli deductibile: {_lei(rezultat.cheltuieli)} lei")
    L.append(f"  • Venit net: {_lei(rezultat.venit_net)} lei")
    if cas > 0:
        L.append(f"  • CAS (pensie): {cas} lei, pe baza de {cas_baza} lei")
    if _lei(rezultat.cass) > 0:
        L.append(f"  • CASS (sanatate): {_lei(rezultat.cass)} lei, "
                 f"pe baza de {_lei(rezultat.cass_baza)} lei")
    L.append(f"  • Impozit: {_lei(rezultat.impozit)} lei")
    L.append("")

    if cas > 0:
        L.append(b("⚠️ PAS OBLIGATORIU: CAS-ul NU vine cu fisierul."))
        L.append(
            f"Formularul ANAF nu preia CAS-ul din import — l-am testat, ramane pe 0. "
            f"Dupa ce importi, scrie {cas_baza} in campul "
            f"\"Baza anuala de calcul al CAS\". Atat. CAS-ul devine {cas} lei."
        )
        L.append(
            f"De ce trebuie sa-l pui tu: legea nu-ti spune cat sa platesti la pensie, "
            f"iti spune doar de la cat in jos nu ai voie. {cas_baza} e MINIMUL care ti "
            f"se aplica. Poti sa scrii mai mult, daca vrei pensie mai mare: platesti "
            f"25% din cat alegi, si exact cat platesti se duce in punctajul tau. "
            f"Alegerea e a ta — eu doar iti arat de unde pleaca."
        )
        L.append("")

    L.append(b("Ce trebuie sa completezi TU in formular (nu le stiu):"))
    L.append("  • Initiala tatalui")
    L.append("  • Statutul tau privind contributiile (salariat, pensionar etc.)")
    L.append("  • Pierderi reportate din anii precedenti, daca ai")
    L.append("")
    L.append(b("Cum il folosesti:"))
    L.append("  1. Intri in SPV cu utilizator si parola")
    L.append("  2. \"Depunere declaratie unica si alte formulare\" → formularul D212")
    L.append("  3. Apesi \"Importa fisier salvat\" si alegi D212.xml")
    if cas > 0:
        L.append(f"  4. Scrii {cas_baza} la \"Baza anuala de calcul al CAS\"")
        L.append("  5. VERIFICI tot, completezi ce lipseste")
        L.append("  6. \"Genereaza fisier PDF pentru depunere\" → depui prin SPV")
    else:
        L.append("  4. VERIFICI tot, completezi ce lipseste")
        L.append("  5. \"Genereaza fisier PDF pentru depunere\" → depui prin SPV")
    L.append("")
    L.append("Cifrele sunt calculate din datele tale, dar raspunderea pentru "
             "declaratie ramane a ta. Verifica-le inainte sa depui.")

    # VERIFICAREA LA MOMENTUL ANGAJAMENTULUI — ultima linie a ghidului, dinadins.
    #
    # Nu putem face greseala imposibila: nu controlam formularul ANAF, deci nu
    # putem impiedica pe nimeni sa depuna cu CAS 0. Singurul loc unde o verificare
    # chiar functioneaza e imediat inaintea pasului ireversibil — nu la inceputul
    # ghidului, unde se citeste si se uita, ci lipita de butonul de depunere.
    #
    # Miza e reala si dubla: fara baza CAS completata, declaratia subdeclara
    # contributia SI supradeclara impozitul (fara CAS dedus, baza impozabila creste).
    if cas > 0:
        L.append("")
        L.append(b("Inainte sa apesi \"Genereaza fisier PDF pentru depunere\", "
                   "uita-te la sumarul din dreapta. Daca la CAS scrie 0, nu ai "
                   "introdus baza — intoarce-te."))
    return "\n".join(L)
