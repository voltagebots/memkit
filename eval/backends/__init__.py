from __future__ import annotations

from typing import Protocol

from harness.models import RetrievedFact, WriteResult


class MemoryBackend(Protocol):
    def write(self, fact_id: str, text: str, at: float) -> WriteResult: ...
    def query(self, text: str, at: float) -> list[RetrievedFact]: ...
    def storage_bytes(self) -> int: ...
