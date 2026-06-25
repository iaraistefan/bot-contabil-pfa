"""
Decizia TVA — vat_engine._apply_vat_rules + analyze() (audit #5 / I3, ultima piesă).

analyze() era testat (la #2) DOAR pe detected_vat_id; logica de DECIZIE (treatment + ce
declarații se declanșează: D300/D301/D390) RULA dar era NEASERTATĂ — gaura cea mai
consecințială fiscal (decide CE se depune la ANAF). Logica e CORECTĂ; aici o dovedim.
Dacă o regresie schimbă o decizie (ex. Bolt nu mai declanșează D390), testul cade.

Constatare (caracterizată, fix SEPARAT după research la sursă): furnizorii non-EU în afara
GB/CH/NO (ex. US — AWS/OpenAI) → UNKNOWN, nu IMPORT. Vezi test_caracterizare_us_unknown.
"""

from app.domain import vat_engine
from app.domain.vat_engine import VATTreatment, CountryGroup
from app.domain.tax_rules import BOLT_VAT_ID


def _rules(country_group, *, country_code="XX", user_is_vat_payer=False):
    return vat_engine._apply_vat_rules(
        country_code=country_code, country_group=country_group,
        detected_vat_id=None, detected_brand=None, confidence=90,
        user_is_vat_payer=user_is_vat_payer, transaction_type="EXPENSE",
    )


# ── A. Direct pe _apply_vat_rules — cele 4 branch-uri ────────

def test_romania_standard_d300_dupa_platitor():
    plat = _rules(CountryGroup.ROMANIA, country_code="RO", user_is_vat_payer=True)
    assert plat.treatment == VATTreatment.STANDARD_21
    assert plat.requires_d300 is True
    assert plat.requires_d301 is False and plat.requires_d390 is False

    neplat = _rules(CountryGroup.ROMANIA, country_code="RO", user_is_vat_payer=False)
    assert neplat.treatment == VATTreatment.STANDARD_21
    assert neplat.requires_d300 is False        # neplătitor → fără D300


def test_eu_reverse_charge_declanseaza_d301_d390():
    d = _rules(CountryGroup.EU, country_code="EE")
    assert d.treatment == VATTreatment.REVERSE_CHARGE
    assert d.requires_d301 is True
    assert d.requires_d390 is True              # VIES (recapitulativă)
    assert d.requires_d300 is False


def test_non_eu_import_d301_fara_d390():
    d = _rules(CountryGroup.NON_EU, country_code="GB")
    assert d.treatment == VATTreatment.IMPORT_NON_EU
    assert d.requires_d301 is True
    assert d.requires_d390 is False             # non-EU NU intră în VIES


def test_unknown_nu_presupune_nimic():
    d = _rules(CountryGroup.UNKNOWN, country_code="US")
    assert d.treatment == VATTreatment.UNKNOWN
    assert d.requires_d301 is False
    assert d.requires_d390 is False
    assert d.requires_d300 is False             # nu declanșează declarații pe presupunere


# ── B. End-to-end prin analyze() — clasificare → reguli ─────

def test_analyze_bolt_eu_reverse_charge_d390():
    d = vat_engine.analyze(platforma="Bolt Operations OU")
    assert d.country_group == CountryGroup.EU
    assert d.treatment == VATTreatment.REVERSE_CHARGE
    assert d.requires_d390 is True and d.requires_d301 is True
    assert d.detected_vat_id == BOLT_VAT_ID      # sursă unică (PR #25)


def test_analyze_gb_non_eu_import():
    d = vat_engine.analyze(platforma="Some UK Ltd", vat_id="GB123456789")
    assert d.country_group == CountryGroup.NON_EU
    assert d.treatment == VATTreatment.IMPORT_NON_EU
    assert d.requires_d301 is True and d.requires_d390 is False


def test_analyze_ro_standard_d300():
    d = vat_engine.analyze(platforma="OMV Petrom", vat_id="RO12345678",
                           user_is_vat_payer=True)
    assert d.country_group == CountryGroup.ROMANIA
    assert d.treatment == VATTreatment.STANDARD_21
    assert d.requires_d300 is True
    assert d.requires_d390 is False and d.requires_d301 is False


def test_us_import_non_eu_d301_fara_d390():
    # FIX (increment fiscal, research la sursă art. 278/307): furnizor US (non-UE) servicii
    # → IMPORT, loc prestării RO → taxare inversă + D301, FĂRĂ D390 (D390 = doar intracom).
    d = vat_engine.analyze(platforma="OpenAI")
    assert d.country_code == "US"
    assert d.country_group == CountryGroup.NON_EU
    assert d.treatment == VATTreatment.IMPORT_NON_EU
    assert d.requires_d301 is True
    assert d.requires_d390 is False
    # nota defensivă despre regimul special (art. 307 alin. 6)
    assert "regim special" in d.explanation.lower()


def test_sg_singapore_import_non_eu():
    # SG (Singapore, non-UE) — aceeași regulă fiscală ca US (art. 278 pt orice non-UE)
    d = vat_engine.analyze(platforma="Moonshot AI")
    assert d.country_code == "SG"
    assert d.country_group == CountryGroup.NON_EU
    assert d.treatment == VATTreatment.IMPORT_NON_EU
    assert d.requires_d301 is True and d.requires_d390 is False


def test_ue_neatins_de_fix_non_eu():
    # REGRESIE 0 pe UE: Bolt (EE) rămâne EU + reverse-charge + D390 (fixul non-UE NU atinge UE)
    d = vat_engine.analyze(platforma="Bolt Operations OU")
    assert d.country_group == CountryGroup.EU
    assert d.treatment == VATTreatment.REVERSE_CHARGE
    assert d.requires_d390 is True
