"""
Registry central pentru activități.

Punct unic prin care codul aplicației accesează activitățile:
  - get_activity("ridesharing") -> RidesharingActivity
  - get_activity_for_user(user_id) -> activitatea profilului user-ului
  - list_activities() -> lista pentru UI
"""

from typing import Dict, List, Optional, Type
import logging

from app.activities.base import BaseActivity
from app.activities.ridesharing import RidesharingActivity
from app.activities.generic import GenericActivity

logger = logging.getLogger(__name__)


# ============================================================
#                       REGISTRY
# ============================================================

# Registry central — adăugăm activități noi pe măsură ce le implementăm
REGISTRY: Dict[str, Type[BaseActivity]] = {
    "ridesharing": RidesharingActivity,
    "generic": GenericActivity,
    # TODO Faza 2 ulterioară:
    # "it_freelance": ITFreelanceActivity,
    # "ecommerce": EcommerceActivity,
    # "consulting": ConsultingActivity,
    # "construction": ConstructionActivity,
    # "medical": MedicalActivity,
    # "transport": TransportActivity,
    # "real_estate": RealEstateActivity,
    # "education": EducationActivity,
}


def get_activity(code: Optional[str]) -> Type[BaseActivity]:
    """
    Returnează clasa de activitate după cod.
    Dacă nu găsește (sau code=None), returnează GenericActivity ca fallback.
    """
    if not code:
        return GenericActivity
    activity = REGISTRY.get(code)
    if activity is None:
        logger.warning(
            f"Activity code '{code}' not found in registry. "
            f"Falling back to GenericActivity."
        )
        return GenericActivity
    return activity


def get_activity_for_user(user_id: int) -> Type[BaseActivity]:
    """
    Returnează activitatea profilului user-ului.
    Dacă user-ul nu are profil sau nu a ales o activitate, returnează GenericActivity.
    """
    from db import get_session
    from app.repositories import users as users_repo

    session = get_session()
    try:
        profile = users_repo.get_profile_dict(session, user_id) or {}
        activity_code = profile.get("activity_code")
        return get_activity(activity_code)
    except Exception as e:
        logger.error(f"get_activity_for_user error: {e}")
        return GenericActivity
    finally:
        session.close()


def list_activities() -> List[Dict]:
    """
    Listă cu toate activitățile pentru UI.
    Returnează un sumar (code, name, icon, etc.) pentru fiecare.
    """
    return [activity.get_summary() for activity in REGISTRY.values()]


def get_activity_codes() -> List[str]:
    """Listă cu toate codurile de activități disponibile."""
    return list(REGISTRY.keys())
