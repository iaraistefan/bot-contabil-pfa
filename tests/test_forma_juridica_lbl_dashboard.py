"""
Gardian: WIZ_FORMA_LBL (dashboard.html) acoperă tot enum-ul FormaJuridica.

Lista formelor juridice trăiește în TREI locuri: enum-ul `FormaJuridica`
(app/domain/fiscal_profile.py), `FORME_JURIDICE` (app/services/onboarding.py) și
`WIZ_FORMA_LBL` din JS-ul wizardului (dashboard.html). Testul ăsta NU elimină
duplicarea — elimină TĂCEREA: dacă apare o a șaptea formă în enum și nimeni nu o
adaugă în JS, wizardul o afișează ca pe un cod brut („SRL_HOLDING") în loc de
etichetă, fără ca nimic să se plângă. Endpoint-ul care ar unifica cele trei liste
rămâne pentru când lista se mai mișcă.

Lista așteptată se DERIVĂ din enum, nu se scrie literal — un gardian cu lista
scrisă de mână ar apăra lista veche și ar pica exact pe cine adaugă forma nouă
corect (aceeași greșeală ca o ancoră „6" în loc de derivată din sursă).

Tehnica (citit dashboard.html ca text) e cea deja folosită în repo — suita nu
execută JS-ul din template, deci verificarea se face pe textul lui.
"""

import re
from pathlib import Path

from app.domain.fiscal_profile import FormaJuridica

_HTML = (Path(__file__).resolve().parent.parent
         / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")


def _wiz_forma_coduri():
    """Codurile (cheile) declarate în obiectul JS WIZ_FORMA_LBL."""
    m = re.search(r"const\s+WIZ_FORMA_LBL\s*=\s*\{([\s\S]*?)\}\s*;", _HTML)
    assert m, "WIZ_FORMA_LBL negăsit în dashboard.html"
    # scoatem valorile (string-uri) ca virgulele/`:`-urile din ele să nu treacă drept chei
    corp = re.sub(r'"[^"]*"|\'[^\']*\'', '""', m.group(1))
    return {k for k in re.findall(r"(?:^|,)\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", corp)}


def test_toate_formele_din_enum_au_eticheta_in_dashboard():
    coduri_js = _wiz_forma_coduri()
    for forma in FormaJuridica:
        assert forma.value in coduri_js, (
            f"forma {forma.value} există în enum-ul FormaJuridica dar lipsește "
            f"din WIZ_FORMA_LBL din dashboard.html"
        )


def test_nicio_eticheta_orfana_in_dashboard():
    # reversul: o cheie în JS care nu există în enum = cod mort sau typo
    coduri_enum = {f.value for f in FormaJuridica}
    orfane = _wiz_forma_coduri() - coduri_enum
    assert not orfane, (
        f"WIZ_FORMA_LBL din dashboard.html conține coduri inexistente în enum-ul "
        f"FormaJuridica: {sorted(orfane)}"
    )
