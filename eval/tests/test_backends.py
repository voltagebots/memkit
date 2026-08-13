import pytest

from backends.raw_history import RawHistoryBackend


def test_raw_history_returns_most_recent_first():
    backend = RawHistoryBackend(return_last_n=2)
    backend.write("f1", "User works at Acme", at=1.0)
    backend.write("f2", "User works at Beta", at=2.0)
    backend.write("f3", "User works at Gamma", at=3.0)

    results = backend.query("where does the user work", at=4.0)

    assert [r.fact_id for r in results] == ["f3", "f2"]


def test_raw_history_storage_bytes_grows_with_writes():
    backend = RawHistoryBackend()
    before = backend.storage_bytes()
    backend.write("f1", "some fact text", at=1.0)
    after = backend.storage_bytes()
    assert after > before


def test_raw_history_write_returns_real_token_count():
    backend = RawHistoryBackend()
    result = backend.write("f1", "User works at Acme Corp", at=1.0)
    assert result.ok
    assert result.token_count > 0


@pytest.mark.slow
def test_local_vector_ranks_semantically_similar_higher():
    try:
        from backends.local_vector import LocalVectorBackend
    except Exception as err:  # pragma: no cover - real dependency missing
        pytest.skip(f"sentence-transformers model unavailable: {err}")

    backend = LocalVectorBackend(top_k=2)
    backend.write("f1", "The user's favorite coffee is a cortado", at=1.0)
    backend.write("f2", "The user's dentist appointment is on Tuesday", at=2.0)

    results = backend.query("what coffee does the user like", at=3.0)

    assert results[0].fact_id == "f1"
