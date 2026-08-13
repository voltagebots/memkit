from pathlib import Path

from harness.models import Metrics, RetrievedFact, WorkloadEvent, WriteResult
from harness.models import Workload as Wl
from scripts import run_evaluation
from scripts.run_evaluation import _run_pair


class AlwaysFailsBackend:
    def write(self, fact_id, text, at):
        return WriteResult(ok=False, latency_ms=0.0, token_count=0, error="still broken")

    def query(self, text, at):
        return [RetrievedFact(fact_id="x", text="x", score=0.0)]

    def storage_bytes(self):
        return 0


def test_resume_skips_a_finished_pair(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(run_evaluation, "CHECKPOINT_PATH", tmp_path / "checkpoint.jsonl")
    done_metrics = {
        "Backend::w": Metrics(
            backend_name="Backend", workload_name="w", workload_kind="synthetic", state="reported", n=5
        )
    }
    workload = Wl(name="w", kind="synthetic", events=())
    metrics, run_log = _run_pair("Backend", None, workload, done_metrics)
    assert metrics.n == 5
    assert run_log is None


def test_resume_does_not_skip_a_failed_pair(tmp_path: Path, monkeypatch):
    """Regression: a checkpointed state='incomplete' result is a *failed*
    attempt (e.g. every hybrid-mode write failing on a billing error), not
    a finished one -- caching it as done would silently skip retry forever,
    even after the underlying problem is fixed."""
    monkeypatch.setattr(run_evaluation, "CHECKPOINT_PATH", tmp_path / "checkpoint.jsonl")
    done_metrics = {
        "Backend::w": Metrics(
            backend_name="Backend", workload_name="w", workload_kind="synthetic", state="incomplete", n=0
        )
    }
    workload = Wl(name="w", kind="synthetic", events=(WorkloadEvent(kind="write", at=1.0, fact_id="f", fact_text="x"),))
    metrics, run_log = _run_pair("Backend", AlwaysFailsBackend(), workload, done_metrics)
    assert run_log is not None  # must have actually retried, not returned the cached failure
