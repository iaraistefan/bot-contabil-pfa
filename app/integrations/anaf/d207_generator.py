"""
Generator pentru Declaratia 207 — Declaratie informativa privind impozitul
retinut la sursa si castigurile/pierderile din investitii, pe beneficiari de
venit nerezidenti.

CAZUL DE UTILIZARE (PFA ridesharing Bolt/Uber):
  - perechea ANUALA a lui D100 (care e lunar): centralizeaza, o data pe an,
    TOATE veniturile platite platformelor nerezidente in anul precedent +
    impozitul aferent — INCLUSIV partea scutita (Uber 0% cu certificat).
  - se depune pana pe ultima zi din februarie a anului urmator (pt 2025 →
    28 feb 2026, mutat pe 2 martie 2026 fiindca 28 feb e sambata).
  - declaratie INFORMATIVA — fara plata (impozitul s-a virat lunar prin D100).
  - se depune pe CUI-ul PFA (ca D100), NU pe codul special TVA.

DOUA DRUMURI (ca la D100/D301/D390):
  - genereaza_d207()      -> XML pentru DUKIntegrator (Drumul B)
  - genereaza_ghid_d207() -> ghid de completare (Drumul A)

STRUCTURA XML (CONFIRMATA byte-cu-byte cu XSD-ul oficial ANAF
`d207_20025020.xsd`, namespace v2, schema version 1.02):
  <declaratie207 luna="12" an d_rec nume_declar prenume_declar functie_declar
                 cui den adresa [telefon] [fax] [mail] totalPlata_A>
    <sect_II tip_venit nrben Tscutit Tbaza Timp Timps/>   (1..21, TOATE intai)
    <benef id_inreg tip_venit1 den1 Stat_R [cifR] [cifS]
           baza1 imp1 imps1 Act_N/>                        (1..N, DUPA sect_II)
  </declaratie207>
  ⚠️ sect_II si benef sunt FRATI intr-o secventa (nu imbricate); toate sect_II
     intai, apoi toti benef. Legatura benef→sect_II = valoarea tip_venit(1).

Toate sumele sunt INTREGI (lei), tip IntPoz15 in XSD (>= 0).
cifR (NIF RO al nerezidentului) = OPTIONAL in XSD → OMIS (nerezidentul n-are
CUI romanesc); cifS = codul fiscal STRAIN (VAT nerezident, din
vat_engine.intracom_operator_for).
"""

from dataclasses import dataclass, field
from typing import List, Optional
from xml.sax.saxutils import escape
import unicodedata
import re


# ============================================================
#                    CONSTANTE
# ============================================================

# CONFIRMAT byte-cu-byte cu XSD-ul oficial (d207_20025020.xsd, version="1.02").
D207_NS_VERSION = "v2"
D207_NAMESPACE = f"mfp:anaf:dgti:d207:declaratie:{D207_NS_VERSION}"
D207_XSD = "D207.xsd"

# Luna raportarii: XSD cere FIX 12 (IntInt12_12SType) — anuala, se raporteaza
# pe decembrie al anului declarat.
D207_LUNA = 12

# Coduri natura venit (tip_venit) din nomenclatorul oficial D207 (structura ANAF):
#   "04" = comisioane (Bolt — impozabil prin Conventie)
#   "25" = venituri din servicii scutite conform Conventiei (Uber cu certificat)
# Baza legala (Act_N): "2" = s-a aplicat Conventia de evitare a dublei impuneri.


# ============================================================
#                    DATACLASSES
# ============================================================

@dataclass
class IdentitateD207:
    """Datele de identificare pentru D207 (pe CUI-ul PFA, ca D100)."""
    cui: str               # CUI PFA numeric (fara "RO")
    denumire: str
    adresa: str
    nume_declarant: str
    prenume_declarant: str
    functie_declarant: str = "TITULAR"
    telefon: str = ""
    fax: str = ""
    email: str = ""


@dataclass
class BeneficiarD207:
    """Un beneficiar de venit nerezident (un rand <benef> + agregat in <sect_II>)."""
    tip_venit: str            # "04" (Bolt) / "25" (Uber) — grupeaza sect_II
    denumire: str             # den1 — denumirea legala (BOLT OPERATIONS OU / UBER B.V.)
    stat: str                 # Stat_R — cod tara 2 litere (EE / NL)
    cif_strain: str           # cifS — cod fiscal strain (VAT nerezident); optional
    baza: int                 # baza1 — venitul platit (lei intregi)
    impozit: int              # imp1 — impozit retinut (lei intregi; 0 la scutit)
    impozit_scutit: int = 0   # imps1 — impozit scutit (lei intregi)
    baza_scutita: int = 0     # contributie la Tscutit pe sectiune
    act_n: str = "2"          # Act_N — 1 (fara conventie) / 2 (cu conventie)


# ============================================================
#                    HELPERS (oglinda d100_generator)
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


# ============================================================
#              GENERATOR XML D207 (Drumul B)
# ============================================================

def genereaza_d207(
    an: int,
    identitate: IdentitateD207,
    beneficiari: List[BeneficiarD207],
    d_rec: int = 0,
) -> str:
    """
    Genereaza XML-ul D207 conform XSD-ului oficial ANAF (namespace v2).

    Args:
        an: anul de raportare (2018-2100)
        identitate: datele declarantului (CUI PFA numeric)
        beneficiari: lista beneficiarilor nerezidenti (>= 1)
        d_rec: 0 = declaratie initiala, 1 = rectificativa

    Returns:
        XML-ul D207 ca string (UTF-8, gata de scris in .xml pentru DUKIntegrator)

    Raises:
        ValueError: date invalide (an, lista goala, sume negative)
    """
    if not (2018 <= an <= 2100):
        raise ValueError(f"An invalid pentru D207: {an} (permis 2018-2100).")
    if not beneficiari:
        raise ValueError(
            "D207 nu se depune pe zero — fara comisioane catre platforme "
            "nerezidente in anul respectiv nu ai aceasta obligatie."
        )
    for b in beneficiari:
        if b.baza < 0 or b.impozit < 0 or b.impozit_scutit < 0:
            raise ValueError(f"Sume negative interzise in D207 ({b.denumire}).")

    cui = _curata_cui(identitate.cui)

    # --- sectiuni: grupare pe tip_venit (o sectiune per natura de venit) ---
    # Ordine stabila: in ordinea primei aparitii a fiecarui tip_venit.
    ordine_tip: List[str] = []
    grupe = {}
    for b in beneficiari:
        if b.tip_venit not in grupe:
            grupe[b.tip_venit] = []
            ordine_tip.append(b.tip_venit)
        grupe[b.tip_venit].append(b)

    sectiuni = []
    total_plata_a = 0
    for tv in ordine_tip:
        membri = grupe[tv]
        nrben = len(membri)
        Tscutit = sum(m.baza_scutita for m in membri)
        Tbaza = sum(m.baza for m in membri)
        Timp = sum(m.impozit for m in membri)
        Timps = sum(m.impozit_scutit for m in membri)
        total_plata_a += nrben + Tscutit + Tbaza + Timp + Timps
        sectiuni.append((tv, nrben, Tscutit, Tbaza, Timp, Timps))

    # --- construire XML ---
    den = _curata_text(identitate.denumire)
    adresa = _curata_text(identitate.adresa)
    nume = _curata_text(identitate.nume_declarant)
    prenume = _curata_text(identitate.prenume_declarant)
    functie = _curata_text(identitate.functie_declarant)
    telefon = _curata_text(identitate.telefon)
    fax = _curata_text(identitate.fax)
    mail = identitate.email.strip()

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    root_attrs = " ".join(a for a in [
        _attr("xmlns", D207_NAMESPACE),
        _attr("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance"),
        _attr("xsi:schemaLocation", f"{D207_NAMESPACE} {D207_XSD}"),
        _attr("luna", f"{D207_LUNA:02d}"),
        _attr("an", an),
        _attr("d_rec", d_rec),  # 0 = declaratie normala
        _attr("nume_declar", nume),
        _attr("prenume_declar", prenume),
        _attr("functie_declar", functie),
        _attr("cui", cui),
        _attr("den", den),
        _attr("adresa", adresa),
        _attr_opt("telefon", telefon),
        _attr_opt("fax", fax),
        _attr_opt("mail", mail),
        _attr("totalPlata_A", total_plata_a),
    ] if a)
    lines.append(f"<declaratie207 {root_attrs}>")

    # sectiuni (TOATE intai — secventa XSD)
    for tv, nrben, Tscutit, Tbaza, Timp, Timps in sectiuni:
        sect_attrs = " ".join([
            _attr("tip_venit", tv),
            _attr("nrben", nrben),
            _attr("Tscutit", Tscutit),
            _attr("Tbaza", Tbaza),
            _attr("Timp", Timp),
            _attr("Timps", Timps),
        ])
        lines.append(f"  <sect_II {sect_attrs}/>")

    # beneficiari (DUPA sectiuni), id_inreg secvential 1..N
    for i, b in enumerate(beneficiari, start=1):
        benef_attrs = " ".join(a for a in [
            _attr("id_inreg", i),
            _attr("tip_venit1", b.tip_venit),
            _attr("den1", _curata_text(b.denumire)),
            _attr("Stat_R", b.stat.upper()),
            # cifR (NIF RO) OMIS: beneficiarul e nerezident, n-are cod fiscal roman.
            _attr_opt("cifS", _curata_text(b.cif_strain)),
            _attr("baza1", int(round(b.baza))),
            _attr("imp1", int(round(b.impozit))),
            _attr("imps1", int(round(b.impozit_scutit))),
            _attr("Act_N", b.act_n),
        ] if a)
        lines.append(f"  <benef {benef_attrs}/>")

    lines.append("</declaratie207>")
    return "\n".join(lines)


# ============================================================
#              GHID DE COMPLETARE D207 (Drumul A)
# ============================================================

def genereaza_ghid_d207(
    an: int,
    identitate: IdentitateD207,
    beneficiari: List[BeneficiarD207],
    *,
    plain: bool = False,
) -> str:
    """Ghid de completare D207 (Telegram/dashboard). `plain=True` = fara markdown."""
    def b(txt):
        return txt if plain else f"*{txt}*"

    L = []
    L.append(b(f"D207 — Declaratie informativa nerezidenti {an}"))
    L.append("")
    L.append(f"Perechea ANUALA a lui D100. Centralizezi TOATE comisioanele platite "
             f"platformelor nerezidente in {an} + impozitul aferent (inclusiv partea "
             f"SCUTITA — Uber cu certificat, impozit 0, se declara oricum).")
    L.append("")
    L.append(b("Termen:") + f" pana pe ultima zi lucratoare din februarie {an + 1} "
             f"(pt {an}: ~28 februarie {an + 1}; daca pica in weekend, prima zi "
             f"lucratoare urmatoare). Declaratie INFORMATIVA — nu platesti nimic "
             f"(impozitul s-a virat lunar prin D100).")
    L.append("")
    L.append(b("Beneficiari raportati:"))
    for benef in beneficiari:
        scutit = " (SCUTIT — impozit 0, dar OBLIGATORIU declarat)" if benef.impozit == 0 else ""
        L.append(f"  • {_curata_text(benef.denumire)} ({benef.stat}) — "
                 f"venit {benef.baza} lei, impozit {benef.impozit} lei{scutit}")
    L.append("")
    L.append(b("Cod fiscal roman (cifR):") + " se lasa GOL — beneficiarul e nerezident, "
             "n-are CUI romanesc. Codul fiscal strain (VAT-ul platformei) intra la cifS.")
    L.append("")
    L.append(b("Certificat de rezidenta:") + " pentru tratamentul din Conventie "
             "(2% Bolt / scutit Uber) trebuie sa ai certificatul de rezidenta fiscala "
             "al platformei pe dosar. Fara el → cota interna 16%.")
    L.append("")
    L.append(b("Cum depui:") + " genereaza XML-ul, valideaza-l local in DUKIntegrator "
             "(iti da PDF-ul depozabil), apoi incarci in SPV.")
    return "\n".join(L)
