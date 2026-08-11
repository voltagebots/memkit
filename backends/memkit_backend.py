from __future__ import annotations

import time

import httpx

from harness.models import RetrievedFact, WriteResult
from harness.tokens import count_tokens


class MemkitBackend:
    """Calls a real, running memkit instance over HTTP -- no mocking of
    its API. Requires `sme-agent-eval` (or any) tenant key already
    provisioned in the target instance's MEMKIT_API_KEYS."""

    def __init__(self, base_url: str, api_key: str, user_id: str, timeout_s: float = 10.0) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_s,
        )
        self._user_id = user_id

    def write(self, fact_id: str, text: str, at: float) -> WriteResult:
        start = time.perf_counter()
        try:
            resp = self._client.post("/v1/memories", json={"user_id": self._user_id, "content": text})
            resp.raise_for_status()
        except httpx.HTTPError as err:
            latency_ms = (time.perf_counter() - start) * 1000
            return WriteResult(ok=False, latency_ms=latency_ms, token_count=count_tokens(text), error=str(err))
        latency_ms = (time.perf_counter() - start) * 1000
        return WriteResult(ok=True, latency_ms=latency_ms, token_count=count_tokens(text))

    def query(self, text: str, at: float) -> list[RetrievedFact]:
        resp = self._client.get("/v1/memories/search", params={"user_id": self._user_id, "q": text})
        resp.raise_for_status()
        results = resp.json().get("results", resp.json() if isinstance(resp.json(), list) else [])
        return [
            RetrievedFact(fact_id=r.get("id"), text=r.get("content", ""), score=r.get("score", 0.0)) for r in results
        ]

    def storage_bytes(self) -> int:
        # memkit has no size-report endpoint today -- real gap, not faked.
        # Callers needing this metric must measure the server's own SQLite
        # file size directly (only possible for a locally-run instance).
        raise NotImplementedError("memkit has no storage-size API; measure the server's SQLite file directly")

    def close(self) -> None:
        self._client.close()
