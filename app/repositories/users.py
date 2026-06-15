"""
Repository pentru User — acces la DB pentru users.

Conventie: orice functie care atinge DB accepta o SQLAlchemy Session ca prim argument.
Asta tine tranzactiile sub controlul apelantului.
"""

from datetime import date
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from app.models import User


# ============================================================
#                     LOOKUP / CREATE
# ============================================================

def get_by_telegram_id(session: Session, telegram_id: int) -> Optional[User]:
    """Returneaza user-ul cu acest telegram_id, sau None."""
    return session.query(User).filter(User.telegram_id == telegram_id).one_or_none()


def get_by_id(session: Session, user_id: int) -> Optional[User]:
    """Returneaza user-ul dupa ID intern, sau None."""
    return session.query(User).filter(User.id == user_id).one_or_none()


def get_or_create_by_telegram_id(
    session: Session,
    telegram_id: int,
    name: Optional[str] = None,
) -> User:
    """
    Returneaza user-ul existent sau il creeaza daca nu exista.
    Commit-ul ramane in grija apelantului.
    """
    user = get_by_telegram_id(session, telegram_id)
    if user is not None:
        if name and user.name != name:
            user.name = name
        return user

    user = User(telegram_id=telegram_id, name=name)
    session.add(user)
    session.flush()
    return user


# ============================================================
#                  PROFIL FIRMA — UPDATE
# ============================================================

def update_profile(
    session: Session,
    user: User,
    *,
    name: Optional[str] = None,
    firma_nume: Optional[str] = None,
    firma_cui: Optional[str] = None,
    firma_forma_juridica: Optional[str] = None,
    cod_special_tva: Optional[str] = None,
    cnp: Optional[str] = None,
    regim_tva: Optional[str] = None,
    regim_impunere: Optional[str] = None,
    regim_nerezident: Optional[str] = None,
    caen_principal: Optional[str] = None,
    activity_code: Optional[str] = None,
    judet: Optional[str] = None,
    localitate: Optional[str] = None,
    data_inceput_activitate: Optional[date] = None,
    email: Optional[str] = None,
    telefon: Optional[str] = None,
    banca: Optional[str] = None,
    iban: Optional[str] = None,
) -> User:
    """
    Actualizeaza campurile de profil ale user-ului.
    Doar valorile non-None sunt aplicate (None = lasa neschimbat).
    Commit la apelant.
    """
    if name is not None:
        user.name = name.strip()[:200] if name else None
    if firma_nume is not None:
        user.firma_nume = firma_nume.strip() if firma_nume else None
    if firma_cui is not None:
        cui_clean = "".join(c for c in str(firma_cui) if c.isdigit())
        user.firma_cui = cui_clean if cui_clean else None
    if firma_forma_juridica is not None:
        user.firma_forma_juridica = firma_forma_juridica
    if cod_special_tva is not None:
        # Pastram doar cifrele (prefixul RO se adauga la afisare)
        cod_clean = "".join(c for c in str(cod_special_tva) if c.isdigit())
        user.cod_special_tva = cod_clean if cod_clean else None
    if cnp is not None:
        cnp_clean = "".join(c for c in str(cnp) if c.isdigit())
        user.cnp = cnp_clean if cnp_clean else None
    if regim_tva is not None:
        user.regim_tva = regim_tva
    if regim_impunere is not None:
        user.regim_impunere = regim_impunere
    if regim_nerezident is not None:
        user.regim_nerezident = regim_nerezident
    if caen_principal is not None:
        user.caen_principal = caen_principal
    if activity_code is not None:
        user.activity_code = activity_code
    if judet is not None:
        user.judet = judet
    if localitate is not None:
        user.localitate = localitate
    if data_inceput_activitate is not None:
        user.data_inceput_activitate = data_inceput_activitate
    if email is not None:
        user.email = email.strip().lower() if email else None
    if telefon is not None:
        user.telefon = telefon.strip() if telefon else None
    if banca is not None:
        user.banca = banca.strip()[:120] if banca else None
    if iban is not None:
        # IBAN: pastram doar litere si cifre, uppercase, fara spatii
        iban_clean = "".join(
            c for c in str(iban).upper() if c.isalnum()
        )
        user.iban = iban_clean[:34] if iban_clean else None

    session.flush()
    return user


def update_profile_by_id(
    session: Session,
    user_id: int,
    **kwargs,
) -> Optional[User]:
    """Varianta convenabila: actualizeaza profilul dupa user_id."""
    user = get_by_id(session, user_id)
    if user is None:
        return None
    return update_profile(session, user, **kwargs)


# ============================================================
#                   ONBOARDING WORKFLOW
# ============================================================

ONBOARDING_STEPS = {
    "NOT_STARTED": 0,
    "NUME_PERSONAL": 1,
    "FORMA_JURIDICA": 2,
    "DENUMIRE_FIRMA": 3,
    "CUI": 4,
    "CAEN_ACTIVITATE": 5,
    "REGIM_TVA": 6,
    "REGIM_IMPUNERE": 7,
    "JUDET": 8,
    "DATA_INCEPUT": 9,
    "COMPLETED": 99,
}


def is_onboarded(session: Session, user_id: int) -> bool:
    user = get_by_id(session, user_id)
    if user is None:
        return False
    return bool(user.onboarding_completed)


def get_onboarding_step(session: Session, user_id: int) -> int:
    user = get_by_id(session, user_id)
    if user is None:
        return 0
    return user.onboarding_step or 0


def set_onboarding_step(
    session: Session,
    user: User,
    step: int,
) -> User:
    user.onboarding_step = step
    if step == ONBOARDING_STEPS["COMPLETED"]:
        user.onboarding_completed = True
    session.flush()
    return user


def advance_onboarding_step(
    session: Session,
    user: User,
    next_step: int,
    profile_updates: Optional[Dict[str, Any]] = None,
) -> User:
    """
    Avanseaza la pasul urmator si (optional) actualizeaza profilul in acelasi timp.
    """
    if profile_updates:
        update_profile(session, user, **profile_updates)
    return set_onboarding_step(session, user, next_step)


def complete_onboarding(session: Session, user: User) -> User:
    user.onboarding_completed = True
    user.onboarding_step = ONBOARDING_STEPS["COMPLETED"]
    session.flush()
    return user


def reset_onboarding(session: Session, user: User) -> User:
    user.onboarding_completed = False
    user.onboarding_step = 0
    session.flush()
    return user


# ============================================================
#                  PROFIL — CITIRE / SERIALIZARE
# ============================================================

def get_profile_dict(session: Session, user_id: int) -> Optional[Dict[str, Any]]:
    user = get_by_id(session, user_id)
    if user is None:
        return None

    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "name": user.name,
        "firma_nume": user.firma_nume,
        "firma_cui": user.firma_cui,
        "firma_forma_juridica": user.firma_forma_juridica,
        "cod_special_tva": user.cod_special_tva,
        "cnp": user.cnp,
        "regim_tva": user.regim_tva,
        "regim_impunere": user.regim_impunere,
        "regim_nerezident": user.regim_nerezident,
        "caen_principal": user.caen_principal,
        "activity_code": user.activity_code,
        "judet": user.judet,
        "localitate": user.localitate,
        "data_inceput_activitate": (
            user.data_inceput_activitate.isoformat()
            if user.data_inceput_activitate else None
        ),
        "onboarding_completed": user.onboarding_completed,
        "onboarding_step": user.onboarding_step,
        "email": user.email,
        "telefon": user.telefon,
        "banca": user.banca,
        "iban": user.iban,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }


def get_pfa_display_name(session: Session, user_id: int) -> str:
    user = get_by_id(session, user_id)
    if user is None:
        return "PFA"
    return user.firma_nume or user.name or "PFA"


def get_pfa_cui(session: Session, user_id: int) -> str:
    user = get_by_id(session, user_id)
    if user is None or not user.firma_cui:
        return ""
    return user.firma_cui


# ============================================================
#         CODURI FISCALE - care cod pe care declaratie
# ============================================================

def cod_pentru_declaratie(profile: Dict[str, Any], declaratie: str) -> Optional[str]:
    """
    Returneaza codul de identificare corect pentru o declaratie data,
    pe baza profilului. Reguli:
      - D301, D390  -> cod special TVA art. 317 (fallback CUI normal)
      - D212        -> CNP (venit personal)
      - D100, D300, alte -> CUI normal
    'profile' e dict-ul de la get_profile_dict.
    """
    d = (declaratie or "").upper().replace("D", "")
    cui = profile.get("firma_cui")
    cod_tva = profile.get("cod_special_tva")
    cnp = profile.get("cnp")

    if d in ("301", "390"):
        return cod_tva or cui
    if d in ("212",):
        return cnp
    # D100, D300 si restul -> CUI normal
    return cui


# ============================================================
#                       VALIDARI
# ============================================================

VALID_FORME_JURIDICE = {
    "PFA", "II", "IF", "SRL_MICRO", "SRL_NORMAL", "PROFESIE_LIBERALA"
}

VALID_REGIMURI_TVA = {
    "NEPLATITOR", "PLATITOR_21", "SPECIAL_INTRACOM"
}

VALID_REGIMURI_IMPUNERE = {
    "SISTEM_REAL", "NORMA_VENIT", "MICRO_1", "MICRO_3"
}

# Regim impozit nerezident D100 (comision Bolt). NU include o valoare "default":
# absenta (None) inseamna neconfigurat, nu o rata presupusa.
VALID_REGIMURI_NEREZIDENT = {
    "CRF_SCUTIT", "CRF_2PCT", "FARA_CRF"
}

VALID_ACTIVITY_CODES = {
    "ridesharing", "it_freelance", "ecommerce", "consulting",
    "construction", "medical", "transport", "real_estate",
    "education", "generic",
}


def is_valid_forma_juridica(value: str) -> bool:
    return value in VALID_FORME_JURIDICE


def is_valid_regim_tva(value: str) -> bool:
    return value in VALID_REGIMURI_TVA


def is_valid_regim_impunere(value: str) -> bool:
    return value in VALID_REGIMURI_IMPUNERE


def is_valid_regim_nerezident(value: str) -> bool:
    return value in VALID_REGIMURI_NEREZIDENT


def is_valid_activity_code(value: str) -> bool:
    return value in VALID_ACTIVITY_CODES
