"""
Wiring D212: generatorul XML (pe main din PR #134) primeste in sfarsit apelanti.

Oglindeste D207 — buton in bot + ruta web, amandoua prin `declaratii_arhiva`,
in ordinea genereaza → arhiveaza → livreaza.

Trei lucruri sunt DIFERITE la D212, si toate trei se masoara aici:
  · contribuabilul e o PERSOANA (identitate cu CNP + certificat ONRC), nu o firma;
  · pe NORMA DE VENIT nu se livreaza fisier — se livreaza cifrele si explicatia,
    fiindca norma se declara in capitolul II, cu alta structura;
  · refuzurile generatorului (data certificatului, an fara scheme) sunt mesaje
    scrise pentru user si trebuie sa ajunga la el ca atare, nu ca eroare tehnica.
"""

import inspect

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.integrations.anaf import declaratii_service as decl
from app.models import User

AN = 2025          # singurul an acoperit de pachetul de scheme vendorizat


def _profil(**kw):
    p = {
        "cnp": "1900101410011",
        "nume_declarant": "IARAI", "prenume_declarant": "ŞTEFAN",
        "firma_cui": "53067338", "firma_nume": "IARAI ŞTEFAN PFA",
        "caen_principal": "4933",
        "nr_doc_autorizare": "F2025049962009",
        "data_doc_autorizare": "2025-12-05",
        "judet": "Bistrița-Năsăud", "localitate": "Bistrița",
        "email": "x@y.ro", "telefon": "0700000000",
    }
    p.update(kw)
    return p


def _db(tmp_path, nume="d212.db"):
    eng = create_engine(f"sqlite:///{(tmp_path / nume).as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S()
    s.add(User(telegram_id=1, eligibilitate_pfa="DA"))
    s.commit()
    uid = s.query(User).one().id
    s.close()
    return S, uid


def _genereaza(profile, **kw):
    from app.services import declaratii_arhiva as arhiva
    return arhiva.genereaza_si_arhiveaza_d212(
        kw.pop("user_id", 1), AN, kw.pop("venit", 120000.0), kw.pop("chelt", 30000.0),
        identitate=decl.identitate_d212_din_profil(profile),
        activitate=decl.activitate_d212_din_profil(profile),
        **kw,
    )


# ── 1. Cifrele largite (varianta (a)) ──

def test_serviciul_intoarce_bazele_si_venitul_impozabil():
    r = decl.genereaza_d212(AN, 120000.0, 30000.0)
    assert r.cas_baza > 0 and r.cass_baza > 0
    # venit_impozabil e chiar baza impozitului: venit net − CAS − CASS
    assert round(r.venit_impozabil, 2) == round(r.venit_net - r.cas - r.cass, 2)
    assert r.xml is None and r.generat is False      # calea de estimare, neschimbata


# ── 2. XML + arhiva ──

def test_xml_si_rand_in_arhiva(tmp_path, monkeypatch):
    from app.services import declaratii_arhiva as arhiva
    from app.models import DeclaratieGenerata
    S, uid = _db(tmp_path, "arh.db")
    monkeypatch.setattr(arhiva, "get_session", lambda: S())

    rez = _genereaza(_profil(), user_id=uid)

    assert rez.generat is True
    assert rez.nume_fisier_xml == "D212_{}.xml".format(AN)
    assert "<d212" in rez.xml
    assert 'nume_c="IARAI"' in rez.xml
    assert 'nr_doc_autoriz="F2025049962009"' in rez.xml
    assert 'data_doc_autoriz="05.12.2025"' in rez.xml

    s = S()
    try:
        randuri = s.query(DeclaratieGenerata).filter_by(tip="D212").all()
        assert len(randuri) == 1
        assert randuri[0].xml and randuri[0].luna is None     # ANUALA → fara luna
        assert randuri[0].generat is True
    finally:
        s.close()


def test_ghidul_livrat_are_pasul_obligatoriu_de_cas(tmp_path, monkeypatch):
    from app.services import declaratii_arhiva as arhiva
    S, uid = _db(tmp_path, "ghid.db")
    monkeypatch.setattr(arhiva, "get_session", lambda: S())
    rez = _genereaza(_profil(), user_id=uid)
    for cheie in ("PAS OBLIGATORIU", "CAS", "Daca la CAS scrie 0"):
        assert cheie in rez.ghid_plain, "ghidul de langa XML nu contine " + repr(cheie)


# ── 3. Norma de venit: cifre + explicatie, NU refuz ──

def test_norma_primeste_cifre_si_explicatie_fara_xml(tmp_path, monkeypatch):
    from app.services import declaratii_arhiva as arhiva
    S, uid = _db(tmp_path, "norma.db")
    monkeypatch.setattr(arhiva, "get_session", lambda: S())
    rez = _genereaza(_profil(), user_id=uid, regim="NORMA_VENIT", norma_anuala=40000.0)

    assert rez.generat is False and rez.xml is None
    assert rez.total_plata > 0                        # cifrele EXISTA
    assert rez.ghid_plain                             # si ghidul
    assert rez.motiv_fara_xml == decl.MESAJ_D212_NORMA


def test_mesajul_de_norma_explica_si_ofera_alternativa():
    m = decl.MESAJ_D212_NORMA
    assert "capitolul II" in m                        # DE CE
    assert "tastează" in m and "SPV" in m             # CE FACE IN SCHIMB
    assert "cifrele" in m


# ── 4. Refuzuri citibile ──

def test_fara_data_certificatului_mesaj_citibil(tmp_path, monkeypatch):
    from app.services import declaratii_arhiva as arhiva
    S, uid = _db(tmp_path, "faradata.db")
    monkeypatch.setattr(arhiva, "get_session", lambda: S())
    with pytest.raises(ValueError) as exc:
        _genereaza(_profil(data_doc_autorizare=None), user_id=uid)
    msg = str(exc.value)
    assert "Data certificatului ONRC lipseste" in msg
    assert "profil" in msg                            # spune UNDE se completeaza


def test_anul_neacoperit_spune_ce_an_se_poate():
    with pytest.raises(ValueError) as exc:
        decl.genereaza_d212(
            2026, 1000.0, 0.0,
            identitate=decl.identitate_d212_din_profil(_profil()),
            activitate=decl.activitate_d212_din_profil(_profil()),
        )
    assert "doar pentru veniturile din {}".format(AN) in str(exc.value)


# ── 5. Arhivarea esuata NU blocheaza livrarea ──

def test_arhivarea_esuata_nu_blocheaza(monkeypatch, caplog):
    """Injectare la nivelul CORECT: cade baza, nu functia care contine protectia.

    Prima versiune a testului inlocuia `_arhiveaza` insusi — adica exact bucata
    care nu arunca niciodata — si masura propriul dublu, nu codul. Aici cade
    `get_session`, care e chiar modul cel mai probabil de esec.
    """
    import logging
    from app.services import declaratii_arhiva as arhiva

    def _db_picata():
        raise RuntimeError("DB picata")

    monkeypatch.setattr(arhiva, "get_session", _db_picata)
    with caplog.at_level(logging.ERROR):
        rez = _genereaza(_profil())

    assert rez.generat is True and rez.xml, "livrarea a fost blocata de arhiva"
    assert any(r.levelno >= logging.ERROR for r in caplog.records), (
        "esecul arhivarii trebuie sa fie ZGOMOTOS, nu doar neblocant"
    )


# ── 6. Wiring-ul propriu-zis ──

def test_ruta_web_exista_si_e_anuala():
    from app.http import app as webapp
    reguli = {str(r) for r in webapp.flask_app.url_map.iter_rules()}
    assert "/api/v1/declaratie-d212/<int:year>" in reguli
    src = inspect.getsource(webapp.genereaza_declaratie_d212)
    assert "genereaza_si_arhiveaza_d212" in src       # prin arhiva, nu direct
    assert "d212_indisponibil" in src                 # ValueError → 400 citibil


def test_butonul_din_bot_exista_si_declara_anul_incheiat():
    import bot_contabil
    src = inspect.getsource(bot_contabil)
    assert 'callback_data=f"d212|{year - 1}"' in src  # anul VENITURILOR
    h = inspect.getsource(bot_contabil.execute_declaratie_d212)
    assert "genereaza_si_arhiveaza_d212" in h
    assert "motiv_fara_xml" in h                      # norma → explicatie, nu tacere


def test_gardianul_f1_acopera_noul_call_site():
    """CONFIRMAT, nu presupus: wiring-ul trece prin arhiva, deci nu apare ca
    apelant direct; iar intrarea tax_engine si-a pierdut conditia de expirare."""
    import tests.test_arhiva_wiring as g
    directe = {f for f, _l in g._apeluri_directe_la_generator()}
    assert "app/http/app.py" not in directe
    assert "bot_contabil.py" not in directe
    permis = g._APELANTI_PERMISI["app/services/tax_engine.py"]
    assert "estimarea" in permis
    assert "se scoate cand" not in permis             # fara conditie fantoma
