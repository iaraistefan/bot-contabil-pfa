"""
Configurarea Oblio — facturare + e-Factura (§1.7 Felia 3, Brick 3a).

Oglindește `stripe_config.py`: singurul loc care traduce env-ul în răspunsul „se
poate factura?". ZERO apeluri la Oblio aici — doar citire de configurare. SDK-ul și
emiterea intră în 3b.

DE CE MODUL SEPARAT, nu în config.py: `Settings` e o declarație de câmpuri; decizia
„avem tot ce trebuie ca să emitem" e logică de domeniu și se testează ca atare.

Degradare grațioasă: fără configurare, plata și abonamentul merg normal — doar
factura nu se emite. NU legăm încasarea de facturare (banii intră oricum; factura
se poate relua, vezi scheduler-ul existent).
"""

from typing import Tuple

from config import settings


# Câmpurile fără de care Oblio nu poate emite nimic. `oblio_secret` e SECRET —
# apare aici doar ca nume, niciodată în loguri sau în răspunsuri.
CAMPURI_NECESARE = (
    "oblio_email",
    "oblio_secret",
    "oblio_cif",
    "oblio_serie_factura",
)


def _lipsa() -> Tuple[str, ...]:
    """
    Câmpurile neconfigurate, citite din `settings` LA APEL (nu la import): env-ul se
    poate schimba între procese/teste, iar o listă înghețată la import ar minți —
    același raționament ca `_price_map()` din Stripe 2a.
    """
    return tuple(c for c in CAMPURI_NECESARE if not getattr(settings, c, None))


def is_oblio_configured() -> bool:
    """
    Putem emite facturi? Are nevoie de TOATE cele patru (cont + token + CIF furnizor
    + serie). Fals → 3b nu încearcă emiterea și logează motivul, fără să crape.
    """
    return not _lipsa()


def campuri_lipsa() -> Tuple[str, ...]:
    """Ce anume lipsește — pentru un log util la deploy („de ce nu se emit facturi?")."""
    return _lipsa()
