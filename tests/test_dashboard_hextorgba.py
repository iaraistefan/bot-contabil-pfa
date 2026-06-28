"""
Test focalizat — helper-ul JS `hexToRgba` din dashboard.html (CULORI pasa 1).

Stops-urile de gradient ale graficului „venit" derivă acum din token-ul --pos via hexToRgba(),
în loc de literalul rgba(25,198,145,...). Dovada „zero schimbare vizuală": helper-ul TREBUIE
să reproducă EXACT literalele originale, byte cu byte (inclusiv alpha fără zero-de-conducere).

Suita nu execută JS → extragem definiția helper-ului și o rulăm prin `node` (ca gardianul de
sintaxă). Dacă node lipsește, se sare (skip).
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

_HTML_PATH = (Path(__file__).resolve().parent.parent
              / "app" / "http" / "templates" / "dashboard.html")


def _extract_hextorgba():
    html = _HTML_PATH.read_text(encoding="utf-8")
    m = re.search(r"const hexToRgba=\(hex,a\)=>\{.*?\};", html, re.S)
    assert m, "definiția hexToRgba nu a fost găsită în dashboard.html"
    return m.group(0)


@pytest.mark.skipif(shutil.which("node") is None, reason="node indisponibil")
def test_hextorgba_reproduce_literalele_originale():
    helper = _extract_hextorgba()
    driver = helper + r"""
const assert=require('assert');
// Literalele ORIGINALE din gradientul venitului (rgba(25,198,145,...) = #19C691 = --pos)
assert.strictEqual(hexToRgba('#19C691',.32),'rgba(25,198,145,.32)');
assert.strictEqual(hexToRgba('#19C691',0),'rgba(25,198,145,0)');
// Sanity suplimentar: 6-digit generic + 3-digit shorthand
assert.strictEqual(hexToRgba('#0D1524',1),'rgba(13,21,36,1)');
assert.strictEqual(hexToRgba('#fff',.5),'rgba(255,255,255,.5)');
console.log('OK');
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as f:
        f.write(driver)
        path = f.name
    try:
        r = subprocess.run(["node", path], capture_output=True, text=True)
    finally:
        Path(path).unlink(missing_ok=True)
    assert r.returncode == 0, f"hexToRgba NU reproduce literalele originale:\n{r.stderr}"
    assert "OK" in r.stdout
