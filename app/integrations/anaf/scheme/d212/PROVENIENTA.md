# Schemele oficiale ANAF pentru D212

Fișiere **nemodificate**, exact cum le publică ANAF. Sunt contractul contra căruia
validăm XML-ul generat de `app/integrations/anaf/d212_generator.py`.

## Sursa

Arhiva de documentație tehnică a formularului D212, de pe portalul de formulare ANAF:

- **https://www.anaf.ro/declaratii/doc/d212.zip**
  (link din <https://www.anaf.ro/declaratii/>, secțiunea „Declarații persoane fizice")

Descărcată la **10 august 2026**. Fișierele de mai jos sunt extrase din acea arhivă,
fără nicio modificare.

Formularul corespunzător e cel aprobat prin **OpANAF nr. 2736/2025** — versiunea cu
formular web (<https://www.anaf.ro/declaratii/duf>), care a înlocuit PDF-ul inteligent.
Namespace: `mfp:anaf:dgti:d212:declaratie:v11`.

## Conținut și amprente

| fișier | octeți | SHA-256 |
|---|---|---|
| `d212_schema.xsd` | 90359 | `7eea6884a176a78fcec48a8cf0a522e6a3e891569c637c033feefcf79ab8272e` |
| `D212.sch` | 1802 | `a93baa99685cfd056544595581774a74e79ef86aae658990ae8e00e51f7e5b1e` |
| `nomenclator_caen.xml` | 66587 | `53ecf647e48a31141b72d375c4675b37717ad60bf49d63b2984431c7a4a279f3` |
| `syntax/d212-syntax.sch` | 1931 | `c5a27fbb909d10c48d8c7095efd03dc42a1791108a92df29a806200d3e685e78` |
| `codes/d212-codes.sch` | 24053 | `48fdd1f5396b5cce8c38fa232e709b300dc46ba9f3054cb6999d79b460658ae2` |
| `business/d212-business.sch` | 42685 | `9be098e4879eaca4efc94d77c97f136453fe5017e456de1a3b2059836030b632` |
| `business/d212-business-2.sch` | 48677 | `ad60876c971c300c68ab32692bb6c2040959eb64af2015c78308e5353707a21f` |
| `business/d212-business-3.sch` | 84621 | `ac3bd904a2f77b65e4d6de0b44175761bd7b6f0aa7defe094b2d89275619caee` |
| `business/d212-business-4.sch` | 69528 | `87b03ecf060c36998588f3d13db1df07c0b79841cee8064041f68ee7a68e5aa3` |

Versiunea XSD la momentul descărcării: **v1.0.4 / 08.04.2026** (istoricul e în antetul
fișierului). Pachetul de documentație era `v1.0.8 / 17.04.2026`.

Nu am vendorizat din arhivă: `d212_docTehnica_v1.0.8_17042026.xls` și
`structura_D212_V1.0.8_17042026.pdf` (documentație pentru oameni, nu artefacte
executabile de validare).

## ⚠️ Pachetul e legat de UN SINGUR an fiscal

Nu e o bibliotecă de reguli valabilă oricând. Două reguli fixează anul, literal:

| regulă | fișier | ce impune |
|---|---|---|
| `BR-D212-0006` | `business/d212-business.sch` | `<let name="isValid" value="$an = 2026"/>` — `an_r` **trebuie** să fie 2026 |
| `BR-D212-0023` | `business/d212-business-2.sch` | `<let name="yearExp" value="string($an_r_num - 1)"/>` — datele de activitate (`data_incep`, `data_sf`, `data_suspendare`, …) trebuie să aibă anul `an_r − 1` |

Deci pachetul acesta validează **exclusiv** declarația cu `an_r=2026`, adică
veniturile realizate în **2025**.

### Ce înseamnă `an_r`

Nu anul veniturilor. Formularul are **două** casete de an — capitolul I
„…pentru anul ……" (veniturile) și capitolul II „…care optează pentru plata
contribuției pentru anul ……" (opțiunea CASS) — dar XML-ul are **un singur**
atribut de an. `BR-D212-0023` arată care dintre ele e: datele de desfășurare a
activității din capitolul I trebuie să fie din `an_r − 1`.

**`an_r` = anul capitolului II = anul depunerii. Anul veniturilor e `an_r − 1`
și nu are câmp propriu în XML.**

Eticheta „Anul de raportare" din documentația de structură induce în eroare:
instrucțiunile oficiale folosesc aceeași expresie pentru anul veniturilor.
Nu te lua după ea.

### Anul nu e hardcodat în generator

`d212_generator.anul_de_raportare_acoperit()` îl **citește din
`BR-D212-0006`** la rulare. Când înlocuiești fișierele de aici cu pachetul
pentru anul următor, generatorul se adaptează fără nicio schimbare de cod.

Dacă ANAF reformulează regula astfel încât extragerea să nu mai reușească,
generatorul **se oprește cu `RuntimeError`** — deliberat nu există valoare
implicită. Un fallback tăcut ar face generatorul să pretindă din nou un domeniu
pe care nu-l poate onora, doar că fără să se mai vadă.

## Cum se actualizează

Când ANAF publică o versiune nouă:

1. Descarcă din nou `d212.zip` și înlocuiește fișierele de aici.
2. Actualizează tabelul de mai sus (dimensiuni + SHA-256) și data descărcării.
3. Rulează `py -3.10 -m pytest tests/test_d212_generator.py`. Regulile noi vor cădea
   ca eșecuri Schematron cu id-ul lor (`BR-D212-xxxx`), cu textul explicativ — de acolo
   se vede exact ce câmp mai trebuie completat.
4. Dacă numărul de reguli declanșate crește mult, ridică `PRAG_REGULI` în
   `tests/anaf_schema_validare.py`.
5. Anul acoperit **nu** trebuie schimbat în cod — se citește din `BR-D212-0006`.
   Testele care pinuiesc anul (`test_anul_se_citeste_din_regula_anaf_nu_e_hardcodat`,
   `test_an_r_e_anul_depunerii_nu_al_veniturilor`) vor cădea cu anul nou; e
   semnalul că actualizarea a intrat, nu o regresie.

## Un avertisment despre `D212.sch`

Fișierul conține două căi absolute, pentru serverul ANAF:

```xml
<let name="schema" value="doc('file:///validare/D212/d212_schema.xsd')"/>
<let name="caen"   value="doc('file:///validare/D212/nomenclator_caen.xml')"/>
```

Nu le modificăm aici — fișierul rămâne identic cu originalul, verificabil prin hash.
Rescrierea în căi relative se face pe o copie temporară, la validare
(`tests/anaf_schema_validare.py`). ANAF însuși lasă varianta relativă comentată
deasupra, pentru rulare locală.
