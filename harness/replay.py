from __future__ import annotations

import time
from pathlib import Path

from backends import MemoryBackend
from harness.event_checkpoint import append_event_checkpoint, load_event_checkpoint
from harness.models import LogEntry, QueryLogEntry, RunLog, Workload, WriteLogEntry, WriteResult
from harness.tokens import count_tokens


def _entry_is_failed(entry: LogEntry) -> bool:
    if isinstance(entry, WriteLogEntry):
        return not entry.result.ok
    return entry.error is not None


def replay_workload(
    backend: MemoryBackend,
    workload: Workload,
    *,
    checkpoint_path: Path | None = None,
    resume_key: str | None = None,
    backend_name: str | None = None,
) -> RunLog:
    """The only function that calls backends directly. A backend failure
    is recorded explicitly as a typed error entry, never silently
    skipped -- a silently-incomplete RunLog would produce a Metrics
    object that looks complete but isn't.

    checkpoint_path/resume_key enable event-level resume: each completed
    event is persisted immediately, so a kill mid-workload loses at most
    one in-flight event rather than the whole (backend, workload) pair.
    Only safe for backends whose state survives a process restart on its
    own (external store keyed by user_id) -- callers must not pass this
    for a pure in-memory backend, since resuming would skip write events
    whose effect was never actually persisted anywhere.

    backend_name defaults to type(backend).__name__, but callers running
    the same class under different configs (Mem0Backend's local/hybrid/
    default modes -- one class, three deployments) must pass an explicit
    override, or the resulting Metrics would silently blend configs under
    one identity, contradicting the disclosed-separation principle applied
    everywhere else in this harness."""
    resolved_name = backend_name if backend_name is not None else type(backend).__name__
    run_log = RunLog(backend_name=resolved_name, workload_name=workload.name, workload_kind=workload.kind)
    resumable = checkpoint_path is not None and resume_key is not None
    existing = load_event_checkpoint(checkpoint_path, resume_key) if resumable else {}

    for i, event in enumerate(workload.events):
        already_done = i in existing
        if already_done:
            entry = existing[i]
        elif event.kind == "write":
            entry = _replay_write(backend, event)
        else:
            entry = _replay_query(backend, event)

        if not already_done and resumable:
            append_event_checkpoint(checkpoint_path, resume_key, i, entry)

        run_log.entries.append(entry)
        if _entry_is_failed(entry):
            run_log.incomplete = True

    return run_log


def _replay_write(backend: MemoryBackend, event) -> WriteLogEntry:
    try:
        result = backend.write(event.fact_id, event.fact_text, at=event.at)
    except Exception as err:
        failed = WriteResult(ok=False, latency_ms=0.0, token_count=count_tokens(event.fact_text or ""), error=str(err))
        return WriteLogEntry(event_at=event.at, result=failed)
    return WriteLogEntry(event_at=event.at, result=result)


def _replay_query(backend: MemoryBackend, event) -> QueryLogEntry:
    start = time.perf_counter()
    try:
        retrieved = backend.query(event.query_text, at=event.at)
    except Exception as err:
        return QueryLogEntry(event_at=event.at, retrieved=(), latency_ms=0.0, error=str(err))
    latency_ms = (time.perf_counter() - start) * 1000
    return QueryLogEntry(event_at=event.at, retrieved=tuple(retrieved), latency_ms=latency_ms)
