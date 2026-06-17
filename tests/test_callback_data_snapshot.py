"""
GARDIAN zero-drift `callback_data` (modernizare butoane — faza UI).

Regula de aur a modernizării: schimbăm DOAR `text=` al butoanelor (diacritice,
lexic uniform), NICIODATĂ `callback_data` (ar rupe rutarea din handle_callback_query).

Acest test e GARDIANUL: extrage TOȚI literalii `callback_data=` din fișierele cu
keyboard-uri și-i compară cu un snapshot ÎNGHEȚAT. Dacă din greșeală se schimbă un
callback_data în loc de text, testul pică imediat.

În plus: butoanele REPLY-MENU (`BTN_*`) sunt rutate prin TEXT (matcher = `if text ==
BTN_RAPORT`) → textul lor E identificatorul; un snapshot separat le îngheață.
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

_FILES = [
    "bot_contabil.py",
    "app/services/bank_tax_ui.py",
    "app/services/bank_import_ui.py",
    "app/integrations/bolt_sync.py",
    "app/services/onboarding.py",
    "app/services/ghid_ui.py",
    "app/services/confirmare.py",
    "app/services/vehicule.py",
    "app/services/reminder_ui.py",
    "app/services/plata_fiscala.py",
    "app/services/foaie_parcurs.py",
    "app/services/declaratie_unica_ui.py",
]

# Prinde "..." și f"..." (prefixul f e în afara grupului de ghilimele).
_PAT = re.compile(r"callback_data\s*=\s*f?([\"'])(.*?)\1")


def _extract_callbacks():
    cbs = set()
    for f in _FILES:
        txt = (_ROOT / f).read_text(encoding="utf-8")
        for m in _PAT.finditer(txt):
            cbs.add(m.group(2))
    return cbs


# Snapshot ÎNGHEȚAT (109 literali; +tvadecl = buton-poartă ecran TVA & Declarații;
# +onb|nerezident = captare regim nerezident D100, fiscal #3 sub-pas E;
# +onb|platforme = gate platforme Bolt/Uber, Uber sub-pas C;
# +ghid|view / ghid|list / ghid|all = ghid de obligații navigabil + toggle personalizat/toate (Ghid 2+3)).
EXPECTED_CALLBACKS = {
    "alerts|history", "alerts|run",
    "bankpost|cancel", "bankpost|cat|{idx}|{key}", "bankpost|dec|{idx}|biz",
    "bankpost|dec|{idx}|pers", "bankpost|dec|{idx}|skip", "bankpost|start",
    "bankpost|verif",
    "banktax|cancel", "banktax|confirm", "banktax|start",
    "boltsync|cancel", "boltsync|confirm|{year}|{month}",
    "coduri|del_cnp", "coduri|del_tva", "coduri|set_cnp", "coduri|set_tva",
    "coduri|skip",
    "confirm|back", "confirm|cancel", "confirm|edit", "confirm|field|{idx}|{field_key}",
    "confirm|item|{i}", "confirm|save", "confirm|tip|{idx}|CHELTUIALA",
    "confirm|tip|{idx}|FACTURA_COMISION", "confirm|tip|{idx}|VENIT",
    "d100|{year}|{month}", "d301|{year}|{month}", "d390|{year}|{month}",
    "tvadecl|{year}|{month}",
    "du|an|{a}", "du|auto|{an}", "du|calc|asig", "du|calc|noasig", "du|manual|{an}",
    "ghid|all", "ghid|list", "ghid|view|{key}",
    "nav|close", "nav|noop",
    "onb|activity|{a['code']}", "onb|cancel", "onb|confirm_all", "onb|cui_retry",
    "onb|cui_save_raw", "onb|done", "onb|finalize|restart", "onb|finalize|yes",
    "onb|fix|activity", "onb|fix|back", "onb|fix|forma", "onb|fix|impunere",
    "onb|fix|menu", "onb|fix|tva", "onb|forma|{f['code']}", "onb|impunere|{r['code']}",
    "onb|nerezident|{r['code']}", "onb|platforme|{p['code']}",
    "onb|skip|{skip_target}", "onb|tva|{r['code']}",
    "parcurs|delok|{trip_id}", "parcurs|excel|{year}|{month}",
    "parcurs|jurnal|{year}|{month}", "parcurs|jurnal|{y}|{m}", "parcurs|luni",
    "parcurs|status", "parcurs|wiz_cancel", "parcurs|wiz_start", "parcurs|wiz_stop",
    "plata|back", "plata|obl|{cod}",
    "plata|paid|{obligation_code}|{year}|{month}",
    "plata|period|{obligation_code}|{year}|{month}", "plata|status",
    "registru|type|annual", "registru|type|monthly",
    "reminder|advance", "reminder|hour", "reminder|menu", "reminder|set_advance|{d}",
    "reminder|set_hour|{h}", "reminder|test", "reminder|toggle",
    "settings|alerts", "settings|export", "settings|menu", "settings|profil",
    "settings|reminder", "settings|reset|ask", "settings|reset|do",
    "vehicul|add", "vehicul|cancel", "vehicul|delok|{vehicul_id}",
    "vehicul|del|{vehicul_id}", "vehicul|edit|{vehicul_id}",
    "vehicul|ef|{vehicul_id}|consum", "vehicul|ef|{vehicul_id}|marca",
    "vehicul|ef|{vehicul_id}|nr", "vehicul|ef|{vehicul_id}|tip", "vehicul|menu",
    "vehicul|setc|{c:g}", "vehicul|tip|{t}", "vehicul|view|{v.id}",
    "vehicul|view|{vehicul_id}",
    "{action}|back", "{action}|month|{year}|{month}", "{action}|year|{y}",
}


def test_callback_data_zero_drift():
    """Niciun callback_data atins de modernizarea de text."""
    current = _extract_callbacks()
    missing = EXPECTED_CALLBACKS - current     # callback_data dispărut/redenumit
    added = current - EXPECTED_CALLBACKS        # callback_data nou/modificat
    assert not missing, f"callback_data DISPĂRUTE (rutare ruptă?): {sorted(missing)}"
    assert not added, f"callback_data NOI/MODIFICATE (atins din greșeală?): {sorted(added)}"


# Reply-menu (text-routed) — textul E identificatorul; matcher-ul se rupe la schimbare.
EXPECTED_BTN_MENU = {
    "BTN_RAPORT": "📊 Raport",
    "BTN_REGISTRU": "📂 Registru",
    "BTN_DASHBOARD": "🖥️ Dashboard",
    "BTN_CALENDAR": "📋 Calendar Fiscal",
    "BTN_PLATA": "💳 Plată Fiscală",
    "BTN_PARCURS": "🛣️ Foaie parcurs",
    "BTN_DU": "🧮 Declarația Unică",
    "BTN_CHELTUIELI": "💸 Cheltuieli",
    "BTN_SETARI": "⚙️ Setări",
    "BTN_AJUTOR": "🆘 Ajutor",
}


def test_btn_menu_text_neschimbat():
    """Butoanele reply-menu (rutate prin text) rămân NEATINSE → matcher intact."""
    import bot_contabil
    for name, val in EXPECTED_BTN_MENU.items():
        assert getattr(bot_contabil, name) == val, f"{name} schimbat → matcher rupt!"
