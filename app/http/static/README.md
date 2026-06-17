# Fișiere statice (servite de Flask la `/static/...`)

## Certificat de rezidență fiscală Bolt

Pune aici documentul COMUN Bolt (Romania.pdf de la suportul/Portalul Bolt),
redenumit cu ANUL, exact în forma:

    certificat_bolt_romania_<AN>.pdf      (ex. certificat_bolt_romania_2026.pdf)

Codul (`app/services/certificat.py`) referă numele DINAMIC pe an
(`certificat_bolt_romania_{an}.pdf`) → la an nou, pune fișierul noului an și e
servit automat la `/static/certificat_bolt_romania_<AN>.pdf`.

E documentul COMUN al firmei Bolt Operations OÜ (același pentru toți șoferii Bolt
din RO), NU unul personalizat. Verifică anul pe document înainte de depunere.

> ⚠️ Asset de furnizat manual (owner). Dacă lipsește, surfețele afișează ghidul de
> obținere fără link de descărcare (degradare grațioasă).
