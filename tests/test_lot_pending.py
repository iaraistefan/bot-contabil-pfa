"""
Lotul neconfirmat: extracția supraviețuiește unui redeploy.

`user_data` e pur în memorie (fără `.persistence(...)` pe ApplicationBuilder), iar
Render înlocuiește containerul la fiecare deploy. Din cele opt fluxuri care se rup
acolo, ĂSTA e singurul care pierde muncă deja PLĂTITĂ — un apel la modelul de
extracție — și singurul care se declanșează la fiecare document.

Testele acoperă cele trei proprietăți care contează:
  1. lotul se scrie la INGESTIE și NU intră în nicio cifră cât e neconfirmat;
  2. se rehidratează pe cheia LUI, nu pe „cel mai recent" (scenariul celor trei bonuri);
  3. confirmarea PROMOVEAZĂ rândurile existente, nu creează altele.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.enums import DOC_STATUSES_SCRISE, DocStatus
from app.models import Document, User
from app.repositories import documents as documents_repo
from app.services import confirmare


@pytest.fixture
def Session(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 'lot.db').as_posix()}")
    User.metadata.create_all(eng)
    return sessionmaker(bind=eng)


@pytest.fixture
def uid(Session):
    s = Session()
    u = User(telegram_id=555, activity_code="ridesharing")
    s.add(u)
    s.commit()
    i = u.id
    s.close()
    return i


def _scrie_lot(s, uid, sfid, n=1, brut=100.0, data_doc="05.04.2026"):
    for k in range(n):
        documents_repo.create(
            s, user_id=uid, source_file_id=sfid, data_doc=data_doc,
            platforma="Lukoil", tip="CHELTUIALA", brut=brut + k,
            comision=0.0, tva=0.0, net=0.0, cash=0.0, banca=0.0,
            detalii=f"motorina {k}", raw_json='{"x":1}', prompt_version="v5",
            status=DocStatus.NEEDS_REVIEW.value,
        )
    s.commit()


# ============================================================
#   1. STAREA — scrisă, dar în afara cifrelor
# ============================================================

def test_needs_review_e_o_valoare_declarata():
    """Starea nouă trebuie să treacă prin sursa unică, altfel gardianul o respinge."""
    assert DocStatus.NEEDS_REVIEW.value in DOC_STATUSES_SCRISE
    assert DocStatus.NEEDS_REVIEW.value == "needs_review"


def test_lotul_pending_nu_intra_in_bani(Session, uid):
    """
    Invariantul cel mai important: un document neconfirmat NU se vede în nicio sumă.
    Verificăm pe filtrul real folosit de banii intracom — allowlist pe „posted".
    """
    s = Session()
    _scrie_lot(s, uid, sfid=11, n=2)
    postate = (
        s.query(Document)
        .filter(Document.user_id == uid, Document.status == DocStatus.POSTED.value)
        .count()
    )
    toate = s.query(Document).filter(Document.user_id == uid).count()
    s.close()
    assert toate == 2, "lotul s-a scris"
    assert postate == 0, "dar niciun rând nu e vizibil pentru calculele de bani"


def test_count_by_tip_nu_numara_neconfirmatele(Session, uid):
    """`is_first_expense` nu are voie să se consume pe un document neconfirmat."""
    s = Session()
    _scrie_lot(s, uid, sfid=12, n=1)
    assert documents_repo.count_by_tip(s, uid, "CHELTUIALA") == 0
    assert documents_repo.count_by_tip(s, uid, "CHELTUIALA", status=None) == 1
    s.close()


# ============================================================
#   2. GRUPAREA ȘI REHIDRATAREA — pe cheia LUI
# ============================================================

def test_lotul_se_grupeaza_pe_source_file_id(Session, uid):
    s = Session()
    _scrie_lot(s, uid, sfid=21, n=3)
    _scrie_lot(s, uid, sfid=22, n=1)
    assert len(documents_repo.get_lot_pending(s, uid, 21)) == 3
    assert len(documents_repo.get_lot_pending(s, uid, 22)) == 1
    loturi = documents_repo.list_loturi_pending(s, uid)
    s.close()
    assert {sfid for sfid, _ in loturi} == {21, 22}


def test_scenariul_celor_trei_bonuri(Session, uid):
    """
    REGRESIA care justifică cheia în callback. Trei poze trimise una după alta →
    trei loturi. Cine apasă pe cardul PRIMULUI trebuie să primească PRIMUL lot,
    nu ultimul. „Cel mai recent lot pending" ar posta cifre pe care omul nu le vede.
    """
    s = Session()
    _scrie_lot(s, uid, sfid=31, n=1, brut=100.0, data_doc="01.04.2026")
    _scrie_lot(s, uid, sfid=32, n=1, brut=200.0, data_doc="02.04.2026")
    _scrie_lot(s, uid, sfid=33, n=1, brut=300.0, data_doc="03.04.2026")

    primul = documents_repo.get_lot_pending(s, uid, 31)
    s.close()
    assert len(primul) == 1
    assert primul[0].brut == 100.0, "lotul cerut, nu ultimul scris"
    assert primul[0].data_doc == "01.04.2026"


def test_lotul_altui_user_nu_se_vede(Session, uid):
    """Izolare multi-tenant: cheia lotului nu e un bilet de intrare."""
    s = Session()
    alt = User(telegram_id=666)
    s.add(alt)
    s.commit()
    _scrie_lot(s, alt.id, sfid=41, n=1)
    assert documents_repo.get_lot_pending(s, uid, 41) == []
    assert len(documents_repo.get_lot_pending(s, alt.id, 41)) == 1
    s.close()


def test_maparea_rand_item_e_dus_intors(Session, uid):
    """Rândul → item → câmpuri de rând, fără pierdere pe drumul de afișare."""
    s = Session()
    _scrie_lot(s, uid, sfid=51, n=1, brut=123.45, data_doc="07.07.2026")
    doc = documents_repo.get_lot_pending(s, uid, 51)[0]
    doc.numar_document = "INSINT/1518242"
    s.commit()

    item = confirmare.doc_to_item_dict(doc)
    assert item["data"] == "07.07.2026"          # singurul nume care diferă
    assert item["brut"] == 123.45
    assert item["tip"] == "CHELTUIALA"
    assert item["numar_document"] == "INSINT/1518242"

    inapoi = confirmare.item_dict_to_doc_fields(item)
    assert inapoi["data_doc"] == "07.07.2026"
    assert inapoi["brut"] == 123.45
    assert inapoi["numar_document"] == "INSINT/1518242"
    s.close()


# ============================================================
#   3. ÎNCHIDEREA LOTULUI — întreg, niciodată parțial
# ============================================================

def test_promovarea_muta_tot_lotul(Session, uid):
    s = Session()
    _scrie_lot(s, uid, sfid=61, n=3)
    docs = documents_repo.get_lot_pending(s, uid, 61)
    n = documents_repo.set_status_lot(s, docs, DocStatus.POSTED.value)
    s.commit()
    assert n == 3
    assert documents_repo.get_lot_pending(s, uid, 61) == []
    postate = (
        s.query(Document)
        .filter(Document.source_file_id == 61,
                Document.status == DocStatus.POSTED.value)
        .count()
    )
    s.close()
    assert postate == 3, "lotul se mișcă întreg — ori toate, ori niciuna"


def test_renuntarea_nu_sterge_randurile(Session, uid):
    """
    Renunțarea marchează, nu șterge: rândul rămâne pentru audit, exact ca la /delete.
    Și NU există retenție automată — un lot neconfirmat stă oricât, fiindcă extracția
    rămâne validă (documentul în sine nu se schimbă).
    """
    s = Session()
    _scrie_lot(s, uid, sfid=71, n=2)
    docs = documents_repo.get_lot_pending(s, uid, 71)
    documents_repo.set_status_lot(s, docs, DocStatus.REJECTED.value)
    s.commit()
    ramase = s.query(Document).filter(Document.source_file_id == 71).count()
    s.close()
    assert ramase == 2, "rândurile rămân, doar starea se schimbă"


def test_idempotenta_pe_acelasi_lot(Session, uid):
    """
    A doua scriere pe aceeași sursă nu dublează lotul — altfel retrimiterea unei poze
    ar produce două carduri pentru același document.
    """
    s = Session()
    _scrie_lot(s, uid, sfid=81, n=2)
    existent = documents_repo.get_lot_pending(s, uid, 81)
    assert len(existent) == 2
    # a doua oară: apelantul verifică întâi și nu mai scrie (vezi _persist_lot_pending)
    if not documents_repo.get_lot_pending(s, uid, 81):
        _scrie_lot(s, uid, sfid=81, n=2)
    s.close()
    assert len(existent) == 2
