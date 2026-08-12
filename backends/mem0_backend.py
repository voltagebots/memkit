from __future__ import annotations

import os
import time
from typing import Literal

from harness.models import RetrievedFact, WriteResult
from harness.tokens import count_tokens

# mem0's telemetry defaults to on (PostHog). Payload is IDs/counts, not
# fact content -- but a privacy-focused eval shouldn't silently phone home
# to a third party regardless, so disable it outright. Must be set before
# `import mem0` anywhere in the process (telemetry.py reads the env var at
# module import time) -- module-level here, ahead of every method below.
os.environ.setdefault("MEM0_TELEMETRY", "False")

# Local, fully-offline config: Qdrant on-disk (no cloud vector DB) + Ollama
# for both the extraction LLM and the embedder. Disclosed asymmetry
# (worf/sentinel finding): mem0's own zero-config default is OpenAI-backed,
# so DEFAULT and LOCAL are genuinely different deployments, run and
# reported separately, not silently blended into one number.
_QDRANT_CONFIG = {
    "provider": "qdrant",
    # CORRECTED (live smoke test): mem0's qdrant store defaults to 1536
    # dims (OpenAI's embedding size). nomic-embed-text produces 768-dim
    # vectors -- left at the default, every write raised a shape-mismatch
    # error instead of writing.
    "config": {"path": "/tmp/memkit-eval-qdrant", "embedding_model_dims": 768},
}
_OLLAMA_EMBEDDER_CONFIG = {"provider": "ollama", "config": {"model": "nomic-embed-text"}}

_LOCAL_CONFIG = {
    "vector_store": _QDRANT_CONFIG,
    "llm": {"provider": "ollama", "config": {"model": "llama3.1:8b"}},
    "embedder": _OLLAMA_EMBEDDER_CONFIG,
}

# HYBRID: same local Qdrant store and local Ollama embedder as LOCAL, but
# the fact-extraction/conflict-decision LLM is Claude instead of a local
# 8B model on CPU. A third, separately-labeled deployment (not silently
# blended into LOCAL's "fully offline" claim) -- added because local
# llama3.1:8b inference made a full run take multiple hours; real API
# cost, user's own ANTHROPIC_API_KEY, explicit opt-in per run.
_HYBRID_CONFIG = {
    "vector_store": _QDRANT_CONFIG,
    "llm": {"provider": "anthropic", "config": {"model": "claude-haiku-4-5-20251001"}},
    "embedder": _OLLAMA_EMBEDDER_CONFIG,
}

Mem0Mode = Literal["default", "local", "hybrid"]

_CONFIG_BY_MODE = {"local": _LOCAL_CONFIG, "hybrid": _HYBRID_CONFIG}


class Mem0Backend:
    def __init__(self, mode: Mem0Mode, user_id: str) -> None:
        from mem0 import Memory

        self._mode = mode
        self._user_id = user_id
        config = _CONFIG_BY_MODE.get(mode)
        self._memory = Memory.from_config(config) if config is not None else Memory()

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
