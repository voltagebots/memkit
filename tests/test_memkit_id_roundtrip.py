"""Direct regression test for spock's cross-vendor BLOCKER: memkit's
server-assigned id must round-trip back to the workload's own fact_id,
or every id-based metric scores 0 on every correct retrieval purely from
a namespace mismatch. Uses httpx.MockTransport to control memkit's
response shape precisely -- this tests OUR client's translation logic
against a realistic response, not a mock of memkit's real behavior."""

import httpx

from backends.memkit_backend import MemkitBackend

SERVER_ID = "srv-9f2a1c"


def _mock_memkit_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v1/memories":
            return httpx.Response(200, json={"id": SERVER_ID, "action": "add"})
        if request.method == "GET" and request.url.path == "/v1/memories/search":
            return httpx.Response(
                200, json={"results": [{"id": SERVER_ID, "content": "User works at Acme", "score": 0.95}]}
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    return httpx.MockTransport(handler)


def test_query_returns_workload_fact_id_not_server_id():
    backend = MemkitBackend(base_url="http://test", api_key="dev-key", user_id="u1")
    backend._client = httpx.Client(base_url="http://test", transport=_mock_memkit_transport())

    write_result = backend.write("workload_fact_1", "User works at Acme", at=1.0)
    assert write_result.ok

    retrieved = backend.query("where does the user work", at=2.0)
    assert len(retrieved) == 1
    assert retrieved[0].fact_id == "workload_fact_1"  # NOT "srv-9f2a1c"
    backend.close()


def test_query_falls_back_to_server_id_for_unmapped_result():
    """A result from a write this backend instance didn't make (e.g. a
    pre-existing memory) has no local mapping -- falls back to the raw
    server id rather than raising, since that's still a valid (if
    unscored) identifier."""
    backend = MemkitBackend(base_url="http://test", api_key="dev-key", user_id="u1")
    backend._client = httpx.Client(base_url="http://test", transport=_mock_memkit_transport())

    retrieved = backend.query("anything", at=1.0)
    assert retrieved[0].fact_id == SERVER_ID
    backend.close()


def test_query_handles_top_level_list_response_without_crashing():
    """Regression for the HIGH: a top-level list response must not raise
    AttributeError via a dead-code .get() fallback."""

    def list_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[{"id": SERVER_ID, "content": "x", "score": 0.5}])
        return httpx.Response(200, json={"id": SERVER_ID, "action": "add"})

    backend = MemkitBackend(base_url="http://test", api_key="dev-key", user_id="u1")
    backend._client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(list_handler))

    retrieved = backend.query("anything", at=1.0)  # must not raise
    assert len(retrieved) == 1
    backend.close()
