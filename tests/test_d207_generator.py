"""
D207 — generator XML + serviciu anual (informativa nerezidenti).

D207 = perechea ANUALA a lui D100. Centralizeaza comisioanele catre platforme
nerezidente + impozitul, INCLUSIV partea SCUTITA (Uber 0% cu certificat — motivul
pentru care D207 exista: scutirea NU te scapa de raportare).

Structura XML confirmata byte-cu-byte cu XSD-ul oficial ANAF (d207_20025020.xsd,
namespace v2): root <declaratie207>, <sect_II> (per natura venit) + <benef> FRATI
in secventa (toate sect_II intai, apoi toti benef).
"""

import re

import pytest

from app.integrations.anaf import d207_generator as d207
from app.integrations.anaf import declaratii_service as decl
from app.domain.fiscal_profile import from_user_dict


def _profile(bolt=None, uber=None):
    return from_user_dict({
        "firma_forma_juridica": "PFA",
        "regim_nerezident_bolt": bolt,
        "regim_nerezident_uber": uber,
    })


def _firma():
    return decl.date_firma_stefan()


def _attrs(xml: str, tag: str):
    """Lista de dict-uri de atribute pentru fiecare element <tag .../> din XML."""
    out = []
    for m in re.finditer(rf"<{tag}\b([^/]*)/>", xml):
        out.append(dict(re.findall(r'(\w+)="([^"]*)"', m.group(1))))
    return out


AN = 2025


# ════════════════════════════════════════════════════════
# 7. Namespace + root exact (confirmate cu XSD oficial)
# ════════════════════════════════════════════════════════
def test_namespace_si_root_exact():
    rez = decl.genereaza_d207_anual(AN, _firma(), {"bolt": 1000.0},
                                    _profile(bolt="BOLT_CU_CRF"))
    assert 'xmlns="mfp:anaf:dgti:d207:declaratie:v2"' in rez.xml
    assert "<declaratie207 " in rez.xml
    assert 'luna="12"' in rez.xml                 # XSD cere fix 12 (anuala)
    assert rez.nume_fisier_xml == f"D207_{AN}.xml"


# ════════════════════════════════════════════════════════
# 1. Bolt-only → benef 04/EE cu impozit, sect_II Timp=impozit
# ════════════════════════════════════════════════════════
def test_bolt_only():
    rez = decl.genereaza_d207_anual(AN, _firma(), {"bolt": 1000.0},
                                    _profile(bolt="BOLT_CU_CRF"))
    assert rez.generat is True and rez.are_plata is False   # informativa, fara plata
    benefs = _attrs(rez.xml, "benef")
    assert len(benefs) == 1
    b = benefs[0]
    assert b["tip_venit1"] == "04"
    assert b["Stat_R"] == "EE"
    assert b["den1"] == "BOLT OPERATIONS OU"
    assert b["cifS"] == "102090374"               # cod fiscal strain (sursa unica)
    assert "cifR" not in b                          # NIF RO omis (nerezident)
    assert b["baza1"] == "1000"
    assert b["imp1"] == "20"                        # round(1000 × 2%)
    assert b["Act_N"] == "2"                        # Conventia aplicata
    sect = _attrs(rez.xml, "sect_II")
    assert len(sect) == 1 and sect[0]["tip_venit"] == "04"
    assert sect[0]["Tbaza"] == "1000" and sect[0]["Timp"] == "20"
    assert sect[0]["nrben"] == "1" and sect[0]["Tscutit"] == "0"


# ════════════════════════════════════════════════════════
# 2. Uber-only SCUTIT (impozit 0) dar OBLIGATORIU declarat
# ════════════════════════════════════════════════════════
def test_uber_only_scutit_dar_declarat():
    rez = decl.genereaza_d207_anual(AN, _firma(), {"uber": 500.0},
                                    _profile(uber="UBER_CU_CRF"))
    assert rez.generat is True                      # SCUTIT dar TOT se genereaza
    benefs = _attrs(rez.xml, "benef")
    assert len(benefs) == 1
    b = benefs[0]
    assert b["tip_venit1"] == "25"
    assert b["Stat_R"] == "NL"
    assert b["den1"] == "UBER B.V."
    assert b["cifS"] == "852071589B01"
    assert b["baza1"] == "500"
    assert b["imp1"] == "0"                          # scutit → impozit 0
    sect = _attrs(rez.xml, "sect_II")
    assert sect[0]["tip_venit"] == "25" and sect[0]["Timp"] == "0"
    assert sect[0]["Tbaza"] == "500"


# ════════════════════════════════════════════════════════
# 3. Bolt + Uber → 2× sect_II, 2× benef, coduri corecte
# ════════════════════════════════════════════════════════
def test_bolt_plus_uber():
    rez = decl.genereaza_d207_anual(
        AN, _firma(), {"bolt": 1000.0, "uber": 500.0},
        _profile(bolt="BOLT_CU_CRF", uber="UBER_CU_CRF"))
    sect = _attrs(rez.xml, "sect_II")
    benefs = _attrs(rez.xml, "benef")
    assert len(sect) == 2 and len(benefs) == 2
    assert {s["tip_venit"] for s in sect} == {"04", "25"}
    tv_stat = {b["tip_venit1"]: b["Stat_R"] for b in benefs}
    assert tv_stat == {"04": "EE", "25": "NL"}
    # id_inreg secvential
    assert {b["id_inreg"] for b in benefs} == {"1", "2"}
    # sect_II TOATE inaintea benef (ordinea secventei XSD)
    assert rez.xml.index("<sect_II") < rez.xml.index("<benef")
    assert rez.xml.rindex("<sect_II") < rez.xml.index("<benef")


# ════════════════════════════════════════════════════════
# 5. totalPlata_A = Σ (nrben + Tscutit + Tbaza + Timp + Timps)
# ════════════════════════════════════════════════════════
def test_total_plata_a_checksum():
    rez = decl.genereaza_d207_anual(
        AN, _firma(), {"bolt": 1000.0, "uber": 500.0},
        _profile(bolt="BOLT_CU_CRF", uber="UBER_CU_CRF"))
    m = re.search(r'totalPlata_A="(\d+)"', rez.xml)   # atribut pe tagul-radacina (deschis)
    assert m
    total = int(m.group(1))
    # sect 04: 1 + 0 + 1000 + 20 + 0 = 1021 ; sect 25: 1 + 0 + 500 + 0 + 0 = 501
    sect = _attrs(rez.xml, "sect_II")
    asteptat = sum(int(s["nrben"]) + int(s["Tscutit"]) + int(s["Tbaza"])
                   + int(s["Timp"]) + int(s["Timps"]) for s in sect)
    assert total == asteptat == 1522


# ════════════════════════════════════════════════════════
# 6. Brand neatribuit (None cu comision) → OPRESTE (optiunea b)
# ════════════════════════════════════════════════════════
def test_neatribuit_opreste():
    with pytest.raises(ValueError) as ei:
        decl.genereaza_d207_anual(AN, _firma(), {"bolt": 1000.0, None: 300.0},
                                  _profile(bolt="BOLT_CU_CRF"))
    msg = str(ei.value).lower()
    assert "platform" in msg and "300" in str(ei.value)


def test_regim_nesetat_opreste():
    # Bolt cu comision dar regim nerezident nesetat → nu putem calcula impozitul.
    with pytest.raises(ValueError):
        decl.genereaza_d207_anual(AN, _firma(), {"bolt": 1000.0}, _profile(bolt=None))


# ════════════════════════════════════════════════════════
# An fara comisioane → negenerat (nu XML gol invalid)
# ════════════════════════════════════════════════════════
def test_an_fara_comisioane_negenerat():
    rez = decl.genereaza_d207_anual(AN, _firma(), {}, _profile())
    assert rez.generat is False
    assert rez.motiv_negenerat == "fara_baza"
    assert rez.xml == ""


# ════════════════════════════════════════════════════════
# Generatorul pur — garda pe lista goala
# ════════════════════════════════════════════════════════
def test_generator_lista_goala_ridica():
    ident = d207.IdentitateD207(cui="12345678", denumire="X PFA", adresa="ADR",
                                nume_declarant="A", prenume_declarant="B")
    with pytest.raises(ValueError):
        d207.genereaza_d207(AN, ident, [])
