"""
FIX comutator cod special TVA (art. 317) + ghid D700.

BUG REAL reparat: `has_cod_special_tva` e derivat din `regim_tva==SPECIAL_INTRACOM`,
dar niciun flux nu seta vreodata SPECIAL_INTRACOM → userul care introducea codul
ramanea NEPLATITOR → D700 il batea la cap permanent si D301 era ascuns.

Fix (users._comuta_regim_intracom, gardat, un singur loc = update_profile):
  NEPLATITOR + cod → SPECIAL_INTRACOM ; SPECIAL_INTRACOM + cod sters → NEPLATITOR ;
  PLATITOR_21 → NEATINS (garda fiscala). D301/D390 citesc STRING-ul cod_special_tva
  (ortogonal), deci nu se sparg.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.repositories import users as users_repo
from app.integrations.anaf import d700_ghid
from app.integrations.anaf import declaratii_service as decl
from app.domain import fiscal_calendar as fc


def _db(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    u = User(telegram_id=7)
    s.add(u); s.commit()
    return s, u


# ════════════════════════════════════════════════════════
# 1. NEPLATITOR + scrie cod → SPECIAL_INTRACOM (D700 stins, D301 apare)
# ════════════════════════════════════════════════════════
def test_neplatitor_scrie_cod_comuta_special(tmp_path):
    s, u = _db(tmp_path)
    users_repo.update_profile(s, u, regim_tva="NEPLATITOR")
    s.commit()

    users_repo.update_profile(s, u, cod_special_tva="53148882")  # doar codul
    s.commit()

    assert u.regim_tva == "SPECIAL_INTRACOM"          # comutat
    assert u.cod_special_tva == "53148882"            # string pastrat

    # Efectul in calendar: has_cod_special_tva=True → D700 se stinge, D301 apare.
    has_cod = (u.regim_tva == "SPECIAL_INTRACOM")     # exact conditia din plata_fiscala
    d700 = fc.DEFINITII_OBLIGATII["D700"]
    d301 = fc.DEFINITII_OBLIGATII["D301"]
    ap_d700, _ = fc._is_aplicabil(d700, "PFA", "ridesharing",
                                  has_intracom_invoice=True, has_cod_special_tva=has_cod)
    ap_d301, _ = fc._is_aplicabil(d301, "PFA", "ridesharing",
                                  has_intracom_invoice=True, has_cod_special_tva=has_cod)
    assert ap_d700 is False                            # D700 se stinge
    assert ap_d301 is True                             # D301 apare


# ════════════════════════════════════════════════════════
# 2. PLATITOR_21 + scrie cod → RAMANE PLATITOR_21 (garda fiscala)
# ════════════════════════════════════════════════════════
def test_platitor_scrie_cod_nu_retrogradeaza(tmp_path):
    s, u = _db(tmp_path)
    users_repo.update_profile(s, u, regim_tva="PLATITOR_21")
    s.commit()

    users_repo.update_profile(s, u, cod_special_tva="53148882")
    s.commit()

    assert u.regim_tva == "PLATITOR_21"               # NU retrogradat
    assert u.cod_special_tva == "53148882"            # string salvat oricum


# ════════════════════════════════════════════════════════
# 3. SPECIAL_INTRACOM + sterge cod → revine NEPLATITOR (simetrie)
# ════════════════════════════════════════════════════════
def test_special_sterge_cod_revine_neplatitor(tmp_path):
    s, u = _db(tmp_path)
    users_repo.update_profile(s, u, regim_tva="NEPLATITOR")
    users_repo.update_profile(s, u, cod_special_tva="53148882")   # → SPECIAL_INTRACOM
    s.commit()
    assert u.regim_tva == "SPECIAL_INTRACOM"

    users_repo.update_profile(s, u, cod_special_tva="")           # stergere (del_tva)
    s.commit()
    assert u.regim_tva == "NEPLATITOR"                # revenit
    assert u.cod_special_tva is None


# ════════════════════════════════════════════════════════
# 4. D301/D390 citesc cod_special_tva NESCHIMBAT dupa comutare (nu le-am spart)
# ════════════════════════════════════════════════════════
def test_d301_d390_neschimbate_de_comutare():
    # Aceleasi date, difera DOAR regim_tva (pre vs post comutare). D301/D390 citesc
    # firma.cod_special_tva (string), ortogonal de regim → XML identic.
    prof_pre = {"firma_nume": "X PFA", "cod_special_tva": "53148882",
                "regim_tva": "NEPLATITOR", "nume_declarant": "A", "prenume_declarant": "B"}
    prof_post = dict(prof_pre, regim_tva="SPECIAL_INTRACOM")
    firma_pre = decl.date_firma_din_profil(prof_pre)
    firma_post = decl.date_firma_din_profil(prof_post)
    assert firma_pre.cod_special_tva == firma_post.cod_special_tva == "53148882"
    for tip in ("D301", "D390"):
        xml_pre = decl.genereaza(tip, 2026, 7, 657, firma=firma_pre).xml
        xml_post = decl.genereaza(tip, 2026, 7, 657, firma=firma_post).xml
        assert xml_pre == xml_post                     # comutarea NU sparge D301/D390


# ════════════════════════════════════════════════════════
# 5. Ghid D700 afisat cand NEPLATITOR + fara cod; ascuns cand are cod
# ════════════════════════════════════════════════════════
def test_ghid_d700_show_hide():
    assert d700_ghid.should_show_d700_ghid("NEPLATITOR", None) is True
    assert d700_ghid.should_show_d700_ghid("NEPLATITOR", "") is True
    assert d700_ghid.should_show_d700_ghid("NEPLATITOR", "53148882") is False  # are cod
    assert d700_ghid.should_show_d700_ghid("SPECIAL_INTRACOM", None) is False   # deja facut
    assert d700_ghid.should_show_d700_ghid("PLATITOR_21", None) is False        # irelevant


def test_ghid_d700_continut():
    g = d700_ghid.genereaza_ghid_d700(plain=True)
    assert "Formularul 700" in g
    assert "1.23.1" in g
    assert "art. 317" in g
    assert "servicii" in g.lower()          # pragul 10.000 e doar pt bunuri, nu servicii


# ════════════════════════════════════════════════════════
# 6. Regresie: regim explicit (onboarding) NU e atins de comutare
# ════════════════════════════════════════════════════════
def test_onboarding_regim_explicit_neatins(tmp_path):
    s, u = _db(tmp_path)
    # onboarding scrie regim_tva EXPLICIT (fara cod_special_tva) → comutarea nu fireaza.
    users_repo.update_profile(s, u, regim_tva="NEPLATITOR")
    s.commit()
    assert u.regim_tva == "NEPLATITOR"
    users_repo.update_profile(s, u, regim_tva="PLATITOR_21")
    s.commit()
    assert u.regim_tva == "PLATITOR_21"


def test_regim_explicit_plus_cod_apelantul_decide(tmp_path):
    # Daca apelantul da SIMULTAN cod si regim_tva explicit → regimul explicit castiga
    # (comutarea e gardata pe regim_tva is None).
    s, u = _db(tmp_path)
    users_repo.update_profile(s, u, regim_tva="NEPLATITOR")
    s.commit()
    users_repo.update_profile(s, u, cod_special_tva="53148882", regim_tva="NEPLATITOR")
    s.commit()
    assert u.regim_tva == "NEPLATITOR"                # explicit → nu comutam
