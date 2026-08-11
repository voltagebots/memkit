from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

WorkloadKind = Literal["synthetic", "real"]


@dataclass(frozen=True)
class GoldAnswer:
    """Synthetic workloads use exact_ids (precise fact ids expected in a
    retrieval) -- exact-match scoring. Real workloads use
    stale_ids_that_must_not_surface only -- direction-only scoring, per
    the C1 privacy-driven real-vs-synthetic split. Never both populated
    for the same event."""

    exact_ids: frozenset[str] | None = None
    stale_ids_that_must_not_surface: frozenset[str] | None = None


@dataclass(frozen=True)
class WorkloadEvent:
    """fact_text/query_text carry real content for real-kind workloads --
    repr=False so an accidental print/log of an event never dumps it."""

    kind: Literal["write", "query"]
    at: float
    fact_id: str | None = None
    fact_text: str | None = field(default=None, repr=False)
    query_text: str | None = field(default=None, repr=False)
    gold: GoldAnswer | None = None


@dataclass(frozen=True)
class Workload:
    name: str
    kind: WorkloadKind
    events: tuple[WorkloadEvent, ...]


@dataclass(frozen=True)
class WriteResult:
    ok: bool
    latency_ms: float
    token_count: int
    error: str | None = None


@dataclass(frozen=True)
class RetrievedFact:
    fact_id: str | None
    text: str = field(default="", repr=False)
    score: float = 0.0


@dataclass(frozen=True)
class WriteLogEntry:
    event_at: float
    result: WriteResult


@dataclass(frozen=True)
class QueryLogEntry:
    event_at: float
    retrieved: tuple[RetrievedFact, ...] = field(default=(), repr=False)
    latency_ms: float = 0.0
    error: str | None = None


LogEntry = WriteLogEntry | QueryLogEntry


@dataclass
class RunLog:
    """Custom __repr__ shows only counts and names, never content -- an
    accidental print()/traceback on a real-data RunLog must not leak raw
    facts. This is a checked mitigation (tests/test_privacy.py), not a
    claim that Python enforces module boundaries -- it doesn't."""

    backend_name: str
    workload_name: str
    workload_kind: WorkloadKind
    entries: list[LogEntry] = field(default_factory=list, repr=False)
    incomplete: bool = False

    def __repr__(self) -> str:
        return (
            f"RunLog(backend={self.backend_name!r}, workload={self.workload_name!r}, "
            f"kind={self.workload_kind!r}, n_entries={len(self.entries)}, "
            f"incomplete={self.incomplete})"
        )


@dataclass(frozen=True)
class RateMetric:
    """value is None when n=0 -- 'no data' must never be conflated with a
    true 0.0 rate."""

    value: float | None
    n: int
    ci_low: float | None = None
    ci_high: float | None = None


@dataclass(frozen=True)
class Metrics:
    backend_name: str
    workload_name: str
    workload_kind: WorkloadKind
    state: Literal["reported", "incomplete"]
    n: int
    precision: RateMetric | None = None
    recall: RateMetric | None = None
    stale_rate: RateMetric | None = None
    contradiction_rate: RateMetric | None = None
    tokens_used: int | None = None
    storage_bytes: int | None = None
    latency_ms_median: float | None = None
    latency_ms_iqr_low: float | None = None
    latency_ms_iqr_high: float | None = None
    update_cost_ms_median: float | None = None


@dataclass(frozen=True)
class PublishCell:
    """label is a controlled string built from backend/workload/metric
    names by the renderer -- never raw fact text. scrub() still greps it
    (defense in depth) in case a future edit changes how labels are built."""

    label: str
    value: float
    n: int
    ci_low: float | None = None
    ci_high: float | None = None


@dataclass(frozen=True)
class PublishCandidate:
    cells: tuple[PublishCell, ...]
    generated_at: float
