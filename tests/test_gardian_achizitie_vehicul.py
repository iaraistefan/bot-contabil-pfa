"""
Gardian achiziție vehicul — o factură de cumpărare de mașină nu mai cade pe
fallback-ul `other_expense` (100% deductibil), unde 48.500 lei se scădeau
integral din venitul lunii.

MECANISM: suma e declanșator de ÎNTREBARE, niciodată clasificator de DECIZIE.
Peste prag botul nu ghicește — întreabă, și omul decide prin buton. Gardianul
cade ÎNCHIS: costul maxim al unui declanșator fals e o întrebare în plus, pe
când un gardian automat (pe VIN) ar cădea DESCHIS exact pe gaura păzită.

SENS vs ARITMETICĂ: categoria e NON_DEDUCTIBLE fiindcă 0 e răspunsul corect la
„ce procent intră luna asta". Că mașina se deduce totuși, în ani, prin
amortizare — asta o poartă CATEGORIA (`vehicle_acquisition`), care se persistă.
"""

import pytest
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User, Document, Transaction
from app.services import posting, tax_engine, confirmare
from app.activities.registry import get_activity
from app.ai.schemas import ExtractionItem
from app.domain.capex import (
    CAT_ACHIZITIE_VEHICUL,
    PRAG_INTREBARE_ACHIZITIE,
    necesita_intrebare_achizitie,
    este_achizitie,
)
from app.integrations.exports.registru import _resolve_category_label

Y, M = 2026, 8


# ════════════════════════════════════════════════════════════
#   Fixture-uri
# ════════════════════════════════════════════════════════════

def _setup(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    monkeypatch.setattr(posting.audit_repo, "write", lambda *a, **k: None)
    s = Session()
    u = User(telegram_id=777, activity_code="ridesharing")
    s.add(u)
    s.commit()
    uid = u.id
    s.close()
    return Session, uid


def _doc(Session, uid):
    s = Session()
    d = Document(user_id=uid, tip="CHELTUIALA", status="posted",
                 data_doc="07.08.2026")
    s.add(d)
    s.commit()
    did = d.id
    s.close()
    return did


def _post(Session, uid, did, **kw):
    s = Session()
    tx_ids = posting.post_document(s, user_id=uid, document_id=did, **kw)
    s.commit()
    s.close()
    return tx_ids


def _masina(Session, uid, brut=48500.0):
    """Postează o achiziție de autoturism, așa cum o scrie butonul userului."""
    did = _doc(Session, uid)
    return _post(
        Session, uid, did, tip="CHELTUIALA",
        platforma="Autoklass", detalii="Dacia Logan", brut=brut, comision=0.0,
        tva=0.0, net=brut, cash=0.0, banca=0.0, data_doc="07.08.2026",
        category_override=CAT_ACHIZITIE_VEHICUL,
    )


def _service(Session, uid, brut=8000.0):
    """Factură de service — fluxul normal, fără override."""
    did = _doc(Session, uid)
    return _post(
        Session, uid, did, tip="CHELTUIALA",
        platforma="Service Auto SRL", detalii="reparatii auto", brut=brut,
        comision=0.0, tva=0.0, net=brut, cash=0.0, banca=0.0,
        data_doc="07.08.2026",
    )


def _totals(Session, uid):
    s = Session()
    t = tax_engine.compute_period(s, user_id=uid, year=Y, month=M)
    s.close()
    return t


# ════════════════════════════════════════════════════════════
#   MIEZUL — suma nu intră în totalurile lunii
# ════════════════════════════════════════════════════════════

def test_achizitia_nu_intra_in_totalul_deductibil(tmp_path, monkeypatch):
    """MIEZUL: 48.500 lei nu se scad din venitul lunii."""
    Session, uid = _setup(tmp_path, monkeypatch)
    _masina(Session, uid)
    _service(Session, uid, brut=1000.0)

    t = _totals(Session, uid)
    # Doar service-ul, la 50% (auto mixt) — nimic din mașină.
    assert t["expense_deductible_total"] == 500.0


def test_achizitia_nu_intra_in_expense_total_brut(tmp_path, monkeypatch):
    """`expense_total_brut` = brutul cheltuielilor LUNII, fără achiziții."""
    Session, uid = _setup(tmp_path, monkeypatch)
    _masina(Session, uid)
    _service(Session, uid, brut=1000.0)

    t = _totals(Session, uid)
    assert t["expense_total_brut"] == 1000.0


def test_achizitia_nu_scade_profitul(tmp_path, monkeypatch):
    """Profitul estimat merge pe deductibil → mașina nu-l atinge."""
    Session, uid = _setup(tmp_path, monkeypatch)
    did_venit = _doc(Session, uid)
    s = Session()
    s.add(Transaction(
        user_id=uid, document_id=did_venit, tx_type="INCOME", category="ride_revenue",
        amount_brut=10000.0, amount_vat=0.0, amount_net=10000.0, currency="RON",
        payment_method="CARD", counterparty="Bolt",
        period_year=Y, period_month=M, locked=False,
    ))
    s.commit()
    s.close()
    _masina(Session, uid)

    t = _totals(Session, uid)
    assert t["profit_estimated"] == 10000.0


# ════════════════════════════════════════════════════════════
#   PROEMINENȚA — nu concurează pe sortare cu cheltuielile lunii
# ════════════════════════════════════════════════════════════

def test_achizitia_nu_e_cea_mai_mare_cheltuiala(tmp_path, monkeypatch):
    """
    Rândul e adevărat, contextul îl făcea să mintă: sortarea descrescătoare
    punea mașina prima, ca „cea mai mare cheltuială a lunii".
    """
    Session, uid = _setup(tmp_path, monkeypatch)
    _masina(Session, uid)
    _service(Session, uid, brut=1000.0)

    t = _totals(Session, uid)
    coduri = [x["code"] for x in t["expense_breakdown"]]
    assert CAT_ACHIZITIE_VEHICUL not in coduri
    assert coduri[0] == "car_service"   # prima cheltuială e cea reală a lunii


def test_achizitia_apare_in_lista_ei(tmp_path, monkeypatch):
    """Separată, dar vizibilă — nu ascunsă."""
    Session, uid = _setup(tmp_path, monkeypatch)
    _masina(Session, uid)

    t = _totals(Session, uid)
    assert t["capex_total"] == 48500.0
    assert len(t["capex_breakdown"]) == 1
    rand = t["capex_breakdown"][0]
    assert rand["code"] == CAT_ACHIZITIE_VEHICUL
    assert rand["amount_brut"] == 48500.0
    assert rand["label"] == "Cumpărare mașină"
    assert "amortizează" in rand["note"]


def test_fara_achizitii_listele_sunt_goale(tmp_path, monkeypatch):
    """Regresie: o lună obișnuită nu capătă nimic nou."""
    Session, uid = _setup(tmp_path, monkeypatch)
    _service(Session, uid, brut=1000.0)

    t = _totals(Session, uid)
    assert t["capex_total"] == 0
    assert t["capex_breakdown"] == []
    assert t["expense_total_brut"] == 1000.0
    assert t["expense_deductible_total"] == 500.0


# ════════════════════════════════════════════════════════════
#   ARHIVA — documentul rămâne și e regăsibil
# ════════════════════════════════════════════════════════════

def test_documentul_ramane_in_arhiva(tmp_path, monkeypatch):
    """Nu-l refuzăm — e document de arhivat 10 ani."""
    Session, uid = _setup(tmp_path, monkeypatch)
    tx_ids = _masina(Session, uid)

    s = Session()
    tx = s.get(Transaction, tx_ids[0])
    assert tx is not None
    assert tx.category == CAT_ACHIZITIE_VEHICUL
    assert tx.amount_brut == 48500.0
    assert tx.deductibility_pct == 0        # aritmetica lunii curente
    assert tx.document_id is not None        # documentul e legat

    # Regăsibil prin interogare pe categorie
    gasit = (
        s.query(Transaction)
        .filter(Transaction.category == CAT_ACHIZITIE_VEHICUL)
        .all()
    )
    assert len(gasit) == 1
    doc = s.get(Document, gasit[0].document_id)
    assert doc is not None                   # documentul-sursă există
    s.close()


def test_registrul_afiseaza_eticheta_romaneasca():
    """Într-un document fiscal nu scrie «Vehicle Acquisition»."""
    label = _resolve_category_label(CAT_ACHIZITIE_VEHICUL)
    assert label == "Cumpărare mașină (mijloc fix)"
    assert "Vehicle" not in label


# ════════════════════════════════════════════════════════════
#   POARTA — când întrebăm și când nu
# ════════════════════════════════════════════════════════════

def test_service_sub_prag_nu_declanseaza_intrebarea():
    """FALS POZITIV: o factură de service de 8.000 lei nu întrerupe fluxul."""
    item = {"tip": "CHELTUIALA", "brut": 8000.0, "detalii": "reparatii auto"}
    assert necesita_intrebare_achizitie(item) is False


def test_suma_mare_declanseaza_intrebarea():
    item = {"tip": "CHELTUIALA", "brut": 48500.0, "detalii": "Dacia Logan"}
    assert necesita_intrebare_achizitie(item) is True


def test_pragul_e_inclusiv():
    item = {"tip": "CHELTUIALA", "brut": PRAG_INTREBARE_ACHIZITIE}
    assert necesita_intrebare_achizitie(item) is True


def test_venitul_mare_nu_declanseaza():
    """Poarta e doar pe cheltuieli — un venit de 50.000 nu întreabă nimic."""
    item = {"tip": "VENIT", "brut": 50000.0, "net": 50000.0}
    assert necesita_intrebare_achizitie(item) is False


def test_suma_lipsa_nu_crapa():
    assert necesita_intrebare_achizitie({"tip": "CHELTUIALA"}) is False
    assert necesita_intrebare_achizitie({"tip": "CHELTUIALA", "brut": None}) is False
    assert necesita_intrebare_achizitie({"tip": "CHELTUIALA", "brut": "x"}) is False


def test_categoria_e_inaccesibila_scoringului():
    """
    FALS POZITIV STRUCTURAL: nici cel mai sugestiv text nu poate ateriza pe
    achiziție prin scoring — categoria n-are keywords, deci singurul drum
    spre ea e butonul apăsat de om.
    """
    activity = get_activity("ridesharing")
    for text in ("achizitie autoturism serie sasiu", "autoturism nou",
                 "factura vehicul", "cumparare masina"):
        cat, _ = activity.detect_expense_category(None, text)
        cod = cat.code if cat else None
        assert cod != CAT_ACHIZITIE_VEHICUL, text


# ════════════════════════════════════════════════════════════
#   BUTOANELE — răspunsul omului
# ════════════════════════════════════════════════════════════

class _Q:
    def __init__(self):
        self.text = None
        self.kb = None
        self.message = SimpleNamespace(chat_id=1)

    async def edit_message_text(self, text, **kw):
        self.text = text
        self.kb = kw.get("reply_markup")


def _ctx(items):
    ctx = SimpleNamespace(user_data={})
    confirmare.store_pending(ctx, items, "file123", "{}", "v1")
    return ctx


def _labels(kb):
    return [b.text for row in kb.inline_keyboard for b in row]


@pytest.mark.asyncio
async def test_peste_prag_botul_intreaba_nu_clasifica():
    q = _Q()
    ctx = _ctx([{"tip": "CHELTUIALA", "brut": 48500.0, "platforma": "Autoklass",
                 "data": "07.08.2026", "detalii": "Dacia Logan"}])
    await confirmare.show_confirmation(1, ctx, query=q)

    assert "ce e documentul ăsta" in q.text
    labels = _labels(q.kb)
    assert any("Cumpărare de mașină" in l for l in labels)
    assert any("Altă cheltuială" in l for l in labels)


@pytest.mark.asyncio
async def test_alta_cheltuiala_duce_pe_fluxul_normal():
    """Răspunsul «Altă cheltuială» lasă documentul complet neatins."""
    q = _Q()
    ctx = _ctx([{"tip": "CHELTUIALA", "brut": 15000.0, "platforma": "Service SRL",
                 "data": "07.08.2026", "detalii": "motor refacut"}])
    upd = SimpleNamespace(callback_query=q)

    await confirmare.handle_callback(upd, ctx, ["confirm", "capex", "0", "nu"])

    item = confirmare.get_pending(ctx)["items"][0]
    assert item.get("category_override") is None      # fără clasificare
    # ...și ajunge la ecranul normal de confirmare, nu la întrebare din nou
    assert "Confirmă și salvează" in " ".join(_labels(q.kb))
    assert "ce e documentul ăsta" not in q.text


@pytest.mark.asyncio
async def test_cumparare_de_masina_seteaza_categoria():
    q = _Q()
    ctx = _ctx([{"tip": "CHELTUIALA", "brut": 48500.0, "platforma": "Autoklass",
                 "data": "07.08.2026", "detalii": "Dacia Logan"}])
    upd = SimpleNamespace(callback_query=q)

    await confirmare.handle_callback(upd, ctx, ["confirm", "capex", "0", "da"])

    item = confirmare.get_pending(ctx)["items"][0]
    assert item["category_override"] == CAT_ACHIZITIE_VEHICUL
    # alegerea e vizibilă înainte de salvare, ca să poată fi anulată
    assert "Cumpărare de mașină" in q.text


@pytest.mark.asyncio
async def test_intrebarea_nu_se_reia_la_infinit():
    """După răspuns, ecranul normal — altfel «Altă cheltuială» ar bucla."""
    q = _Q()
    ctx = _ctx([{"tip": "CHELTUIALA", "brut": 20000.0, "data": "07.08.2026"}])
    upd = SimpleNamespace(callback_query=q)

    await confirmare.handle_callback(upd, ctx, ["confirm", "capex", "0", "nu"])
    await confirmare.show_confirmation(1, ctx, query=q)

    assert "ce e documentul ăsta" not in q.text


@pytest.mark.asyncio
async def test_sub_prag_nu_apare_intrebarea():
    """Un bon obișnuit ajunge direct la confirmare — zero fricțiune nouă."""
    q = _Q()
    ctx = _ctx([{"tip": "CHELTUIALA", "brut": 200.0, "platforma": "Lukoil",
                 "data": "07.08.2026", "detalii": "motorina"}])
    await confirmare.show_confirmation(1, ctx, query=q)

    assert "ce e documentul ăsta" not in q.text
    assert "Confirmă și salvează" in " ".join(_labels(q.kb))


# ════════════════════════════════════════════════════════════
#   AI-ul nu poate seta categoria
# ════════════════════════════════════════════════════════════

def test_ai_nu_poate_inventa_categoria():
    """
    `category_override` e câmp de BUTON, nu de AI: lista albă respinge orice
    altceva, deci o halucinație nu poate capitaliza o cheltuială reală.
    """
    it = ExtractionItem(tip="CHELTUIALA", brut=500.0, category_override="fuel")
    assert it.category_override is None

    it = ExtractionItem(tip="CHELTUIALA", brut=500.0,
                        category_override="orice_altceva")
    assert it.category_override is None

    # valoarea legitimă trece
    it = ExtractionItem(tip="CHELTUIALA", brut=48500.0,
                        category_override=CAT_ACHIZITIE_VEHICUL)
    assert it.category_override == CAT_ACHIZITIE_VEHICUL


def test_default_e_none():
    """Regresie: itemii existenți (fără câmp) rămân pe fluxul normal."""
    it = ExtractionItem(tip="CHELTUIALA", brut=200.0)
    assert it.category_override is None
    assert este_achizitie(it.category_override) is False
