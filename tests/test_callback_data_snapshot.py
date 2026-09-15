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
# +ghid|view / ghid|list / ghid|all = ghid de obligații navigabil + toggle personalizat/toate (Ghid 2+3);
# +vehicul|regim|{r} / regim|{REGIM_UTILIZARE_MIXT} / regimok / ef|regim = gardian UI regim utilizare
#   (MIXT/EXCLUSIV) pe vehicul, editare + gardian confirmare uz exclusiv;
# +d212|{year - 1} = Declaratia Unica ANUALA (wiring D212). Anul e cel al
#   VENITURILOR, adica anul incheiat — de aici `- 1`. Buton NOU, `missing` gol;
# +confirm|capex|{idx}|da / |nu = gardian achiziție vehicul — peste pragul de sumă botul
#   ÎNTREABĂ ce e documentul în loc să-l clasifice automat. Butoane NOI, nu redenumiri:
#   niciun callback_data existent nu s-a schimbat (`missing` a rămas gol);
# +onb|certdata|ok / |edit / |skip = confirmarea datei de pe certificatul ONRC
#   (nr_doc_autoriz + data_doc_autoriz, D212). Tot butoane NOI: `missing` gol.
#   Data e pre-completată din ANAF, dar NU se scrie tăcut — de aici cele trei
#   ieșiri: confirmă, corectează de pe certificat, sau amână;
# +coduri|set_certdata = aceeași dată, completată DUPĂ onboarding, din
#   /coduri_fiscale (ecranul care ține deja CNP-ul „folosit pe D212"). Fără el,
#   cine amâna data la configurare rămânea fără drum înapoi, deși mesajul de
#   refuz al generatorului D212 îl trimite „în profil". Buton NOU: `missing` gol.
# +coduri|set_certnr = NUMĂRUL certificatului, tastat de mână. Butonul lipsea
#   fiindcă numărul „se ia automat din ANAF" — asumpție dezmințită în producție:
#   userul 1 îl avea gol (ANAF nu-l întorsese), D212 refuza, și niciun ecran nu
#   putea repara. Automatizarea rămâne; asta e calea de mână de lângă ea.
# +coduri|anaf_refresh = re-cheamă lookup-ul ANAF și umple GOLURILE din profil
#   (inclusiv câmpuri apărute din migrări ulterioare contului). Nu rescrie ce e
#   completat — diferențele se raportează. Ambele butoane NOI: `missing` gol.
EXPECTED_CALLBACKS = {
    "alerts|history", "alerts|run",
    "bankpost|cancel", "bankpost|cat|{idx}|{key}", "bankpost|dec|{idx}|biz",
    "bankpost|dec|{idx}|pers", "bankpost|dec|{idx}|skip", "bankpost|start",
    "bankpost|verif",
    "banktax|cancel", "banktax|confirm", "banktax|start",
    "boltsync|cancel", "boltsync|confirm|{year}|{month}",
    "coduri|anaf_refresh",
    "coduri|del_cnp", "coduri|del_tva", "coduri|set_certdata", "coduri|set_certnr",
    "coduri|set_cnp",
    "d212|{year - 1}",
    "coduri|set_tva",
    "coduri|skip",
    "confirm|back", "confirm|cancel", "confirm|capex|{idx}|da", "confirm|capex|{idx}|nu",
    "confirm|edit", "confirm|field|{idx}|{field_key}",
    "confirm|item|{i}", "confirm|save", "confirm|tip|{idx}|CHELTUIALA",
    # +confirm|save|{sfid} / |{source_file_id} = cheia LOTULUI în callback, ca
    #   butonul să știe CE confirmă după ce procesul a repornit (extracția e acum
    #   persistată ca lot „needs_review"). `confirm|save` RĂMÂNE emis — e calea de
    #   intrare prin TEXT, care n-are fișier-sursă, deci nici lot. `missing` gol:
    #   nicio rutare existentă nu s-a atins.
    #   DE CE cheie și nu „cel mai recent lot pending": omul fotografiază trei
    #   bonuri unul după altul, primește trei carduri, apoi apasă „Confirmă" pe
    #   PRIMUL. Cardul arată cifre precise — pentru el nu e ambiguu nicio clipă —
    #   dar „ultimul lot" ar posta datele celei de-a treia poze. A confirma altceva
    #   decât ce scrie pe ecran e eroare fiscală. În plus, mesajele Telegram trăiesc
    #   la nesfârșit: un card poate fi apăsat peste luni. Forma scurtă fără lot viu
    #   se REFUZĂ, cu mesaj și cu ieșire (/neterminate).
    #   Cele două literale sunt scrise ca literale (nu printr-o variabilă) tocmai ca
    #   gardianul ăsta să le vadă.
    #   Ambele locuri care-l emit (cardul de confirmare și lista /neterminate)
    #   folosesc aceeași variabilă `sfid` → un singur literal în snapshot.
    "confirm|save|{sfid}",
    "confirm|tip|{idx}|FACTURA_COMISION", "confirm|tip|{idx}|VENIT",
    "d100|{year}|{month}", "d301|{year}|{month}", "d390|{year}|{month}",
    "d207|{year}",  # fisa D207 ANUALA (fara luna) — wire-up buton D207
    "tvadecl|{year}|{month}",
    "du|an|{a}", "du|auto|{an}", "du|calc|asig", "du|calc|noasig", "du|manual|{an}",
    "ghid|all", "ghid|list", "ghid|view|{key}",
    "nav|close", "nav|noop",
    "onb|activity|{a['code']}", "onb|cancel", "onb|confirm_all", "onb|cui_retry",
    "onb|cui_save_raw", "onb|done", "onb|finalize|restart", "onb|finalize|yes",
    "onb|fix|activity", "onb|fix|back", "onb|fix|forma", "onb|fix|impunere",
    "onb|fix|menu", "onb|fix|tva", "onb|forma|{f['code']}", "onb|impunere|{r['code']}",
    "onb|certdata|edit", "onb|certdata|ok", "onb|certdata|skip",
    "onb|nerezident|{r['code']}", "onb|platforme|{p['code']}",
    "onb|skip|{skip_target}", "onb|tva|{r['code']}",
    "parcurs|delok|{trip_id}", "parcurs|excel|{year}|{month}",
    "parcurs|jurnal|{year}|{month}", "parcurs|jurnal|{y}|{m}", "parcurs|luni",
    "parcurs|status", "parcurs|wiz_cancel", "parcurs|wiz_start", "parcurs|wiz_stop",
    "plata|back", "plata|obl|{cod}",
    # −plata|paid: buton „Marchează plătit" ascuns până Pas 12 (SPV) — nu persista nimic.
    "plata|period|{obligation_code}|{year}|{month}", "plata|status",
    "registru|type|annual", "registru|type|monthly",
    "reminder|advance", "reminder|hour", "reminder|menu", "reminder|set_advance|{d}",
    "reminder|set_hour|{h}", "reminder|test", "reminder|toggle",
    "settings|alerts", "settings|export", "settings|menu", "settings|profil",
    "settings|reminder", "settings|reset|ask", "settings|reset|do",
    "vehicul|add", "vehicul|cancel", "vehicul|delok|{vehicul_id}",
    "vehicul|del|{vehicul_id}", "vehicul|edit|{vehicul_id}",
    "vehicul|ef|{vehicul_id}|consum", "vehicul|ef|{vehicul_id}|marca",
    "vehicul|ef|{vehicul_id}|nr", "vehicul|ef|{vehicul_id}|regim",
    "vehicul|ef|{vehicul_id}|tip", "vehicul|menu",
    "vehicul|regim|{r}", "vehicul|regim|{REGIM_UTILIZARE_MIXT}", "vehicul|regimok",
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


# ============================================================
#   GARDIAN DE FORMĂ: `callback_data=` primește LITERAL, nu o variabilă
# ============================================================
#
# Gardianul de zero-drift de mai sus extrage LITERALI. Un `cb = f"..."` urmat de
# `callback_data=cb` e invizibil pentru el — butonul dispare din snapshot fără ca
# nimic să se plângă, iar de-atunci încolo poate fi redenumit liber.
#
# Nu e ipotetic: la persistarea lotului pending, prima variantă a butonului de
# confirmare era exact așa (`save_cb = f"confirm|save|{sfid}" if sfid else
# "confirm|save"`), și a fost rescrisă în două ramuri cu literale TOCMAI ca să rămână
# în raza gardianului. Acolo a ținut o notă scrisă de om. Nota apără o dată; testul
# ăsta apără mereu.
#
# MĂSURAT la scriere (15.09.2026): 182 de apeluri `callback_data=`, ZERO pe variabilă.
# Gaura se închide cât e încă teoretică — adică fără nicio reparație de făcut.

_CB_ARG = re.compile(r"callback_data\s*=\s*([^,\)\n]+)")
_E_LITERAL = re.compile(r"^f?[\"'].*[\"']$", re.DOTALL)

# Apeluri care primesc `callback_data=` fără să fie BUTOANE. Allowlist pe apel, nu pe
# fișier: `monitoring.capture_exception(e, callback_data=data)` trimite string-ul la
# Sentry ca etichetă de diagnostic. Nu randează nimic, deci n-are ce păzi gardianul.
_APELURI_NEBUTON = ("capture_exception(",)


def _fara_comentarii(txt: str) -> str:
    """Scoate comentariile, păstrând numerotarea liniilor.

    Necesar fiindcă notele DESPRE gardian conțin `callback_data=` în proză — iar un
    gardian care se declanșează pe propria documentație e un gardian pe care îl
    dezarmezi în a doua zi.
    """
    iesire = []
    for linie in txt.split("\n"):
        taiat = linie.split("#", 1)[0] if "#" in linie else linie
        iesire.append(taiat)
    return "\n".join(iesire)


def test_callback_data_nu_primeste_variabile():
    vinovati = []
    for f in _FILES:
        txt = _fara_comentarii((_ROOT / f).read_text(encoding="utf-8"))
        for m in _CB_ARG.finditer(txt):
            arg = m.group(1).strip()
            if _E_LITERAL.match(arg):
                continue
            inceput_linie = txt.rfind("\n", 0, m.start()) + 1
            context = txt[max(0, inceput_linie - 200):m.start()]
            if any(a in context for a in _APELURI_NEBUTON):
                continue
            nr = txt[:m.start()].count("\n") + 1
            vinovati.append(f"{f}:{nr} → callback_data={arg}")

    assert not vinovati, (
        "`callback_data=` primește o VARIABILĂ:\n  " + "\n  ".join(vinovati)
        + "\n\nGardianul de zero-drift extrage literali — o variabilă face butonul "
        "INVIZIBIL pentru el, iar de-atunci poate fi redenumit fără ca nimic să "
        "cadă. Scrie literalul la fața locului; dacă ai două forme, scrie DOUĂ "
        "ramuri (vezi butonul de confirmare din app/services/confirmare.py).\n"
        "Dacă apelul nu e un buton, adaugă-l în _APELURI_NEBUTON, cu motiv."
    )


def test_gardianul_de_forma_chiar_vede_apelurile():
    """
    Ancoră. Dacă `_CB_ARG` nu mai prinde nimic (forma apelurilor s-a schimbat),
    testul de mai sus ar trece pe vid — verde, și inutil.
    """
    total = sum(
        len(_CB_ARG.findall(_fara_comentarii((_ROOT / f).read_text(encoding="utf-8"))))
        for f in _FILES
    )
    assert total >= 150, f"gardianul de formă vede doar {total} apeluri `callback_data=`"
