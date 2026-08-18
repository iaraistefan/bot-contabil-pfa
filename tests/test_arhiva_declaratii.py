"""
F1 — arhiva declaratiilor: schema, serializare si GARDIANUL de semnatura.

Gardianul (`test_semnaturi_generatoare_cunoscute`) cade daca un generator capata un
parametru pe care arhiva nu-l cunoaste. Fara el, un parametru nou ar intra tacit in
calcul si ar lipsi din `inputuri_json` — adica arhiva ar pretinde ca e reproductibila
fara sa fie. Exact clasa de esec pentru care exista blocantul.

⚠️ VERIFICAT PRIN INJECTARE DELIBERATA: am adaugat un parametru fals in semnatura lui
`genereaza_d212`, am confirmat ca testul PICA, apoi l-am scos. Un gardian netestat la
regresie e decor (vezi §4, august 2026 — aceeasi disciplina ca la gardianul „10 zile").
"""

import inspect

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User, DeclaratieGenerata, DECL_TIPURI_ARHIVATE
from app.services import declaratii_arhiva as arh
from app.integrations.anaf import declaratii_service as decl


# ════════════════════════════════════════════════════════════
#   GARDIANUL DE SEMNATURA
# ════════════════════════════════════════════════════════════

# Parametrii pe care arhiva ii CUNOASTE si ii serializeaza, per generator.
# La adaugarea unui parametru nou intr-un generator: adauga-l aici SI asigura-te ca
# `declaratii_arhiva` chiar il pune in `inputuri_json`.
_SEMNATURI_CUNOSCUTE = {
    decl.genereaza: {
        "tip", "an", "luna", "baza_intracom_lei", "firma",
        "d_rec", "factura_nr", "factura_data", "suportat_de_bolt",
        "cota_nerezident", "d100_plan", "intracom_by_brand",
    },
    decl.genereaza_d207_anual: {
        "an", "firma", "by_brand", "profile", "d_rec",
    },
    decl.genereaza_d212: {
        "an", "venit_brut_anual", "cheltuieli_anuale", "salariu_minim",
        "regim", "norma_anuala", "pensionar", "asigurat_salariat",
        "data_inceput", "data_sfarsit",
        "are_activitate_neeligibila", "data_adaugare",
        "venit_brut_post", "cheltuieli_post",
        # Wiring-ul XML: identitatea persoanei + activitatea declarata. Optionale —
        # fara ele functia ramane exact calea de estimare de dinainte.
        "identitate", "activitate", "d_rec",
    },
}


@pytest.mark.parametrize("fn", list(_SEMNATURI_CUNOSCUTE), ids=lambda f: f.__name__)
def test_semnaturi_generatoare_cunoscute(fn):
    """
    Niciun parametru necunoscut arhivei. Daca pica: ai adaugat un input care
    INFLUENTEAZA declaratia, dar care NU ajunge in `inputuri_json` — arhiva ar
    deveni ireproductibila in tacere.
    """
    reali = set(inspect.signature(fn).parameters) - {"args", "kwargs"}
    cunoscuti = _SEMNATURI_CUNOSCUTE[fn]
    necunoscuti = reali - cunoscuti
    assert not necunoscuti, (
        f"{fn.__name__} are parametri pe care arhiva nu-i cunoaste: "
        f"{sorted(necunoscuti)}. Adauga-i in _SEMNATURI_CUNOSCUTE SI in "
        f"declaratii_arhiva, altfel nu ajung in inputuri_json."
    )
    disparuti = cunoscuti - reali
    assert not disparuti, (
        f"{fn.__name__} nu mai are parametrii: {sorted(disparuti)}. "
        "Arhiva ii serializeaza degeaba - actualizeaza lista."
    )


def test_campurile_firmei_exista_pe_dataclass():
    """Lista explicita de campuri nu are voie sa se desincronizeze de DateFirma."""
    reale = set(inspect.signature(decl.DateFirma).parameters)
    assert set(arh._CAMPURI_FIRMA) <= reale, (
        f"_CAMPURI_FIRMA are campuri inexistente: "
        f"{sorted(set(arh._CAMPURI_FIRMA) - reale)}"
    )


def test_datele_bancare_si_de_contact_nu_se_arhiveaza():
    """
    `inputuri_json` pastreaza ce a INFLUENTAT CALCULUL, nu artefactul depus (ala e
    XML-ul). Un IBAN nu schimba niciun numar, deci a doua copie nu cumpara nimic.
    Cade daca cineva le readauga „pentru completitudine".
    """
    d = arh.serializeaza_firma(decl.date_firma_stefan())
    for camp in ("cont", "telefon", "email"):
        assert camp not in d, (
            f"[{camp}] a reaparut in inputuri_json - nu influenteaza calculul."
        )


def test_d212_nu_primeste_firma():
    """
    D212 produce fisier (din PR #134), dar contribuabilul lui e o PERSOANA, nu o
    firma: primeste `identitate` (CNP, nume, prenume) si `activitate` (CAEN +
    certificat ONRC), NU `firma` ca celelalte. Distinctia e portanta — `firma`
    aici ar insemna ca cineva a copiat tiparul D390 fara sa se uite la formular.
    """
    assert "firma" not in inspect.signature(decl.genereaza_d212).parameters
    assert "firma" in inspect.signature(decl.genereaza).parameters
    assert "firma" in inspect.signature(decl.genereaza_d207_anual).parameters


# ════════════════════════════════════════════════════════════
#   SERIALIZAREA — explicita, nu dump de obiect
# ════════════════════════════════════════════════════════════

def test_serializare_firma_pe_lista_explicita():
    f = decl.date_firma_stefan()
    d = arh.serializeaza_firma(f)
    assert set(d) == set(arh._CAMPURI_FIRMA)
    assert d["cui_pfa"] == f.cui_pfa
    # Nu e dump de obiect: un camp inventat pe instanta NU trebuie sa apara.
    f.camp_inventat = "X"
    assert "camp_inventat" not in arh.serializeaza_firma(f)


def test_serializare_none_e_none():
    assert arh.serializeaza_firma(None) is None
    assert arh.serializeaza_profil(None) is None


def test_val_json_safe():
    from datetime import date as _d
    from app.domain.fiscal_profile import RegimTVA
    assert arh._val(_d(2026, 3, 15)) == "2026-03-15"
    assert arh._val(RegimTVA.NEPLATITOR) == RegimTVA.NEPLATITOR.value
    assert arh._val({"a": [1, _d(2026, 1, 1)]}) == {"a": [1, "2026-01-01"]}


# ════════════════════════════════════════════════════════════
#   SCHEMA — append-only, nullable unde trebuie
# ════════════════════════════════════════════════════════════

def _db(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S()
    u = User(telegram_id=4242, activity_code="ridesharing")
    s.add(u); s.commit(); uid = u.id; s.close()
    return S, uid


def test_anualele_au_luna_null(tmp_path):
    """D207 si D212 n-au luna — coloana trebuie sa accepte NULL."""
    S, uid = _db(tmp_path)
    s = S()
    s.add(DeclaratieGenerata(user_id=uid, tip="D212", an=2026, luna=None))
    s.commit()
    r = s.query(DeclaratieGenerata).one()
    assert r.luna is None and r.d_rec == 0 and r.generat is True
    s.close()


def test_d212_fara_xml(tmp_path):
    """D212 e calcul + ghid, fara fisier — xml ramane NULL."""
    S, uid = _db(tmp_path)
    s = S()
    s.add(DeclaratieGenerata(user_id=uid, tip="D212", an=2026,
                             rezultat_json={"cas": 1.0}, xml=None))
    s.commit()
    assert s.query(DeclaratieGenerata).one().xml is None
    s.close()


def test_esecurile_se_arhiveaza(tmp_path):
    """„Am incercat si n-a iesit" e informatie fiscala (D100 scutit / neconfigurat)."""
    S, uid = _db(tmp_path)
    s = S()
    s.add(DeclaratieGenerata(user_id=uid, tip="D100", an=2026, luna=3,
                             generat=False, motiv_negenerat="scutit"))
    s.commit()
    r = s.query(DeclaratieGenerata).one()
    assert r.generat is False and r.motiv_negenerat == "scutit"
    s.close()


def test_fara_unicitate_generari_repetate(tmp_path):
    """
    DELIBERAT fara UNIQUE: doua generari ale aceleiasi perioade sunt doua evenimente
    reale. Unicitatea ar transforma o arhiva append-only in tabel de stare.
    """
    S, uid = _db(tmp_path)
    s = S()
    for _ in range(2):
        s.add(DeclaratieGenerata(user_id=uid, tip="D390", an=2026, luna=3, d_rec=0))
    s.commit()
    assert s.query(DeclaratieGenerata).count() == 2
    s.close()


def test_rectificativa_coexista(tmp_path):
    S, uid = _db(tmp_path)
    s = S()
    s.add(DeclaratieGenerata(user_id=uid, tip="D390", an=2026, luna=3, d_rec=0))
    s.add(DeclaratieGenerata(user_id=uid, tip="D390", an=2026, luna=3, d_rec=1))
    s.commit()
    assert {r.d_rec for r in s.query(DeclaratieGenerata).all()} == {0, 1}
    s.close()


def test_d700_nu_e_tip_arhivat():
    """D700 e cerere de inregistrare prin SPV (ghid text), nu declaratie."""
    assert "D700" not in DECL_TIPURI_ARHIVATE
    assert set(DECL_TIPURI_ARHIVATE) == {"D100", "D301", "D390", "D207", "D212"}


def test_arhiva_nu_expune_update():
    """IMUTABIL: modulul nu are voie sa capete o cale de update."""
    interzise = [n for n in dir(arh)
                 if any(w in n.lower() for w in ("update", "modifica", "sterge", "delete"))]
    assert not interzise, f"Arhiva e append-only, dar expune: {interzise}"


# ════════════════════════════════════════════════════════════
#   ESECUL ARHIVARII — nu blocheaza, dar TIPA
# ════════════════════════════════════════════════════════════

def test_esec_arhivare_nu_arunca_si_logheaza(monkeypatch, caplog):
    """
    Ordinea e genereaza → arhiveaza → livreaza: un esec de arhivare NU are voie sa
    opreasca livrarea. Dar trebuie sa fie ZGOMOTOS, cu context de reconstruit.
    """
    def _boom():
        raise RuntimeError("DB indisponibil")
    monkeypatch.setattr(arh, "get_session", _boom)

    with caplog.at_level("ERROR"):
        rid = arh._arhiveaza(
            user_id=7, tip="D390", an=2026, luna=3, d_rec=0,
            inputuri={"x": 1}, rezultat={"suma_plata": 123.45},
        )

    assert rid is None                      # esec semnalat prin retur, nu prin exceptie
    txt = caplog.text
    assert "ARHIVARE DECLARATIE ESUATA" in txt
    for fragment in ("user=7", "tip=D390", "an=2026", "luna=3", "123.45"):
        assert fragment in txt, f"lipseste contextul [{fragment}] din logul de eroare"
