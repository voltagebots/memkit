from __future__ import annotations

import math

from harness.models import RateMetric


def wilson_ci(successes: int, n: int, z: float = 1.96) -> RateMetric:
    """95% Wilson score interval -- more robust than the normal
    approximation at small n, which is exactly the regime this project's
    real-data cells live in (worf/sentinel finding: real-data n is small
    by design, per the privacy-driven MIN_REAL_CELL_N floor)."""
    if n == 0:
        return RateMetric(value=None, n=0, ci_low=None, ci_high=None)
    p = successes / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = (z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n)) / denom
    return RateMetric(value=p, n=n, ci_low=max(0.0, center - margin), ci_high=min(1.0, center + margin))
