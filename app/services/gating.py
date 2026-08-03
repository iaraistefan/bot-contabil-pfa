"""
Felia 4b — APLICAREA gating-ului pe features + teaser-ul „armei secrete" (§1.7/§1.8).

Felia 1 a construit fundația de citire a tier-ului (subscription.py), Felia 4a a
făcut-o trial-aware. Aici o CONSUMĂM: sursă unică pentru
  1. maparea feature → tier minim (cine ce poate),
  2. copy-ul de upgrade (ton liniștitor, adresare „tu", emoji prietenos),
  3. teaser-ul reconcilierii = cârligul de aur (FREE vede CĂ există o nepotrivire,
     dar nu ce anume și nici cum se rezolvă).

CE RĂMÂNE GRATIS (FREE „Radar", decizia din research #9): alertele de termene cu
sume, vizualizarea, estimarea aproximativă. Nu monetizăm vizualizarea — monetizăm
automatizarea, reconcilierea și depunerea.

NU atinge subscription.py (user_tier/is_in_trial/trial_days_left doar se citesc de
aici) și nici motoarele de reconciliere — doar AFIȘAREA lor ramifică.
"""

import logging

from db import get_session
from app.repositories import users as users_repo
from app.services import subscription as sub

logger = logging.getLogger(__name__)

# Dashboard-ul e locul unde se activează abonamentul (sursă unică; bot_contabil îl
# importă de aici ca să nu existe două adevăruri despre URL).
DASHBOARD_URL = "https://bot-contabil-pfa.onrender.com/dashboard"


# ══════════════════════════════════════════════════════════════
# 1. Maparea feature → tier minim (§1.8)
# ══════════════════════════════════════════════════════════════
# `label` = cum numim feature-ul în mesaj; `beneficiu` = ce face Coniar concret în
# planul ăla (nu „deblochezi funcția X", ci ce câștigi tu).
FEATURES = {
    "declaratii": {
        "tier": sub.PRO,
        "label": "Depunerea declarațiilor (D301 / D390 / D100 / D207)",
        "beneficiu": (
            "îți pregătește declarația completă, cu ghid de completare și fișierul "
            "XML gata de urcat în SPV"
        ),
    },
    "bolt_sync": {
        "tier": sub.START,
        "label": "Sincronizarea automată Bolt",
        "beneficiu": (
            "îți aduce singur cursele din contul tău Bolt și le trece în Registru, "
            "fără să le mai treci de mână"
        ),
    },
    "d212": {
        "tier": sub.START,
        "label": "Declarația Unică (D212) calculată pe datele tale",
        "beneficiu": (
            "îți calculează impozitul, CAS-ul și CASS-ul pe veniturile tale reale, "
            "actualizat pe măsură ce înregistrezi"
        ),
    },
    "reconciliere": {
        "tier": sub.PRO,
        "label": "Reconcilierea completă Bolt",
        "beneficiu": (
            "îți arată exact ce nu se potrivește între Bolt și ce ai declarat și cum "
            "se rezolvă, înainte să întrebe ANAF"
        ),
    },
}

# Namespace de callback (bot) → feature. Ce NU e aici rămâne liber (alertele de
# termene, registrul, rapoartele, ghidul, extrasul bancar — FREE „Radar").
NAMESPACE_FEATURE = {
    "d301": "declaratii",
    "d390": "declaratii",
    "d100": "declaratii",
    "d207": "declaratii",
    "du": "d212",
}


def feature_tier(feature: str) -> str:
    """Tier-ul minim cerut de un feature. Feature necunoscut → FREE (nu blocăm orbește)."""
    return FEATURES.get(feature, {}).get("tier", sub.FREE)


# ══════════════════════════════════════════════════════════════
# 2. Citirea tier-ului (consumă Felia 4a, n-o modifică)
# ══════════════════════════════════════════════════════════════
def has_feature(session, user_id: int, min_tier: str, now=None) -> bool:
    """
    Userul `user_id` are cel puțin `min_tier`? Trial activ = PRO (Felia 4a).
    User negăsit → False (conservator: tratat ca FREE).
    """
    user = users_repo.get_by_id(session, user_id)
    if user is None:
        return False
    return sub.has_tier_at_least(user, min_tier)


def user_has_feature(user_id: int, min_tier: str) -> bool:
    """
    Ca `has_feature`, dar își deschide singur sesiunea (pt apelanții care n-au una).
    Defensiv: o eroare de DB NU deschide poarta — întoarce False.
    """
    session = get_session()
    try:
        return has_feature(session, user_id, min_tier)
    except Exception as e:
        logger.error(f"has_feature failed user={user_id} tier={min_tier}: {e}")
        return False
    finally:
        session.close()


def _load_user(user_id: int):
    """User-ul (pt linia de trial în copy) sau None. Nu propagă erori."""
    session = get_session()
    try:
        return users_repo.get_by_id(session, user_id)
    except Exception:
        return None
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════
# 3. Copy de upgrade — ton liniștitor, „tu", emoji prietenos
# ══════════════════════════════════════════════════════════════
def trial_line(user, now=None):
    """
    Linia de trial („îți mai rămân N zile") sau None dacă nu e în trial.
    Consumă `trial_days_left` din Felia 4a.
    """
    if user is None or not sub.is_in_trial(user, now=now):
        return None
    zile = sub.trial_days_left(user, now=now)
    zi_txt = "zi" if zile == 1 else "zile"
    return (
        f"✨ Ești în perioada PRO gratuită — îți mai rămân {zile} {zi_txt} "
        f"cu toate funcțiile deblocate."
    )


# Etichetele celor două CTA-uri posibile. Sursă unică: și textul, și butonul le
# citesc de aici, ca mesajul să numească EXACT butonul de dedesubt (Brick 2b).
CTA_DASHBOARD = "🖥️ Deschide Dashboard"


def checkout_disponibil(tier: str) -> bool:
    """
    Putem duce userul direct la plată pentru `tier`? (Brick 2b: chei Stripe + price
    configurat pt tier-ul ăsta.) Fals → CTA-ul cade pe dashboard, ca înainte —
    degradare grațioasă, nu buton mort.
    """
    from app.services import stripe_config
    return bool(stripe_config.is_payment_configured()
                and stripe_config.price_id_for_tier(tier))


def cta_label(tier: str) -> str:
    """Eticheta butonului de upgrade pt `tier` — checkout dacă se poate, altfel dashboard."""
    return f"💳 Activează {tier}" if checkout_disponibil(tier) else CTA_DASHBOARD


def _tier_de_activat(feature: str, min_tier: str = None) -> str:
    """
    Tier-ul pe care userul trebuie să-l ia. Din FEATURES dacă feature-ul e cunoscut;
    altfel `min_tier` (cel cerut de gardian), altfel PRO. Sursă unică pt text ȘI buton
    — altfel mesajul ar putea spune PRO și butonul ar duce la START.
    """
    f = FEATURES.get(feature)
    if f:
        return f["tier"]
    return min_tier or sub.PRO


def upgrade_text(feature: str, user=None, now=None, min_tier: str = None) -> str:
    """
    Mesajul de upgrade pentru un feature blocat. Explică CE e blocat, CE câștigi și
    UNDE se activează. Fără alarmă, fără reproș — invitație, nu perete.
    """
    f = FEATURES.get(feature)
    tier = _tier_de_activat(feature, min_tier)
    if not f:
        label, beneficiu = "Funcția asta", "îți automatizează partea de contabilitate"
    else:
        label, beneficiu = f["label"], f["beneficiu"]

    eticheta = cta_label(tier)
    if checkout_disponibil(tier):
        cta = f"Apasă *{eticheta}* — te duc direct la plata securizată, pe Stripe."
    else:
        cta = f"Apasă *{eticheta}* pentru a activa {tier}."

    linii = [
        f"💡 *{label}* face parte din planul {tier}.",
        "",
        f"În {tier}, Coniar {beneficiu}.",
        "",
        cta,
    ]
    t = trial_line(user, now=now)
    if t:
        linii += ["", t]
    return "\n".join(linii)


def upgrade_markup(tier: str = None, dashboard_url: str = None):
    """
    Butonul de sub mesajul de upgrade.

    Brick 2b: dacă plata e configurată pentru `tier`, butonul declanșează checkout-ul
    pentru ACEL tier (callback `upgrade|TIER` → botul creează sesiunea Stripe și
    răspunde cu link-ul de plată). Nu punem URL-ul de plată direct aici: sesiunea
    Stripe expiră și ar însemna un apel de rețea la fiecare mesaj de gating, inclusiv
    pentru userii care nu apasă niciodată.

    Fără chei/price (sau fără tier) → butonul vechi „Deschide Dashboard", neschimbat.

    Import telegram LAZY — gating.py rămâne importabil și din contextul web (Flask).
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    if tier and checkout_disponibil(tier):
        return InlineKeyboardMarkup([[
            InlineKeyboardButton(cta_label(tier), callback_data=f"upgrade|{tier}")
        ]])
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(CTA_DASHBOARD,
                             web_app=WebAppInfo(url=dashboard_url or DASHBOARD_URL))
    ]])


def require_tier_bot(user_id: int, min_tier: str, feature: str = None):
    """
    Gardianul de tier pentru bot. Oglindește șablonul owner-only (verifică → dacă nu,
    răspunde și NU execută), dar întoarce payload-ul în loc să-l trimită — apelantul
    decide cum îl livrează (`reply_text` la comenzi, `edit_message_text` la callback).

    Args:
        user_id: userul din `ensure_user` (dă doar id-ul, nu obiectul User).
        min_tier: tier-ul minim cerut (sub.START / sub.PRO / sub.MAX).
        feature: cheia din FEATURES pentru copy (opțional; fără ea → text generic).

    Returns:
        (ok, text, markup):
          ok=True  → apelantul continuă normal (text/markup = None)
          ok=False → apelantul trimite text+markup și SE OPREȘTE (feature-ul NU rulează)

    Defensiv: user negăsit / eroare DB → poarta rămâne închisă (nu deschidem din greșeală).
    """
    if user_has_feature(user_id, min_tier):
        return True, None, None
    # Același tier pentru text ȘI buton (2b): mesajul numește planul, butonul duce
    # exact la checkout-ul lui — nu pot diverge.
    tier = _tier_de_activat(feature, min_tier)
    return (False,
            upgrade_text(feature, user=_load_user(user_id), min_tier=min_tier),
            upgrade_markup(tier))


# ══════════════════════════════════════════════════════════════
# 4. Teaser-ul armei secrete — cârligul de aur (§1.8)
# ══════════════════════════════════════════════════════════════
# Regula: FREE află CĂ există o nepotrivire și CÂT de mare e (asta e valoarea „Radar",
# și e onest — nu-l lăsăm orb într-o problemă reală), dar NU află ce anume n-a mers
# și nici cum se rezolvă. Ton liniștitor: „am observat", „posibilă" — nu „ai greșit".
# NU e black-box (spune suma) și nu e gratis (ascunde rezolvarea).

def teaser_reconciliere(dif, user=None, now=None) -> str:
    """
    Teaser pentru o discrepanță de SUMĂ (axa brut↔declarat și axa bancară).
    `dif` = diferența semnată; afișăm mărimea ei, nu semnul (semnul ar fi deja un
    indiciu de cauză). ZERO cauze, ZERO pași — alea sunt în PRO.
    """
    linii = [
        f"🔎 Am observat o posibilă nepotrivire între veniturile tale Bolt și ce ai "
        f"declarat — o diferență de ~{abs(dif):.2f} lei.",
        "",
        "Reconcilierea completă (unde vezi exact ce nu se potrivește și cum o rezolvi "
        "înainte de un control ANAF) e în planul PRO.",
    ]
    t = trial_line(user, now=now)
    if t:
        linii += ["", t]
    return "\n".join(linii)


def teaser_prezenta(n_luni: int, user=None, now=None) -> str:
    """
    Teaser pentru axa de PREZENȚĂ (luni cu Bolt în extras dar nesincronizate).
    Spune CÂTE luni sunt, dar nu le enumeră și nu dă comanda de sincronizare —
    sincronizarea Bolt e oricum din planul START, deci n-ar avea ce face cu ea.
    """
    luna_txt = "lună" if n_luni == 1 else "luni"
    linii = [
        "───────────────",
        f"🔎 *Verificare venit Bolt*",
        f"Văd încasări Bolt în extras pentru {n_luni} {luna_txt} care nu apar încă "
        f"sincronizate în Coniar.",
        "",
        "Sincronizarea automată a curselor din Bolt (ca veniturile să fie complete "
        "fără muncă de mână) e în planul START.",
    ]
    t = trial_line(user, now=now)
    if t:
        linii += ["", t]
    return "\n".join(linii)
