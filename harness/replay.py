from __future__ import annotations

import time

from backends import MemoryBackend
from harness.models import QueryLogEntry, RunLog, Workload, WriteLogEntry, WriteResult
from harness.tokens import count_tokens


def replay_workload(backend: MemoryBackend, workload: Workload) -> RunLog:
    """The only function that calls backends directly. A backend failure
    is recorded explicitly as a typed error entry, never silently
    skipped -- a silently-incomplete RunLog would produce a Metrics
    object that looks complete but isn't."""
    run_log = RunLog(backend_name=type(backend).__name__, workload_name=workload.name, workload_kind=workload.kind)

    for event in workload.events:
        if event.kind == "write":
            _replay_write(backend, event, run_log)
        else:
            _replay_query(backend, event, run_log)

    return run_log


def _replay_write(backend: MemoryBackend, event, run_log: RunLog) -> None:
    try:
        result = backend.write(event.fact_id, event.fact_text, at=event.at)
    except Exception as err:
        run_log.incomplete = True
        failed = WriteResult(ok=False, latency_ms=0.0, token_count=count_tokens(event.fact_text or ""), error=str(err))
        run_log.entries.append(WriteLogEntry(event_at=event.at, result=failed))
        return
    run_log.entries.append(WriteLogEntry(event_at=event.at, result=result))


def _replay_query(backend: MemoryBackend, event, run_log: RunLog) -> None:
    start = time.perf_counter()
    try:
        retrieved = backend.query(event.query_text, at=event.at)
    except Exception as err:
        run_log.incomplete = True
        run_log.entries.append(QueryLogEntry(event_at=event.at, retrieved=(), latency_ms=0.0, error=str(err)))
        return
    latency_ms = (time.perf_counter() - start) * 1000
    run_log.entries.append(QueryLogEntry(event_at=event.at, retrieved=tuple(retrieved), latency_ms=latency_ms))
