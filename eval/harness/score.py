from __future__ import annotations

import statistics

from harness.models import Metrics, QueryLogEntry, RunLog, Workload, WriteLogEntry
from harness.scoring_stats import wilson_ci


def score_run(run_log: RunLog, workload: Workload) -> Metrics:
    """The privacy chokepoint: the only function that turns raw (possibly
    real, possibly private) data into aggregate numbers. An incomplete
    RunLog produces state="incomplete", never a "reported" Metrics --
    build_publish_candidate refuses anything but "reported"."""
    if run_log.incomplete:
        return Metrics(
            backend_name=run_log.backend_name,
            workload_name=run_log.workload_name,
            workload_kind=run_log.workload_kind,
            state="incomplete",
            n=0,
        )

    write_entries = [e for e in run_log.entries if isinstance(e, WriteLogEntry)]
    query_entries_with_gold = [
        (event, e)
        for event, e in zip(workload.events, run_log.entries, strict=True)
        if isinstance(e, QueryLogEntry) and event.gold is not None
    ]

    precision, recall = _score_precision_recall(query_entries_with_gold)
    stale_rate, contradiction_rate = _score_stale_and_contradiction(query_entries_with_gold)

    # CORRECTED (spock LOW): latency_ms previously mixed write and query
    # latencies into one number, even though update_cost_ms already
    # exists as a separate write-only metric -- "Retrieval latency" and
    # "Update cost" are listed as distinct metrics in this project's own
    # evaluation design; conflating them here was redundant with, and
    # inconsistent with, that split. latency_ms is now query-only.
    latencies = [e.latency_ms for _, e in query_entries_with_gold if isinstance(e, QueryLogEntry)]
    update_latencies = [e.result.latency_ms for e in write_entries]

    return Metrics(
        backend_name=run_log.backend_name,
        workload_name=run_log.workload_name,
        workload_kind=run_log.workload_kind,
        state="reported",
        n=len(query_entries_with_gold),
        precision=precision,
        recall=recall,
        stale_rate=stale_rate,
        contradiction_rate=contradiction_rate,
        tokens_used=sum(e.result.token_count for e in write_entries) or None,
        latency_ms_median=statistics.median(latencies) if latencies else None,
        latency_ms_iqr_low=_percentile(latencies, 25) if len(latencies) >= 4 else None,
        latency_ms_iqr_high=_percentile(latencies, 75) if len(latencies) >= 4 else None,
        update_cost_ms_median=statistics.median(update_latencies) if update_latencies else None,
    )


def _score_precision_recall(query_entries_with_gold):
    """Exact-match scoring -- meaningful only for the synthetic workload,
    where GoldAnswer.exact_ids is populated. Real workloads use
    stale_ids_that_must_not_surface instead (direction-only, per C1) and
    naturally score 0 contributions here."""
    precisions, recalls = [], []
    for event, entry in query_entries_with_gold:
        if event.gold.exact_ids is None:
            continue
        retrieved_ids = {r.fact_id for r in entry.retrieved}
        true_positives = retrieved_ids & event.gold.exact_ids
        if retrieved_ids:
            precisions.append(len(true_positives) / len(retrieved_ids))
        if event.gold.exact_ids:
            recalls.append(len(true_positives) / len(event.gold.exact_ids))
    precision = wilson_ci(sum(1 for p in precisions if p >= 1.0), len(precisions)) if precisions else None
    recall = wilson_ci(sum(1 for r in recalls if r >= 1.0), len(recalls)) if recalls else None
    return precision, recall


def _score_stale_and_contradiction(query_entries_with_gold):
    """stale_rate: a query surfaced a fact flagged stale, at all.
    contradiction_rate: a query surfaced BOTH the current fact AND a
    stale one it should have superseded, in the same retrieval -- the
    operational definition this harness uses (event.gold.exact_ids as
    "current", event.gold.stale_ids_that_must_not_surface as "stale",
    both drawn from the same GoldAnswer)."""
    stale_hits, contradiction_hits, n = 0, 0, 0
    for event, entry in query_entries_with_gold:
        if event.gold.stale_ids_that_must_not_surface is None:
            continue
        n += 1
        retrieved_ids = {r.fact_id for r in entry.retrieved}
        surfaced_stale = bool(retrieved_ids & event.gold.stale_ids_that_must_not_surface)
        surfaced_current = bool(retrieved_ids & (event.gold.exact_ids or frozenset()))
        if surfaced_stale:
            stale_hits += 1
        if surfaced_stale and surfaced_current:
            contradiction_hits += 1
    stale_rate = wilson_ci(stale_hits, n) if n else None
    contradiction_rate = wilson_ci(contradiction_hits, n) if n else None
    return stale_rate, contradiction_rate


def _percentile(values: list[float], pct: float) -> float:
    sorted_values = sorted(values)
    k = (len(sorted_values) - 1) * (pct / 100)
    f, c = int(k), min(int(k) + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)
