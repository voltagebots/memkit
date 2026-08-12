import os

import pytest

pytest.importorskip("mem0")


def _ollama_has(model: str) -> bool:
    try:
        import httpx

        resp = httpx.get("http://localhost:11434/api/tags", timeout=1.0)
        resp.raise_for_status()
        return any(m["name"].startswith(model) for m in resp.json().get("models", []))
    except Exception:
        return False


@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
def test_write_and_query_mem0_default():
    from backends.mem0_backend import Mem0Backend

    backend = Mem0Backend(mode="default", user_id="memkit-eval-smoke")
    result = backend.write("f1", "User works at Acme", at=1.0)
    assert result.ok
    retrieved = backend.query("where does the user work", at=2.0)
    assert len(retrieved) > 0


@pytest.mark.skipif(
    not (_ollama_has("llama3.1") and _ollama_has("nomic-embed-text")),
    reason="local mem0 config needs `ollama pull llama3.1:8b` and `ollama pull nomic-embed-text`",
)
def test_write_and_query_mem0_local():
    from backends.mem0_backend import Mem0Backend

    backend = Mem0Backend(mode="local", user_id="memkit-eval-smoke")
    try:
        result = backend.write("f1", "User works at Acme", at=1.0)
        assert result.ok
        retrieved = backend.query("where does the user work", at=2.0)
        assert len(retrieved) > 0
    finally:
        backend.close()


@pytest.mark.skipif(
    not _ollama_has("nomic-embed-text"),
    reason="local qdrant + embedder needs `ollama pull nomic-embed-text`",
)
def test_close_releases_the_qdrant_lock_for_the_next_instance():
    """Regression: creating a fresh Mem0Backend per workload (this harness's
    own per-workload isolation pattern in run_evaluation.py) crashed the
    second instance with "Storage folder ... is already accessed by another
    instance of Qdrant client" -- close() didn't release the on-disk
    Qdrant client's exclusive file lock, only the unrelated SQLite history
    connection Memory.close() actually touches."""
    from backends.mem0_backend import Mem0Backend

    first = Mem0Backend(mode="local", user_id="memkit-eval-lock-test-1")
    first.close()

    # Must not raise -- the whole point of close() is that a second
    # instance can now open the same on-disk path.
    second = Mem0Backend(mode="local", user_id="memkit-eval-lock-test-2")
    second.close()
