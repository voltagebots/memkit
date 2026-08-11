from __future__ import annotations

import dataclasses
import time

from harness.constants import MIN_RATE_N, MIN_REAL_CELL_N
from harness.models import Metrics, PublishCandidate, PublishCell

_RATE_FIELDS = ("precision", "recall", "stale_rate", "contradiction_rate")
_MEASUREMENT_FIELDS = (
    "tokens_used",
    "storage_bytes",
    "latency_ms_median",
    "latency_ms_iqr_low",
    "latency_ms_iqr_high",
    "update_cost_ms_median",
)


def build_publish_candidate(metrics: list[Metrics]) -> PublishCandidate:
    """Signature takes list[Metrics] only -- not RunLog. Note (per
    structure review, corrected): this is a CONVENTION this project's
    tests enforce, not a Python-enforced guarantee -- there is no CI here
    and a type hint alone stops nothing at runtime. The actual enforced
    guarantee is what scrub() checks (see prepublish_scrub.py)."""
    reported = [m for m in metrics if m.state == "reported"]
    cells: list[PublishCell] = []

    for m in reported:
        label_prefix = f"{m.backend_name} / {m.workload_name}"
        threshold = MIN_RATE_N if m.workload_kind == "synthetic" else MIN_REAL_CELL_N
        cells.extend(_rate_cells(m, label_prefix, threshold))
        if m.workload_kind == "synthetic":
            cells.extend(_measurement_cells(m, label_prefix, threshold=0))

    cells.extend(_pooled_real_measurement_cells(reported))

    return PublishCandidate(cells=tuple(cells), generated_at=time.time())


def _rate_cells(m: Metrics, label_prefix: str, threshold: int) -> list[PublishCell]:
    cells = []
    for field_name in _RATE_FIELDS:
        rate = getattr(m, field_name)
        if rate is None or rate.value is None or rate.n < threshold:
            continue
        cells.append(
            PublishCell(
                label=f"{label_prefix} / {field_name}",
                value=rate.value,
                n=rate.n,
                ci_low=rate.ci_low,
                ci_high=rate.ci_high,
            )
        )
    return cells


def _measurement_cells(m: Metrics, label_prefix: str, threshold: int) -> list[PublishCell]:
    if m.n < threshold:
        return []
    cells = []
    for field_name in _MEASUREMENT_FIELDS:
        value = getattr(m, field_name)
        if value is None:
            continue
        cells.append(PublishCell(label=f"{label_prefix} / {field_name}", value=value, n=m.n))
    return cells


def _pooled_real_measurement_cells(reported: list[Metrics]) -> list[PublishCell]:
    """C.5 condition 5: real-data measurement metrics are POOLED across
    all real workloads per backend before the MIN_REAL_CELL_N check --
    per-workload-type breakdowns re-identify at small n ('3/4' on 4 real
    PRs IS the four real PRs), a pooled cross-workload number does not
    fingerprint which specific workload it came from."""
    real_by_backend: dict[str, list[Metrics]] = {}
    for m in reported:
        if m.workload_kind == "real":
            real_by_backend.setdefault(m.backend_name, []).append(m)

    cells = []
    for backend_name, workload_metrics in real_by_backend.items():
        pooled_n = sum(m.n for m in workload_metrics)
        if pooled_n < MIN_REAL_CELL_N:
            continue
        for field_name in _MEASUREMENT_FIELDS:
            values = [getattr(m, field_name) for m in workload_metrics if getattr(m, field_name) is not None]
            if not values:
                continue
            pooled_value = sum(values) / len(values)
            cells.append(
                PublishCell(label=f"{backend_name} / pooled real data / {field_name}", value=pooled_value, n=pooled_n)
            )
    return cells


def assert_numbers_only(candidate: PublishCandidate) -> None:
    """Runtime allowlist check, called by scrub() -- corrected per HIGH-2:
    the primary guard is now enforced at runtime, not just a dataclass
    shape nobody promised to keep clean."""
    for cell in candidate.cells:
        for f in dataclasses.fields(cell):
            value = getattr(cell, f.name)
            if f.name == "label":
                continue
            if value is not None and not isinstance(value, (int, float)):
                raise ValueError(f"PublishCell field '{f.name}' is not numeric: {type(value)}")
