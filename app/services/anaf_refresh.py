"""
REIMPROSPATAREA datelor de la ANAF — umple golurile, nu rescrie deciziile.

CE REZOLVA
Profilul unui user se completeaza O SINGURA DATA, la configurare. Orice camp
adaugat DUPA aceea ramane gol pe conturile existente, pentru totdeauna: n-are cine
sa-l umple, fiindca lookup-ul ANAF nu se mai cheama niciodata. Asa a ajuns userul 1
de pe productie fara `nr_doc_autorizare` — si a aflat luni mai tarziu, cand D212 a
refuzat sa se genereze.

Migrarile adauga COLOANA, nu si VALOAREA. Modulul asta e piesa lipsa: o a doua
sansa de captare, ceruta de user, oricand.

Foloseste si cand realitatea firmei s-a schimbat (sediu mutat, CAEN modificat,
intrare in scop de TVA) — ANAF stie deja, noi nu.

REGULA, UNA SINGURA
  Camp GOL la noi        → il completam din ANAF.
  Camp COMPLETAT la noi  → NU-l atingem; daca ANAF spune altceva, RAPORTAM.

De ce nu suprascriem automat nici cand ANAF „stie mai bine": campurile astea sunt
fiscale. `regim_tva` schimba tratamentul TVA pe tot ce urmeaza; `caen_principal`
intra pe D212; `judet` + `localitate` decid norma de venit. O rescriere tacuta ar
schimba cifre pe care userul le-a vazut deja, fara ca el sa afle. Asa ca aratam
diferenta si il lasam pe el sa decida — aceeasi disciplina ca la data certificatului
(o propunem, o confirma el) si ca la webhook-ul Stripe (`tier=None` = «lasa
neschimbat», nu «inventeaza unul»).

DATA CERTIFICATULUI nu se atinge NICIODATA, nici macar cand e goala: e singurul
camp pe care ANAF nu-l poate sti (vezi antetul din app/domain/doc_autorizare.py —
„Data eliberarii" de pe certificat nu apare in raspuns). O completare „din ANAF"
ar fi o cifra plauzibila prezentata ca fapt. Ramane la confirmarea userului.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from app.domain.doc_autorizare import motiv_nr_doc_text, nr_doc_din_anaf
from app.integrations import anaf_lookup
from app.repositories import users as users_repo

logger = logging.getLogger(__name__)


# Campurile pe care le reimprospatam, in ordinea in care le aratam userului.
# (cheie_profil, cheie_anaf, eticheta). Lista e EXPLICITA, nu derivata din
# raspunsul ANAF: ce nu e aici nu se scrie, oricat de tentant ar fi campul.
#
# NU sunt aici, deliberat:
#   data_doc_autorizare — ANAF n-o stie (vezi antetul modulului)
#   activity_code       — e alegerea userului („ce faci"), nu un fapt din registru
#   regim_impunere      — la fel: real vs norma e o optiune fiscala, nu o stare
#   cnp                 — nu vine de la ANAF si n-are ce cauta intr-o sincronizare
CAMPURI = (
    ("firma_nume",           "denumire",                 "Denumire"),
    ("firma_forma_juridica", "forma_juridica_detectata", "Formă juridică"),
    ("caen_principal",       "cod_caen",                 "CAEN"),
    ("regim_tva",            "regim_tva",                "Regim TVA"),
    ("judet",                "judet",                    "Județ"),
    ("localitate",           "localitate",               "Localitate"),
    ("nume_declarant",       "nume_declarant",           "Nume titular"),
    ("prenume_declarant",    "prenume_declarant",        "Prenume titular"),
)


@dataclass
class RezultatReimprospatare:
    """Ce s-a intamplat, in termeni pe care ii poate citi si botul si dashboardul."""

    ok: bool = False
    eroare: Optional[str] = None                      # text pentru USER, nu pentru log
    # (eticheta, valoare_noua) — campuri care erau goale si acum nu mai sunt.
    completate: List[Tuple[str, str]] = field(default_factory=list)
    # (eticheta, ce_avem, ce_spune_anaf) — NEaplicate, doar semnalate.
    diferente: List[Tuple[str, str, str]] = field(default_factory=list)
    # Numarul de certificat: a intrat acum? de ce nu, daca nu?
    nr_completat: Optional[str] = None
    nr_motiv: Optional[str] = None

    @property
    def ceva_de_aratat(self) -> bool:
        return bool(self.completate or self.diferente or self.nr_motiv)


def _gol(v) -> bool:
    """Camp „gol" la noi: None, sir vid sau numai spatii. 0 si False NU sunt goluri."""
    return v is None or (isinstance(v, str) and not v.strip())


def reimprospateaza(session, user_id: int) -> RezultatReimprospatare:
    """Re-cheama ANAF pe CUI-ul userului si completeaza golurile. Commit la apelant.

    Nu arunca: orice esec devine `ok=False` + `eroare` scrisa pentru user. O actiune
    de reparare care crapa in fata celui care incearca sa repare e mai rea decat
    lipsa ei.
    """
    profile = users_repo.get_profile_dict(session, user_id) or {}
    cui = (profile.get("firma_cui") or "").strip()
    if not cui:
        return RezultatReimprospatare(
            ok=False,
            eroare="N-am CUI-ul tău în profil, deci n-am pe ce să întreb ANAF. "
                   "Completează întâi CUI-ul.",
        )

    try:
        res = anaf_lookup.lookup_cui(cui)
    except Exception as e:                                  # pragmatic: retea, parsare
        logger.exception(f"reimprospatare ANAF a esuat user={user_id} cui={cui}: {e}")
        return RezultatReimprospatare(
            ok=False,
            eroare="Nu am putut ajunge la ANAF chiar acum. Mai încearcă peste "
                   "câteva minute — datele tale rămân neatinse.",
        )

    if not res.get("found"):
        return RezultatReimprospatare(
            ok=False,
            eroare=f"ANAF nu mi-a răspuns pentru CUI {cui}: "
                   f"{res.get('error') or 'motiv necunoscut'}.",
        )

    rez = RezultatReimprospatare(ok=True)
    updates = {}

    for cheie, cheie_anaf, eticheta in CAMPURI:
        val_anaf = res.get(cheie_anaf)
        if _gol(val_anaf):
            continue                                        # ANAF n-are ce da
        val_anaf = str(val_anaf).strip()
        val_noastra = profile.get(cheie)
        if _gol(val_noastra):
            updates[cheie] = val_anaf
            rez.completate.append((eticheta, val_anaf))
        elif str(val_noastra).strip() != val_anaf:
            rez.diferente.append((eticheta, str(val_noastra).strip(), val_anaf))

    # ── numarul de certificat: singurul camp cu stare proprie ────────────────
    # Se atinge DOAR daca e gol la noi. Daca e completat, nu-l clatinam: poate
    # userul l-a tastat de pe certificat tocmai fiindca ANAF il da altfel.
    if _gol(profile.get("nr_doc_autorizare")):
        nr, motiv = nr_doc_din_anaf(res.get("nr_reg_com"))
        if nr:
            updates["nr_doc_autorizare"] = nr
            rez.nr_completat = nr
            rez.completate.append(("Număr certificat ONRC", nr))
        else:
            # Esecul se SCRIE, nu se logheaza si se uita. Data viitoare cand userul
            # deschide Setarile, campul stie de ce e gol.
            updates["nr_doc_autorizare_motiv"] = motiv
            rez.nr_motiv = motiv
            logger.warning(
                f"reimprospatare: nr_doc_autorizare tot gol user={user_id} "
                f"cui={cui} motiv={motiv} brut={res.get('nr_reg_com')!r}"
            )

    if updates:
        user = users_repo.get_by_id(session, user_id)
        if user is None:
            return RezultatReimprospatare(ok=False, eroare="Nu te-am putut identifica.")
        try:
            users_repo.update_profile(session, user, **updates)
        except Exception as e:
            session.rollback()
            logger.exception(f"reimprospatare: scrierea a esuat user={user_id}: {e}")
            return RezultatReimprospatare(
                ok=False,
                eroare="Am luat datele de la ANAF, dar nu le-am putut salva. "
                       "Mai încearcă — nu s-a schimbat nimic.",
            )

    return rez


# ============================================================
#          TEXTUL REZULTATULUI — o singura sursa, doua ecrane
# ============================================================

def text_rezultat(rez: RezultatReimprospatare, markdown: bool = True) -> str:
    """Rezultatul → mesaj pentru user. Acelasi continut in bot si in Setari web.

    `markdown=False` pentru suprafetele care nu-l parseaza (dashboardul scrie text
    simplu in bula de status). Doar accentele difera; frazele sunt identice.
    """
    b = "*" if markdown else ""

    if not rez.ok:
        return f"⚠️ {rez.eroare}"

    linii = []
    if rez.completate:
        linii.append(f"✅ {b}Am completat din ANAF:{b}")
        linii += [f"• {et}: {val}" for et, val in rez.completate]

    if rez.nr_motiv:
        if linii:
            linii.append("")
        linii.append(f"📜 {b}Numărul certificatului ONRC — tot gol.{b}")
        linii.append(motiv_nr_doc_text(rez.nr_motiv) or "")

    if rez.diferente:
        if linii:
            linii.append("")
        linii.append(f"🔎 {b}ANAF spune altceva decât am eu:{b}")
        linii += [
            f'• {et}: am „{al_meu}", ANAF spune „{al_lor}"'
            for et, al_meu, al_lor in rez.diferente
        ]
        linii.append("")
        linii.append(
            "N-am schimbat nimic din astea — sunt date fiscale, iar o rescriere "
            "tăcută ți-ar muta cifre pe care le-ai văzut deja. Dacă ANAF are "
            "dreptate, schimbă-le tu și le folosesc de acum."
        )

    if not linii:
        linii.append("✅ Am întrebat ANAF: totul e la zi, n-a fost nimic de completat.")

    return "\n".join(linii)
