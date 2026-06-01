"""
Serviciu comun pentru generarea declaratiilor ANAF (D390, D301, D100).

Este "creierul" folosit deopotriva de:
  - dashboard (butoane "Genereaza D390/D301/D100")
  - botul Telegram (comenzi)

Centralizeaza:
  - datele de identificare ale firmei (cele DOUA coduri: CUI PFA + cod special)
  - apelarea generatorului corect in functie de tip
  - intoarcerea unui rezultat uniform (ghid + XML + suma de plata)

PLASARE IN REPO:
  Pune acest fisier + cele 3 generatoare in app/integrations/anaf/:
    app/integrations/anaf/__init__.py
    app/integrations/anaf/d390_generator.py
    app/integrations/anaf/d301_generator.py
    app/integrations/anaf/d100_generator.py
    app/integrations/anaf/declaratii_service.py   <-- acest fisier
  Daca le pui in alt loc, ajusteaza importurile de mai jos.
"""

from dataclasses import dataclass, field
from datetime import date
import calendar
from typing import List, Optional

# Importurile generatoarelor. In repo (acelasi pachet) foloseste relativ:
try:
    from . import d390_generator as d390
    from . import d301_generator as d301
    from . import d100_generator as d100
    from . import d212_calc as d212
except ImportError:
    # fallback pentru rulare locala / teste (fisiere in acelasi folder)
    import d390_generator as d390
    import d301_generator as d301
    import d100_generator as d100
    import d212_calc as d212


# ============================================================
#                DATELE FIRMEI (identitate)
# ============================================================

@dataclass
class DateFirma:
    """
    Datele de identificare ale firmei pentru declaratii.

    IMPORTANT — doua coduri diferite:
      - cui_pfa        = CUI-ul PFA (pt D100, D212 — impozite)
      - cod_special_tva = codul special art. 317 (pt D301, D390 — TVA)
    """
    cui_pfa: str
    cod_special_tva: str
    denumire: str
    adresa: str
    nume_declarant: str
    prenume_declarant: str
    functie_declarant: str = "TITULAR"
    telefon: str = ""
    email: str = ""
    banca: str = ""          # pt D301 (obligatoriu in formular)
    cont: str = ""           # IBAN, pt D301


def date_firma_stefan() -> DateFirma:
    """
    Datele confirmate ale PFA-ului (din PDF-ul D390 real depus).

    Pentru produs multi-tenant, acestea se vor citi din profilul user-ului
    in loc sa fie hardcodate. Pentru moment sunt datele reale confirmate.
    """
    return DateFirma(
        cui_pfa="53067338",          # CUI PFA
        cod_special_tva="53148882",  # cod special TVA art. 317
        denumire="IARAI STEFAN PERSOANA FIZICA AUTORIZATA",
        adresa="JUD BISTRITA NASAUD MUN BISTRITA STR MESTEACANULUI NR15 ET 2 AP 2",
        nume_declarant="IARAI",
        prenume_declarant="STEFAN",
        functie_declarant="TITULAR",
        telefon="0756284346",
        email="iaraistefan@gmail.com",
        banca="",   # de completat (apare in ghid ca [completeaza])
        cont="",    # de completat (IBAN)
    )


def _split_nume_prenume(denumire: str, nume: str, prenume: str):
    """
    Determina nume + prenume declarant.
    Daca profilul nu le are explicit, le deduce din denumirea PFA
    (ex. "IARAI STEFAN PERSOANA FIZICA AUTORIZATA" -> IARAI / STEFAN).
    """
    if nume and prenume:
        return nume, prenume
    den = (denumire or "").upper()
    # taie sufixele de forma juridica
    for suf in ("PERSOANA FIZICA AUTORIZATA", "PFA", "INTREPRINDERE INDIVIDUALA",
                "II", "INTREPRINDERE FAMILIALA", "IF"):
        den = den.replace(suf, "")
    parts = [p for p in den.split() if p]
    if len(parts) >= 2:
        return parts[0], parts[1]
    if len(parts) == 1:
        return parts[0], parts[0]
    return (nume or "TITULAR"), (prenume or "")


def date_firma_din_profil(profile: dict) -> DateFirma:
    """
    Construieste DateFirma din profilul real al user-ului (get_profile_dict).

    Asta face serviciul multi-tenant: fiecare user isi are propriile date
    (CUI, cod special, banca, IBAN). Cu fallback-uri sigure unde lipseste ceva.

    Args:
        profile: dict de la users_repo.get_profile_dict
    """
    profile = profile or {}
    denumire = profile.get("firma_nume") or "PFA"
    nume = profile.get("nume_declarant") or ""
    prenume = profile.get("prenume_declarant") or ""
    nume, prenume = _split_nume_prenume(denumire, nume, prenume)

    # adresa din judet + localitate daca nu exista camp dedicat
    adresa = profile.get("adresa") or ""
    if not adresa:
        loc = profile.get("localitate") or ""
        jud = profile.get("judet") or ""
        adresa = " ".join(p for p in [jud, loc] if p) or "[completeaza adresa]"

    return DateFirma(
        cui_pfa=profile.get("firma_cui") or "",
        cod_special_tva=profile.get("cod_special_tva") or profile.get("firma_cui") or "",
        denumire=denumire,
        adresa=adresa,
        nume_declarant=nume,
        prenume_declarant=prenume,
        functie_declarant="TITULAR",
        telefon=profile.get("telefon") or "",
        email=profile.get("email") or "",
        banca=profile.get("banca") or "",
        cont=profile.get("iban") or "",
    )


# ============================================================
#                REZULTAT UNIFORM
# ============================================================

@dataclass
class RezultatDeclaratie:
    """Rezultatul generarii unei declaratii — uniform pentru toate tipurile."""
    tip: str                       # "D390" / "D301" / "D100"
    an: int
    luna: int
    ghid_telegram: str             # ghid formatat (markdown, pentru Telegram)
    ghid_plain: str                # ghid text simplu (dashboard / log)
    xml: str                       # continutul XML (Drumul B)
    nume_fisier_xml: str           # ex. "D390_2026_01.xml"
    are_plata: bool = False        # True daca declaratia implica plata
    suma_plata: float = 0.0        # suma de plata (lei), daca e cazul
    namespace_de_confirmat: bool = False  # True pt D301/D100 (XML neconfirmat)
    avertismente: List[str] = field(default_factory=list)


# ============================================================
#                FUNCTIA PRINCIPALA
# ============================================================

def _ultima_zi_luna(an: int, luna: int) -> date:
    return date(an, luna, calendar.monthrange(an, luna)[1])


def genereaza(
    tip: str,
    an: int,
    luna: int,
    baza_intracom_lei: float,
    firma: Optional[DateFirma] = None,
    *,
    d_rec: int = 0,
    factura_nr: Optional[str] = None,
    factura_data: Optional[date] = None,
    suportat_de_bolt: bool = True,
) -> RezultatDeclaratie:
    """
    Genereaza o declaratie ANAF pe luna data, pe baza comisionului Bolt.

    Args:
        tip: "D390", "D301" sau "D100" (case-insensitive)
        an, luna: perioada
        baza_intracom_lei: baza (comisionul Bolt, fara TVA, in lei)
        firma: datele firmei (default = date_firma_stefan())
        d_rec: 0 = initiala, 1 = rectificativa
        factura_nr, factura_data: pt D301 (default: nr generic + ultima zi)
        suportat_de_bolt: pt D100 (default True -> suma de plata 0)

    Returns:
        RezultatDeclaratie cu ghid + XML + eventuala suma de plata.

    Raises:
        ValueError: tip necunoscut sau baza invalida.
    """
    tip = tip.upper().strip()
    if firma is None:
        firma = date_firma_stefan()

    baza = int(round(baza_intracom_lei))
    if baza <= 0:
        raise ValueError(
            f"Baza intracom este {baza} lei. {tip} nu se depune pe zero — "
            f"in lunile fara factura Bolt nu ai aceasta obligatie."
        )

    if factura_data is None:
        factura_data = _ultima_zi_luna(an, luna)
    if factura_nr is None:
        factura_nr = f"BOLT-{an}-{luna:02d}"

    if tip == "D390":
        identitate = d390.IdentitateDeclarant(
            cui=firma.cod_special_tva,
            denumire=firma.denumire,
            adresa=firma.adresa,
            nume_declarant=firma.nume_declarant,
            prenume_declarant=firma.prenume_declarant,
            functie_declarant=firma.functie_declarant,
            telefon=firma.telefon,
            email=firma.email,
        )
        operatori = [d390.operator_bolt(baza)]
        xml = d390.genereaza_d390(an, luna, identitate, operatori, d_rec=d_rec)
        ghid_tg = d390.genereaza_ghid_d390(an, luna, identitate, operatori,
                                           d_rec=d_rec, plain=False)
        ghid_pl = d390.genereaza_ghid_d390(an, luna, identitate, operatori,
                                           d_rec=d_rec, plain=True)
        return RezultatDeclaratie(
            tip="D390", an=an, luna=luna,
            ghid_telegram=ghid_tg, ghid_plain=ghid_pl,
            xml=xml, nume_fisier_xml=f"D390_{an}_{luna:02d}.xml",
            are_plata=False, suma_plata=0.0,
            namespace_de_confirmat=False,
        )

    if tip == "D301":
        identitate = d301.IdentitateD301(
            cif=firma.cod_special_tva,
            denumire=firma.denumire,
            adresa=firma.adresa,
            banca=firma.banca or "[completeaza banca ta]",
            cont=firma.cont or "[completeaza IBAN-ul tau]",
            nume_declarant=firma.nume_declarant,
            prenume_declarant=firma.prenume_declarant,
            functie_declarant=firma.functie_declarant,
        )
        facturi = [d301.factura_bolt_lei(factura_nr, factura_data, baza)]
        xml = d301.genereaza_d301(an, luna, identitate, facturi, d_rec=d_rec)
        ghid_tg = d301.genereaza_ghid_d301(an, luna, identitate, facturi,
                                           d_rec=d_rec, plain=False)
        ghid_pl = d301.genereaza_ghid_d301(an, luna, identitate, facturi,
                                           d_rec=d_rec, plain=True)
        tva = round(sum(f.tva_lei() for f in facturi), 2)
        avert = []
        if not firma.banca or not firma.cont:
            avert.append("Completeaza banca si IBAN-ul in formular "
                         "(D301 le cere obligatoriu).")
        return RezultatDeclaratie(
            tip="D301", an=an, luna=luna,
            ghid_telegram=ghid_tg, ghid_plain=ghid_pl,
            xml=xml, nume_fisier_xml=f"D301_{an}_{luna:02d}.xml",
            are_plata=True, suma_plata=tva,
            namespace_de_confirmat=True,
            avertismente=avert,
        )

    if tip == "D100":
        identitate = d100.IdentitateD100(
            cui=firma.cui_pfa,  # CUI PFA, NU codul special!
            denumire=firma.denumire,
            adresa=firma.adresa,
            nume_declarant=firma.nume_declarant,
            prenume_declarant=firma.prenume_declarant,
            functie_declarant=firma.functie_declarant,
        )
        xml = d100.genereaza_d100(an, luna, identitate, baza,
                                  d_rec=d_rec, suportat_de_bolt=suportat_de_bolt)
        ghid_tg = d100.genereaza_ghid_d100(an, luna, identitate, baza,
                                           d_rec=d_rec,
                                           suportat_de_bolt=suportat_de_bolt,
                                           plain=False)
        ghid_pl = d100.genereaza_ghid_d100(an, luna, identitate, baza,
                                           d_rec=d_rec,
                                           suportat_de_bolt=suportat_de_bolt,
                                           plain=True)
        suma = 0.0 if suportat_de_bolt else float(d100.calcul_impozit_nerezident(baza))
        return RezultatDeclaratie(
            tip="D100", an=an, luna=luna,
            ghid_telegram=ghid_tg, ghid_plain=ghid_pl,
            xml=xml, nume_fisier_xml=f"D100_{an}_{luna:02d}.xml",
            are_plata=(suma > 0), suma_plata=suma,
            namespace_de_confirmat=True,
            avertismente=["Din 2023 Bolt suporta de obicei cei 2%. "
                          "Verifica in SPV daca mai depui D100."],
        )

    raise ValueError(f"Tip declaratie necunoscut: {tip}. "
                     f"Foloseste D390, D301 sau D100.")


TIPURI_SUPORTATE = ("D390", "D301", "D100")


# ============================================================
#       D212 — Declaratia Unica anuala (calcul, nu generator XML)
# ============================================================

@dataclass
class RezultatD212Service:
    """Rezultat D212 pentru dashboard/Telegram (calcul + ghid)."""
    an: int
    venit_brut: float
    cheltuieli: float
    venit_net: float
    cas: float
    cass: float
    impozit: float
    total_plata: float
    bonificatie: float
    total_cu_bonificatie: float
    ghid_telegram: str
    ghid_plain: str
    avertismente: List[str] = field(default_factory=list)


def genereaza_d212(
    an: int,
    venit_brut_anual: float,
    cheltuieli_anuale: float,
    salariu_minim: int = 4050,
) -> RezultatD212Service:
    """
    Calculeaza Declaratia Unica (D212) pe baza venitului si cheltuielilor anuale.

    Args:
        an: anul de raportare (ex. 2025)
        venit_brut_anual: total incasari pe an (din motorul fiscal, 12 luni)
        cheltuieli_anuale: total cheltuieli deductibile pe an
        salariu_minim: salariul minim de referinta (default 4050)
    """
    r = d212.calculeaza_d212(
        venit_brut=venit_brut_anual,
        cheltuieli_deductibile=cheltuieli_anuale,
        an=an,
        salariu_minim=salariu_minim,
    )
    return RezultatD212Service(
        an=r.an,
        venit_brut=r.venit_brut, cheltuieli=r.cheltuieli, venit_net=r.venit_net,
        cas=r.cas, cass=r.cass, impozit=r.impozit,
        total_plata=r.total_plata, bonificatie=r.bonificatie,
        total_cu_bonificatie=r.total_cu_bonificatie,
        ghid_telegram=d212.genereaza_ghid_d212(r, plain=False),
        ghid_plain=d212.genereaza_ghid_d212(r, plain=True),
        avertismente=r.avertismente,
    )


# ============================================================
#                    TEST / DEMO
# ============================================================

if __name__ == "__main__":
    for tip in TIPURI_SUPORTATE:
        print("=" * 60)
        print(f"  {tip}")
        print("=" * 60)
        r = genereaza(tip, an=2026, luna=1, baza_intracom_lei=657)
        print(f"Fisier XML: {r.nume_fisier_xml}")
        print(f"Are plata: {r.are_plata}  Suma: {r.suma_plata} lei")
        print(f"Namespace de confirmat: {r.namespace_de_confirmat}")
        if r.avertismente:
            print("Avertismente:", "; ".join(r.avertismente))
        print("--- ghid (plain) ---")
        print(r.ghid_plain)
        print()
