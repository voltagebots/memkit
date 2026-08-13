"""Event-level resume for replay_workload -- the pair-level checkpoint in
harness/checkpoint.py only protects already-*finished* (backend, workload)
pairs. Mem0Backend(local)'s single synthetic-workload pair takes hours as
one unit; if killed mid-way, pair-level checkpointing salvages nothing for
it. This persists one line per completed event, immediately, so a kill
mid-run loses at most the one in-flight event.

Only safe to use for backends whose state survives a process restart on
its own (MemkitBackend, Mem0Backend -- external store keyed by user_id).
For a pure in-memory backend (RawHistoryBackend, LocalVectorBackend),
skipping "already-done" write events on resume would leave the backend's
in-process state empty while pretending those facts exist -- callers must
not pass a checkpoint_path for those."""

from __future__ import annotations

import json
from pathlib import Path

from harness.models import LogEntry, QueryLogEntry, RetrievedFact, WriteLogEntry, WriteResult

EVENT_CHECKPOINT_PATH = Path(__file__).parent.parent / "data" / "private" / "event_checkpoint.jsonl"


def _entry_to_dict(entry: LogEntry) -> dict:
    if isinstance(entry, WriteLogEntry):
        return {
            "type": "write",
            "event_at": entry.event_at,
            "result": {
                "ok": entry.result.ok,
                "latency_ms": entry.result.latency_ms,
                "token_count": entry.result.token_count,
                "error": entry.result.error,
            },
        }
    return {
        "type": "query",
        "event_at": entry.event_at,
        "retrieved": [{"fact_id": r.fact_id, "text": r.text, "score": r.score} for r in entry.retrieved],
        "latency_ms": entry.latency_ms,
        "error": entry.error,
    }


def _entry_from_dict(d: dict) -> LogEntry:
    if d["type"] == "write":
        r = d["result"]
        return WriteLogEntry(
            event_at=d["event_at"],
            result=WriteResult(ok=r["ok"], latency_ms=r["latency_ms"], token_count=r["token_count"], error=r["error"]),
        )
    return QueryLogEntry(
        event_at=d["event_at"],
        retrieved=tuple(RetrievedFact(fact_id=r["fact_id"], text=r["text"], score=r["score"]) for r in d["retrieved"]),
        latency_ms=d["latency_ms"],
        error=d["error"],
    )


def append_event_checkpoint(path: Path, key: str, event_index: int, entry: LogEntry) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"key": key, "event_index": event_index, "entry": _entry_to_dict(entry)}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def load_event_checkpoint(path: Path, key: str) -> dict[int, LogEntry]:
    """Returns {event_index: entry} for the given key. A later line for the
    same (key, event_index) overwrites an earlier one -- last write wins,
    matching append-only-log semantics for a retried event."""
    if not path.exists():
        return {}
    out: dict[int, LogEntry] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["key"] != key:
            continue
        out[row["event_index"]] = _entry_from_dict(row["entry"])
    return out
