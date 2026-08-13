from __future__ import annotations

import dataclasses
import time

from harness.constants import MIN_RATE_N, MIN_REAL_CELL_N
from harness.models import Metrics, PublishCandidate, PublishCell

_RATE_FIELDS = ("precision", "recall", "stale_rate", "contradiction_rate")

# CORRECTED (spock MEDIUM): tokens_used was count_tokens(input_text) via
# local tiktoken for every backend identically -- it measures the input
# fact/query size, not any backend's real cost, so it published as an
# identical, uninformative number across all four backends. Dropped from
# the publish path entirely rather than shipped as a misleading metric.
_PER_CALL_MEASUREMENT_FIELDS = (
    "latency_ms_median",
    "latency_ms_iqr_low",
    "latency_ms_iqr_high",
    "update_cost_ms_median",
)
_END_STATE_MEASUREMENT_FIELDS = ("storage_bytes",)
_MEASUREMENT_FIELDS = _PER_CALL_MEASUREMENT_FIELDS + _END_STATE_MEASUREMENT_FIELDS

# Allowlist for label validation (spock HIGH: 'label' was unchecked free
# text, the structural residual of the original leak BLOCKER). Backend
# names are the fixed set of MemoryBackend implementations; synthetic
# workload names are the fixed set this repo's generator produces. A
# label that doesn't match this shape is rejected, regardless of what
# value/n/ci it carries -- this makes "no arbitrary operator text in a
# label" enforced, not just true by the current call sites' behavior.
_KNOWN_BACKENDS = frozenset(
    {
        "RawHistoryBackend",
        "LocalVectorBackend",
        "MemkitBackend",
        "MemkitClaudeResolverBackend",
        "Mem0Backend(local)",
        "Mem0Backend(hybrid)",
    }
)
_KNOWN_SYNTHETIC_WORKLOADS = frozenset({"contradiction_workload"})
_KNOWN_FIELDS = frozenset(_RATE_FIELDS) | frozenset(_MEASUREMENT_FIELDS)


def build_publish_candidate(metrics: list[Metrics]) -> PublishCandidate:
    """Signature takes list[Metrics] only -- not RunLog. Note (per
    structure review, corrected): this is a CONVENTION this project's
    tests enforce, not a Python-enforced guarantee -- there is no CI here
    and a type hint alone stops nothing at runtime. The actual enforced
    guarantee is what scrub() and assert_numbers_only() check at runtime.

    CORRECTED after a code-review pass (worf BLOCKER): rate metrics are
    published ONLY for synthetic workloads, never real ones, and never
    carry an operator-chosen workload_name in a real cell's label. This
    was the original C1 design intent (rate metrics live on synthetic
    data, where n is a free variable; real data contributes only pooled,
    opaquely-labeled measurement metrics)."""
    reported = [m for m in metrics if m.state == "reported"]
    cells: list[PublishCell] = []

    for m in reported:
        if m.workload_kind != "synthetic":
            continue  # real-workload rate metrics are never published, per-workload or pooled
        label_prefix = f"{m.backend_name} / {m.workload_name}"
        cells.extend(_rate_cells(m, label_prefix, MIN_RATE_N))
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
    fingerprint which specific workload it came from. The label is a
    fixed literal ('pooled real data'), never an operator-chosen
    workload_name -- this is the ONLY path real data reaches a published
    cell through, by construction (see build_publish_candidate above).

    CORRECTED (spock MEDIUM): per-call fields (latency, update cost) pool
    with n = total query/write count, which is the right denominator for
    an average over calls. End-state fields (storage_bytes is a snapshot,
    not a per-call sample) instead pool with n = number of workloads
    pooled -- averaging N end-state snapshots and reporting a call-count
    denominator was a real mismatch between what the number means and
    what n claims to count."""
    real_by_backend: dict[str, list[Metrics]] = {}
    for m in reported:
        if m.workload_kind == "real":
            real_by_backend.setdefault(m.backend_name, []).append(m)

    cells = []
    for backend_name, workload_metrics in real_by_backend.items():
        pooled_call_n = sum(m.n for m in workload_metrics)
        pooled_workload_n = len(workload_metrics)

        for field_name in _PER_CALL_MEASUREMENT_FIELDS:
            if pooled_call_n < MIN_REAL_CELL_N:
                continue
            values = [getattr(m, field_name) for m in workload_metrics if getattr(m, field_name) is not None]
            if not values:
                continue
            cells.append(
                PublishCell(
                    label=f"{backend_name} / pooled real data / {field_name}",
                    value=sum(values) / len(values),
                    n=pooled_call_n,
                )
            )

        for field_name in _END_STATE_MEASUREMENT_FIELDS:
            if pooled_workload_n < MIN_REAL_CELL_N:
                continue
            values = [getattr(m, field_name) for m in workload_metrics if getattr(m, field_name) is not None]
            if not values:
                continue
            cells.append(
                PublishCell(
                    label=f"{backend_name} / pooled real data / {field_name}",
                    value=sum(values) / len(values),
                    n=pooled_workload_n,
                )
            )
    return cells


def assert_numbers_only(candidate: PublishCandidate) -> None:
    """Runtime allowlist check, called by scrub() -- corrected per HIGH-2:
    the primary guard is now enforced at runtime, not just a dataclass
    shape nobody promised to keep clean. CORRECTED (worf MEDIUM): bool is
    an int subclass in Python -- isinstance(True, int) is True -- so a
    bool value would have silently passed this check before. Rejected
    explicitly now.

    CORRECTED (spock HIGH): label itself is now validated against a fixed
    allowlist shape -- {known_backend} / (known_synthetic_workload |
    'pooled real data') / {known_field} -- so an arbitrary string can no
    longer reach a published cell's label even via a future code path
    that doesn't go through today's two label-building call sites. This
    converts 'the denylist is the only backstop for label content' into
    'label content is structurally constrained', closing the residual of
    the original leak BLOCKER."""
    for cell in candidate.cells:
        _assert_label_allowed(cell.label)
        for f in dataclasses.fields(cell):
            value = getattr(cell, f.name)
            if f.name == "label":
                continue
            if isinstance(value, bool):
                raise ValueError(f"PublishCell field '{f.name}' is a bool, not a meaningful numeric value")
            if value is not None and not isinstance(value, (int, float)):
                raise ValueError(f"PublishCell field '{f.name}' is not numeric: {type(value)}")


def _assert_label_allowed(label: str) -> None:
    parts = label.split(" / ")
    if len(parts) != 3:
        raise ValueError(f"label does not match the required 3-part shape: {label!r}")
    backend, middle, field_name = parts
    if backend not in _KNOWN_BACKENDS:
        raise ValueError(f"label references an unknown backend: {backend!r}")
    if middle != "pooled real data" and middle not in _KNOWN_SYNTHETIC_WORKLOADS:
        raise ValueError(
            f"label's middle segment is neither a known synthetic workload nor 'pooled real data': {middle!r}"
        )
    if field_name not in _KNOWN_FIELDS:
        raise ValueError(f"label references an unknown field: {field_name!r}")
