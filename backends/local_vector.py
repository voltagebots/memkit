from __future__ import annotations

import time

import numpy as np

from harness.models import RetrievedFact, WriteResult
from harness.tokens import count_tokens

_MODEL_NAME = "all-MiniLM-L6-v2"
_model = None  # lazy singleton -- loading a real embedding model has real startup cost


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(_MODEL_NAME)
    return _model


class LocalVectorBackend:
    """This is the SCIENTIFICALLY CORRECT control for MemKit's actual
    thesis (worf finding C2): same real embedding-based retrieval, no
    write-time conflict resolution at all. If MemKit beats this, that is
    evidence write-time conflict resolution matters. Beating the no-op
    RawHistoryBackend is not."""

    def __init__(self, top_k: int = 5) -> None:
        self._top_k = top_k
        self._facts: list[tuple[str, str]] = []  # (fact_id, text)
        self._vectors: list[np.ndarray] = []

    def write(self, fact_id: str, text: str, at: float) -> WriteResult:
        start = time.perf_counter()
        vec = _get_model().encode(text, normalize_embeddings=True)
        self._facts.append((fact_id, text))
        self._vectors.append(vec)
        latency_ms = (time.perf_counter() - start) * 1000
        return WriteResult(ok=True, latency_ms=latency_ms, token_count=count_tokens(text))

    def query(self, text: str, at: float) -> list[RetrievedFact]:
        if not self._vectors:
            return []
        q_vec = _get_model().encode(text, normalize_embeddings=True)
        scores = np.array(self._vectors) @ q_vec  # cosine similarity, vectors already normalized
        top_indices = np.argsort(-scores)[: self._top_k]
        return [
            RetrievedFact(fact_id=self._facts[i][0], text=self._facts[i][1], score=float(scores[i]))
            for i in top_indices
        ]

    def storage_bytes(self) -> int:
        text_bytes = sum(len(fid.encode("utf-8")) + len(t.encode("utf-8")) for fid, t in self._facts)
        vector_bytes = sum(v.nbytes for v in self._vectors)
        return text_bytes + vector_bytes
