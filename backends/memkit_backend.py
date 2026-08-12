from __future__ import annotations

import time

import httpx

from harness.models import RetrievedFact, WriteResult
from harness.tokens import count_tokens


class MemkitBackend:
    """Calls a real, running memkit instance over HTTP -- no mocking of
    its API. Requires `sme-agent-eval` (or any) tenant key already
    provisioned in the target instance's MEMKIT_API_KEYS."""

    def __init__(self, base_url: str, api_key: str, user_id: str, timeout_s: float = 10.0, top_k: int = 5) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_s,
        )
        self._user_id = user_id
        self._top_k = top_k
        # CORRECTED (spock cross-vendor BLOCKER): memkit's write API has no
        # client-supplied id field -- it returns a server-assigned uuid,
        # which can never match the workload's own gold fact_ids. Without
        # this map, MemKit would score 0 on every id-based metric
        # (precision/recall/stale_rate/contradiction_rate) on every
        # correct retrieval, purely from an id-namespace mismatch -- not a
        # real quality difference. This map translates memkit's server id
        # back to the workload's fact_id at query time.
        self._server_id_to_fact_id: dict[str, str] = {}

    def write(self, fact_id: str, text: str, at: float) -> WriteResult:
        start = time.perf_counter()
        try:
            resp = self._client.post("/v1/memories", json={"user_id": self._user_id, "content": text})
            resp.raise_for_status()
            server_id = resp.json().get("id")
            if server_id is not None:
                self._server_id_to_fact_id[server_id] = fact_id
        except httpx.HTTPError as err:
            latency_ms = (time.perf_counter() - start) * 1000
            return WriteResult(ok=False, latency_ms=latency_ms, token_count=count_tokens(text), error=str(err))
        latency_ms = (time.perf_counter() - start) * 1000
        return WriteResult(ok=True, latency_ms=latency_ms, token_count=count_tokens(text))

    def query(self, text: str, at: float) -> list[RetrievedFact]:
        resp = self._client.get(
            "/v1/memories/search", params={"user_id": self._user_id, "q": text, "limit": self._top_k}
        )
        resp.raise_for_status()
        # CORRECTED (spock HIGH): the old fallback `data.get(..., data if
        # isinstance(data, list) else [])` evaluated .get() on `data`
        # first, raising AttributeError before the list branch was ever
        # reached if the server ever returned a bare top-level array.
        # replay.py's try/except then silently marked the run incomplete,
        # dropping memkit from the comparison instead of surfacing the
        # shape mismatch.
        data = resp.json()
        results = data.get("memories", []) if isinstance(data, dict) else data
        return [
            RetrievedFact(
                fact_id=self._server_id_to_fact_id.get(r.get("id"), r.get("id")),
                text=r.get("content", ""),
                score=r.get("score", 0.0),
            )
            for r in results
        ]

    def storage_bytes(self) -> int:
        # memkit has no size-report endpoint today -- real gap, not faked.
        # Callers needing this metric must measure the server's own SQLite
        # file size directly (only possible for a locally-run instance).
        raise NotImplementedError("memkit has no storage-size API; measure the server's SQLite file directly")

    def close(self) -> None:
        self._client.close()
