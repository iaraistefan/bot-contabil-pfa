"""
Generator pentru Declaratia 301 — Decont special de taxa pe valoarea adaugata.

Structura conforma cu:
  - OPANAF 592/2016, formularul versiunea 5
  - radacina <declaratie301>, structura din structura_D301 (ANAF)

CAZUL DE UTILIZARE (PFA ridesharing Bolt, cod special TVA art. 317):
  - PFA neplatitor TVA cu cod special (art. 317)
  - achizitie intracomunitara de SERVICII (comision Bolt) cu taxare inversa
  - beneficiarul (PFA) e obligat la plata TVA conform art. 307 alin. (2)
  - se depune LUNAR (pana pe 25), DOAR in lunile cu factura Bolt
  - AICI se PLATESTE TVA-ul (spre deosebire de D390 care e doar declarativa)

DOUA DRUMURI (ca la D390):
  - genereaza_d301()      -> XML pentru DUKIntegrator (Drumul B)
  - genereaza_ghid_d301() -> ghid de completare pentru dashboard/Telegram (Drumul A)

REGULI FISCALE IMPORTANTE:
  - COTA TVA depinde de DATA facturii:
      * 19% pana la 31.07.2025
      * 21% incepand cu 01.08.2025
    NU se hardcodeaza! Se aplica dupa data_doc.
  - baza = round(val_valuta * curs_valutar, 0)  -> intreg (0 zecimale)
  - tva = baza * cota
  - operatiunea Bolt = tip_operatie 5 (achizitii servicii intracom,
    beneficiarul plateste TVA). Se reflecta in S4 (baza4/tva4) SI in
    S4.1 (baza5/tva5), pentru ca S4.1 e subset preluat din S4.

⚠️ NAMESPACE DE CONFIRMAT:
  Namespace-ul XML 'mfp:anaf:dgti:d301:declaratie:vN' (digitul versiunii)
  NU a fost confirmat 100% in cercetare. Pentru Drumul A (ghid completare)
  NU conteaza deloc. Pentru Drumul B (XML), trebuie verificat empiric:
  - genereaza un D301 oficial din PDF inteligent, deschide XML-ul atasat
    (agrafa -> Salvare atasament) si citeste 'xmlns', SAU
  - DUKIntegrator iti va spune valoarea corecta in mesajul de eroare.
  Modifica D301_NS_VERSION mai jos cu valoarea reala cand o afli.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional
from xml.sax.saxutils import escape
import unicodedata
import re


# ============================================================
#                    CONSTANTE
# ============================================================

# ⚠️ DE CONFIRMAT EMPIRIC — pune aici versiunea reala a namespace-ului D301
D301_NS_VERSION = "v1"  # CONFIRMAT empiric cu DUKIntegrator (01.06.2026)
D301_NAMESPACE = f"mfp:anaf:dgti:d301:declaratie:{D301_NS_VERSION}"
D301_XSD = "D301.xsd"

# Cote TVA Romania, dupa data exigibilitatii/facturii
COTA_TVA_PANA_31_07_2025 = 0.19
COTA_TVA_DUPA_01_08_2025 = 0.21
DATA_SCHIMBARE_COTA = date(2025, 8, 1)

# tip_operatie pentru achizitii servicii intracom (beneficiar plateste TVA)
TIP_OP_SERVICII_INTRACOM = 5


# ============================================================
#                    DATACLASSES
# ============================================================

@dataclass
class FacturaIntracom:
    """O factura de comision intracomunitar (ex. Bolt)."""
    nr_doc: str            # numarul facturii
    data_doc: date         # data facturii (decide cota TVA)
    val_valuta: float      # valoarea in valuta (ex. EUR)
    tip_valuta: str        # "EUR", "USD", "RON" etc.
    curs_valutar: float    # cursul BNR la data_doc (1.0 daca e RON)

    def baza_lei(self) -> int:
        """Baza in lei = round(val_valuta * curs, 0), intreg."""
        return int(round(self.val_valuta * self.curs_valutar, 0))

    def cota(self) -> float:
        """Cota TVA dupa data facturii (19% sau 21%)."""
        if self.data_doc >= DATA_SCHIMBARE_COTA:
            return COTA_TVA_DUPA_01_08_2025
        return COTA_TVA_PANA_31_07_2025

    def tva_lei(self) -> float:
        """TVA = baza * cota, rotunjit la 2 zecimale."""
        return round(self.baza_lei() * self.cota(), 2)


@dataclass
class IdentitateD301:
    """Datele de identificare pentru D301."""
    cif: str               # cod special TVA (ex. "53148882"), fara/ cu RO
    denumire: str
    adresa: str
    banca: str             # banca (obligatoriu in D301)
    cont: str              # IBAN (obligatoriu in D301)
    nume_declarant: str
    prenume_declarant: str
    functie_declarant: str = "TITULAR"
    pers_inreg: int = 2    # 2 = inregistrat art. 317 doar pt achizitii intracom


# ============================================================
#                    HELPERS
# ============================================================

def _curata_text(text: str) -> str:
    """Elimina diacriticele si caracterele nepermise (alfabet latin)."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    fara = "".join(c for c in nfkd if not unicodedata.combining(c))
    curatat = re.sub(r"[^A-Za-z0-9 +\-.@/]", " ", fara)
    return re.sub(r"\s+", " ", curatat).strip()


def _curata_cif(cif: str) -> str:
    """Scoate prefixul RO si non-cifrele."""
    return re.sub(r"\D", "", str(cif))


def _attr(name: str, value) -> str:
    return f'{name}="{escape(str(value), {chr(34): "&quot;"})}"'


def _attr_opt(name: str, value) -> str:
    """Atribut optional: omis complet daca valoarea e goala (ANAF respinge atribute vide)."""
    if value is None or str(value).strip() == "":
        return ""
    return _attr(name, value)


def calcul_nr_evid(an: int, luna: int, mijl_transp: int = 0) -> str:
    """
    Calculeaza numarul de evidenta a platii (C(23)), conform structurii oficiale.

    Structura pe pozitii:
      1-2:   "10"
      3-5:   "301" (nomenclator)
      6-7:   "01"
      8-11:  LLAA  (luna+an raportare, ex. luna=4 an=2026 -> "0426")
      12-17: ZZLLAA (scadenta platii = 25 a lunii URMATOARE, ex. "250526")
      18:    "0" daca mijl_transp=0, "1" daca =1
      19-21: "000"
      22-23: suma de control = ultimele 2 cifre din suma primelor 21 cifre
    """
    # perioada raportare LLAA
    ll = f"{luna:02d}"
    aa = f"{an % 100:02d}"
    perioada = ll + aa  # "0426"

    # scadenta = 25 a lunii urmatoare
    if luna == 12:
        scad_luna, scad_an = 1, an + 1
    else:
        scad_luna, scad_an = luna + 1, an
    scadenta = f"25{scad_luna:02d}{scad_an % 100:02d}"  # ZZLLAA "250526"

    p18 = "1" if mijl_transp == 1 else "0"

    primele21 = "10" + "301" + "01" + perioada + scadenta + p18 + "000"
    # suma cifrelor primelor 21 de pozitii
    suma = sum(int(c) for c in primele21 if c.isdigit())
    control = f"{suma % 100:02d}"

    return primele21 + control


# ============================================================
#       HELPER: factura Bolt din valoare EUR + curs
# ============================================================

def factura_bolt(
    nr_doc: str,
    data_doc: date,
    comision_eur: float,
    curs_bnr: float,
) -> FacturaIntracom:
    """Construieste rapid o factura de comision Bolt (in EUR)."""
    return FacturaIntracom(
        nr_doc=nr_doc,
        data_doc=data_doc,
        val_valuta=round(comision_eur, 2),
        tip_valuta="EUR",
        curs_valutar=round(curs_bnr, 4),
    )


def factura_bolt_lei(nr_doc: str, data_doc: date, comision_lei: float) -> FacturaIntracom:
    """
    Construieste o factura Bolt direct din suma in LEI (curs = 1).
    Util cand ai deja baza in lei (din motorul fiscal Contai).
    """
    return FacturaIntracom(
        nr_doc=nr_doc,
        data_doc=data_doc,
        val_valuta=round(comision_lei, 2),
        tip_valuta="RON",
        curs_valutar=1.0,
    )


# ============================================================
#                    GENERATOR XML D301 (Drumul B)
# ============================================================

def genereaza_d301(
    an: int,
    luna: int,
    identitate: IdentitateD301,
    facturi: List[FacturaIntracom],
    d_rec: int = 0,
    mijl_transp: int = 0,
    temei: int = 0,
) -> str:
    """
    Genereaza XML-ul D301 (decont special TVA).

    ⚠️ Verifica D301_NS_VERSION inainte de a te baza pe acest XML in productie.
    """
    if not (2013 <= an <= 2099):
        raise ValueError(f"An invalid: {an}")
    if not (1 <= luna <= 12):
        raise ValueError(f"Luna invalida: {luna}")
    if not facturi:
        raise ValueError(
            "D301 nu se depune pe zero. Daca nu ai factura Bolt in aceasta "
            "luna, NU depui D301."
        )

    cif = _curata_cif(identitate.cif)

    # Operatiunea Bolt intra in S4 (tip 4) si S4.1 (tip 5, subset).
    # baza4/tva4 = tot ce e S4 (incl. subset S4.1); baza5/tva5 = doar S4.1.
    baza_total = sum(f.baza_lei() for f in facturi)
    tva_total = round(sum(f.tva_lei() for f in facturi), 2)

    baza = {1: 0, 2: 0, 3: 0, 4: baza_total, 5: baza_total}
    tva = {1: 0.0, 2: 0.0, 3: 0.0, 4: tva_total, 5: tva_total}

    # totalPlata_A = INT(suma baze + suma tva)
    total_plata_a = int(sum(baza.values()) + sum(tva.values()))

    nr_evid = calcul_nr_evid(an, luna, mijl_transp)

    den = _curata_text(identitate.denumire)
    adresa = _curata_text(identitate.adresa)
    banca = _curata_text(identitate.banca)
    cont = _curata_text(identitate.cont)
    nume = _curata_text(identitate.nume_declarant)
    prenume = _curata_text(identitate.prenume_declarant)
    functie = _curata_text(identitate.functie_declarant)

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    root_attrs = " ".join(a for a in [
        _attr("xmlns", D301_NAMESPACE),
        _attr("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance"),
        _attr("xsi:schemaLocation", f"{D301_NAMESPACE} {D301_XSD}"),
        _attr("luna", f"{luna:02d}"),
        _attr("an", an),
        _attr("d_rec", d_rec),
        _attr("mijl_trans", mijl_transp),
        _attr("temei", temei),
        _attr("cif", cif),
        _attr("denumire", den),
        _attr("adresa", adresa),
        _attr_opt("banca", banca),
        _attr_opt("cont", cont),
        _attr("pers_inreg", identitate.pers_inreg),
        _attr("nr_evid", nr_evid),
        _attr("baza1", baza[1]), _attr("tva1", f"{tva[1]:.2f}"),
        _attr("baza2", baza[2]), _attr("tva2", f"{tva[2]:.2f}"),
        _attr("baza3", baza[3]), _attr("tva3", f"{tva[3]:.2f}"),
        _attr("baza4", baza[4]), _attr("tva4", f"{tva[4]:.2f}"),
        _attr("baza5", baza[5]), _attr("tva5", f"{tva[5]:.2f}"),
        _attr("totalPlata_A", total_plata_a),
        _attr("nume_declarant", nume),
        _attr("prenume_declarant", prenume),
        _attr("functia_declarant", functie),
    ] if a)
    lines.append(f"<declaratie301 {root_attrs}>")

    def _rand(f, tip_op):
        attrs = " ".join([
            _attr("tip_operatie", tip_op),
            _attr("nr_doc", _curata_text(f.nr_doc)),
            _attr("data_doc", f.data_doc.strftime("%d.%m.%Y")),
            _attr("val_valuta", f"{f.val_valuta:.2f}"),
            _attr("tip_valuta", f.tip_valuta.upper()),
            _attr("curs_valutar", f"{f.curs_valutar:.4f}"),
            _attr("baza", f.baza_lei()),
            _attr("tva", f"{f.tva_lei():.2f}"),
        ])
        return f"  <sectiune {attrs}/>"

    # Pentru achizitii de servicii intracom (Bolt), operatiunea apartine
    # sectiunii S4.1 (tip 5), care e subset al S4 (tip 4). Regulile ANAF:
    #   baza4 = sum(baza) pt. tip_operatie=4  (S4 = S4.1 + S4.2)
    #   baza5 = sum(baza) pt. tip_operatie=5  (S4.1)
    # Cum S4.2 = 0 la noi, fiecare factura trebuie sa apara in AMBELE:
    # un rand tip 4 (intra in S4) si un rand tip 5 (intra in S4.1).
    for f in facturi:
        lines.append(_rand(f, 4))   # S4
        lines.append(_rand(f, TIP_OP_SERVICII_INTRACOM))  # S4.1 (=5)

    lines.append("</declaratie301>")
    return "\n".join(lines)


# ============================================================
#       GHID DE COMPLETARE D301 (Drumul A)
# ============================================================

_LUNI = {
    1: "Ianuarie", 2: "Februarie", 3: "Martie", 4: "Aprilie",
    5: "Mai", 6: "Iunie", 7: "Iulie", 8: "August",
    9: "Septembrie", 10: "Octombrie", 11: "Noiembrie", 12: "Decembrie",
}


def genereaza_ghid_d301(
    an: int,
    luna: int,
    identitate: IdentitateD301,
    facturi: List[FacturaIntracom],
    d_rec: int = 0,
    plain: bool = False,
) -> str:
    """
    Ghid de completare D301 — valorile exacte de pus in formular.
    """
    cif = _curata_cif(identitate.cif)
    luna_nume = _LUNI.get(luna, str(luna))

    baza_total = sum(f.baza_lei() for f in facturi)
    tva_total = round(sum(f.tva_lei() for f in facturi), 2)
    # cota afisata (din prima factura — toate dintr-o luna au aceeasi cota)
    cota_pct = int(round(facturi[0].cota() * 100)) if facturi else 21

    b = (lambda s: s) if plain else (lambda s: f"*{s}*")
    h = "" if plain else "📋 "
    sep = "──────────────────────────"

    L = []
    L.append(f"{h}{b(f'D301 — Decont special TVA — {luna_nume} {an}')}")
    L.append("Declaratie initiala" if d_rec == 0 else "Declaratie RECTIFICATIVA")
    L.append(sep)
    L.append("Perioada de raportare")
    L.append(f"   Anul: {b(an)}    Luna: {b(f'{luna:02d}')}")
    L.append("")
    L.append(f"{'' if plain else '🧾 '}{b('Date de identificare')}")
    L.append(f"   Cod fiscal (dupa RO): {b(cif)}   _(codul special TVA)_" if not plain
             else f"   Cod fiscal (dupa RO): {cif}  (codul special TVA)")
    L.append(f"   Denumire: {_curata_text(identitate.denumire)}")
    L.append(f"   Adresa: {_curata_text(identitate.adresa)}")
    L.append(f"   Banca: {_curata_text(identitate.banca)}")
    L.append(f"   Cont (IBAN): {_curata_text(identitate.cont)}")
    L.append("")
    L.append(f"{'' if plain else '📝 '}{b('Operatiuni (taxare inversa servicii)')}")
    for i, f in enumerate(facturi, 1):
        cota_f = int(round(f.cota() * 100))
        L.append(f"   {b(f'Factura {i}')} — {_curata_text(f.nr_doc)} / {f.data_doc.strftime('%d.%m.%Y')}")
        if f.tip_valuta != "RON":
            L.append(f"      Valuta: {f.val_valuta:.2f} {f.tip_valuta} × curs {f.curs_valutar:.4f}")
        L.append(f"      Baza impozabila: {b(f.baza_lei())} lei")
        L.append(f"      TVA {cota_f}%: {b(f'{f.tva_lei():.2f}')} lei")
    L.append("")
    L.append(f"{'' if plain else '💰 '}{b('TOTAL')}")
    L.append(f"   Baza totala: {b(baza_total)} lei")
    L.append(f"   {b(f'TVA DE PLATA: {tva_total:.2f} lei')}  (cota {cota_pct}%)")
    L.append("")
    L.append(f"{'' if plain else '✍️ '}Declarant: {_curata_text(identitate.nume_declarant)} "
             f"{_curata_text(identitate.prenume_declarant)} — "
             f"{_curata_text(identitate.functie_declarant)}")
    L.append(sep)
    if not plain:
        L.append(f"_Dupa completare: VALIDARE -> semneaza eToken -> depune in SPV. "
                 f"Apoi platesti {tva_total:.2f} lei (cont TVA pe codul special)._")
    else:
        L.append(f"Dupa completare: Validare -> eToken -> SPV. "
                 f"Plata TVA: {tva_total:.2f} lei pe codul special.")
    return "\n".join(L)


# ============================================================
#                    TEST / DEMO
# ============================================================

if __name__ == "__main__":
    identitate = IdentitateD301(
        cif="53148882",  # codul special de TVA
        denumire="IARAI STEFAN PERSOANA FIZICA AUTORIZATA",
        adresa="JUD BISTRITA NASAUD MUN BISTRITA STR MESTEACANULUI NR15 ET 2 AP 2",
        banca="Banca Transilvania",
        cont="RO00BTRL0000000000000000",
        nume_declarant="IARAI",
        prenume_declarant="STEFAN",
        functie_declarant="TITULAR",
    )

    # Ianuarie 2026: comision Bolt 657 lei (din D390 real). Cota 21% (dupa 08.2025).
    facturi = [factura_bolt_lei("BOLT-2026-01", date(2026, 1, 31), 657)]

    print("=" * 60)
    print("nr_evid (Ianuarie 2026):", calcul_nr_evid(2026, 1))
    print("=" * 60)
    print("DRUMUL B — XML D301 (pentru DUKIntegrator):")
    print("=" * 60)
    print(genereaza_d301(an=2026, luna=1, identitate=identitate, facturi=facturi))
    print()
    print("=" * 60)
    print("DRUMUL A — GHID COMPLETARE D301:")
    print("=" * 60)
    print(genereaza_ghid_d301(an=2026, luna=1, identitate=identitate,
                              facturi=facturi, plain=True))
