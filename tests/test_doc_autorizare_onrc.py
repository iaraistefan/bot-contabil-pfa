"""
Certificatul ONRC → nr_doc_autoriz / data_doc_autoriz (D212).

Trei lucruri se masoara aici:

1. GARDIANUL de lungime. nr_doc_autoriz e C15Type (maxLength 15). Peste 15
   trebuie sa CADA, nu sa trunchieze: un numar de registru taiat trece de XSD
   fara sa clipeasca si ajunge in declaratie ca numar FALS. Cazul de 15 fix
   („F06/123456/2018", forma veche) trebuie sa treaca — limita e inclusiva.

2. CONVERSIA de data. ANAF da „YYYY-MM-DD", D212 cere D10Type cu lungime FIXA
   10, in forma zz.ll.aaaa. Conversie prin `date`, nu copiere de sir.

3. WIRING-ul pe amandoua drumurile: allowlist-ul web, campurile de tip data si
   parametrii repo-ului exista si sunt legati.
"""

from datetime import date

import pytest

from app.domain.doc_autorizare import (
    LEN_DATA_DOC_AUTORIZARE,
    MAX_LEN_NR_DOC_AUTORIZARE,
    NrDocAutorizarePreaLung,
    formateaza_data_d212,
    normalizeaza_nr_doc_autorizare,
    parseaza_data_anaf,
    text_confirmare_data,
)


# ── 1. Gardianul de lungime ──────────────────────────────────

@pytest.mark.parametrize("nr", ["J2018000137062", "F2025049962009"])
def test_numarul_real_din_anaf_trece(nr):
    # doua esantioane verificate pe CUI-uri reale (un SRL si un PFA): formatul
    # nou ONRC da 14 caractere, identic caracter cu caracter cu certificatul
    assert len(nr) == 14
    assert normalizeaza_nr_doc_autorizare(nr) == nr


def test_forma_veche_de_15_caractere_trece():
    # limita e INCLUSIVA — „F06/123456/2018" are exact 15
    vechi = "F06/123456/2018"
    assert len(vechi) == MAX_LEN_NR_DOC_AUTORIZARE
    assert normalizeaza_nr_doc_autorizare(vechi) == vechi


def test_peste_15_cade_zgomotos_nu_trunchiaza():
    prea_lung = "F06/1234567/2018"          # 16
    with pytest.raises(NrDocAutorizarePreaLung) as exc:
        normalizeaza_nr_doc_autorizare(prea_lung)
    # mesajul spune de ce, si nu returneaza nimic taiat
    assert "15" in str(exc.value)


def test_gol_si_none_dau_none():
    assert normalizeaza_nr_doc_autorizare(None) is None
    assert normalizeaza_nr_doc_autorizare("") is None
    assert normalizeaza_nr_doc_autorizare("   ") is None


def test_spatiile_se_string_inainte_de_masuratoare():
    # „J 2018 000137062" are 16 caractere brut, dar 14 reale — nu e o depasire
    assert normalizeaza_nr_doc_autorizare("J 2018 000137062") == "J2018000137062"


# ── 2. Conversia de data ─────────────────────────────────────

def test_data_anaf_devine_obiect_date():
    assert parseaza_data_anaf("2025-12-05") == date(2025, 12, 5)


def test_data_anaf_cu_ora_se_taie_la_zi():
    assert parseaza_data_anaf("2025-12-05 00:00:00") == date(2025, 12, 5)


def test_data_invalida_da_none_nu_arunca():
    assert parseaza_data_anaf("") is None
    assert parseaza_data_anaf(None) is None
    assert parseaza_data_anaf("05.12.2025") is None      # deja in alt format
    assert parseaza_data_anaf("2025-13-45") is None      # luna/zi imposibile


def test_formatul_d212_e_zz_ll_aaaa_de_fix_10():
    s = formateaza_data_d212(date(2025, 12, 5))
    assert s == "05.12.2025"
    assert len(s) == LEN_DATA_DOC_AUTORIZARE          # D10Type, lungime fixa


def test_ziua_si_luna_sunt_cu_zero_in_fata():
    # 5 ianuarie → „05.01.2026", nu „5.1.2026" (ar avea 8, nu 10)
    assert formateaza_data_d212(date(2026, 1, 5)) == "05.01.2026"


# ── 3. Textul de confirmare ──────────────────────────────────

def test_textul_arata_data_in_formatul_declaratiei():
    # pereche COERENTA: numarul si data sunt ale aceluiasi PFA, dintr-un singur
    # lookup. (Numarul si data vin mereu din acelasi `_parse_anaf_response`.)
    t = text_confirmare_data(date(2025, 12, 5), nr_doc="F2025049962009")
    assert "05.12.2025" in t                    # cifra i-o aratam cum va aparea
    assert "F2025049962009" in t                # si numarul de unde vine
    assert "zz.ll.aaaa" in t                    # ce sa faca daca difera


def test_textul_fara_data_cere_userului_data():
    # Fraza e NEUTRA fata de motiv, dinadins: acelasi text serveste configurarea
    # (ANAF n-a dat data) si Setarile (userul a amanat-o). Varianta initiala,
    # „n-am gasit-o in ANAF", ar fi fost falsa pe al doilea drum.
    t = text_confirmare_data(None)
    assert "Data nu e completată încă" in t


# ── 4. Wiring ────────────────────────────────────────────────

def test_web_accepta_ambele_campuri_iar_data_e_tratata_ca_data():
    from app.http import app as webapp
    assert "nr_doc_autorizare" in webapp._ONBOARDING_SAVE_FIELDS
    assert "data_doc_autorizare" in webapp._ONBOARDING_SAVE_FIELDS
    # data trebuie sa fie in lista de DATE, altfel ar ajunge string in coloana DATE
    assert "data_doc_autorizare" in webapp._ONBOARDING_DATE_FIELDS


def test_repo_are_parametrii_si_profilul_ii_expune():
    import inspect
    from app.repositories import users as users_repo
    p = inspect.signature(users_repo.update_profile).parameters
    assert "nr_doc_autorizare" in p and "data_doc_autorizare" in p


def test_lookup_anaf_intoarce_numarul_si_data_pe_drumul_web():
    # endpoint-ul trebuie sa le puna in JSON — pana acum numarul nici nu iesea
    import inspect
    from app.http import app as webapp
    src = inspect.getsource(webapp)
    assert '"nr_doc_autorizare"' in src
    assert '"data_doc_autorizare_propusa"' in src


# ── 5. Amandoua suprafetele intreaba, si spun acelasi lucru ──
#
# PR #137 tocmai reparase asimetria „botul intreaba, web-ul nu". Aici ea nu are
# voie sa reapara: DOUA drumuri, ACELEASI promisiuni. Textul e scris de doua ori
# (bot in Python, web in template) — testul nu sterge duplicarea, dar face ca
# divergenta pe frazele purtatoare sa nu treaca in tacere.

_PROMISIUNI = [
    "ANAF le vrea pereche",          # de ce cerem si data
    "Data eliberării",               # de ce nu e o certitudine
    "documentul tău are dreptate",   # ce sa faca daca difera
    "zz.ll.aaaa",                    # in ce format
]


def _text_bot():
    return text_confirmare_data(date(2025, 12, 5), nr_doc="F2025049962009")


def _text_web():
    from pathlib import Path
    return (Path(__file__).resolve().parent.parent
            / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("promisiune", _PROMISIUNI)
def test_ambele_suprafete_fac_aceleasi_promisiuni(promisiune):
    assert promisiune.lower() in _text_bot().lower(), "lipseste din textul din bot"
    assert promisiune.lower() in _text_web().lower(), "lipseste din wizardul web"


def test_web_ul_confirma_data_si_o_trimite_ca_iso():
    html = _text_web()
    assert "wizCertConfirm" in html                 # butonul de confirmare exista
    assert "data_doc_autorizare:iso" in html        # si scrie campul, in ISO
    assert "wiz-cert-data" in html                  # cu input pre-completat


def test_botul_intreaba_data_cu_optiune_de_amanare():
    import inspect
    from app.services import onboarding
    src = inspect.getsource(onboarding)
    assert "onb|certdata|ok" in src                 # confirmare dintr-o apasare
    assert "onb|certdata|edit" in src               # corectare de pe certificat
    assert "onb|certdata|skip" in src               # NU e obligatorie


def test_d212_spune_explicit_ce_lipseste_daca_data_a_fost_sarita():
    # Amanarea e permisa, deci generatorul TREBUIE sa stie sa explice lipsa —
    # nu sa crape tehnic pe strftime(None).
    import inspect
    from app.integrations.anaf import d212_generator
    src = inspect.getsource(d212_generator.genereaza_d212)
    assert "Data certificatului ONRC lipseste" in src
    assert "BR-D212-0096" in src
