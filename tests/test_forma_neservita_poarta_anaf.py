"""
Poarta formei juridice: drumurile pe care forma se ATRIBUIE din CUI.

Retragerea SRL-ului din ofertă (butoane scoase din bot, `<select>` scurtat pe web)
ar fi fost pur cosmetică fără poarta asta. Forma juridică nu se alege în cazul
comun — se DEDUCE din CUI-ul introdus și se scrie în profil fără ca userul să fi
apăsat ceva. Cine deschidea Coniar și tasta CUI-ul firmei primea
`firma_forma_juridica=SRL_MICRO` scris tăcut, indiferent ce butoane există.

Drumurile, fiecare cu testul lui aici:
  1. lookup web            — `/api/v1/cui-lookup`
  2. reîmprospătare ANAF   — `anaf_refresh.reimprospateaza`
  3. (backstop) salvarea   — `/api/v1/onboarding/save`, pentru POST-ul direct
Drumul botului (`onboarding.handle_text` pe STEP_CUI) e acoperit în
tests/test_onboarding_forma_neservita.py, unde există deja schela de Telegram.

Contra-probele sunt la fel de importante ca probele: un PFA trebuie să treacă, și
mai ales trebuie să treacă un PFA pentru care ANAF întoarce forma GOALĂ — caz des
(ANAF lasă câmpul necompletat la persoane fizice) pe care o poartă scrisă neatent
l-ar bloca, transformând reparația într-un blocaj pentru utilizatorii reali.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain import forma_servita
from app.integrations import anaf_lookup
from app.models import User


def _web(monkeypatch, tmp_path):
    """Aceeași schelă ca tests/test_onboarding_wizard_b1.py."""
    from app.http import app as webapp
    eng = create_engine(f"sqlite:///{(tmp_path / 'fs.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=1, eligibilitate_pfa="DA")
    s.add(u); s.commit(); uid = u.id; s.close()
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    return webapp.flask_app.test_client(), S, uid


def _anaf(denumire, forma, **extra):
    baza = {
        "found": True, "cui": "12345678", "denumire": denumire,
        "forma_juridica_detectata": forma, "cod_caen": "4932",
        "regim_tva": "NEPLATITOR", "is_platitor_tva": False, "is_inactiv": False,
        "stare_inregistrare": "INREGISTRAT", "judet": "BN", "localitate": "Bistrița",
        "nr_reg_com": "F06/123/2020",
    }
    baza.update(extra)
    return baza


# ══════════════════════════════════════════════════════════════
#  Predicatul — inima regulii
# ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("forma", ["PFA", "II", "IF", "PROFESIE_LIBERALA"])
def test_formele_servite_trec(forma):
    assert forma_servita.e_servita(forma)


@pytest.mark.parametrize("forma", ["SRL_MICRO", "SRL_NORMAL"])
def test_formele_neservite_nu_trec(forma):
    assert not forma_servita.e_servita(forma)


@pytest.mark.parametrize("gol", [None, "", "   "])
def test_forma_absenta_nu_e_forma_neservita(gol):
    """ANAF lasă câmpul gol la PFA — ăsta e cazul comun, nu o respingere."""
    assert forma_servita.e_servita(gol)


def test_mesajul_spune_toate_cele_trei_lucruri():
    m = forma_servita.mesaj_forma_neservita("I-SHTEF BUSINESS SRL")
    assert "I-SHTEF BUSINESS SRL" in m                       # ce s-a întâmplat
    assert "altă bază decât la un PFA" in m                  # DE CE
    assert "cifre greșite" in m
    assert "Ai și un PFA?" in m                              # ce să facă
    assert "CUI-ul PFA-ului" in m


def test_mesajul_nu_pretinde_regimul_de_impunere():
    """Gardian pe capcana din punctul 1: forma vine dintr-o GHICITURĂ pe denumire.

    `anaf_lookup` mapează orice „SRL" la SRL_MICRO și orice „SA" la SRL_NORMAL —
    ANAF nu ne dă regimul de impunere. Un mesaj care spune „la o microîntreprindere
    impozitul se aplică pe cifra de afaceri" prezintă presupunerea noastră ca fapt,
    fix în ecranul prin care ne lăudăm că nu dăm cifre nesigure. Mesajul e UNUL
    singur și adevărat pentru ambele forme.
    """
    m = forma_servita.mesaj_forma_neservita("ORICE SRL")
    for pretentie in ("microîntreprindere", "cifra de afaceri", "1%", "3%", "16%",
                      "impozit pe profit"):
        assert pretentie not in m, (
            f"mesajul pretinde regimul de impunere ({pretentie}) pe baza unei "
            f"ghicituri din denumire"
        )


def test_mesajul_nu_se_sparge_fara_denumire():
    m = forma_servita.mesaj_forma_neservita(None)
    assert "CUI-ul ăsta e al unei firme." in m
    assert "Ai și un PFA?" in m


# ══════════════════════════════════════════════════════════════
#  Drumul 1 — lookup web
# ══════════════════════════════════════════════════════════════

def test_lookup_web_opreste_pe_srl(monkeypatch, tmp_path):
    monkeypatch.setattr(anaf_lookup, "lookup_cui",
                        lambda cui: _anaf("I-SHTEF BUSINESS SRL", "SRL_MICRO"))
    client, _, _ = _web(monkeypatch, tmp_path)
    d = client.get("/api/v1/cui-lookup?cui=12345678").get_json()
    assert d["found"] is True, "firma EXISTĂ — „found: False” ar fi o minciună"
    assert d["forma_neservita"] is True
    assert "altă bază decât la un PFA" in d["mesaj"]
    # Nimic din ce i-ar permite wizardului să continue:
    assert "regim_tva" not in d and "activity_code" not in d


def test_lookup_web_lasa_pfa_sa_treaca(monkeypatch, tmp_path):
    monkeypatch.setattr(anaf_lookup, "lookup_cui",
                        lambda cui: _anaf("POPESCU ION PFA", "PFA"))
    client, _, _ = _web(monkeypatch, tmp_path)
    d = client.get("/api/v1/cui-lookup?cui=12345678").get_json()
    assert d["found"] is True and not d.get("forma_neservita")
    assert d["forma_juridica"] == "PFA"


def test_lookup_web_lasa_sa_treaca_forma_goala(monkeypatch, tmp_path):
    """Contra-proba care contează: PFA fără formă declarată de ANAF."""
    monkeypatch.setattr(anaf_lookup, "lookup_cui",
                        lambda cui: _anaf("CEVA NEIDENTIFICABIL", None))
    client, _, _ = _web(monkeypatch, tmp_path)
    d = client.get("/api/v1/cui-lookup?cui=12345678").get_json()
    assert not d.get("forma_neservita")


# ══════════════════════════════════════════════════════════════
#  Drumul 2 — reîmprospătarea ANAF
# ══════════════════════════════════════════════════════════════

def test_reimprospatarea_nu_scrie_forma_neservita(monkeypatch, tmp_path):
    """Un profil cu forma goală n-are voie să primească SRL_MICRO pe tăcute."""
    from app.services import anaf_refresh
    eng = create_engine(f"sqlite:///{(tmp_path / 'r.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S()
    u = User(telegram_id=2, firma_cui="12345678", firma_forma_juridica=None)
    s.add(u); s.commit(); uid = u.id

    monkeypatch.setattr(anaf_lookup, "lookup_cui",
                        lambda cui: _anaf("I-SHTEF BUSINESS SRL", "SRL_MICRO"))
    rez = anaf_refresh.reimprospateaza(s, uid)
    s.commit()

    assert rez.ok
    refacut = s.query(User).filter(User.id == uid).one()
    assert refacut.firma_forma_juridica is None, "forma neservită a fost scrisă"
    # Semnalată, nu ascunsă:
    etichete = [d[0] for d in rez.diferente]
    assert "Formă juridică" in etichete
    s.close()


def test_reimprospatarea_scrie_o_forma_servita(monkeypatch, tmp_path):
    from app.services import anaf_refresh
    eng = create_engine(f"sqlite:///{(tmp_path / 'r2.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S()
    u = User(telegram_id=3, firma_cui="12345678", firma_forma_juridica=None)
    s.add(u); s.commit(); uid = u.id

    monkeypatch.setattr(anaf_lookup, "lookup_cui",
                        lambda cui: _anaf("POPESCU ION PFA", "PFA"))
    anaf_refresh.reimprospateaza(s, uid)
    s.commit()

    assert s.query(User).filter(User.id == uid).one().firma_forma_juridica == "PFA"
    s.close()


# ══════════════════════════════════════════════════════════════
#  Drumul 3 — backstop-ul de salvare (POST direct, fără UI)
# ══════════════════════════════════════════════════════════════

def test_salvarea_respinge_forma_neservita(monkeypatch, tmp_path):
    """Dropdown-ul scurtat e decor dacă endpoint-ul acceptă orice."""
    client, S, uid = _web(monkeypatch, tmp_path)
    r = client.post("/api/v1/onboarding/save",
                    json={"firma_forma_juridica": "SRL_MICRO"})
    assert r.status_code == 400
    assert r.get_json()["error"] == "forma_neservita"
    s = S()
    assert s.query(User).filter(User.id == uid).one().firma_forma_juridica is None
    s.close()


def test_salvarea_accepta_forma_servita(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path)
    r = client.post("/api/v1/onboarding/save",
                    json={"firma_forma_juridica": "PFA"})
    assert r.status_code == 200
    s = S()
    assert s.query(User).filter(User.id == uid).one().firma_forma_juridica == "PFA"
    s.close()
