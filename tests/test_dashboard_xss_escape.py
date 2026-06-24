"""
Escape XSS robust în dashboard (fix securitate #3-A).

Datele user/AI (counterparty, label, marca mașinii etc.) sunt injectate în innerHTML.
`escHtml()` trebuie să neutralizeze HTML ȘI atribute. Testăm COMPORTAMENTUL real al
funcției — o extragem din template și o rulăm prin node pe payload-uri — nu doar prezența
ei (testele „string-presence" pot da false-positive pe logică stricată).
"""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

_HTML = (Path(__file__).resolve().parent.parent
         / "app" / "http" / "templates" / "dashboard.html")

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node indisponibil — test escape comportamental doar cu node")


def _extract_eschtml():
    html = _HTML.read_text(encoding="utf-8")
    # one-liner → captăm până la finalul liniei (replace-urile conțin ';' în "&amp;" etc.,
    # deci un .*?; non-greedy ar trunchia funcția)
    m = re.search(r"const escHtml\s*=.*", html)
    assert m, "escHtml nu e definit pe o singură linie în dashboard.html"
    return m.group(0)


def _run_esc(inputs):
    """Rulează escHtml REAL (extras din template) pe inputuri, întoarce outputurile."""
    src = _extract_eschtml()
    script = src + f"\nconsole.log(JSON.stringify(({json.dumps(inputs)}).map(escHtml)));"
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as f:
        f.write(script)
        path = f.name
    try:
        r = subprocess.run(["node", path], capture_output=True, text=True)
    finally:
        Path(path).unlink(missing_ok=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_escapeaza_tag_img_onerror():
    [out] = _run_esc(["<img src=x onerror=alert(1)>"])
    assert "<" not in out and ">" not in out          # niciun tag executabil
    assert "&lt;img" in out and "&gt;" in out


def test_breakout_atribut_ghilimele_duble():
    # cazul urât :2416 — interpolare în value="..."
    [out] = _run_esc(['" onmouseover="alert(1)'])
    assert '"' not in out
    assert "&quot;" in out


def test_escapeaza_apostrof_si_slash():
    [out] = _run_esc(["' </script> /path"])
    assert "'" not in out and "&#39;" in out
    assert "/" not in out and "&#47;" in out
    assert "<" not in out


def test_null_si_number_fara_crash():
    out = _run_esc([None, 12345])
    assert out[0] == ""                # null/undefined → string gol
    assert out[1] == "12345"           # number → text, neschimbat


def test_amp_escapat_primul_fara_dubla_escapare():
    [out] = _run_esc(["a & b < c"])
    assert out == "a &amp; b &lt; c"   # & escapat ÎNTÂI, fără &amp;lt;


def test_sinks_untrusted_trec_prin_eschtml():
    """Secundar: câmpurile user/AI cheie sunt înfășurate în escHtml înainte de innerHTML."""
    html = _HTML.read_text(encoding="utf-8")
    for camp in ["t.counterparty", "i.label", "v.marca_model",
                 "d.platforma", "d.tip"]:
        assert f"escHtml({camp}" in html, \
            f"{camp} nu e trecut prin escHtml înainte de innerHTML"
