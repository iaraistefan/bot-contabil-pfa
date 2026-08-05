"""
Felia 3 / Brick 3a — fundația facturării (§1.7).

DOAR fundația: config + tabel + captarea adresei. ZERO apeluri Oblio (emiterea = 3b).

Miezul: UNIQUE pe `stripe_invoice_id`. Webhook-urile Stripe se livrează repetat, iar
o plată NU are voie să producă două facturi la ANAF. Testăm că BAZA refuză dublura —
nu că try/except-ul nostru e atent.

Al doilea miez: adresa se completează, dar NU suprascrie. Ce a declarat userul despre
sine bate ce a tastat în formularul de plată.
"""

import json
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import FacturaAbonament, User
from app.services import oblio_config
from app.services import stripe_checkout
from app.services import stripe_config
from app.services import stripe_webhook
from app.services import subscription as sub


def _db(tmp_path, **user_kw):
    eng = create_engine(f"sqlite:///{(tmp_path / 'o.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=5, **user_kw); s.add(u); s.commit()
    return S, s, u


# ══════════════════════════════════════════════════════════════
# 1. Configurarea Oblio — degradare grațioasă
# ══════════════════════════════════════════════════════════════

def _oblio(monkeypatch, email=None, secret=None, cif=None, serie=None):
    monkeypatch.setattr(oblio_config.settings, "oblio_email", email)
    monkeypatch.setattr(oblio_config.settings, "oblio_secret", secret)
    monkeypatch.setattr(oblio_config.settings, "oblio_cif", cif)
    monkeypatch.setattr(oblio_config.settings, "oblio_serie_factura", serie)


def test_fara_env_nu_e_configurat(monkeypatch):
    _oblio(monkeypatch)
    assert oblio_config.is_oblio_configured() is False
    assert set(oblio_config.campuri_lipsa()) == set(oblio_config.CAMPURI_NECESARE)


def test_cu_toate_cele_patru_e_configurat(monkeypatch):
    _oblio(monkeypatch, email="a@b.ro", secret="tok", cif="RO123", serie="CNR")
    assert oblio_config.is_oblio_configured() is True
    assert oblio_config.campuri_lipsa() == ()


def test_configurare_partiala_nu_trece(monkeypatch):
    """Trei din patru nu emit nimic — vrem să știm CARE lipsește."""
    _oblio(monkeypatch, email="a@b.ro", secret="tok", cif="RO123")   # fără serie
    assert oblio_config.is_oblio_configured() is False
    assert oblio_config.campuri_lipsa() == ("oblio_serie_factura",)


def test_citit_la_apel_nu_la_import(monkeypatch):
    """Env-ul se poate schimba între procese — o hartă înghețată la import ar minți."""
    _oblio(monkeypatch)
    assert oblio_config.is_oblio_configured() is False
    _oblio(monkeypatch, email="a@b.ro", secret="tok", cif="RO123", serie="CNR")
    assert oblio_config.is_oblio_configured() is True


def test_campurile_sunt_optional_in_settings():
    """Lipsa lor NU oprește aplicația (ca stripe_*)."""
    from config import Settings
    for c in ("oblio_email", "oblio_secret", "oblio_cif", "oblio_serie_factura"):
        assert c in Settings.model_fields
        assert Settings.model_fields[c].default is None


# ══════════════════════════════════════════════════════════════
# 2. UNIQUE pe stripe_invoice_id — o plată, o singură factură
# ══════════════════════════════════════════════════════════════

def test_baza_refuza_stripe_invoice_id_dublat(tmp_path):
    """
    CRUCIAL: apărarea e în SCHEMĂ, nu în cod. Două facturi pentru aceeași plată =
    problemă reală la ANAF, nu doar date urâte.
    """
    S, s, u = _db(tmp_path)
    s.add(FacturaAbonament(user_id=u.id, stripe_invoice_id="in_1"))
    s.commit()

    s.add(FacturaAbonament(user_id=u.id, stripe_invoice_id="in_1"))   # aceeași plată
    with pytest.raises(IntegrityError):
        s.commit()
    s.rollback()

    s2 = S()
    assert s2.query(FacturaAbonament).count() == 1
    s2.close(); s.close()


def test_facturi_diferite_trec(tmp_path):
    S, s, u = _db(tmp_path)
    s.add(FacturaAbonament(user_id=u.id, stripe_invoice_id="in_1"))
    s.add(FacturaAbonament(user_id=u.id, stripe_invoice_id="in_2"))
    s.commit()
    assert s.query(FacturaAbonament).count() == 2
    s.close()


def test_statusul_implicit_e_pending(tmp_path):
    """Un rând nou = factură DE EMIS, nu emisă."""
    from app.models import FACTURA_PENDING

    S, s, u = _db(tmp_path)
    f = FacturaAbonament(user_id=u.id, stripe_invoice_id="in_9")
    s.add(f); s.commit()

    assert f.status == FACTURA_PENDING
    assert f.oblio_serie is None and f.oblio_numar is None and f.emisa_at is None
    s.close()


def test_stripe_invoice_id_e_obligatoriu(tmp_path):
    """Fără el n-am ști pentru ce plată e factura — și n-ar mai fi idempotent."""
    S, s, u = _db(tmp_path)
    s.add(FacturaAbonament(user_id=u.id))
    with pytest.raises(IntegrityError):
        s.commit()
    s.rollback(); s.close()


def test_migrarea_025_vine_dupa_024_si_are_unique():
    """
    Gardian pe ORDINE, nu pe „ultima" — exact capcana în care au căzut cele patru
    teste de dinainte când 3a a adăugat 025. Feliile viitoare adaugă legitim migrări.
    """
    from app import migrations

    ids = [m["id"] for m in migrations.MIGRATIONS]
    i = ids.index("025_factura_abonament")
    assert i == ids.index("024_trial_ends_at") + 1      # 2a/4a neatinse

    sql = " ".join(m for m in migrations.MIGRATIONS[i]["sql"])
    assert "stripe_invoice_id VARCHAR(255) NOT NULL UNIQUE" in sql
    assert "adresa_strada" in sql and "cod_postal" in sql
    assert "IF NOT EXISTS" in sql                  # idempotentă


def test_fk_ul_e_restrict_nu_cascade():
    """
    Factura emisă e DOCUMENT FISCAL (arhivare 10 ani) — nu are voie să dispară cu
    userul. RESTRICT, spre deosebire de restul tabelelor per-user care sunt CASCADE.
    Verificat în AMBELE locuri: migrarea (producție) și modelul ORM.
    """
    from app import migrations
    from app.models import FacturaAbonament

    i = [m["id"] for m in migrations.MIGRATIONS].index("025_factura_abonament")
    sql = " ".join(migrations.MIGRATIONS[i]["sql"])
    assert "REFERENCES users(id) ON DELETE RESTRICT" in sql
    assert "ON DELETE CASCADE" not in sql

    fk = list(FacturaAbonament.__table__.c.user_id.foreign_keys)[0]
    assert fk.ondelete == "RESTRICT"


# ══════════════════════════════════════════════════════════════
# 3. Checkout cere adresa de facturare
# ══════════════════════════════════════════════════════════════

class _FakeSDK:
    URL = "https://checkout.stripe.com/c/pay/cs_test_1"

    def __init__(self):
        self.captured = None
        eu = self

        class _Session:
            @staticmethod
            def create(**kw):
                eu.captured = kw
                return SimpleNamespace(url=_FakeSDK.URL)

        class _Checkout:
            Session = _Session

        self.checkout = _Checkout


def test_checkout_cere_adresa_de_facturare(monkeypatch):
    monkeypatch.setattr(stripe_config.settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(stripe_config.settings, "stripe_price_pro", "price_P")
    sdk = _FakeSDK()
    monkeypatch.setattr(stripe_checkout, "_stripe", lambda: sdk)

    stripe_checkout.create_checkout_session(
        SimpleNamespace(id=3, stripe_customer_id=None), sub.PRO)

    assert sdk.captured["billing_address_collection"] == "required"
    # restul sesiunii, neatins (regresie 2b)
    assert sdk.captured["client_reference_id"] == "3"
    assert sdk.captured["mode"] == "subscription"


# ══════════════════════════════════════════════════════════════
# 4. Adresa se salvează la webhook — dar NU suprascrie
# ══════════════════════════════════════════════════════════════

ADRESA = {
    "line1": "Str. Lalelelor 12", "line2": "ap. 3",
    "postal_code": "300123", "city": "Timișoara", "state": "Timiș",
}


def _checkout_obj(user_id, adresa=ADRESA, tier="PRO"):
    return {
        "payment_status": "paid",
        "client_reference_id": str(user_id),
        "customer": "cus_1",
        "subscription": "sub_1",
        "metadata": {"user_id": str(user_id), "tier": tier},
        "customer_details": {"address": adresa} if adresa else None,
    }


def _proceseaza(session, tip, obiect):
    return stripe_webhook.proceseaza(
        session, {"type": tip, "data": {"object": obiect}})


def test_adresa_se_scrie_cand_lipseste(tmp_path):
    S, s, u = _db(tmp_path)

    assert _proceseaza(s, "checkout.session.completed", _checkout_obj(u.id)) == "procesat"
    s.commit()

    assert u.adresa_strada == "Str. Lalelelor 12 ap. 3"    # line1 + line2
    assert u.cod_postal == "300123"
    assert u.localitate == "Timișoara"
    assert u.judet == "Timiș"
    assert u.stripe_status == "active" and u.stripe_tier == "PRO"   # abonamentul, intact
    s.close()


def test_adresa_NU_suprascrie_ce_a_declarat_userul(tmp_path):
    """CRUCIAL: onboarding-ul bate formularul de plată. Umplem doar golurile."""
    S, s, u = _db(tmp_path, judet="Cluj", localitate="Cluj-Napoca")

    _proceseaza(s, "checkout.session.completed", _checkout_obj(u.id))
    s.commit()

    assert u.judet == "Cluj"                    # NEATINS
    assert u.localitate == "Cluj-Napoca"        # NEATINS
    assert u.adresa_strada == "Str. Lalelelor 12 ap. 3"   # golul, completat
    assert u.cod_postal == "300123"
    s.close()


def test_fara_adresa_in_payload_abonamentul_tot_se_activeaza(tmp_path):
    """Omul a plătit: o adresă lipsă NU are voie să blocheze activarea."""
    S, s, u = _db(tmp_path)

    assert _proceseaza(s, "checkout.session.completed",
                       _checkout_obj(u.id, adresa=None)) == "procesat"
    s.commit()

    assert u.stripe_status == "active" and u.stripe_tier == "PRO"
    assert u.adresa_strada is None
    s.close()


def test_adresa_partiala_scrie_doar_ce_are(tmp_path):
    S, s, u = _db(tmp_path)

    _proceseaza(s, "checkout.session.completed",
                _checkout_obj(u.id, adresa={"line1": "Bd. Unirii 1", "city": "București"}))
    s.commit()

    assert u.adresa_strada == "Bd. Unirii 1"
    assert u.localitate == "București"
    assert u.cod_postal is None and u.judet is None
    s.close()


def test_checkout_neplatit_nu_scrie_nici_adresa(tmp_path):
    """Ignorat = ignorat: nici abonament, nici adresă."""
    S, s, u = _db(tmp_path)
    obiect = _checkout_obj(u.id)
    obiect["payment_status"] = "unpaid"

    assert _proceseaza(s, "checkout.session.completed", obiect) == "ignorat"
    s.commit()

    assert u.adresa_strada is None and u.stripe_status is None
    s.close()


# ══════════════════════════════════════════════════════════════
# 5. Regresie — 3a nu cheamă Oblio și nu atinge feliile anterioare
# ══════════════════════════════════════════════════════════════

def _sursa(rel):
    from pathlib import Path
    return (Path(__file__).resolve().parent.parent / rel).read_text(encoding="utf-8")


def test_zero_apeluri_oblio_in_3a():
    """Brick 3a e doar fundația: niciun import de SDK, nicio cerere HTTP."""
    import ast

    arbore = ast.parse(_sursa("app/services/oblio_config.py"))
    module = set()
    for nod in ast.walk(arbore):
        if isinstance(nod, ast.Import):
            module |= {a.name for a in nod.names}
        elif isinstance(nod, ast.ImportFrom):
            module.add(nod.module or "")
    for m in module:
        assert "oblio" not in m.lower() or m == "config"
        assert m not in ("requests", "httpx", "urllib.request")


def test_secretul_oblio_nu_apare_in_loguri():
    """`oblio_secret` e token API — numele poate apărea, valoarea niciodată."""
    src = _sursa("app/services/oblio_config.py")
    assert "settings.oblio_secret" not in src        # citit doar prin getattr generic
    assert "logger" not in src                        # modulul nici nu logează


def test_logica_de_abonament_neatinsa(tmp_path):
    """Adresa e un adaos lateral — 2c decide abonamentul exact ca înainte."""
    import inspect
    from app.repositories import users as users_repo

    assert list(inspect.signature(users_repo.set_subscription).parameters) == [
        "session", "user", "customer_id", "subscription_id", "status", "tier",
    ]

    S, s, u = _db(tmp_path)
    _proceseaza(s, "customer.subscription.deleted",
                {"metadata": {"user_id": str(u.id)}})
    s.commit()
    assert u.stripe_status == "canceled"
    s.close()


def test_userii_fara_adresa_raman_valizi(tmp_path):
    """Câmpurile noi sunt nullable — userii existenți neschimbați."""
    S, s, u = _db(tmp_path)
    assert u.adresa_strada is None and u.cod_postal is None
    assert sub.user_tier(u) == "FREE"
    s.close()
