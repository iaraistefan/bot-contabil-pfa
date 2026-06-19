"""
Gardian JS — sintaxa blocului <script> din dashboard.html.

Suita e Python (backend + gardieni template pe string-presence) și NU executa JS, deci o
eroare de sintaxa JS putea ajunge in productie nedetectata (ex.: ghilimea ASCII " care inchide
prematur un string → SyntaxError → TOT scriptul inline moare → dashboard gol + butoane moarte
pentru TOTI userii). S-a intamplat la merge-ul onboardingului (#6).

Acest test extrage blocul <script> si ruleaza `node --check` → orice eroare de sintaxa JS
e prinsa la pytest, nu in productie. Daca node nu e disponibil, testul se sare (skip) — pe
CI/dev cu node instalat devine gardian dur.
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

_HTML_PATH = (Path(__file__).resolve().parent.parent
              / "app" / "http" / "templates" / "dashboard.html")


def _script_blocks():
    html = _HTML_PATH.read_text(encoding="utf-8")
    return re.findall(r"<script>(.*?)</script>", html, re.S)


@pytest.mark.skipif(shutil.which("node") is None, reason="node indisponibil — gardian dur doar cu node")
def test_dashboard_script_syntax_valid():
    blocks = _script_blocks()
    assert blocks, "niciun bloc <script> gasit in dashboard.html"
    for i, block in enumerate(blocks):
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as f:
            f.write(block)
            path = f.name
        try:
            r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
        finally:
            Path(path).unlink(missing_ok=True)
        assert r.returncode == 0, (
            f"Eroare de sintaxa JS in blocul <script> #{i} din dashboard.html:\n{r.stderr}"
        )


def test_fara_ghilimea_ascii_in_string_cu_curly():
    """
    Lock anti-regresie pe tiparul exact care a cazut productia: o ghilimea curly de DESCHIDERE
    „ urmata de text si o ghilimea ASCII " (in loc de curly ") care inchide string-ul JS prematur.
    Verificam DOAR liniile de cod (nu comentariile //), unde tiparul e periculos.
    """
    suspecte = []
    for n, line in enumerate(_HTML_PATH.read_text(encoding="utf-8").splitlines(), 1):
        cod = line.split("//", 1)[0]          # ignoram comentariile (acolo " ASCII e inofensiv)
        if "„" in cod and '".' in cod and "”" not in cod.split("„", 1)[1][:30]:
            # are „ deschidere, dar imediat dupa apare " ASCII fara curly de inchidere
            suspecte.append(f"L{n}: {line.strip()}")
    assert not suspecte, "Ghilimea ASCII inchide string-ul dupa „ (risc SyntaxError):\n" + "\n".join(suspecte)
