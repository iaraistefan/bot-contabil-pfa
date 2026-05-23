"""
Pas A - Repository pentru vehicule.

Operatii CRUD pe tabelul `vehicule`, plus regula de limitare a numarului
de masini in functie de forma juridica.
"""

from datetime import datetime

from app.models import Vehicul


# ============================================================
#       Limita de vehicule pe forma juridica
# ============================================================

# PFA si profesia liberala = un singur titular -> o singura masina
# (Cod Fiscal: PFA poate deduce cheltuieli auto pe un singur vehicul).
# I.I., I.F., SRL pot avea flota (mai multi soferi).
FORME_O_SINGURA_MASINA = {"PFA", "PROFESIE_LIBERALA"}
MAX_FLOTA = 99


def max_vehicule_for_forma(forma_juridica: str) -> int:
    """Returneaza numarul maxim de vehicule permis pentru o forma juridica."""
    if forma_juridica in FORME_O_SINGURA_MASINA:
        return 1
    return MAX_FLOTA


# ============================================================
#       CRUD
# ============================================================

def create(session, user_id: int, nr_inmatriculare: str,
           marca_model: str = None, norma_consum: float = 7.5,
           tip_detinere: str = None) -> Vehicul:
    """Creeaza un vehicul nou. Nu face commit - apelantul decide."""
    v = Vehicul(
        user_id=user_id,
        nr_inmatriculare=(nr_inmatriculare or "").strip().upper(),
        marca_model=((marca_model or "").strip() or None),
        norma_consum=norma_consum if norma_consum else 7.5,
        tip_detinere=tip_detinere,
        activ=True,
    )
    session.add(v)
    session.flush()
    return v


def get_by_id(session, vehicul_id: int, user_id: int) -> Vehicul:
    """Returneaza un vehicul al user-ului (user_id verificat - securitate)."""
    return (
        session.query(Vehicul)
        .filter(Vehicul.id == vehicul_id, Vehicul.user_id == user_id)
        .first()
    )


def list_active(session, user_id: int):
    """Toate vehiculele active ale user-ului, ordonate cronologic."""
    return (
        session.query(Vehicul)
        .filter(Vehicul.user_id == user_id, Vehicul.activ == True)  # noqa: E712
        .order_by(Vehicul.created_at)
        .all()
    )


def count_active(session, user_id: int) -> int:
    """Numarul de vehicule active ale user-ului."""
    return (
        session.query(Vehicul)
        .filter(Vehicul.user_id == user_id, Vehicul.activ == True)  # noqa: E712
        .count()
    )


def get_default(session, user_id: int) -> Vehicul:
    """
    Vehiculul implicit - prima masina activa.
    Folosit de foaia de parcurs cand user-ul are o singura masina.
    """
    return (
        session.query(Vehicul)
        .filter(Vehicul.user_id == user_id, Vehicul.activ == True)  # noqa: E712
        .order_by(Vehicul.created_at)
        .first()
    )


def update(session, vehicul: Vehicul, **fields) -> Vehicul:
    """Actualizeaza campurile permise ale unui vehicul."""
    allowed = {
        "nr_inmatriculare", "marca_model", "norma_consum",
        "tip_detinere", "km_curent", "activ",
    }
    for key, value in fields.items():
        if key in allowed:
            if key == "nr_inmatriculare" and value:
                value = value.strip().upper()
            setattr(vehicul, key, value)
    vehicul.updated_at = datetime.utcnow()
    session.flush()
    return vehicul


def soft_delete(session, vehicul: Vehicul) -> None:
    """Marcheaza vehiculul ca inactiv (soft-delete - pastreaza istoricul)."""
    vehicul.activ = False
    vehicul.updated_at = datetime.utcnow()
    session.flush()


def update_km_curent(session, vehicul: Vehicul, km: int) -> None:
    """
    Actualizeaza km_curent doar daca noua valoare e mai mare
    (kilometrajul nu scade niciodata).
    """
    if km is None:
        return
    if vehicul.km_curent is None or km > vehicul.km_curent:
        vehicul.km_curent = km
        vehicul.updated_at = datetime.utcnow()
        session.flush()


def to_dict(vehicul: Vehicul) -> dict:
    """Serializare pentru audit log."""
    return {
        "id": vehicul.id,
        "nr_inmatriculare": vehicul.nr_inmatriculare,
        "marca_model": vehicul.marca_model,
        "norma_consum": vehicul.norma_consum,
        "tip_detinere": vehicul.tip_detinere,
        "km_curent": vehicul.km_curent,
        "activ": vehicul.activ,
    }
