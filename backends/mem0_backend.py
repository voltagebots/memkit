from __future__ import annotations

import time
from typing import Literal

from harness.models import RetrievedFact, WriteResult
from harness.tokens import count_tokens

# Local, fully-offline config: Qdrant on-disk (no cloud vector DB) + Ollama
# for both the extraction LLM and the embedder. Disclosed asymmetry
# (worf/sentinel finding): mem0's own zero-config default is OpenAI-backed,
# so DEFAULT and LOCAL are genuinely different deployments, run and
# reported separately, not silently blended into one number.
_LOCAL_CONFIG = {
    "vector_store": {"provider": "qdrant", "config": {"path": "/tmp/memkit-eval-qdrant"}},
    "llm": {"provider": "ollama", "config": {"model": "llama3.1:8b"}},
    "embedder": {"provider": "ollama", "config": {"model": "nomic-embed-text"}},
}

Mem0Mode = Literal["default", "local"]


class Mem0Backend:
    def __init__(self, mode: Mem0Mode, user_id: str) -> None:
        from mem0 import Memory

        self._mode = mode
        self._user_id = user_id
        self._memory = Memory.from_config(_LOCAL_CONFIG) if mode == "local" else Memory()

    def write(self, fact_id: str, text: str, at: float) -> WriteResult:
        start = time.perf_counter()
        try:
            self._memory.add(text, user_id=self._user_id, metadata={"fact_id": fact_id})
        except Exception as err:  # mem0/provider errors are not enumerable in advance
            latency_ms = (time.perf_counter() - start) * 1000
            return WriteResult(ok=False, latency_ms=latency_ms, token_count=count_tokens(text), error=str(err))
        latency_ms = (time.perf_counter() - start) * 1000
        return WriteResult(ok=True, latency_ms=latency_ms, token_count=count_tokens(text))

    def query(self, text: str, at: float) -> list[RetrievedFact]:
        result = self._memory.search(text, filters={"user_id": self._user_id})
        rows = result.get("results", []) if isinstance(result, dict) else result
        return [
            RetrievedFact(
                fact_id=(r.get("metadata") or {}).get("fact_id", r.get("id")),
                text=r.get("memory", ""),
                score=r.get("score", 0.0),
            )
            for r in rows
        ]

    def storage_bytes(self) -> int:
        # mem0's OSS library has no size-report API either -- same honest
        # gap as MemkitBackend, not faked.
        raise NotImplementedError("mem0 has no storage-size API; measure the vector store's on-disk size directly")
