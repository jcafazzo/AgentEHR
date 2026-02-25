"""Clinical scoring systems for inpatient care oversight."""

from .clinical_scores import (
    calculate_news2,
    calculate_qsofa,
    calculate_sofa,
    calculate_kdigo,
    calculate_all_available_scores,
)

__all__ = [
    "calculate_news2",
    "calculate_qsofa",
    "calculate_sofa",
    "calculate_kdigo",
    "calculate_all_available_scores",
]
