"""
Numele declarantului se capteaza la SURSA, nu se ghiceste dintr-un camp liber.

Bug-ul care a produs fisierul: pe CUI 53067338, ANAF intoarce
„IARAI ŞTEFAN PERSOANĂ FIZICĂ AUTORIZATĂ" (nume de familie intai), dar in
profil statea „ȘTEFAN IARAI PFA", tastat de mana. Derivarea „primele doua
cuvinte" e corecta pentru formatul ANAF si gresita pentru al doilea — deci D390
iesea cu nume_declar=STEFAN, prenume_declar=IARAI. Inversat, in XML-ul real.

Se masoara:
  1. profil CU campurile noi → numele corect in XML, fara nicio derivare;
  2. profil FARA ele → cade pe derivare SI aprinde avertismentul (verificat prin
     injectare: fara log, testul pica);
  3. sufixul cu diacritice se taie (varianta veche nu-l taia niciodata);
  4. un nume care contine „II" nu e mutilat (varianta veche facea
     „ILIIESCU" → „ILESCU");
  5. `name` (numele conversational din onboarding) NU ajunge in niciun XML —
     gardianul care tine promisiunea „nu apare pe niciun document" legata de cod.
"""

import inspect
import logging
import re

import pytest

from app.domain.nume_declarant import split_denumire
from app.integrations.anaf import declaratii_service as decl


def _profil(**kw):
    baza = {
        "firma_nume": "ȘTEFAN IARAI PFA",       # ordinea INVERSA, ca in baza reala
        "firma_cui": "53067338",
        "cod_special_tva": "53148882",
        "judet": "Bistrița-Năsăud",
        "localitate": "Bistrița",
    }
    baza.update(kw)
    return baza


def _xml_d390(profile):
    firma = decl.date_firma_din_profil(profile)
    return decl.genereaza("D390", 2026, 1, 1000.0, firma=firma).xml or ""


def _atr(xml, nume_atribut):
    m = re.search(nume_atribut + r'="([^"]*)"', xml)
    return m.group(1) if m else None


# ── 1. Cu campurile noi: numele corect, fara derivare ────────

def test_campurile_din_profil_bat_derivarea_din_firma_nume():
    xml = _xml_d390(_profil(nume_declarant="IARAI", prenume_declarant="ŞTEFAN"))
    assert _atr(xml, "nume_declar") == "IARAI"
    assert _atr(xml, "prenume_declar") == "STEFAN"        # diacriticele cad la emitere


def test_capturarea_din_denumirea_anaf_da_ordinea_corecta():
    # exact sirul intors azi de ANAF pe CUI-ul real
    assert split_denumire("IARAI ŞTEFAN PERSOANĂ FIZICĂ AUTORIZATĂ") == ("IARAI", "ŞTEFAN")


def test_prenume_compus_ramane_intreg():
    # al doilea PFA real din registru: prenume cu cratima
    assert split_denumire("BAROANĂ NICOLETA-ILEANA PERSOANĂ FIZICĂ AUTORIZATĂ") == (
        "BAROANĂ", "NICOLETA-ILEANA",
    )


def test_denumire_de_firma_nu_produce_nume_de_om():
    # SRL/SA: denumirea e un brand, nu o persoana → nu ghicim
    assert split_denumire("I-SHTEF SRL") == (None, None)
    assert split_denumire("ALFA SA") == (None, None)


# ── 2. Fara campuri: derivare + avertisment zgomotos ─────────

def test_fara_campuri_cade_pe_derivare_si_avertizeaza(caplog):
    with caplog.at_level(logging.WARNING):
        firma = decl.date_firma_din_profil(_profil())
    assert (firma.nume_declarant, firma.prenume_declarant) == ("ȘTEFAN", "IARAI")
    mesaje = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("poate fi inversat" in m for m in mesaje), (
        "derivarea dintr-un camp liber trebuie sa fie ZGOMOTOASA"
    )
    assert any("ȘTEFAN IARAI PFA" in m for m in mesaje)    # cu valoarea, ca sa fie gasibil


def test_cu_campuri_nu_avertizeaza(caplog):
    with caplog.at_level(logging.WARNING):
        decl.date_firma_din_profil(
            _profil(nume_declarant="IARAI", prenume_declarant="ŞTEFAN")
        )
    assert not [
        r for r in caplog.records
        if r.levelno >= logging.WARNING and "poate fi inversat" in r.getMessage()
    ], "profilul capturat la sursa nu are de ce sa avertizeze"


# ── 3-4. Cele doua hibe ale splitter-ului vechi ──────────────

def test_sufixul_cu_diacritice_se_taie():
    # varianta veche cauta „PERSOANA FIZICA AUTORIZATA" fara diacritice, deci nu
    # taia NICIODATA ce scrie ANAF; scapa doar fiindca lua primele doua cuvinte
    n, p = split_denumire("POPESCU ION PERSOANĂ FIZICĂ AUTORIZATĂ")
    assert (n, p) == ("POPESCU", "ION")
    assert "PERSOAN" not in (p or "")


def test_numele_care_contine_ii_nu_e_mutilat():
    # varianta veche: den.replace("II", "") → „ILIIESCU" devenea „ILESCU"
    n, p = split_denumire("ILIIESCU MARIA PERSOANĂ FIZICĂ AUTORIZATĂ")
    assert n == "ILIIESCU"
    assert p == "MARIA"


def test_ii_ca_forma_juridica_se_taie_totusi():
    # cuvantul „II" intreg ramane sufix valid — reparatia nu strica potrivirea
    assert split_denumire("POPESCU ION II") == ("POPESCU", "ION")


def test_pfa_cu_puncte_se_recunoaste():
    assert split_denumire("POPESCU ION P.F.A.") == ("POPESCU", "ION")


# ── 5. GARDIAN: `name` nu ajunge in niciun XML ───────────────
#
# Onboarding-ul promite, in bot: „Doar ca să știu cum să-ți spun — nu apare pe
# niciun document." Promisiunea e adevarata PRIN CONSTRUCTIE (numele de
# declarant vine din alta parte), dar constructia se poate schimba tacut. Testul
# ancoreaza promisiunea de cod.

_SENTINELA = "ZZSENTINELAZZ"


@pytest.mark.parametrize("tip", ["D390", "D301", "D100"])
def test_name_nu_ajunge_in_niciun_xml(tip):
    profile = _profil(
        name=_SENTINELA,                                   # numele conversational
        nume_declarant="IARAI", prenume_declarant="ŞTEFAN",
    )
    firma = decl.date_firma_din_profil(profile)
    assert _SENTINELA not in str(firma), "`name` s-a scurs in DateFirma"
    rez = decl.genereaza(tip, 2026, 1, 1000.0, firma=firma, cota_nerezident=0.02)
    assert _SENTINELA not in (rez.xml or ""), f"`name` a ajuns in XML-ul {tip}"
    assert _SENTINELA not in (rez.ghid_plain or ""), f"`name` a ajuns in ghidul {tip}"


def test_constructorul_de_date_firma_nu_citeste_name():
    # gardian static, in plus fata de cel comportamental: campul nici macar nu e
    # consultat, deci nu poate ajunge nicaieri printr-un drum nou
    src = inspect.getsource(decl.date_firma_din_profil)
    assert '"name"' not in src and "'name'" not in src


def test_promisiunea_din_onboarding_e_inca_scrisa():
    # daca textul se schimba, gardianul de mai sus trebuie recitit — nu sters
    from app.services import onboarding
    src = inspect.getsource(onboarding)
    assert "nu apare pe niciun document" in src
