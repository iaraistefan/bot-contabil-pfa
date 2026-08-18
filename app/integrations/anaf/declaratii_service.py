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
import logging
from typing import List, Optional

from app.domain.nume_declarant import split_denumire

logger = logging.getLogger(__name__)

# Importurile generatoarelor. In repo (acelasi pachet) foloseste relativ:
try:
    from . import d390_generator as d390
    from . import d301_generator as d301
    from . import d100_generator as d100
    from . import d207_generator as d207
    from . import d212_calc as d212
except ImportError:
    # fallback pentru rulare locala / teste (fisiere in acelasi folder)
    import d390_generator as d390
    import d301_generator as d301
    import d100_generator as d100
    import d207_generator as d207
    import d212_calc as d212

# Identitatea beneficiarului nerezident (D207) — sursa unica, refolosita din PR #105.
try:
    from app.domain.vat_engine import intracom_operator_for
except ImportError:  # rulare standalone / teste in folder
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from app.domain.vat_engine import intracom_operator_for


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

    CALE DE REZERVA. Sursa buna sunt campurile `nume_declarant` /
    `prenume_declarant` din profil, capturate la lookup-ul ANAF unde ordinea e
    stabila. Aici ajungem doar pentru profilele dinaintea capturarii, si atunci
    spargem `firma_nume` — un camp LIBER, care poate purta ordinea inversa.

    Taierea o face app/domain/nume_declarant.split_denumire, care potriveste
    sufixele pe CUVANT INTREG si cu diacritice. Varianta veche de aici avea
    doua hibe, ambele reparate acolo: lista de sufixe fara diacritice (nu se
    potrivea niciodata cu ce scrie ANAF) si `replace("II", "")`, care mutila
    orice nume continand „II" („ILIIESCU" -> „ILESCU").
    """
    if nume and prenume:
        return nume, prenume
    n, p = split_denumire(denumire)
    if n and p:
        return n, p
    # Denumire fara sufix de persoana fizica (SRL/SA) sau prea scurta: pastram
    # comportamentul vechi, ca sa nu ramana declaratia fara declarant.
    parts = [x for x in (denumire or "").split() if x]
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
    if not (nume and prenume):
        # Zgomotos DELIBERAT: derivarea dintr-un camp liber e o ghicitura care
        # poate iesi inversata in declaratie (s-a si intamplat — vezi migrarea
        # 028). Daca profilul a trecut prin lookup ANAF, campurile exista si
        # linia asta nu se aprinde niciodata.
        logger.warning(
            "nume de declarant derivat dintr-un camp liber, poate fi inversat "
            "(firma_nume=%r, CUI=%r) — profilul n-are nume_declarant/"
            "prenume_declarant; se recaptureaza la urmatorul lookup ANAF",
            denumire, profile.get("firma_cui"),
        )
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
    # Generare conditionata (D100): la cota nerezident 0/None NU se produce XML.
    # generat=False → xml gol, nume_fisier gol; apelantul NU trimite fisier, ci
    # afiseaza ghidul (motivul). Vezi fiscal #3 — date la ANAF, grija maxima.
    generat: bool = True
    motiv_negenerat: Optional[str] = None  # "scutit" / "neconfigurat"


# ============================================================
#                FUNCTIA PRINCIPALA
# ============================================================

def _ultima_zi_luna(an: int, luna: int) -> date:
    return date(an, luna, calendar.monthrange(an, luna)[1])


def _d100_negenerat(an: int, luna: int, *, motiv: str, ghid: str) -> RezultatDeclaratie:
    """
    Rezultat D100 NEGENERAT (cota 0/None) — fara XML, doar ghidul/motivul.

    Garda Strat 1: la scutit (CRF→0%) sau neconfigurat NU producem XML
    (xml gol, nume_fisier gol). Apelantul verifica `generat` si NU trimite
    fisier — afiseaza ghidul. Astfel e imposibil sa iasa un XML cu suma 0
    sau cu o cota presupusa (date la ANAF — vezi #3).
    """
    return RezultatDeclaratie(
        tip="D100", an=an, luna=luna,
        ghid_telegram=ghid, ghid_plain=ghid,
        xml="", nume_fisier_xml="",
        are_plata=False, suma_plata=0.0,
        namespace_de_confirmat=False,
        generat=False, motiv_negenerat=motiv,
    )


_D100_ETICHETA = {"bolt": "Bolt", "uber": "Uber"}

# Branduri rideshare cu identitate intracom cunoscută (D390 operator / D301 factură).
# Acelasi set ca _D100_BRANDS din tax_engine — furnizorii pe care Contai stie sa-i
# declare corect (tara + cod TVA). Eticheta pt numarul de factura D301 (BOLT-/UBER-).
_INTRACOM_BRANDS = ("bolt", "uber")
_INTRACOM_ETICHETA_FACTURA = {"bolt": "BOLT", "uber": "UBER"}


def _branded_intracom(intracom_by_brand):
    """
    Din dict-ul {brand: vat_out} (vezi tax_engine.vat_out_by_brand), intoarce lista
    ordonata [(brand, vat)] de furnizori rideshare cunoscuti cu vat>0.

    Cheia None (VAT_OUT dintr-o factura intracom neatribuita unei platforme) cu vat>0
    → OPRESTE (opțiunea b): D390/D301 sunt OBLIGATORII pe orice achizitie intracom;
    fara furnizor identificat nu putem construi operatorul (tara/cod), deci NU depunem
    tacut ceva incomplet si NU excludem in tacere randul. Cere atribuirea platformei.
    (Difera de D100, unde omiterea unui brand e sigura — acolo lipsa doar amana impozitul
    pe venit; aici lipsa ar produce o declaratie TVA incompleta.)
    """
    neatribuit = round((intracom_by_brand.get(None) or 0.0), 2)
    if neatribuit > 0:
        raise ValueError(
            f"Comision intracom de {neatribuit:.2f} lei fara platforma identificata. "
            f"Atribuie furnizorul (Bolt/Uber) pe facturile respective inainte de a genera "
            f"D390/D301 — altfel declaratia ar fi incompleta (furnizor lipsa)."
        )
    branded = [(b, round(v, 2)) for b, v in intracom_by_brand.items()
               if b in _INTRACOM_BRANDS and (v or 0) > 0]
    return sorted(branded)  # ordine stabila: [('bolt', …), ('uber', …)]


def _apportion(total, weights, decimals):
    """
    Imparte `total` in len(weights) cote proportionale cu `weights`, rotunjite la
    `decimals` zecimale, cu reziduul de rotunjire adaugat cotei celei mai mari →
    Σ cote == total EXACT (niciun leu pierdut la split).

    Pe un singur brand (cazul real dominant), cota = total → regresia Bolt-only e
    identica bit-cu-bit.
    """
    wsum = sum(weights)
    cote = [round(total * w / wsum, decimals) for w in weights]
    rezidual = round(total - sum(cote), decimals)
    i_max = max(range(len(weights)), key=lambda k: weights[k])
    cote[i_max] = round(cote[i_max] + rezidual, decimals)
    return cote


def _genereaza_d100_din_plan(an, luna, firma, plan, *, d_rec=0, suportat_de_bolt=False):
    """
    Genereaza D100 dintr-un `tax_engine.D100Plan` (multi-brand, Uber sub-pas B).

    D100 = O SINGURA pozitie agregata (lei intregi); cota difera pe platforma →
    suma = Σ pe segment. Statusul planului decide XML vs negenerat:
      - 'de_depus'     → XML cu segmente (Bolt 2% + Uber 16% etc.), defalcare cu bani;
      - 'neconfigurat' → BLOCAT (opt.1): brand recunoscut cu regim nesetat → niciun XML;
      - 'scutit'       → toate la cota 0 (CRF) → D207 anual, niciun XML;
      - 'fara_baza'    → vat_out neatribuit unei platforme rideshare → niciun XML + nudge.
    """
    if plan.status == "neconfigurat":
        nume = " si ".join(_D100_ETICHETA.get(b, b) for b in plan.neconfig_brands) or "platforma"
        return _d100_negenerat(
            an, luna, motiv="neconfigurat",
            ghid=(
                f"⚙️ *D100 — regim nerezident nesetat ({nume})*\n\n"
                f"Ai facturi *{nume}* in aceasta luna, dar n-ai setat regimul "
                f"nerezident pentru {nume}. Ca sa calculam corect impozitul (poz. 634), "
                f"alege regimul in Setari (sau /start):\n"
                f"• cu certificat de rezidenta fiscala (CRF) → *0%* (D100 nu se depune; "
                f"declari anual in D207)\n"
                f"• cu CRF, interpretare conservatoare → *2%* (doar Bolt)\n"
                f"• fara CRF → *16%*\n\n"
                f"NU emitem D100 pana nu alegi — un XML partial ar subdeclara la ANAF."
            ),
        )

    if plan.status in ("scutit", "fara_baza"):
        if plan.status == "scutit":
            ghid = (
                "✅ *D100 — scutit (CRF, 0%)*\n\n"
                "Cu certificatul de rezidenta fiscala si aplicarea Conventiei, "
                "impozitul pe comision este *0%* — D100 *nu se depune* lunar.\n\n"
                "⚠️ Venitul scutit se declara *anual in D207* (informativa, "
                "termen 28 februarie)."
            )
        else:
            ghid = (
                "ℹ️ *D100 — nicio factura atribuita unei platforme nerezidente*\n\n"
                "Exista TVA colectat (taxare inversa) in aceasta luna, dar facturile "
                "nu sunt atribuite unei platforme rideshare (Bolt/Uber). Verifica "
                "furnizorul pe facturile respective — D100 (poz. 634) nu se depune "
                "pana nu identificam platforma."
            )
        return _d100_negenerat(an, luna, motiv=plan.status, ghid=ghid)

    # de_depus → XML cu segmente (suma agregata, lei intregi; defalcare cu bani in ghid).
    identitate = d100.IdentitateD100(
        cui=firma.cui_pfa,  # CUI PFA, NU codul special!
        denumire=firma.denumire,
        adresa=firma.adresa,
        nume_declarant=firma.nume_declarant,
        prenume_declarant=firma.prenume_declarant,
        functie_declarant=firma.functie_declarant,
    )
    segmente = [(s.baza, s.cota, s.eticheta) for s in plan.segmente]
    xml = d100.genereaza_d100(an, luna, identitate, segmente=segmente,
                              d_rec=d_rec, suportat_de_bolt=suportat_de_bolt)
    ghid_tg = d100.genereaza_ghid_d100(an, luna, identitate, segmente=segmente,
                                       d_rec=d_rec, suportat_de_bolt=suportat_de_bolt,
                                       plain=False)
    ghid_pl = d100.genereaza_ghid_d100(an, luna, identitate, segmente=segmente,
                                       d_rec=d_rec, suportat_de_bolt=suportat_de_bolt,
                                       plain=True)
    suma = float(plan.suma_declarata or 0.0)
    pcte = " / ".join(f"{s.cota * 100:.0f}%" for s in plan.segmente)
    return RezultatDeclaratie(
        tip="D100", an=an, luna=luna,
        ghid_telegram=ghid_tg, ghid_plain=ghid_pl,
        xml=xml, nume_fisier_xml=f"D100_{an}_{luna:02d}.xml",
        are_plata=(suma > 0), suma_plata=suma,
        namespace_de_confirmat=True,
        avertismente=[f"D100 e obligatoriu lunar pentru comisioanele platformelor "
                      f"nerezidente (impozit nerezident {pcte}). Se depune pana pe 25 "
                      f"a lunii urmatoare. Impozitul se plateste din buzunar."],
    )


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
    suportat_de_bolt: bool = False,  # DEPRECATED — fara efect (vezi mai jos)
    cota_nerezident: Optional[float] = None,  # D100 legacy (1 brand): cota profil (0.0/0.02/0.16/None)
    d100_plan: Optional[object] = None,  # D100 multi-brand: tax_engine.D100Plan (split per-platforma)
    intracom_by_brand: Optional[dict] = None,  # D390/D301 multi-brand: {brand: vat_out} (split per-furnizor)
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
        suportat_de_bolt: DEPRECATED — fara efect. Cu certificat de rezidenta,
                          impozitul nerezident se plateste de PFA din buzunar;
                          suma de plata D100 = suma datorata intotdeauna.
        cota_nerezident: (DOAR D100) cota din profil dupa regimul nerezident:
                          0.02 / 0.16 (Bolt cu/fara certificat) → genereaza XML;
                          0.0 (scutit, ex. Uber cu certificat) → negenerat "scutit" (D207);
                          None (neconfigurat) → negenerat, motiv "neconfigurat".
                          Verifica rez.generat inainte de a trimite XML-ul.
        intracom_by_brand: (DOAR D390/D301) {brand: vat_out} din vat_out_by_brand.
                          Cand e furnizat, D390/D301 construiesc cate un operator/factura
                          PE BRAND (Bolt EE + Uber NL, cu identitatea corecta), impartind
                          baza proportional (Σ == baza scalara). Neatribuit (cheia None
                          cu vat>0) → ValueError (cere atribuirea platformei). None
                          (nefurnizat) → calea Bolt-only pe baza scalara (backward-compat).

    Returns:
        RezultatDeclaratie cu ghid + XML + eventuala suma de plata.
        Pentru D100 la cota 0/None: rez.generat=False, xml gol (NU trimite fisier).

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
        if intracom_by_brand is not None:
            # Multi-brand: un operator PE furnizor (Bolt EE / Uber NL), cu identitatea
            # corecta. Baza (int lei) impartita proportional cu vat_out per brand →
            # Σ == baza (niciun leu pierdut). Neatribuit → _branded_intracom ridica.
            branded = _branded_intracom(intracom_by_brand)
            if branded:
                cote = _apportion(baza, [v for _, v in branded], 0)
                operatori = [d390.operator_for_brand(b, int(round(c)))
                             for (b, _), c in zip(branded, cote)]
            else:
                operatori = [d390.operator_bolt(baza)]  # defensiv (nu se atinge: baza>0 ⇒ brand>0)
        else:
            operatori = [d390.operator_bolt(baza)]  # backward-compat: scalar Bolt-only
        assert sum(o.baza for o in operatori) == baza, "D390: split-ul pe brand pierde lei"
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
        if intracom_by_brand is not None:
            # Multi-brand: o factura PE furnizor, cu numarul etichetat corect
            # (UBER-/BOLT-). Valoarea (RON, 2 zecimale) impartita proportional cu
            # vat_out per brand → Σ == baza. FacturaIntracom nu poarta furnizorul,
            # deci diferenta reala e doar eticheta nr_doc (numeric era deja corect).
            branded = _branded_intracom(intracom_by_brand)  # neatribuit → ridica
            if branded:
                total = round(float(baza), 2)
                cote = _apportion(total, [v for _, v in branded], 2)
                _factura = {"bolt": d301.factura_bolt_lei, "uber": d301.factura_uber_lei}
                facturi = [
                    _factura[b](f"{_INTRACOM_ETICHETA_FACTURA[b]}-{an}-{luna:02d}",
                                factura_data, c)
                    for (b, _), c in zip(branded, cote)
                ]
            else:
                facturi = [d301.factura_bolt_lei(factura_nr, factura_data, baza)]  # defensiv
        else:
            facturi = [d301.factura_bolt_lei(factura_nr, factura_data, baza)]  # backward-compat
        assert round(sum(f.val_valuta for f in facturi), 2) == round(float(baza), 2), \
            "D301: split-ul pe brand pierde lei"
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
            namespace_de_confirmat=False,  # v1 confirmat in DUKIntegrator (01.06.2026)
            avertismente=avert,
        )

    if tip == "D100":
        # Multi-brand (Uber sub-pas B): daca primim un D100Plan, il folosim ca sursa
        # unica (status + segmente + suma agregata in lei intregi). Altfel, calea
        # LEGACY single-brand de mai jos (backward-compat — apeluri cu cota_nerezident).
        if d100_plan is not None:
            return _genereaza_d100_din_plan(
                an, luna, firma, d100_plan, d_rec=d_rec, suportat_de_bolt=suportat_de_bolt)

        # Rata D100 depinde de regimul nerezident (CRF) — sursa unica, din profil.
        # 4 ramuri; XML se produce DOAR la cota > 0 (Strat 1 al garzii — vezi #3).
        cota = cota_nerezident

        if cota is None:
            # Neconfigurat → NU presupunem o rata, NU generam XML. Prompt de setare.
            return _d100_negenerat(
                an, luna, motiv="neconfigurat",
                ghid=(
                    "⚙️ *D100 — regim nerezident nesetat*\n\n"
                    "Ca să calculăm corect impozitul pe comisionul Bolt, "
                    "spune-ne ce regim ai (depinde de certificatul de rezidență "
                    "fiscală — CRF):\n"
                    "• cu CRF, aplicând Convenția → *0%* (D100 nu se depune; "
                    "declari anual în D207)\n"
                    "• cu CRF, interpretare conservatoare → *2%*\n"
                    "• fără CRF → *16%*\n\n"
                    "Setează regimul în Setări (sau /start). NU afișăm o cifră "
                    "până nu alegi — ar putea fi greșită la ANAF."
                ),
            )

        if cota <= 0:
            # cota 0 (scutit, ex. Uber cu certificat) → D100 NU se depune; D207 anual.
            return _d100_negenerat(
                an, luna, motiv="scutit",
                ghid=(
                    "✅ *D100 — scutit (CRF, 0%)*\n\n"
                    "Cu certificatul de rezidență fiscală și aplicarea Convenției "
                    "RO-Estonia, impozitul pe comisionul Bolt este *0%* — D100 "
                    "*nu se depune* lunar.\n\n"
                    "⚠️ Venitul scutit se declară *anual în D207* (informativă, "
                    "termen 28 februarie). D207 rămâne obligatorie."
                ),
            )

        # cota > 0 (Bolt 2%/16%) → generam XML normal, cu cota din profil.
        identitate = d100.IdentitateD100(
            cui=firma.cui_pfa,  # CUI PFA, NU codul special!
            denumire=firma.denumire,
            adresa=firma.adresa,
            nume_declarant=firma.nume_declarant,
            prenume_declarant=firma.prenume_declarant,
            functie_declarant=firma.functie_declarant,
        )
        xml = d100.genereaza_d100(an, luna, identitate, baza,
                                  cota=cota, d_rec=d_rec,
                                  suportat_de_bolt=suportat_de_bolt)
        ghid_tg = d100.genereaza_ghid_d100(an, luna, identitate, baza,
                                           cota=cota, d_rec=d_rec,
                                           suportat_de_bolt=suportat_de_bolt,
                                           plain=False)
        ghid_pl = d100.genereaza_ghid_d100(an, luna, identitate, baza,
                                           cota=cota, d_rec=d_rec,
                                           suportat_de_bolt=suportat_de_bolt,
                                           plain=True)
        # Suma reala: PFA plateste impozitul din buzunar (suportat_de_bolt
        # DEPRECATED si ignorat intentionat).
        suma = float(d100.calcul_impozit_nerezident(baza, cota))
        pct = f"{cota * 100:.0f}%"
        return RezultatDeclaratie(
            tip="D100", an=an, luna=luna,
            ghid_telegram=ghid_tg, ghid_plain=ghid_pl,
            xml=xml, nume_fisier_xml=f"D100_{an}_{luna:02d}.xml",
            are_plata=(suma > 0), suma_plata=suma,
            namespace_de_confirmat=True,
            avertismente=[f"D100 e obligatoriu lunar pentru comisionul Bolt "
                          f"(impozit nerezident {pct}). Se depune pana pe 25 a "
                          f"lunii urmatoare. Impozitul se plateste din buzunar, "
                          f"suplimentar fata de comisionul Bolt."],
        )

    raise ValueError(f"Tip declaratie necunoscut: {tip}. "
                     f"Foloseste D390, D301 sau D100.")


TIPURI_SUPORTATE = ("D390", "D301", "D100")


# ============================================================
#       D207 — informativa ANUALA nerezidenti (perechea lui D100)
# ============================================================
#
# D207 e ANUALA (fara luna) → semnatura separata, NU intra in `genereaza`
# lunar / `TIPURI_SUPORTATE` (ca sa nu spargem orchestrarea lunara).

_D207_TIP_VENIT = {"bolt": "04", "uber": "25"}  # natura venitului (nomenclator ANAF)
_D207_ACT_N = "2"  # baza legala: s-a aplicat Conventia de evitare a dublei impuneri


def _d207_negenerat(an: int, *, motiv: str, ghid: str) -> RezultatDeclaratie:
    """D207 NEGENERAT (an fara comisioane nerezidente) — fara XML, doar ghid."""
    return RezultatDeclaratie(
        tip="D207", an=an, luna=d207.D207_LUNA,
        ghid_telegram=ghid, ghid_plain=ghid,
        xml="", nume_fisier_xml="",
        are_plata=False, suma_plata=0.0,
        namespace_de_confirmat=False,
        generat=False, motiv_negenerat=motiv,
    )


def genereaza_d207_anual(an, firma, by_brand, profile, *, d_rec=0):
    """
    Genereaza D207 (informativa anuala nerezidenti) dintr-un dict {brand: baza}.

    PURA (fara DB): `by_brand` vine din tax_engine.nerezident_anual_by_brand (Σ 12
    luni, DECIZIA A2). `profile.cota_nerezident_for(brand)` da cota (Bolt 2%/16%,
    Uber 0%). Identitatea beneficiarului (tara/cod/denumire) din sursa unica
    vat_engine.intracom_operator_for.

    Args:
        an: anul de raportare
        firma: DateFirma (CUI PFA — ca D100, NU codul special TVA)
        by_brand: {'bolt': baza, 'uber': baza, None: neatribuit} (lei, float)
        profile: FiscalProfile (pt cota_nerezident_for)
        d_rec: 0 = initiala, 1 = rectificativa

    Returns:
        RezultatDeclaratie (tip="D207"). `generat=False` daca anul n-are comisioane.

    Raises:
        ValueError: comision neatribuit unei platforme (optiunea b — nu depune
                    incomplet), sau brand cu comision dar regim nerezident nesetat.
    """
    if firma is None:
        firma = date_firma_stefan()

    # Optiunea (b) — comision intracom neatribuit unei platforme: OPRESTE.
    # (ca la PR #105 D390/D301: nu depunem tacut ceva incomplet.)
    neatribuit = round((by_brand.get(None) or 0.0), 2)
    if neatribuit > 0:
        raise ValueError(
            f"Comision de {neatribuit:.2f} lei fara platforma identificata in {an}. "
            f"Atribuie furnizorul (Bolt/Uber) inainte de a genera D207 — altfel "
            f"declaratia ar fi incompleta (beneficiar nerezident lipsa)."
        )

    beneficiari = []
    for brand in ("bolt", "uber"):
        baza = round((by_brand.get(brand) or 0.0), 2)
        if baza <= 0:
            continue
        cota = profile.cota_nerezident_for(brand)
        if cota is None:
            raise ValueError(
                f"Regim nerezident nesetat pentru {brand} — nu putem calcula "
                f"impozitul D207. Alege regimul (cu/fara certificat) in Setari."
            )
        info = intracom_operator_for(brand)  # (tara, cod_numeric, denumire_legala)
        tara, cod, den = info
        beneficiari.append(d207.BeneficiarD207(
            tip_venit=_D207_TIP_VENIT[brand],
            denumire=den, stat=tara, cif_strain=cod,
            baza=int(round(baza)),
            impozit=int(round(baza * cota)),
            impozit_scutit=0, baza_scutita=0,
            act_n=_D207_ACT_N,
        ))

    if not beneficiari:
        return _d207_negenerat(
            an, motiv="fara_baza",
            ghid=(f"ℹ️ *D207 {an}* — nu ai avut comisioane catre platforme "
                  f"nerezidente in {an}, deci D207 nu se depune pentru acest an."),
        )

    identitate = d207.IdentitateD207(
        cui=firma.cui_pfa,  # CUI PFA (ca D100), NU codul special TVA
        denumire=firma.denumire,
        adresa=firma.adresa,
        nume_declarant=firma.nume_declarant,
        prenume_declarant=firma.prenume_declarant,
        functie_declarant=firma.functie_declarant,
        telefon=firma.telefon,
        email=firma.email,
    )
    xml = d207.genereaza_d207(an, identitate, beneficiari, d_rec=d_rec)
    ghid_tg = d207.genereaza_ghid_d207(an, identitate, beneficiari, plain=False)
    ghid_pl = d207.genereaza_ghid_d207(an, identitate, beneficiari, plain=True)
    return RezultatDeclaratie(
        tip="D207", an=an, luna=d207.D207_LUNA,
        ghid_telegram=ghid_tg, ghid_plain=ghid_pl,
        xml=xml, nume_fisier_xml=f"D207_{an}.xml",
        are_plata=False, suma_plata=0.0,
        namespace_de_confirmat=False,  # namespace v2 confirmat cu XSD oficial
        avertismente=["D207 e informativa (fara plata) — centralizeaza ANUAL "
                      "comisioanele catre nerezidenti, inclusiv partea scutita."],
    )


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
    # Cele trei de mai jos NU sunt „adaptare la generator": proiectia era prea
    # INGUSTA. `venit_impozabil` e chiar baza impozitului (venit net − CAS − CASS),
    # adica cifra pe care userul o cauta cand vrea sa inteleaga de unde vine
    # impozitul; `cas_baza`/`cass_baza` sunt bazele de contributii, singurele care
    # explica de ce CAS-ul e cat e. Le calculam de la inceput in d212_calc si le
    # aruncam la iesire — asta era greseala, nu lipsa lor din generator.
    cas_baza: float = 0.0
    cass_baza: float = 0.0
    venit_impozabil: float = 0.0

    ghid_telegram: str = ""
    ghid_plain: str = ""
    avertismente: List[str] = field(default_factory=list)
    regim: str = "SISTEM_REAL"  # SISTEM_REAL / NORMA_VENIT (pentru afisare)

    # XML-ul D212, cand a fost cerut SI se poate genera. None = nu s-a cerut sau
    # nu se poate — `motiv_fara_xml` spune care din doua, in cuvintele userului.
    xml: Optional[str] = None
    nume_fisier_xml: Optional[str] = None
    motiv_fara_xml: Optional[str] = None

    @property
    def generat(self) -> bool:
        """Oglindeste `RezultatDeclaratie.generat` (D100/D301/D390/D207)."""
        return bool(self.xml)


# Ce vede userul pe NORMA DE VENIT. NU un refuz sec: primeste cifrele si ghidul,
# ii spunem de ce nu vine si un fisier, si ce face in schimb. Norma se declara in
# alt capitol al formularului, cu alta structura — a o imbraca in cap. I ar
# insemna sa trimitem la ANAF o declaratie care arata a sistem real.
MESAJ_D212_NORMA = """Pe *normă de venit* îți dau cifrele și ghidul, dar nu și fișierul XML.

Motivul: norma se declară în *capitolul II* al Declarației Unice, care are altă structură decât cel pentru sistemul real. Un fișier generat pe structura greșită ar fi respins de ANAF — sau, mai rău, acceptat și greșit.

Ce faci în schimb: deschide Declarația Unică în SPV și *tastează* cifrele de mai jos. Sunt exact aceleași pe care le-ar fi purtat fișierul — le ai aici, calculate, nu trebuie să le refaci."""


def genereaza_d212(
    an: int,
    venit_brut_anual: float,
    cheltuieli_anuale: float,
    salariu_minim: int = 4050,
    *,
    regim: str = "SISTEM_REAL",
    norma_anuala: float = 0.0,
    pensionar: bool = False,
    asigurat_salariat: bool = False,
    data_inceput=None,
    data_sfarsit=None,
    are_activitate_neeligibila: bool = False,
    data_adaugare=None,
    venit_brut_post: float = 0.0,
    cheltuieli_post: float = 0.0,
    identitate=None,
    activitate=None,
    d_rec: int = 0,
) -> RezultatD212Service:
    """
    Calculeaza Declaratia Unica (D212) pe baza venitului si cheltuielilor anuale.

    Args:
        an: anul de raportare (ex. 2025)
        venit_brut_anual: total incasari pe an (din motorul fiscal, 12 luni)
        cheltuieli_anuale: total cheltuieli deductibile pe an
        salariu_minim: salariul minim de referinta (default 4050)
        regim: "SISTEM_REAL" / "NORMA_VENIT" (motorul e regim-aware)
        norma_anuala: norma de venit (lei/an) — folosita DOAR pe NORMA_VENIT
        data_inceput/data_sfarsit: date activitate pentru proportionalizare mid-an
            (date | ISO str | None). None = activitate pe tot anul (regresie 0).
    """
    r = d212.calculeaza_d212(
        venit_brut=venit_brut_anual,
        cheltuieli_deductibile=cheltuieli_anuale,
        an=an,
        salariu_minim=salariu_minim,
        regim=regim,
        norma_anuala=norma_anuala,
        pensionar=pensionar,
        asigurat_salariat=asigurat_salariat,
        data_inceput=data_inceput,
        data_sfarsit=data_sfarsit,
        are_activitate_neeligibila=are_activitate_neeligibila,
        data_adaugare=data_adaugare,
        venit_brut_post=venit_brut_post,
        cheltuieli_post=cheltuieli_post,
    )
    # XML-ul se produce DOAR daca apelantul a cerut-o (a dat identitate+activitate).
    # Calea de estimare (tax_engine, dashboard) nu-l cere → nimic nu se schimba
    # pentru ea. Ordinea conteaza: verificam regimul INAINTE de generator, ca
    # norma sa primeasca o explicatie, nu o exceptie.
    xml = nume_fisier = motiv = None
    ghid_tg = d212.genereaza_ghid_d212(r, plain=False)
    ghid_pl = d212.genereaza_ghid_d212(r, plain=True)
    if identitate is not None and activitate is not None:
        if r.regim != "SISTEM_REAL":
            motiv = MESAJ_D212_NORMA
        else:
            from app.integrations.anaf import d212_generator as _gen
            # Orice ValueError de aici (an neacoperit, CNP, certificat lipsa) URCA
            # la apelant: sunt mesaje scrise pentru user, nu erori tehnice.
            xml = _gen.genereaza_d212(an, identitate, activitate, r, d_rec=d_rec)
            nume_fisier = f"D212_{an}.xml"
            # Ghidul care insoteste FISIERUL e cel scris pentru el (pasul obligatoriu
            # al bazei CAS + verificarea de la final), nu ghidul de estimare.
            ghid_tg = _gen.genereaza_ghid_d212(an, r, plain=False)
            ghid_pl = _gen.genereaza_ghid_d212(an, r, plain=True)

    return RezultatD212Service(
        an=r.an,
        venit_brut=r.venit_brut, cheltuieli=r.cheltuieli, venit_net=r.venit_net,
        cas=r.cas, cass=r.cass, impozit=r.impozit,
        cas_baza=r.cas_baza, cass_baza=r.cass_baza, venit_impozabil=r.venit_impozabil,
        total_plata=r.total_plata, bonificatie=r.bonificatie,
        total_cu_bonificatie=r.total_cu_bonificatie,
        ghid_telegram=ghid_tg,
        ghid_plain=ghid_pl,
        avertismente=r.avertismente,
        regim=r.regim,
        xml=xml, nume_fisier_xml=nume_fisier, motiv_fara_xml=motiv,
    )


def identitate_d212_din_profil(profile: dict):
    """Profil → IdentitateD212. Numele vin din nume_declarant/prenume_declarant
    (capturate din ANAF, PR #141), NU din `name` sau din firma_nume."""
    from app.integrations.anaf.d212_generator import IdentitateD212
    profile = profile or {}
    adresa = profile.get("adresa") or " ".join(
        p for p in [profile.get("judet") or "", profile.get("localitate") or ""] if p
    )
    return IdentitateD212(
        cnp=profile.get("cnp") or "",
        nume=profile.get("nume_declarant") or "",
        prenume=profile.get("prenume_declarant") or "",
        sediu=adresa or "[completeaza adresa]",
        email=profile.get("email") or "",
        telefon=profile.get("telefon") or "",
        iban=profile.get("iban") or "",
    )


def activitate_d212_din_profil(profile: dict):
    """Profil → ActivitateD212. Certificatul ONRC vine din nr_doc_autorizare /
    data_doc_autorizare (PR #138). Data lipsa → generatorul refuza cu mesajul lui."""
    from app.integrations.anaf.d212_generator import ActivitateD212
    from app.domain.doc_autorizare import parseaza_data_anaf
    profile = profile or {}
    caen = (profile.get("caen_principal") or "").strip()
    return ActivitateD212(
        caen=caen,
        den_caen=DEN_CAEN.get(caen, ""),
        nr_doc_autorizare=profile.get("nr_doc_autorizare") or "",
        data_doc_autorizare=parseaza_data_anaf(profile.get("data_doc_autorizare")),
    )


# Denumirile CAEN de care avem nevoie azi. `den_caen` e OPTIONAL in XSD
# (_attr_opt), deci un cod necunoscut da sir gol, nu o denumire inventata.
DEN_CAEN = {
    "4933": "Transporturi cu taxiuri",
    "4932": "Transporturi cu taxiuri",
}


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
