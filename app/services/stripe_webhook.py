"""
Brick 2c — webhook-ul Stripe: ULTIMA verigă a lanțului de plată (§1.7 Felia 2).

Aici, și DOAR aici, se acordă un abonament. 2b creează sesiunea de checkout dar nu
scrie nimic (garanție structurală: funcția lui n-are `session`); `success_url` e o
pagină cosmetică pe care oricine o poate deschide fără să fi plătit. Singura dovadă
că banii au intrat e un eveniment SEMNAT de Stripe — deci singura scriere pornește
de aici.

CE TRATĂM (cele 4 evenimente ascultate în dashboardul Stripe):
  · checkout.session.completed  → prima plată  → status='active' + tier
  · customer.subscription.updated → schimbare  → comută pe STATUS (vezi capcana)
  · customer.subscription.deleted → anulare    → clear_subscription
  · invoice.paid                  → IGNORAT intenționat (vezi mai jos)

DE CE E IGNORAT invoice.paid: factura nu poartă nici `client_reference_id`, nici
metadata abonamentului — doar `customer` (cus_...), iar noi n-avem lookup după
stripe_customer_id. N-am putea spune A CUI e plata. Reînnoirile produc oricum
`customer.subscription.updated`, care ARE metadata (pusă de 2b) — deci nu pierdem
nimic ignorând-o.

⚠️ CAPCANA `cancel_at_period_end`: când userul anulează, Stripe trimite un
`customer.subscription.updated` cu `cancel_at_period_end=true` dar cu `status` ÎNCĂ
`active` — omul a plătit până la finalul perioadei și are dreptul la acces până
atunci. Comutăm pe STATUS, niciodată pe `cancel_at_period_end`. Anularea reală vine
separat, ca `.deleted`.

DE UNDE VINE TIER-UL, pe fiecare eveniment:
  · checkout.session.completed → `metadata.tier` (pus de 2b). NU din price:
    `line_items` nu vine în payload-ul evenimentului.
  · customer.subscription.* → `items.data[0].price.id` → `tier_for_price_id` (2a).
    Price străin → NU ghicim tier-ul, scriem doar statusul.

CONVENȚIA DE COMMIT: modulul nu comite — scrie prin repository (care face `flush`) și
întoarce PROCESAT/IGNORAT; ruta decide și comite o singură dată. Așa rămâne valabilă
regula „commit la apelant" din tot repository-ul.

⏳ FOLLOW-UP PRE-LANSARE (decis conștient): ordinea evenimentelor nu e garantată de
Stripe — un `.deleted` întârziat poate ajunge după un `.updated` mai nou și ar
reactiva/anula greșit. Acum riscul e zero, dar NU fiindcă n-ar fi useri în
producție (sunt 9): fiindcă niciunul n-are abonament, deci webhook-ul n-are pe
cine reactiva greșit. Condiția e falsificabilă, nu o impresie:
    SELECT count(*) FROM users WHERE stripe_customer_id IS NOT NULL   -- 0 la 17.08.2026
În ziua în care nu mai e 0, riscul devine real. De apărat înainte de lansarea
publică (ex. compară `event.created` cu un timestamp pe user).
"""

import logging

from app.repositories import users as users_repo
from app.services import stripe_config
from app.services import subscription as sub
from config import settings

logger = logging.getLogger(__name__)

# Rezultatul procesării. Cine îl citește (ruta) decide codul HTTP — dar AMBELE
# înseamnă „nu mai reîncerca": IGNORAT e o stare permanentă (user inexistent, price
# străin, event netratat), pe care un retry n-o repară.
PROCESAT = "procesat"
IGNORAT = "ignorat"

# Statusuri Stripe care înseamnă „abonamentul s-a încheiat" → clear_subscription.
STATUS_INCHEIAT = ("canceled", "unpaid", "incomplete_expired")


# ══════════════════════════════════════════════════════════════
# 1. Autentificarea: semnătura Stripe pe octeții bruți
# ══════════════════════════════════════════════════════════════

def verifica_semnatura(payload: bytes, sig_header: str):
    """
    Întoarce evenimentul Stripe VERIFICAT, sau None dacă nu putem avea încredere.

    E singura autentificare a rutei: nu există initData Telegram aici, requestul vine
    de la Stripe. `payload` trebuie să fie octeții BRUȚI ai corpului (Stripe semnează
    byte-cu-byte; orice re-serializare prin JSON strică semnătura).

    `construct_event` verifică și prospețimea timestamp-ului (toleranță 5 min), ca
    `auth_date` la Telegram — o semnătură valabilă la nesfârșit ar fi un credential
    exfiltrabil.
    """
    secret = settings.stripe_webhook_secret
    if not secret:
        logger.error("Webhook Stripe primit, dar STRIPE_WEBHOOK_SECRET nu e configurat.")
        return None
    if not sig_header:
        logger.warning("Webhook Stripe fără antet Stripe-Signature — respins.")
        return None

    import stripe
    try:
        return stripe.Webhook.construct_event(payload, sig_header, secret)
    except Exception as e:
        # SignatureVerificationError (semnătură/timestamp) sau ValueError (payload).
        logger.warning(f"Semnătură Stripe invalidă — respins: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# 2. Citire tolerantă din payload
# ══════════════════════════════════════════════════════════════

def _camp(obiect, *cale):
    """
    Citește `obiect.a.b.c` fără să crape pe câmpuri lipsă. Obiectele SDK-ului sunt
    dict-like, dar în teste primim dict-uri simple — mergem pe ambele.
    Indicii întregi merg în liste (ex. items.data[0]).
    """
    curent = obiect
    for cheie in cale:
        if curent is None:
            return None
        if isinstance(cheie, int):
            try:
                curent = curent[cheie]
            except (IndexError, KeyError, TypeError):
                return None
        elif isinstance(curent, dict):
            curent = curent.get(cheie)
        else:
            curent = getattr(curent, cheie, None)
    return curent


def _user(session, user_id, context: str):
    """
    Userul din id-ul venit prin `client_reference_id`/metadata, sau None + log.
    None e o stare PERMANENTĂ (userul nu apare mai târziu) → apelantul dă IGNORAT,
    nu eroare: altfel Stripe ar reîncerca zile în șir pentru nimic.
    """
    if user_id in (None, ""):
        logger.error(f"{context}: eveniment fără id de user — nu știu a cui e plata.")
        return None
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        logger.error(f"{context}: id de user neinterpretabil ({user_id!r}).")
        return None
    user = users_repo.get_by_id(session, uid)
    if user is None:
        logger.error(f"{context}: userul {uid} nu există în DB — eveniment ignorat.")
    return user


def _tier_din_abonament(obiect, context: str):
    """
    Tier-ul cumpărat, din price ID-ul liniei de abonament. None dacă price-ul nu e
    al niciunui tier configurat — caz în care NU ghicim (scriem doar statusul).
    """
    price_id = _camp(obiect, "items", "data", 0, "price", "id")
    if not price_id:
        logger.warning(f"{context}: abonament fără price ID — nu pot deduce tier-ul.")
        return None
    tier = stripe_config.tier_for_price_id(price_id)
    if tier is None:
        logger.warning(f"{context}: price {price_id!r} nu e al niciunui tier configurat.")
    return tier


# ══════════════════════════════════════════════════════════════
# 3. Tratarea evenimentelor
# ══════════════════════════════════════════════════════════════

def _salveaza_adresa_facturare(user, obiect) -> None:
    """
    Completează adresa de facturare din datele colectate de Stripe la checkout
    (Felia 3: factura cere stradă + nr, onboarding-ul dă doar județ/localitate).

    NU SUPRASCRIE nimic completat: ce a scris userul despre sine are prioritate față
    de ce a tastat în formularul de plată. Umplem doar golurile.

    Best-effort: o adresă lipsă NU trebuie să blocheze activarea abonamentului (omul
    a plătit). Fără adresă, 3b va ști că factura n-are toate datele.
    """
    adresa = _camp(obiect, "customer_details", "address")
    if not adresa:
        return

    linie = " ".join(p for p in (_camp(adresa, "line1"), _camp(adresa, "line2")) if p)
    for camp, valoare in (
        ("adresa_strada", linie or None),
        ("cod_postal", _camp(adresa, "postal_code")),
        ("localitate", _camp(adresa, "city")),
        ("judet", _camp(adresa, "state")),
    ):
        if valoare and not getattr(user, camp, None):
            setattr(user, camp, valoare)


def _checkout_finalizat(session, obiect) -> str:
    """Prima plată: activăm abonamentul și legăm userul de clientul Stripe."""
    ctx = "checkout.session.completed"

    plata = _camp(obiect, "payment_status")
    if plata != "paid":
        logger.info(f"{ctx}: payment_status={plata!r} — nu activez nimic.")
        return IGNORAT

    user = _user(session, _camp(obiect, "client_reference_id"), ctx)
    if user is None:
        return IGNORAT

    tier = _camp(obiect, "metadata", "tier")
    if tier not in sub.PAID_TIERS:
        logger.error(f"{ctx}: tier {tier!r} necunoscut în metadata — NU acord nimic.")
        return IGNORAT

    users_repo.set_subscription(
        session, user,
        customer_id=_camp(obiect, "customer"),
        subscription_id=_camp(obiect, "subscription"),
        status="active",
        tier=tier,
    )
    # Felia 3: adresa de facturare, dacă Stripe a colectat-o. Separat de abonament —
    # o adresă lipsă nu are voie să împiedice activarea.
    _salveaza_adresa_facturare(user, obiect)
    logger.info(f"{ctx}: user={user.id} → {tier} ACTIV.")
    return PROCESAT


def _abonament_actualizat(session, obiect) -> str:
    """
    Schimbare de abonament. Comutăm pe STATUS — vezi capcana `cancel_at_period_end`
    din capul fișierului: `active` rămâne `active` chiar dacă anularea e programată.
    """
    ctx = "customer.subscription.updated"

    user = _user(session, _camp(obiect, "metadata", "user_id"), ctx)
    if user is None:
        return IGNORAT

    status = _camp(obiect, "status")

    if status in STATUS_INCHEIAT:
        users_repo.clear_subscription(session, user)
        logger.info(f"{ctx}: user={user.id} status={status} → abonament încheiat.")
        return PROCESAT

    if status == "active":
        # `tier=None` (price străin) = «lasă tier-ul neschimbat» — nu inventăm unul.
        tier = _tier_din_abonament(obiect, ctx)
        users_repo.set_subscription(session, user, status="active", tier=tier)
        logger.info(f"{ctx}: user={user.id} ACTIV, tier={tier or 'neschimbat'}.")
        return PROCESAT

    # past_due / incomplete / trialing: scriem statusul, dar NU dăm tier. `is_subscribed`
    # (2a) cere exact 'active', deci userul cade pe FREE (sau pe trial-ul intern, dacă
    # mai e valabil — prioritatea din 4a decide, nu noi aici).
    users_repo.set_subscription(session, user, status=status)
    logger.info(f"{ctx}: user={user.id} status={status} → fără tier.")
    return PROCESAT


def _abonament_sters(session, obiect) -> str:
    """Anularea REALĂ (perioada plătită s-a terminat). Cade pe FREE — sau pe trial."""
    ctx = "customer.subscription.deleted"

    user = _user(session, _camp(obiect, "metadata", "user_id"), ctx)
    if user is None:
        return IGNORAT

    users_repo.clear_subscription(session, user)
    logger.info(f"{ctx}: user={user.id} → abonament anulat.")
    return PROCESAT


def proceseaza(session, event) -> str:
    """
    Rutează evenimentul VERIFICAT către tratarea lui. Întoarce PROCESAT (s-a scris,
    apelantul comite) sau IGNORAT (nimic de scris — și nimic de reîncercat).

    NU prinde excepții: o eroare neașteptată (DB picat) trebuie să urce la rută, care
    o traduce în 500 ca Stripe să reîncerce. Stările permanente sunt deja IGNORAT.
    """
    tip = _camp(event, "type")
    obiect = _camp(event, "data", "object")

    if tip == "checkout.session.completed":
        return _checkout_finalizat(session, obiect)
    if tip == "customer.subscription.updated":
        return _abonament_actualizat(session, obiect)
    if tip == "customer.subscription.deleted":
        return _abonament_sters(session, obiect)
    if tip == "invoice.paid":
        logger.info("invoice.paid ignorat — reînnoirile vin prin customer.subscription.updated.")
        return IGNORAT

    logger.info(f"Event Stripe netratat: {tip!r} — confirmat, fără acțiune.")
    return IGNORAT
