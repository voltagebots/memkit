from __future__ import annotations

import time

from harness.models import RetrievedFact, WriteResult
from harness.tokens import count_tokens


class RawHistoryBackend:
    """The floor baseline -- no conflict resolution, no ranking. A query
    just returns the N most recent facts verbatim, the way a naive agent
    dumping raw conversation history into context would. Beating this
    proves only that a system does more than nothing; it's an existence
    check, not evidence of quality (worf finding C2)."""

    def __init__(self, return_last_n: int = 5) -> None:
        self._return_last_n = return_last_n
        self._facts: list[tuple[str, str]] = []  # (fact_id, text), in write order

    def write(self, fact_id: str, text: str, at: float) -> WriteResult:
        start = time.perf_counter()
        self._facts.append((fact_id, text))
        latency_ms = (time.perf_counter() - start) * 1000
        return WriteResult(ok=True, latency_ms=latency_ms, token_count=count_tokens(text))

    def query(self, text: str, at: float) -> list[RetrievedFact]:
        recent = self._facts[-self._return_last_n :]
        return [RetrievedFact(fact_id=fid, text=t, score=0.0) for fid, t in reversed(recent)]

    def storage_bytes(self) -> int:
        return sum(len(fid.encode("utf-8")) + len(t.encode("utf-8")) for fid, t in self._facts)
