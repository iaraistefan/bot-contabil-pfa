"""
Detecția formei juridice din denumire (`anaf_lookup._detect_forma_juridica_from_name`).

DE CE EXISTĂ ACEST FIȘIER: funcția n-avea niciun test. Suita o ocolea complet —
toate cele ~25 de trimiteri la `forma_juridica` din teste sunt fixture-uri care
pun direct "PFA", sau mock-uri de `lookup_cui` care întorc
`forma_juridica_detectata` gata calculat. Adică exact bucata de cod care ghicește
nu era executată niciodată de suită.

Și nu e o funcție marginală: pentru un PFA, ANAF întoarce `forma_juridica`,
`forma_organizare` și `forma_de_proprietate` GOALE (măsurat pe CUI 53067338,
13 august 2026). Drumul principal — harta pe câmpul oficial — nu se activează
deloc, deci răspunde plasa de siguranță, adică tocmai ghicitul din denumire.
"""

import pytest

from app.integrations.anaf_lookup import (
    _detect_forma_juridica_from_name as detecteaza,
    _map_forma_juridica,
)


# ════════════════════════════════════════════════════════
#   Cazul REAL din producție — cu diacritice
# ════════════════════════════════════════════════════════

def test_cazul_real_din_productie_cu_diacritice():
    """Exact ce a întors ANAF pentru CUI 53067338 pe 13 august 2026."""
    assert detecteaza("IARAI ŞTEFAN PERSOANĂ FIZICĂ AUTORIZATĂ") == "PFA"


def test_acelasi_caz_fara_diacritice():
    assert detecteaza("IARAI STEFAN PERSOANA FIZICA AUTORIZATA") == "PFA"


def test_ambele_variante_de_s_si_t_romanesc():
    """Ş (cedilă, U+015E) și Ș (virgulă, U+0218) — codificări diferite, același rezultat."""
    assert detecteaza("POPESCU ŞTEFAN PERSOANĂ FIZICĂ AUTORIZATĂ") == "PFA"
    assert detecteaza("POPESCU ȘTEFAN PERSOANĂ FIZICĂ AUTORIZATĂ") == "PFA"


# ════════════════════════════════════════════════════════
#   Cele PATRU variante măsurate ca eșecuri, acum reparate
# ════════════════════════════════════════════════════════

@pytest.mark.parametrize("denumire, asteptat", [
    ("PFA POPESCU ION", "PFA"),            # prefix — vechiul " PFA" cerea spațiu înainte
    ("POPESCU ION P.F.A.", "PFA"),         # punctuație internă — nenormalizată înainte
    ("POPESCU ION II", "II"),              # abreviere la final — " II " cerea spații ambele
    ("POPESCU ION I.I.", "II"),            # idem, cu puncte
    ("ALFA SA", "SRL_NORMAL"),             # " SA " cerea spații; "ALFA S.A." mergea, "ALFA SA" nu
])
def test_variantele_reparate(denumire, asteptat):
    assert detecteaza(denumire) == asteptat


# ════════════════════════════════════════════════════════
#   Toate cele ȘASE forme juridice
# ════════════════════════════════════════════════════════

@pytest.mark.parametrize("denumire, asteptat", [
    ("POPESCU ION PERSOANA FIZICA AUTORIZATA", "PFA"),
    ("POPESCU ION PFA", "PFA"),
    ("POPESCU ION INTREPRINDERE INDIVIDUALA", "II"),
    ("POPESCU ION II", "II"),
    ("FAMILIA POPESCU INTREPRINDERE FAMILIALA", "IF"),
    ("POPESCU IF", "IF"),
    ("I-SHTEF BUSINESS S.R.L.", "SRL_MICRO"),
    ("I-SHTEF BUSINESS SRL", "SRL_MICRO"),
    ("ALFA S.A.", "SRL_NORMAL"),
    ("CABINET MEDICAL DR POPESCU", "PROFESIE_LIBERALA"),
    ("CABINET INDIVIDUAL DE AVOCAT POPESCU", "PROFESIE_LIBERALA"),
    ("BIROU INDIVIDUAL NOTARIAL POPESCU", "PROFESIE_LIBERALA"),
])
def test_toate_cele_sase_forme(denumire, asteptat):
    assert detecteaza(denumire) == asteptat


def test_cele_sase_forme_sunt_acoperite_toate():
    """Gardian: dacă apare a șaptea formă, testul de mai sus trebuie extins."""
    from app.integrations.anaf_lookup import _FORMA_DUPA_EXPRESIE, _FORMA_DUPA_CUVANT
    forme = {f for _, f in _FORMA_DUPA_EXPRESIE} | {f for _, f in _FORMA_DUPA_CUVANT}
    assert forme == {"PFA", "II", "IF", "SRL_MICRO", "SRL_NORMAL", "PROFESIE_LIBERALA"}


# ════════════════════════════════════════════════════════
#   Eșecul onest — fără marcă de formă
# ════════════════════════════════════════════════════════

@pytest.mark.parametrize("denumire", [
    "IARAI STEFAN",             # denumire fără nicio marcă
    "ALFA BETA GAMMA",
    "",
    None,
])
def test_fara_marca_de_forma_intoarce_none(denumire):
    """None e răspunsul corect: mai bine „nu știu" decât o formă inventată.

    În bot, None declanșează întrebarea către user (onboarding: forma_lipsa).
    """
    assert detecteaza(denumire) is None


# ════════════════════════════════════════════════════════
#   Ambiguitate: cifră romană vs. formă juridică
# ════════════════════════════════════════════════════════

def test_cifra_romana_nu_bate_forma_juridica_reala():
    """„CAROL II SRL" e un SRL. Abrevierile ambigue (II/IF) se verifică ULTIMELE."""
    assert detecteaza("CAROL II SRL") == "SRL_MICRO"
    assert detecteaza("PAPA IOAN II S.A.") == "SRL_NORMAL"


def test_expresia_bate_abrevierea():
    """Expresiile complete sunt neambigue, deci au prioritate."""
    assert detecteaza("INTREPRINDERE INDIVIDUALA SA POPESCU") == "II"


# ════════════════════════════════════════════════════════
#   Drumul principal: câmpul oficial de la ANAF
# ════════════════════════════════════════════════════════

def test_campul_oficial_are_prioritate_fata_de_denumire():
    assert _map_forma_juridica("SOCIETATE CU RASPUNDERE LIMITATA", "ORICE") == "SRL_MICRO"


def test_camp_oficial_gol_cade_pe_denumire():
    """Cazul REAL pentru PFA: ANAF întoarce forma_juridica="" (măsurat 13.08.2026)."""
    assert _map_forma_juridica("", "IARAI ŞTEFAN PERSOANĂ FIZICĂ AUTORIZATĂ") == "PFA"


def test_camp_oficial_cu_diacritice_se_potriveste():
    """ANAF scrie „SOCIETATE COMERCIALĂ CU RĂSPUNDERE LIMITATĂ" (CUI 38853056)."""
    assert _map_forma_juridica(
        "SOCIETATE COMERCIALĂ CU RĂSPUNDERE LIMITATĂ", "I-SHTEF BUSINESS S.R.L."
    ) == "SRL_MICRO"


def test_nici_camp_nici_denumire_intoarce_none():
    assert _map_forma_juridica("", "IARAI STEFAN") is None


# ════════════════════════════════════════════════════════
#   Plasa din fiscal_profile: rămâne, dar face zgomot
# ════════════════════════════════════════════════════════

def test_forma_absenta_da_PFA_dar_LOGHEAZA(caplog):
    """`or "PFA"` e ultima plasă și rămâne — dar dacă se aprinde, vrem să aflăm."""
    from app.domain.fiscal_profile import from_user_dict, FormaJuridica
    with caplog.at_level("WARNING"):
        p = from_user_dict({"firma_forma_juridica": None})
    assert p.forma_juridica == FormaJuridica.PFA
    assert any("ABSENTA" in r.message for r in caplog.records), caplog.text


def test_forma_prezenta_NU_logheaza(caplog):
    from app.domain.fiscal_profile import from_user_dict, FormaJuridica
    with caplog.at_level("WARNING"):
        p = from_user_dict({"firma_forma_juridica": "SRL_MICRO"})
    assert p.forma_juridica == FormaJuridica.SRL_MICRO
    assert not any("forma juridica" in r.message.lower() for r in caplog.records)


def test_forma_invalida_logheaza_ca_inainte(caplog):
    from app.domain.fiscal_profile import from_user_dict, FormaJuridica
    with caplog.at_level("WARNING"):
        p = from_user_dict({"firma_forma_juridica": "SRL_URIAS"})
    assert p.forma_juridica == FormaJuridica.PFA
    assert any("invalida" in r.message for r in caplog.records)
