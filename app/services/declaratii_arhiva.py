"""
ARHIVA declaratiilor generate — blocantul fiscal F1.

CE REZOLVA
Pana acum nu se persista NIMIC: nici rezultatul, nici inputurile. Generatoarele din
`app/integrations/anaf/` sunt pure, XML-ul pleca prin BytesIO si disparea. NU e gaura
de conformitate (copia autoritativa e in SPV), ci de REPRODUCTIBILITATE si RASPUNDERE:
recalcularea unui an trecut citea TACIT profilul de azi, deci putea da alt numar decat
s-a depus — si nu puteam distinge „motorul era gresit atunci" de „userul a raspuns
altfel atunci".

ARHITECTURA — de ce un modul separat, si nu scriere in generatoare
Generatoarele raman PURE, fara `session`. Puritatea directorului `anaf/` e o
proprietate reala (verificabila cu `grep "session.add|commit"` → gol), nu o
intamplare; n-o rupem pentru comoditate. Modulul asta e stratul care CHEAMA
generatorul pur si persista ce a iesit.

SESIUNE PROPRIE, nu primita ca parametru
Call-site-urile din bot (`bot_contabil.py:1868`, `:1957`) isi INCHID sesiunea in
`finally` INAINTE sa cheme generatorul — sesiunea traieste doar cat se calculeaza baza
din DB. Deci la momentul generarii nu exista sesiune de imprumutat. O sesiune scurta,
proprie, e singurul tipar care merge identic din bot SI din web.

ORDINEA: genereaza → arhiveaza → livreaza
Esecul arhivarii NU blocheaza livrarea — userul isi primeste declaratia oricum. Dar
esecul e ZGOMOTOS: log de eroare cu destul context (user, tip, perioada, sume) ca sa se
poata reconstrui manual ce a plecat. O arhivare care cade in tacere ar recrea exact
punctul orb pentru care exista blocantul.

IMUTABIL: append-only. Nicio functie de update. O declaratie generata e fapt istoric.
"""

import logging
from datetime import date, datetime
from enum import Enum

from db import get_session
from app import monitoring
from app.models import DeclaratieGenerata
from app.integrations.anaf import declaratii_service as _decl

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
#   SERIALIZARE — liste EXPLICITE, nu dump de obiect
# ════════════════════════════════════════════════════════════
# `firma` (DateFirma) si `profile` (FiscalProfile) sunt OBIECTE. Un `__dict__` ar lega
# arhiva de forma lor interna: orice camp adaugat acolo ar intra tacit in arhiva, si
# orice camp redenumit ar disparea la fel de tacit. Listele de mai jos sunt contractul
# explicit — iar `test_arhiva_declaratii.py` cade daca semnatura unui generator capata
# un parametru pe care arhiva nu-l cunoaste.

# DE CE lipsesc `cont` (IBAN), `telefon` si `email`, desi sunt pe DateFirma:
# XML-ul stocat pastreaza ARTEFACTUL asa cum a fost depus; `inputuri_json` pastreaza
# ce a INFLUENTAT CALCULUL. Un IBAN nu schimba niciun numar — nu e input in sensul care
# conteaza, iar o a doua copie a datelor bancare nu cumpara nimic.
# (`banca` ramane: la D301 e camp de formular, deci parte din identitatea depunerii.)
#
# NOTA: `firma` ajunge DOAR la `genereaza` (D100/D301/D390) si `genereaza_d207_anual`.
# `genereaza_d212` NU primeste firma — D212 nu produce fisier, deci n-are nevoie de
# date de identificare. Verificat pe semnatura, nu presupus.
_CAMPURI_FIRMA = (
    "cui_pfa", "cod_special_tva", "denumire", "adresa",
    "nume_declarant", "prenume_declarant", "functie_declarant",
    "banca",
)

# Din FiscalProfile pastram DOAR ce influenteaza iesirea unei declaratii. Restul
# (praguri derivate, cote calculate) se poate reconstitui din astea + anul.
_CAMPURI_PROFIL = (
    "forma_juridica", "regim_impunere", "regim_tva", "activity_code",
    "regim_nerezident_bolt", "regim_nerezident_uber",
)


def _val(v):
    """Valoare JSON-safe: enum → .value, data → ISO, obiect necunoscut → repr."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [_val(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _val(x) for k, x in v.items()}
    return repr(v)


def _ser_obiect(obj, campuri):
    """Serializeaza un obiect pe lista EXPLICITA de campuri. None → None."""
    if obj is None:
        return None
    return {c: _val(getattr(obj, c, None)) for c in campuri}


def serializeaza_firma(firma):
    return _ser_obiect(firma, _CAMPURI_FIRMA)


def serializeaza_profil(profile):
    return _ser_obiect(profile, _CAMPURI_PROFIL)


# ════════════════════════════════════════════════════════════
#   PERSISTENTA — append-only, cu esec ZGOMOTOS
# ════════════════════════════════════════════════════════════

def _arhiveaza(*, user_id, tip, an, luna, d_rec, inputuri, rezultat,
               xml=None, nume_fisier_xml=None, generat=True, motiv_negenerat=None):
    """
    Scrie un rand in arhiva. Sesiune PROPRIE, scurta.

    NU arunca niciodata: apelantul trebuie sa livreze declaratia chiar daca insertul
    cade. Dar logheaza ZGOMOTOS, cu destul context ca sa se poata reconstrui manual
    ce s-a generat.

    Returneaza id-ul randului, sau None la esec.
    """
    if not user_id:
        return None
    # get_session() INTRA in try: daca baza e cazuta, `get_session` insusi arunca —
    # si ala e chiar modul cel mai probabil de esec. Lasat afara, ar fi ocolit
    # protectia si ar fi blocat livrarea. (Prins de test la injectare deliberata.)
    session = None
    try:
        session = get_session()
        rand = DeclaratieGenerata(
            user_id=user_id, tip=tip, an=an, luna=luna, d_rec=d_rec,
            inputuri_json=inputuri, rezultat_json=rezultat,
            xml=xml, nume_fisier_xml=nume_fisier_xml,
            generat=generat, motiv_negenerat=motiv_negenerat,
        )
        session.add(rand)
        session.commit()
        rid = rand.id
        logger.info(
            f"ARHIVA declaratie: id={rid} user={user_id} {tip} "
            f"an={an} luna={luna} d_rec={d_rec} generat={generat}"
        )
        return rid
    except Exception as e:
        if session is not None:
            try:
                session.rollback()
            except Exception:
                logger.exception("rollback esuat in arhiva declaratii")
        # ZGOMOTOS — „a plecat o declaratie si n-am inregistrat-o" trebuie sa TIPE.
        # Contextul de mai jos e minimul din care se poate reconstrui manual randul.
        logger.error(
            "❌ ARHIVARE DECLARATIE ESUATA (declaratia SE LIVREAZA oricum) — "
            f"user={user_id} tip={tip} an={an} luna={luna} d_rec={d_rec} "
            f"generat={generat} motiv_negenerat={motiv_negenerat} "
            f"nume_fisier={nume_fisier_xml} xml_bytes="
            f"{len(xml.encode('utf-8')) if xml else 0} "
            f"rezultat={rezultat} eroare={e!r}",
            exc_info=True,
        )
        try:
            monitoring.capture_exception(e, stage="declaratii_arhiva")
        except Exception:
            logger.exception("monitoring.capture_exception a esuat in arhiva")
        return None
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                logger.exception("close esuat in arhiva declaratii")


def _rezultat_declaratie(rez):
    """Partea de rezultat a unui RezultatDeclaratie (D100/D301/D390/D207)."""
    return {
        "are_plata": bool(getattr(rez, "are_plata", False)),
        "suma_plata": _val(getattr(rez, "suma_plata", 0.0)),
        "namespace_de_confirmat": bool(getattr(rez, "namespace_de_confirmat", False)),
        "avertismente": _val(list(getattr(rez, "avertismente", None) or [])),
        # „De ce"-ul deja compus — materia prima pentru „Audit Trail" (I1).
        "ghid_plain": getattr(rez, "ghid_plain", None),
    }


# ════════════════════════════════════════════════════════════
#   PUNCTELE DE INTRARE — cate unul per generator
# ════════════════════════════════════════════════════════════

def genereaza_si_arhiveaza(user_id, tip, an, luna, baza_intracom_lei,
                           firma=None, **kw):
    """
    D100 / D301 / D390 — cheama `declaratii_service.genereaza` si arhiveaza.

    Semnatura oglindeste generatorul; `**kw` trece mai departe parametrii optionali
    (d_rec, factura_nr, factura_data, cota_nerezident, d100_plan, intracom_by_brand).
    Intoarce EXACT ce intoarce generatorul — apelantul livreaza ca pana acum.
    """
    rez = _decl.genereaza(tip, an, luna, baza_intracom_lei, firma=firma, **kw)

    inputuri = {
        "tip": tip, "an": an, "luna": luna,
        "baza_intracom_lei": _val(baza_intracom_lei),
        "firma": serializeaza_firma(firma),
        **{k: _val(v) for k, v in kw.items()},
    }
    _arhiveaza(
        user_id=user_id, tip=rez.tip, an=rez.an, luna=rez.luna,
        d_rec=int(kw.get("d_rec", 0) or 0),
        inputuri=inputuri, rezultat=_rezultat_declaratie(rez),
        xml=(rez.xml or None), nume_fisier_xml=(rez.nume_fisier_xml or None),
        generat=bool(rez.generat), motiv_negenerat=rez.motiv_negenerat,
    )
    return rez


def genereaza_si_arhiveaza_d207(user_id, an, firma, by_brand, profile, *, d_rec=0):
    """D207 (anuala) — `luna` ramane NULL in arhiva."""
    rez = _decl.genereaza_d207_anual(an, firma, by_brand, profile, d_rec=d_rec)

    inputuri = {
        "an": an,
        "firma": serializeaza_firma(firma),
        "by_brand": _val(by_brand),
        "profile": serializeaza_profil(profile),
        "d_rec": d_rec,
    }
    _arhiveaza(
        user_id=user_id, tip="D207", an=an, luna=None, d_rec=int(d_rec or 0),
        inputuri=inputuri, rezultat=_rezultat_declaratie(rez),
        xml=(rez.xml or None), nume_fisier_xml=(rez.nume_fisier_xml or None),
        generat=bool(rez.generat), motiv_negenerat=rez.motiv_negenerat,
    )
    return rez


def genereaza_si_arhiveaza_d212(user_id, an, venit_brut_anual, cheltuieli_anuale,
                                salariu_minim=4050, **kw):
    """
    D212 (anuala) — calcul + ghid, si XML daca apelantul da `identitate`+`activitate`.

    Fara ele (calea de estimare) `xml` ramane NULL, ca inainte. Cu ele, XML-ul se
    genereaza in serviciu si se arhiveaza aici — o singura cale spre generator,
    ca la celelalte patru.

    Inputurile sunt exact ce face reproductibil calculul: regim, norma, pensionar,
    asigurat_salariat, datele de activitate si salariul minim al anului — adica tocmai
    ce se citea pana acum TACIT din profilul de azi la o recalculare.
    """
    rez = _decl.genereaza_d212(
        an, venit_brut_anual, cheltuieli_anuale, salariu_minim, **kw
    )

    # `identitate`/`activitate` sunt dataclass-uri (nu JSON) SI contin date
    # personale (CNP). Nu intra in `inputuri`: reproductibilitatea calculului nu
    # depinde de ele — sunt datele de pe formular, nu cifrele.
    inputuri = {
        "an": an,
        "venit_brut_anual": _val(venit_brut_anual),
        "cheltuieli_anuale": _val(cheltuieli_anuale),
        "salariu_minim": salariu_minim,
        **{k: _val(v) for k, v in kw.items()
           if k not in ("identitate", "activitate")},
    }
    rezultat = {
        "venit_brut": _val(rez.venit_brut), "cheltuieli": _val(rez.cheltuieli),
        "venit_net": _val(rez.venit_net), "cas": _val(rez.cas), "cass": _val(rez.cass),
        "impozit": _val(rez.impozit), "total_plata": _val(rez.total_plata),
        "bonificatie": _val(rez.bonificatie),
        "total_cu_bonificatie": _val(rez.total_cu_bonificatie),
        "regim": rez.regim,
        "cas_baza": _val(rez.cas_baza), "cass_baza": _val(rez.cass_baza),
        "venit_impozabil": _val(rez.venit_impozabil),
        "avertismente": _val(list(rez.avertismente or [])),
        "ghid_plain": rez.ghid_plain,
        "motiv_fara_xml": rez.motiv_fara_xml,
    }
    _arhiveaza(
        user_id=user_id, tip="D212", an=an, luna=None,
        d_rec=int(kw.get("d_rec", 0) or 0),
        inputuri=inputuri, rezultat=rezultat,
        xml=rez.xml, nume_fisier_xml=rez.nume_fisier_xml,
        generat=rez.generat, motiv_negenerat=(
            "norma_venit" if (rez.motiv_fara_xml and not rez.xml) else None),
    )
    return rez


# ════════════════════════════════════════════════════════════
#   CITIRI — arhiva e append-only, deci doar SELECT
# ════════════════════════════════════════════════════════════

def listeaza(session, *, user_id, tip=None, an=None, limit=50):
    """Declaratiile arhivate ale unui user, cele mai recente intai."""
    q = session.query(DeclaratieGenerata).filter(
        DeclaratieGenerata.user_id == user_id
    )
    if tip:
        q = q.filter(DeclaratieGenerata.tip == tip)
    if an:
        q = q.filter(DeclaratieGenerata.an == an)
    return q.order_by(DeclaratieGenerata.created_at.desc()).limit(limit).all()
