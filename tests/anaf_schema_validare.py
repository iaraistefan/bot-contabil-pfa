"""
Lantul de validare contra schemelor OFICIALE ANAF pentru D212.

Doua niveluri, amandoua pe fisierele publicate de ANAF (vendorizate in
app/integrations/anaf/scheme/d212/, vezi PROVENIENTA.md):

  1. XSD        — d212_schema.xsd, namespace mfp:anaf:dgti:d212:declaratie:v11.
                  Verifica structura si tipurile. Ruleaza pe lxml.
  2. Schematron — D212.sch + syntax/ codes/ business/ (regulile BR-D212-* si
                  CD-D212-*). Sunt scrise cu queryBinding="xslt2", deci lxml NU
                  le poate rula (libxslt e XSLT 1.0). Ruleaza pe SaxonC.

⚠️ PETICUL AXEI DE ATRIBUTE — motivul pentru care exista acest modul:
   Skeleton-ul ISO Schematron genereaza reguli de traversare care coboara doar
   pe axa elementelor: <xsl:apply-templates select="*" mode="M7"/>. Dar regulile
   ANAF sunt scrise majoritar pe context //@* (atribute), fiindca D212 tine
   TOATE datele in atribute. Fara petic, tiparul `codes` intreg (CD-D212-*) si
   jumatate din `business` nu se declanseaza NICIODATA, iar validarea raporteaza
   fericita "VALID" dupa ce a evaluat 6 reguli din ~118. Adica teatru.
   Peticim traversarea la select="*|@*" si verificam prin PRAG_REGULI ca nu am
   pierdut-o pe drum (vezi test_d212_generator.py::test_lantul_chiar_ruleaza).
"""

import os
import re
import shutil
import tempfile

# Numarul de reguli declansate pe un D212 complet, cu peticul aplicat, la data
# scrierii: 118. Pragul e mult sub el ca sa nu fie fragil la actualizari ANAF,
# dar mult peste cele 6 reguli din varianta necarpita — asa ca daca peticul
# dispare, testul cade zgomotos in loc sa treaca in tacere.
PRAG_REGULI = 60

SVRL_NS = "http://purl.oclc.org/dsdl/svrl"

_AICI = os.path.dirname(os.path.abspath(__file__))
SCHEME = os.path.join(_AICI, "..", "app", "integrations", "anaf", "scheme", "d212")
SKELETON = os.path.join(_AICI, "schematron_skeleton")

_validator_compilat = None


def _lxml():
    from lxml import etree
    return etree


def valideaza_xsd(xml: str):
    """Returneaza lista de erori XSD (goala = valid)."""
    etree = _lxml()
    schema = etree.XMLSchema(etree.parse(os.path.join(SCHEME, "d212_schema.xsd")))
    doc = etree.fromstring(xml.encode("utf-8"))
    if schema.validate(doc):
        return []
    return ["%s (linia %s)" % (e.message, e.line) for e in schema.error_log]


def _peticeste_axa_atribute(cale_xsl):
    """Extinde traversarea generata de la `*` la `*|@*`. Vezi nota din capul modulului."""
    txt = open(cale_xsl, encoding="utf-8").read()
    nou, n = re.subn(r'select="\*" mode="(M\d+)"', r'select="*|@*" mode="\1"', txt)
    if n == 0:
        raise RuntimeError(
            "Peticul axei de atribute nu s-a aplicat pe validatorul generat. "
            "Fara el regulile ANAF pe atribute nu se declanseaza si validarea "
            "devine decorativa. Verifica skeleton-ul din tests/schematron_skeleton/."
        )
    open(cale_xsl, "w", encoding="utf-8").write(nou)


def _compileaza():
    """Compileaza Schematron-ul ANAF intr-un XSLT validator. O singura data pe sesiune.

    Lucram intr-un director temporar: D212.sch trebuie modificat (caile doc() sunt
    absolute, `file:///validare/D212/...`, adica pentru serverul ANAF), iar
    validatorul compilat trebuie sa stea langa d212_schema.xsd si
    nomenclator_caen.xml ca doc() relativ sa se rezolve. Fisierele oficiale din
    repo raman NEATINSE — pot fi verificate byte-cu-byte contra ANAF.
    """
    global _validator_compilat
    if _validator_compilat:
        return _validator_compilat

    from saxonche import PySaxonProcessor

    lucru = tempfile.mkdtemp(prefix="d212_schematron_")
    shutil.copytree(SCHEME, lucru, dirs_exist_ok=True)

    sch = os.path.join(lucru, "D212.sch")
    txt = open(sch, encoding="utf-8").read()
    txt = txt.replace("doc('file:///validare/D212/d212_schema.xsd')", "doc('d212_schema.xsd')")
    txt = txt.replace("doc('file:///validare/D212/nomenclator_caen.xml')",
                      "doc('nomenclator_caen.xml')")
    open(sch, "w", encoding="utf-8").write(txt)

    with PySaxonProcessor(license=False) as proc:
        xslt = proc.new_xslt30_processor()
        sursa = sch
        for stil, iesire in [("iso_dsdl_include.xsl", "_pas1.sch"),
                             ("iso_abstract_expand.xsl", "_pas2.sch"),
                             ("iso_svrl_for_xslt2.xsl", "_validator.xsl")]:
            out = os.path.join(lucru, iesire)
            proc_stil = xslt.compile_stylesheet(stylesheet_file=os.path.join(SKELETON, stil))
            proc_stil.transform_to_file(source_file=sursa, output_file=out)
            sursa = out

    _peticeste_axa_atribute(sursa)
    _validator_compilat = sursa
    return sursa


def valideaza_schematron(xml: str):
    """Ruleaza Schematron-ul ANAF. Returneaza (esecuri, numar_reguli_declansate).

    esecuri = lista de dict-uri {id, text} pentru failed-assert / successful-report.
    """
    from saxonche import PySaxonProcessor

    etree = _lxml()
    validator = _compileaza()

    lucru = os.path.dirname(validator)
    tinta = os.path.join(lucru, "_tinta.xml")
    open(tinta, "w", encoding="utf-8").write(xml)

    with PySaxonProcessor(license=False) as proc:
        xslt = proc.new_xslt30_processor()
        executabil = xslt.compile_stylesheet(stylesheet_file=validator)
        svrl = executabil.transform_to_string(source_file=tinta)

    raiz = etree.fromstring(svrl.encode("utf-8"))
    esecuri = []
    for eticheta in ("failed-assert", "successful-report"):
        for nod in raiz.findall(".//{%s}%s" % (SVRL_NS, eticheta)):
            text = " ".join((nod.findtext("{%s}text" % SVRL_NS) or "").split())
            esecuri.append({"id": nod.get("id") or "?", "text": text})
    reguli = len(raiz.findall(".//{%s}fired-rule" % SVRL_NS))
    return esecuri, reguli
