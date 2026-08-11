"""
D212 — generator XML (Declaratia Unica, PFA activitate independenta, sistem real).

Validarea e pe schemele OFICIALE ANAF vendorizate in app/integrations/anaf/scheme/d212/:
  - XSD (d212_schema.xsd, namespace v11) — structura si tipurile
  - Schematron (D212.sch + syntax/codes/business) — regulile BR-D212-* / CD-D212-*

Plus un GARDIAN ARITMETIC al nostru, fiindca Schematron-ul ANAF nu verifica
rd.1 - rd.2: o minciuna COERENTA (net gresit, dar recalculat la fel de gresit)
trece de toate cele ~118 reguli ANAF. Vezi test_schematron_anaf_nu_prinde_*.
"""

import re
from dataclasses import dataclass
from datetime import date

import pytest

from app.integrations.anaf import d212_generator as d212
from app.integrations.anaf.d212_calc import calculeaza_d212

AN = 2025


# ════════════════════════════════════════════════════════
#                     AJUTOARE
# ════════════════════════════════════════════════════════

def _identitate(**kw):
    date_ = dict(cnp="1900101400012", nume="POPESCU", prenume="ION",
                 sediu="Bucuresti, Sector 3", email="ion@example.ro",
                 telefon="0722000000", iban="RO49AAAA1B31007593840000")
    date_.update(kw)
    return d212.IdentitateD212(**date_)


def _activitate(**kw):
    date_ = dict(caen="4932", den_caen="Transporturi terestre de pasageri, ocazionale",
                 nr_doc_autorizare="B/12/345/2019",
                 data_doc_autorizare=date(2019, 3, 15))
    date_.update(kw)
    return d212.ActivitateD212(**date_)


@dataclass
class RezultatFals:
    """Rezultat de calcul fabricat — pentru injectarea de incoerente aritmetice."""
    venit_brut: float
    cheltuieli: float
    venit_net: float
    cas: float
    cas_baza: float
    cass: float
    cass_baza: float
    venit_impozabil: float
    impozit: float
    bonificatie: float
    salariu_minim: int = 4050
    regim: str = "SISTEM_REAL"


def _rezultat_real(venit_brut=120000, cheltuieli=45000):
    return calculeaza_d212(venit_brut=venit_brut,
                           cheltuieli_deductibile=cheltuieli, an=AN)


def _xml(rezultat=None, **kw):
    return d212.genereaza_d212(
        an_venituri=AN,
        identitate=kw.pop("identitate", _identitate()),
        activitate=kw.pop("activitate", _activitate()),
        rezultat=rezultat if rezultat is not None else _rezultat_real(),
        **kw)


def _atribute(xml, tag):
    m = re.search(rf"<{tag}\b([^>]*)/?>", xml)
    return dict(re.findall(r'([\w\-]+)="([^"]*)"', m.group(1))) if m else {}


# ════════════════════════════════════════════════════════
#      GARDIAN ARITMETIC — al nostru, nu al ANAF
# ════════════════════════════════════════════════════════

def verifica_aritmetica(xml: str):
    """Returneaza lista de incoerente aritmetice din XML-ul generat (goala = curat).

    Schematron-ul ANAF NU verifica aceste doua identitati. Sunt fundamentul
    declaratiei: daca venitul net nu e brut minus cheltuieli, tot restul
    (CAS, CASS, impozit) e construit pe o cifra falsa.
    """
    erori = []
    cap11 = _atribute(xml, "cap11")
    oblig = _atribute(xml, "oblig_realizat")

    def n(dictionar, cheie):
        return int(dictionar.get(cheie, 0) or 0)

    brut, chelt = n(cap11, "venit_brut"), n(cap11, "chelt_deduc")
    net = n(cap11, "venit_net_anual")
    if net != brut - chelt:
        erori.append(f"venit_net_anual={net} dar venit_brut-chelt_deduc={brut - chelt}")

    if oblig.get("real_venit_net_impozabil_ai") is not None and oblig:
        impozabil = n(oblig, "real_venit_net_impozabil_ai")
        cas, cass = n(oblig, "cas_datorat"), n(oblig, "cass_datorat_ai")
        if "real_venit_net_impozabil_ai" in oblig and impozabil != net - cas - cass:
            erori.append(
                f"real_venit_net_impozabil_ai={impozabil} dar "
                f"venit_net-CAS-CASS={net - cas - cass}")
    return erori


def test_gardian_aritmetic_trece_pe_calculul_real():
    assert verifica_aritmetica(_xml()) == []


def test_gardian_aritmetic_prinde_net_fals():
    """Injectare: net care nu e brut - cheltuieli."""
    fals = RezultatFals(venit_brut=120000, cheltuieli=45000,
                        venit_net=70000,           # ← minciuna: ar trebui 75000
                        cas=12150, cas_baza=48600, cass=7000, cass_baza=70000,
                        venit_impozabil=50850, impozit=5085, bonificatie=153)
    erori = verifica_aritmetica(_xml(fals))
    assert any("venit_net_anual" in e for e in erori), erori


def test_gardian_aritmetic_prinde_impozabil_fals():
    """Injectare: impozabil care nu e net - CAS - CASS."""
    fals = RezultatFals(venit_brut=120000, cheltuieli=45000, venit_net=75000,
                        cas=12150, cas_baza=48600, cass=7500, cass_baza=75000,
                        venit_impozabil=60000,     # ← minciuna: ar trebui 55350
                        impozit=6000, bonificatie=180)
    erori = verifica_aritmetica(_xml(fals))
    assert any("real_venit_net_impozabil_ai" in e for e in erori), erori


# ════════════════════════════════════════════════════════
#      STRUCTURA (fara dependinte externe)
# ════════════════════════════════════════════════════════

def test_namespace_si_radacina_exacte():
    xml = _xml()
    assert 'xmlns="mfp:anaf:dgti:d212:declaratie:v11"' in xml
    assert "<d212 " in xml
    assert 'luna_r="12"' in xml          # BR-D212-0005
    assert 'an_r="2026"' in xml          # an_r = an_venituri + 1 (BR-D212-0006)


def test_oblig_realizat_inaintea_lui_cap11():
    """Secventa din XSD: oblig_realizat, apoi cap11. Ordinea inversa = invalid."""
    xml = _xml()
    assert xml.index("<oblig_realizat") < xml.index("<cap11")


def test_total_plata_a_e_suma_cifrelor_din_cnp():
    """BR-D212-0004 — suma de control ciudata, dar asta e regula."""
    xml = _xml(identitate=_identitate(cnp="1900101400012"))
    assert _atribute(xml, "d212")["totalPlata_A"] == "19"


def test_campurile_lasate_goale_deliberat_lipsesc():
    """Nu inventam ce nu stim: formularul ANAF e editabil, completeaza userul."""
    xml = _xml()
    for camp in ("initiala_c", "statut", "pierdere_precedenta", "pierdere_compensata"):
        assert f'{camp}="' not in xml


def test_atributele_optionale_goale_se_omit_nu_se_scriu_vide():
    """SN-D212-002 respinge atributele prezente-dar-vide."""
    xml = _xml(identitate=_identitate(email="", telefon="", iban=""))
    assert 'email_c=""' not in xml and "email_c" not in xml
    assert "cont_bancar" not in xml


def test_cifrele_ajung_in_xml():
    xml = _xml()
    cap11 = _atribute(xml, "cap11")
    oblig = _atribute(xml, "oblig_realizat")
    assert cap11["venit_brut"] == "120000"
    assert cap11["chelt_deduc"] == "45000"
    assert cap11["venit_net_anual"] == "75000"
    assert oblig["cas_baza"] == "48600" and oblig["cas_datorat"] == "12150"
    assert oblig["baza_cass_datorat_ai"] == "75000" and oblig["cass_datorat_ai"] == "7500"
    assert oblig["real_venit_net_impozabil_ai"] == "55350"
    assert oblig["real_impozit_datorat_ai"] == "5535"
    assert oblig["oblimpozit_real_bonif"] == "166"


# ════════════════════════════════════════════════════════
#      BIFELE — derivate din starea reala, nu fixe
# ════════════════════════════════════════════════════════

def test_bifele_pornesc_cand_exista_obligatia():
    radacina = _atribute(_xml(), "d212")
    assert radacina["bifa111"] == "1"      # avem cap11
    assert radacina["bifa131"] == "1"      # CAS > 0
    assert radacina["bifa132"] == "1"      # CASS > 0
    assert radacina["bifa14"] == "1"       # impozit > 0
    assert radacina["bifa18"] == "1"       # bonificatie > 0


def test_fara_cas_bifa131_e_zero_si_sectiunea_lipseste():
    """Venit net sub 12 salarii minime → CAS 0. Bifa NU trebuie sa fie 1."""
    rez = _rezultat_real(venit_brut=40000, cheltuieli=10000)   # net 30000 < 48600
    assert rez.cas == 0
    xml = _xml(rez)
    assert _atribute(xml, "d212")["bifa131"] == "0"
    # atributul exact, nu substring: `cas_datorata_ai` din Sectiunea 4 e alt camp
    assert 'cas_datorat="' not in xml and 'cas_baza="' not in xml


def test_bifa_cas_real_urmeaza_pragul():
    """1 = intre 12 si 24 salarii minime, 2 = peste 24 (BR-D212-0047)."""
    sub24 = _xml(_rezultat_real(venit_brut=120000, cheltuieli=45000))   # net 75000
    assert _atribute(sub24, "oblig_realizat")["bifa_cas_real"] == "1"
    peste24 = _xml(_rezultat_real(venit_brut=200000, cheltuieli=50000))  # net 150000
    assert _atribute(peste24, "oblig_realizat")["bifa_cas_real"] == "2"


# ════════════════════════════════════════════════════════
#      REFUZURI (mai bine nimic decat un fisier fals)
# ════════════════════════════════════════════════════════

def test_refuza_cnp_incomplet():
    with pytest.raises(ValueError, match="CNP invalid"):
        _xml(identitate=_identitate(cnp="123"))


def test_refuza_fara_nume():
    with pytest.raises(ValueError, match="[Nn]ume"):
        _xml(identitate=_identitate(nume="  "))


def test_refuza_fara_certificat_onrc():
    """BR-D212-0095 il cere. Nu inventam un numar de autorizatie."""
    with pytest.raises(ValueError, match="ONRC"):
        _xml(activitate=_activitate(nr_doc_autorizare=""))


def test_ghidul_nu_cere_userului_ce_completam_noi():
    """Certificatul ONRC il punem noi (e input obligatoriu) — sa nu-l mai ceara ghidul."""
    ghid = d212.genereaza_ghid_d212(AN, _rezultat_real(), plain=True)
    dupa_titlu = ghid.split("Ce trebuie sa completezi TU")[1]
    assert "ONRC" not in dupa_titlu
    assert "Initiala tatalui" in dupa_titlu


def test_ghidul_spune_ca_baza_cas_e_o_alegere():
    ghid = d212.genereaza_ghid_d212(AN, _rezultat_real(), plain=True)
    assert "ALEGERE" in ghid and "MARESTI" in ghid
    assert "48600" in ghid           # minimul aplicabil, pus de noi


def test_refuza_norma_de_venit():
    """Norma se declara in cap12, alta structura — nu o aproximam cu cap11."""
    rez = calculeaza_d212(venit_brut=0, cheltuieli_deductibile=0, an=AN,
                          regim="NORMA_VENIT", norma_anuala=30000)
    with pytest.raises(ValueError, match="SISTEM_REAL"):
        _xml(rez)


def test_data_dintr_un_alt_an_se_omite_nu_se_falsifica():
    """BR-D212-0023: anul oricarei date = an_r - 1. Activitate din 2019 → omisa."""
    xml = _xml(activitate=_activitate(data_incepere=date(2019, 3, 15)))
    assert "data_incep=" not in xml
    xml_in_an = _xml(activitate=_activitate(data_incepere=date(AN, 3, 15)))
    assert 'data_incep="15.03.2025"' in xml_in_an


# ════════════════════════════════════════════════════════
#      SCHEMELE OFICIALE ANAF (XSD + Schematron)
# ════════════════════════════════════════════════════════

lxml = pytest.importorskip("lxml", reason="lxml lipseste — vezi requirements-dev.txt")


def test_valid_contra_xsd_oficial():
    from tests import anaf_schema_validare as validare
    assert validare.valideaza_xsd(_xml()) == []


def test_valid_contra_xsd_si_fara_cas():
    from tests import anaf_schema_validare as validare
    rez = _rezultat_real(venit_brut=40000, cheltuieli=10000)
    assert validare.valideaza_xsd(_xml(rez)) == []


@pytest.fixture(scope="module")
def validare_schematron():
    pytest.importorskip("saxonche",
                        reason="saxonche lipseste — vezi requirements-dev.txt")
    from tests import anaf_schema_validare as validare
    return validare


def test_valid_contra_schematron_anaf(validare_schematron):
    esecuri, _ = validare_schematron.valideaza_schematron(_xml())
    assert esecuri == [], [f"{e['id']}: {e['text']}" for e in esecuri]


def test_valid_contra_schematron_si_fara_cas(validare_schematron):
    """PFA mic, sub plafonul CAS: bifa131=0, sectiunea 3.1 lipseste cu totul."""
    rez = _rezultat_real(venit_brut=40000, cheltuieli=10000)
    esecuri, _ = validare_schematron.valideaza_schematron(_xml(rez))
    assert esecuri == [], [f"{e['id']}: {e['text']}" for e in esecuri]


def test_lantul_chiar_ruleaza(validare_schematron):
    """ANTI-TEATRU: fara peticul axei de atribute se declanseaza 6 reguli din ~118.

    Un validator care spune DA dupa ce a evaluat 5% din reguli e mai rau decat
    niciun validator, fiindca da incredere falsa. Pragul prinde disparitia peticului.
    """
    _, reguli = validare_schematron.valideaza_schematron(_xml())
    assert reguli >= validare_schematron.PRAG_REGULI, (
        f"doar {reguli} reguli declansate — peticul axei de atribute lipseste?")


def test_schematron_anaf_nu_prinde_minciuna_coerenta(validare_schematron):
    """De ce avem gardian propriu: ANAF nu verifica rd.1 - rd.2.

    Net fals, dar recalculat coerent peste tot → trece de toate regulile ANAF.
    Daca ANAF adauga cindva regula, testul asta cade si stergem gardianul nostru.
    """
    fals = RezultatFals(venit_brut=120000, cheltuieli=45000,
                        venit_net=70000,          # ← nu e 120000 - 45000
                        cas=12150, cas_baza=48600, cass=7000, cass_baza=70000,
                        venit_impozabil=50850, impozit=5085, bonificatie=153)
    xml = _xml(fals)
    esecuri, _ = validare_schematron.valideaza_schematron(xml)
    assert esecuri == [], "ANAF a inceput sa verifice aritmetica — reevalueaza gardianul"
    assert verifica_aritmetica(xml) != [], "gardianul nostru trebuie sa prinda"
