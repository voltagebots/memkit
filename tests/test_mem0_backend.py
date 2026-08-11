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
    result = backend.write("f1", "User works at Acme", at=1.0)
    assert result.ok
    retrieved = backend.query("where does the user work", at=2.0)
    assert len(retrieved) > 0
