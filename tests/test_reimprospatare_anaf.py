"""
Reimprospatarea datelor de la ANAF + starea „de ce lipseste numarul ONRC".

Bug-ul de productie pe care il inchid testele astea: userul 1 avea
`nr_doc_autorizare` NULL desi lookup-ul ANAF ii scrisese numele in ACEEASI rulare.
Cauza s-a pierdut intr-un logger.warning, campul a ramas gol fara explicatie, si
D212 a refuzat sa se genereze — pentru un user care PLATISE planul care il include.
Nicio suprafata din produs nu putea repara asta: `/coduri_fiscale` avea buton doar
pentru DATA certificatului, fiindca numarul „se ia automat din ANAF".

Cele patru axe, in ordinea in care musca:
  1. captarea nu mai tace   (nr_doc_din_anaf intoarce motivul, nu-l inghite)
  2. motivul se PERSISTA    (si se sterge cand numarul apare — invariant)
  3. reimprospatarea umple golurile, dar NU rescrie ce e completat
  4. refuzul D212 spune UNDE se completeaza
"""

import pytest

from app.domain import doc_autorizare as da
from app.services import anaf_refresh


@pytest.fixture
def session(tmp_path):
    """DB proprie pe disc, per test — nimic partajat, nimic de curatat dupa."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models import User
    eng = create_engine(f"sqlite:///{(tmp_path / 'reimprosp.db').as_posix()}")
    User.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


@pytest.fixture
def user(session):
    from app.models import User
    u = User(telegram_id=4242, activity_code="ridesharing")
    session.add(u)
    session.commit()
    return u


# ════════════════════════════════════════════════════════════
#   1. CAPTAREA — esecul e o valoare, nu un eveniment pierdut
# ════════════════════════════════════════════════════════════

def test_nr_doc_din_anaf_numar_bun():
    assert da.nr_doc_din_anaf("J2018000137062") == ("J2018000137062", None)


def test_nr_doc_din_anaf_normalizeaza_spatii_si_minuscule():
    assert da.nr_doc_din_anaf(" f06/123456/2018 ") == ("F06/123456/2018", None)


@pytest.mark.parametrize("gol", [None, "", "   "])
def test_nr_doc_din_anaf_gol_da_motivul_ANAF_GOL(gol):
    """Cazul REAL al userului 1: ANAF nu intoarce numarul."""
    nr, motiv = da.nr_doc_din_anaf(gol)
    assert nr is None
    assert motiv == da.MOTIV_NR_ANAF_GOL


def test_nr_doc_din_anaf_prea_lung_nu_arunca_si_nu_trunchiaza():
    """Peste C15Type: motiv, NU exceptie si NU un numar taiat (= numar fals)."""
    nr, motiv = da.nr_doc_din_anaf("J2018000137062XYZABC")
    assert nr is None
    assert motiv == da.MOTIV_NR_PREA_LUNG


def test_fiecare_motiv_are_text_pentru_om():
    """Un cod fara traducere ar ajunge pe ecran ca 'ANAF_GOL'."""
    for motiv in (da.MOTIV_NR_ANAF_GOL, da.MOTIV_NR_PREA_LUNG):
        txt = da.motiv_nr_doc_text(motiv)
        assert txt and len(txt) > 30
        assert motiv not in txt          # cod tradus, nu cod afisat


def test_motiv_necunoscut_sau_absent_nu_inventeaza_text():
    assert da.motiv_nr_doc_text(None) is None
    assert da.motiv_nr_doc_text("") is None
    assert da.motiv_nr_doc_text("CEVA_NOU") is None


def test_motivele_incap_in_coloana():
    """VARCHAR(30) din migrarea 031 — codurile nu au voie sa creasca peste ea."""
    for motiv in (da.MOTIV_NR_ANAF_GOL, da.MOTIV_NR_PREA_LUNG):
        assert len(motiv) <= da.MAX_LEN_MOTIV_NR_DOC


# ════════════════════════════════════════════════════════════
#   2. PERSISTENTA motivului + invariantul „numar ⇒ fara motiv"
# ════════════════════════════════════════════════════════════

def test_motivul_se_scrie_pe_profil(session, user):
    from app.repositories import users as users_repo
    users_repo.update_profile(
        session, user, nr_doc_autorizare_motiv=da.MOTIV_NR_ANAF_GOL)
    session.commit()
    prof = users_repo.get_profile_dict(session, user.id)
    assert prof["nr_doc_autorizare_motiv"] == da.MOTIV_NR_ANAF_GOL


def test_completarea_numarului_STERGE_motivul(session, user):
    """Motivul explica o LIPSA. Cand lipsa dispare, explicatia trebuie sa dispara.

    Altfel Setarile ar arata la nesfarsit „ANAF n-a avut numarul" chiar langa
    numarul pe care userul tocmai l-a tastat.
    """
    from app.repositories import users as users_repo
    users_repo.update_profile(
        session, user, nr_doc_autorizare_motiv=da.MOTIV_NR_ANAF_GOL)
    session.commit()

    users_repo.update_profile(session, user, nr_doc_autorizare="J2018000137062")
    session.commit()

    prof = users_repo.get_profile_dict(session, user.id)
    assert prof["nr_doc_autorizare"] == "J2018000137062"
    assert prof["nr_doc_autorizare_motiv"] is None


def test_invariantul_tine_si_cand_apelantul_da_ambele(session, user):
    """Numar SI motiv in aceeasi scriere → numarul castiga, motivul se sterge.

    Pazeste ORDINEA din update_profile: daca motivul s-ar aplica dupa numar, ar
    ramane in baza o explicatie pentru o lipsa inexistenta.
    """
    from app.repositories import users as users_repo
    users_repo.update_profile(
        session, user,
        nr_doc_autorizare="J2018000137062",
        nr_doc_autorizare_motiv=da.MOTIV_NR_ANAF_GOL,
    )
    session.commit()
    prof = users_repo.get_profile_dict(session, user.id)
    assert prof["nr_doc_autorizare"] == "J2018000137062"
    assert prof["nr_doc_autorizare_motiv"] is None


# ════════════════════════════════════════════════════════════
#   3. REIMPROSPATAREA — umple golurile, nu rescrie deciziile
# ════════════════════════════════════════════════════════════

RASPUNS_ANAF = {
    "found": True,
    "cui": "53067338",
    "denumire": "IARAI STEFAN PERSOANA FIZICA AUTORIZATA",
    "forma_juridica_detectata": "PFA",
    "cod_caen": "4932",
    "regim_tva": "NEPLATITOR",
    "judet": "CLUJ",
    "localitate": "Cluj-Napoca",
    "nume_declarant": "IARAI",
    "prenume_declarant": "STEFAN",
    "nr_reg_com": "J2018000137062",
}


@pytest.fixture
def anaf(monkeypatch):
    """Inlocuieste apelul de retea. Testele nu ating ANAF."""
    def _set(raspuns):
        monkeypatch.setattr(anaf_refresh.anaf_lookup, "lookup_cui",
                            lambda cui: dict(raspuns))
    return _set


def test_reimprospatarea_completeaza_numarul_lipsa(session, user, anaf):
    """Cazul userului 1, reparat: contul are CUI, numarul e gol, ANAF il are."""
    from app.repositories import users as users_repo
    users_repo.update_profile(session, user, firma_cui="53067338")
    session.commit()
    anaf(RASPUNS_ANAF)

    rez = anaf_refresh.reimprospateaza(session, user.id)
    session.commit()

    assert rez.ok
    assert rez.nr_completat == "J2018000137062"
    prof = users_repo.get_profile_dict(session, user.id)
    assert prof["nr_doc_autorizare"] == "J2018000137062"


def test_reimprospatarea_NU_rescrie_un_camp_completat(session, user, anaf):
    """Regula centrala. Judetul e completat si difera → se RAPORTEAZA, nu se scrie."""
    from app.repositories import users as users_repo
    users_repo.update_profile(
        session, user, firma_cui="53067338", judet="BUCURESTI")
    session.commit()
    anaf(RASPUNS_ANAF)

    rez = anaf_refresh.reimprospateaza(session, user.id)
    session.commit()

    prof = users_repo.get_profile_dict(session, user.id)
    assert prof["judet"] == "BUCURESTI"                  # NEATINS
    etichete = [d[0] for d in rez.diferente]
    assert "Județ" in etichete
    dif = next(d for d in rez.diferente if d[0] == "Județ")
    assert dif[1] == "BUCURESTI" and dif[2] == "CLUJ"


def test_reimprospatarea_NU_atinge_niciodata_data_certificatului(session, user, anaf):
    """ANAF n-o stie — o completare „din ANAF" ar fi o ipoteza prezentata ca fapt."""
    from app.repositories import users as users_repo
    users_repo.update_profile(session, user, firma_cui="53067338")
    session.commit()
    anaf({**RASPUNS_ANAF, "data_inregistrare": "2018-05-10"})

    anaf_refresh.reimprospateaza(session, user.id)
    session.commit()

    prof = users_repo.get_profile_dict(session, user.id)
    assert prof["data_doc_autorizare"] is None


def test_data_certificatului_nu_e_in_lista_de_campuri():
    """Gardian pe HARTA, nu doar pe comportament: daca cineva o adauga, cade aici."""
    chei = [c for c, _, _ in anaf_refresh.CAMPURI]
    assert "data_doc_autorizare" not in chei
    # Nici alegerile userului nu se sincronizeaza dintr-un registru.
    assert "activity_code" not in chei
    assert "regim_impunere" not in chei
    assert "cnp" not in chei


def test_numarul_completat_nu_se_clatina(session, user, anaf):
    """Userul poate sa-l fi tastat de pe certificat tocmai fiindca ANAF il da altfel."""
    from app.repositories import users as users_repo
    users_repo.update_profile(
        session, user, firma_cui="53067338", nr_doc_autorizare="F06/123456/2018")
    session.commit()
    anaf(RASPUNS_ANAF)

    rez = anaf_refresh.reimprospateaza(session, user.id)
    session.commit()

    prof = users_repo.get_profile_dict(session, user.id)
    assert prof["nr_doc_autorizare"] == "F06/123456/2018"
    assert rez.nr_completat is None


def test_reimprospatarea_persista_motivul_cand_ANAF_da_gol(session, user, anaf):
    """A doua incercare esueaza tot — dar de data asta profilul stie DE CE."""
    from app.repositories import users as users_repo
    users_repo.update_profile(session, user, firma_cui="53067338")
    session.commit()
    anaf({**RASPUNS_ANAF, "nr_reg_com": ""})

    rez = anaf_refresh.reimprospateaza(session, user.id)
    session.commit()

    assert rez.nr_motiv == da.MOTIV_NR_ANAF_GOL
    prof = users_repo.get_profile_dict(session, user.id)
    assert prof["nr_doc_autorizare"] is None
    assert prof["nr_doc_autorizare_motiv"] == da.MOTIV_NR_ANAF_GOL


def test_fara_cui_nu_crapa_si_spune_ce_lipseste(session, user):
    rez = anaf_refresh.reimprospateaza(session, user.id)
    assert rez.ok is False
    assert "CUI" in rez.eroare


def test_anaf_cazut_nu_crapa_si_nu_atinge_datele(session, user, monkeypatch):
    """O actiune de REPARARE care crapa in fata celui care repara e mai rea decat lipsa ei."""
    from app.repositories import users as users_repo
    users_repo.update_profile(
        session, user, firma_cui="53067338", judet="CLUJ")
    session.commit()

    def explodeaza(cui):
        raise RuntimeError("retea cazuta")
    monkeypatch.setattr(anaf_refresh.anaf_lookup, "lookup_cui", explodeaza)

    rez = anaf_refresh.reimprospateaza(session, user.id)
    assert rez.ok is False
    assert rez.eroare
    assert users_repo.get_profile_dict(session, user.id)["judet"] == "CLUJ"


def test_anaf_nu_gaseste_cui_ul(session, user, anaf):
    from app.repositories import users as users_repo
    users_repo.update_profile(session, user, firma_cui="99999999")
    session.commit()
    anaf({"found": False, "error": "CUI 99999999 nu există în registrul ANAF"})

    rez = anaf_refresh.reimprospateaza(session, user.id)
    assert rez.ok is False
    assert "99999999" in rez.eroare


# ── textul rezultatului ─────────────────────────────────────

def test_textul_spune_ce_a_completat(session, user, anaf):
    from app.repositories import users as users_repo
    users_repo.update_profile(session, user, firma_cui="53067338")
    session.commit()
    anaf(RASPUNS_ANAF)
    rez = anaf_refresh.reimprospateaza(session, user.id)
    session.commit()

    txt = anaf_refresh.text_rezultat(rez)
    assert "Am completat din ANAF" in txt
    assert "J2018000137062" in txt


def test_textul_spune_ca_NU_a_schimbat_diferentele(session, user, anaf):
    """Userul trebuie sa afle ca diferenta e semnalata, nu aplicata."""
    from app.repositories import users as users_repo
    users_repo.update_profile(session, user, firma_cui="53067338", judet="BUCURESTI")
    session.commit()
    anaf(RASPUNS_ANAF)
    rez = anaf_refresh.reimprospateaza(session, user.id)
    session.commit()

    txt = anaf_refresh.text_rezultat(rez)
    assert "N-am schimbat nimic" in txt
    assert "BUCURESTI" in txt and "CLUJ" in txt


def test_textul_explica_motivul_cand_numarul_ramane_gol(session, user, anaf):
    from app.repositories import users as users_repo
    users_repo.update_profile(session, user, firma_cui="53067338")
    session.commit()
    anaf({**RASPUNS_ANAF, "nr_reg_com": ""})
    rez = anaf_refresh.reimprospateaza(session, user.id)
    session.commit()

    txt = anaf_refresh.text_rezultat(rez)
    assert da.motiv_nr_doc_text(da.MOTIV_NR_ANAF_GOL) in txt


def test_textul_nu_minte_cand_nu_e_nimic_de_facut(session, user, anaf):
    from app.repositories import users as users_repo
    users_repo.update_profile(
        session, user, firma_cui="53067338",
        firma_nume=RASPUNS_ANAF["denumire"],
        firma_forma_juridica="PFA", caen_principal="4932",
        regim_tva="NEPLATITOR", judet="CLUJ", localitate="Cluj-Napoca",
        nume_declarant="IARAI", prenume_declarant="STEFAN",
        nr_doc_autorizare="J2018000137062",
    )
    session.commit()
    anaf(RASPUNS_ANAF)
    rez = anaf_refresh.reimprospateaza(session, user.id)

    txt = anaf_refresh.text_rezultat(rez)
    assert "totul e la zi" in txt


def test_textul_fara_markdown_nu_poarta_stele():
    """Dashboardul scrie text simplu — steluțele ar ajunge pe ecran ca atare."""
    rez = anaf_refresh.RezultatReimprospatare(
        ok=True, completate=[("Județ", "CLUJ")])
    assert "*" not in anaf_refresh.text_rezultat(rez, markdown=False)
    assert "*" in anaf_refresh.text_rezultat(rez, markdown=True)


# ════════════════════════════════════════════════════════════
#   4. REFUZUL D212 — numeste lipsa SI da drumul
# ════════════════════════════════════════════════════════════

def _activitate(nr=""):
    from app.integrations.anaf.d212_generator import ActivitateD212
    from datetime import date
    return ActivitateD212(
        caen="4932", den_caen="Transporturi cu taxiuri",
        nr_doc_autorizare=nr, data_doc_autorizare=date(2018, 5, 10),
    )


def _identitate():
    from app.integrations.anaf.d212_generator import IdentitateD212
    return IdentitateD212(
        cnp="1900101223344", nume="IARAI", prenume="STEFAN",
        sediu="Cluj-Napoca", email="", telefon="", iban="")


class _Rezultat:
    regim = "SISTEM_REAL"
    venit_brut = 100000.0
    cheltuieli = 20000.0
    venit_net = 80000.0
    cas = 0.0
    cass = 0.0
    impozit = 0.0
    cas_baza = 0.0
    cass_baza = 0.0
    venit_impozabil = 80000.0
    total_plata = 0.0
    an = 2025
    avertismente = []


def test_refuzul_pentru_numar_spune_UNDE_se_completeaza():
    """Un refuz care numeste lipsa fara sa dea drumul e o fundatura.

    Exact ce a patit userul de productie: mesajul spunea „Nu inventam un numar"
    si atat, iar el nu avea de unde sa stie ca exista un ecran unde se pune.
    """
    from app.integrations.anaf import d212_generator as gen
    with pytest.raises(ValueError) as exc:
        gen.genereaza_d212(2025, _identitate(), _activitate(nr=""), _Rezultat())
    mesaj = str(exc.value)
    assert "BR-D212-0095" in mesaj                 # temeiul legal ramane
    assert "profil" in mesaj.lower()               # ...si acum are si o iesire
    assert "eimprospateaz" in mesaj                # a doua cale, cea automata


def test_refuzul_pentru_data_a_ramas_neatins():
    """Perechea lui trimitea de mult in profil — nu strica ce era bun."""
    from app.integrations.anaf import d212_generator as gen
    act = _activitate(nr="J2018000137062")
    act.data_doc_autorizare = None
    with pytest.raises(ValueError) as exc:
        gen.genereaza_d212(2025, _identitate(), act, _Rezultat())
    assert "BR-D212-0096" in str(exc.value)
    assert "profil" in str(exc.value).lower()


# ════════════════════════════════════════════════════════════
#   GARDIAN: promisiunea are DESTINATIE (perechea celui din
#   test_certificat_editabil.py, care acoperea doar DATA)
# ════════════════════════════════════════════════════════════
#
# Gardianul de dinainte lega fraza „o completezi in profil" de existenta unui
# camp — dar numai pentru DATA. Numarul n-avea promisiune, deci n-avea nici
# gardian, deci nimeni n-a observat ca n-are nici camp. Trei ani de asumptie
# („se ia automat din ANAF") si un user blocat. Aici se inchide si a doua axa.

import inspect
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def test_promisiunea_pentru_NUMAR_are_destinatie_pe_ambele_suprafete():
    """Daca refuzul spune «il completezi in profil», profilul trebuie sa-l accepte."""
    src_bot = (_ROOT / "bot_contabil.py").read_text(encoding="utf-8")
    assert "coduri|set_certnr" in src_bot, (
        "Refuzul D212 trimite userul in profil pentru NUMAR, dar botul n-are "
        "butonul (coduri|set_certnr). Exact starea care a blocat userul 1."
    )
    assert '"certnr"' in src_bot, (
        "Butonul exista dar n-are ramura de wizard care sa primeasca textul."
    )

    from app.http import app as webapp
    html = (_ROOT / "app" / "http" / "templates" / "dashboard.html").read_text(
        encoding="utf-8")
    assert 'id="set-cert-nr"' in html, (
        "Setarile web n-au camp pentru numarul certificatului."
    )
    assert "nr_doc_autorizare" in inspect.getsource(webapp.setari_post), (
        "Campul exista in HTML dar serverul nu-l accepta la salvare."
    )


def test_reimprospatarea_promisa_in_refuz_exista_pe_ambele_suprafete():
    """A doua iesire promisa de mesaj („apesi Reimprospateaza") trebuie sa existe."""
    from app.integrations.anaf import d212_generator as gen
    mesaj = inspect.getsource(gen.genereaza_d212)
    assert "eimprospateaz" in mesaj, (
        "Refuzul nu mai promite reimprospatarea. Daca ai reformulat intentionat, "
        "muta gardianul pe formularea noua — nu-l sterge."
    )

    src_bot = (_ROOT / "bot_contabil.py").read_text(encoding="utf-8")
    assert "coduri|anaf_refresh" in src_bot, "Botul n-are butonul de reimprospatare."

    from app.http import app as webapp
    assert any(
        r.rule == "/api/v1/anaf/reimprospateaza"
        for r in webapp.flask_app.url_map.iter_rules()
    ), "Web-ul n-are ruta de reimprospatare."
