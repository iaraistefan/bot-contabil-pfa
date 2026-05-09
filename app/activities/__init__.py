
"""
Sistemul de activități plug-in pentru Bot Contabil.

Fiecare activitate (Ridesharing, IT, Comerț, etc.) e un plug-in cu reguli proprii:
  - Categorii de cheltuieli/venituri specifice
  - Reguli de deductibilitate
  - Reguli TVA per categorie
  - Calendar fiscal personalizat
  - Hint-uri pentru AI extraction

Punct de intrare unic — registry.get_activity(code).
"""

from app.activities.base import (
    BaseActivity,
    ExpenseCategory,
    VATTreatment,
    DeductibilityRule,
)
from app.activities.registry import (
    get_activity,
    get_activity_for_user,
    list_activities,
    REGISTRY,
)

__all__ = [
    "BaseActivity",
    "ExpenseCategory",
    "VATTreatment",
    "DeductibilityRule",
    "get_activity",
    "get_activity_for_user",
    "list_activities",
    "REGISTRY",
]
