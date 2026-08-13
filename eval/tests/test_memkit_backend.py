import httpx
import pytest

from backends.memkit_backend import MemkitBackend

MEMKIT_URL = "http://localhost:8080"


def _memkit_reachable() -> bool:
    try:
        httpx.get(f"{MEMKIT_URL}/healthz", timeout=1.0).raise_for_status()
        return True
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(not _memkit_reachable(), reason="no memkit instance running at localhost:8080")
def test_write_and_query_real_memkit():
    backend = MemkitBackend(base_url=MEMKIT_URL, api_key="dev-key", user_id="memkit-eval-smoke")
    result = backend.write("f1", "User works at Acme", at=1.0)
    assert result.ok

    retrieved = backend.query("where does the user work", at=2.0)
    assert any("Acme" in r.text for r in retrieved)
    backend.close()
