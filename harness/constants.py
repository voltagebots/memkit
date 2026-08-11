"""Two independent thresholds, deliberately not one -- see plan.md C.5
condition 5. Conflating them was the MEDIUM finding: a low bar for
measurement metrics is right for statistical validity but wrong for
anti-re-identification, since ANY real-data cell (rate or measurement)
below a small n discloses roughly which real items were involved."""

MIN_RATE_N = 100
"""Statistical: keeps the 95% CI on a proportion usable. In practice only
the synthetic workload (hundreds of engineered pairs) realistically
reaches this -- real-data rate metrics are not expected to publish."""

MIN_REAL_CELL_N = 10
"""Privacy: no real-data aggregate, of ANY metric type, publishes below
this. Independent of MIN_RATE_N -- a measurement metric with n=9 real
examples is blocked by this even though it would pass a purely
statistical bar."""
