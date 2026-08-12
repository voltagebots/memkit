from harness.models import GoldAnswer, RetrievedFact, Workload, WorkloadEvent, WriteResult
from harness.replay import replay_workload
from harness.score import score_run
from harness.scoring_stats import wilson_ci


class FakeBackend:
    """Deterministic in-memory backend for testing the harness's own
    control flow, not a mock of a real integration -- appropriate here
    since replay.py/score.py's correctness is independent of which real
    backend is plugged in."""

    def __init__(self, retrieved_by_query: dict[str, list[RetrievedFact]]) -> None:
        self._retrieved_by_query = retrieved_by_query
        self.writes: list[tuple[str, str]] = []

    def write(self, fact_id, text, at):
        self.writes.append((fact_id, text))
        return WriteResult(ok=True, latency_ms=1.0, token_count=len((text or "").split()))

    def query(self, text, at):
        return self._retrieved_by_query.get(text, [])

    def storage_bytes(self):
        return 0


class RaisingBackend:
    def write(self, fact_id, text, at):
        raise RuntimeError("backend down")

    def query(self, text, at):
        raise RuntimeError("backend down")

    def storage_bytes(self):
        return 0


def test_replay_records_write_and_query_entries():
    backend = FakeBackend({"q1": [RetrievedFact(fact_id="f1", text="x", score=0.9)]})
    workload = Workload(
        name="w",
        kind="synthetic",
        events=(
            WorkloadEvent(kind="write", at=1.0, fact_id="f1", fact_text="fact one"),
            WorkloadEvent(kind="query", at=2.0, query_text="q1", gold=GoldAnswer(exact_ids=frozenset({"f1"}))),
        ),
    )
    run_log = replay_workload(backend, workload)
    assert len(run_log.entries) == 2
    assert not run_log.incomplete


def test_replay_backend_name_defaults_to_class_name():
    backend = FakeBackend({})
    workload = Workload(name="w", kind="synthetic", events=())
    run_log = replay_workload(backend, workload)
    assert run_log.backend_name == "FakeBackend"


def test_replay_backend_name_override_prevents_config_conflation():
    """Regression: a single class run under different configs (e.g.
    Mem0Backend's local/hybrid/default modes) must not silently share one
    backend_name -- that would blend genuinely different deployments'
    Metrics under one identity."""
    backend = FakeBackend({})
    workload = Workload(name="w", kind="synthetic", events=())
    run_log = replay_workload(backend, workload, backend_name="FakeBackend(special-mode)")
    assert run_log.backend_name == "FakeBackend(special-mode)"


def test_replay_marks_incomplete_on_backend_error():
    workload = Workload(
        name="w", kind="synthetic", events=(WorkloadEvent(kind="write", at=1.0, fact_id="f1", fact_text="x"),)
    )
    run_log = replay_workload(RaisingBackend(), workload)
    assert run_log.incomplete
    assert run_log.entries[0].result.error == "backend down"


def test_score_incomplete_run_produces_incomplete_metrics():
    workload = Workload(
        name="w", kind="synthetic", events=(WorkloadEvent(kind="write", at=1.0, fact_id="f1", fact_text="x"),)
    )
    run_log = replay_workload(RaisingBackend(), workload)
    metrics = score_run(run_log, workload)
    assert metrics.state == "incomplete"


def test_score_precision_recall_exact_match():
    backend = FakeBackend({"where": [RetrievedFact(fact_id="f1", text="Acme", score=0.9)]})
    workload = Workload(
        name="w",
        kind="synthetic",
        events=(
            WorkloadEvent(kind="write", at=1.0, fact_id="f1", fact_text="works at Acme"),
            WorkloadEvent(kind="query", at=2.0, query_text="where", gold=GoldAnswer(exact_ids=frozenset({"f1"}))),
        ),
    )
    run_log = replay_workload(backend, workload)
    metrics = score_run(run_log, workload)
    assert metrics.precision.value == 1.0
    assert metrics.recall.value == 1.0
    assert metrics.n == 1


def test_score_stale_rate_detects_surfaced_stale_fact():
    backend = FakeBackend({"where": [RetrievedFact(fact_id="f_old", text="Google", score=0.9)]})
    workload = Workload(
        name="w",
        kind="synthetic",
        events=(
            WorkloadEvent(kind="write", at=1.0, fact_id="f_old", fact_text="works at Google"),
            WorkloadEvent(kind="write", at=2.0, fact_id="f_new", fact_text="works at OpenAI"),
            WorkloadEvent(
                kind="query",
                at=3.0,
                query_text="where",
                gold=GoldAnswer(exact_ids=frozenset({"f_new"}), stale_ids_that_must_not_surface=frozenset({"f_old"})),
            ),
        ),
    )
    run_log = replay_workload(backend, workload)
    metrics = score_run(run_log, workload)
    assert metrics.stale_rate.value == 1.0
    # current fact never surfaced alongside it in this fixture -> no contradiction
    assert metrics.contradiction_rate.value == 0.0


def test_score_contradiction_requires_both_current_and_stale_together():
    backend = FakeBackend(
        {
            "where": [
                RetrievedFact(fact_id="f_old", text="Google", score=0.9),
                RetrievedFact(fact_id="f_new", text="OpenAI", score=0.8),
            ]
        }
    )
    workload = Workload(
        name="w",
        kind="synthetic",
        events=(
            WorkloadEvent(
                kind="query",
                at=1.0,
                query_text="where",
                gold=GoldAnswer(exact_ids=frozenset({"f_new"}), stale_ids_that_must_not_surface=frozenset({"f_old"})),
            ),
        ),
    )
    run_log = replay_workload(backend, workload)
    metrics = score_run(run_log, workload)
    assert metrics.contradiction_rate.value == 1.0


def test_score_zero_n_is_none_not_zero():
    backend = FakeBackend({})
    workload = Workload(name="w", kind="synthetic", events=())
    run_log = replay_workload(backend, workload)
    metrics = score_run(run_log, workload)
    assert metrics.precision is None
    assert metrics.stale_rate is None


def test_wilson_ci_n_zero_returns_none():
    result = wilson_ci(0, 0)
    assert result.value is None
    assert result.n == 0


def test_wilson_ci_reasonable_bounds_at_small_n():
    result = wilson_ci(successes=5, n=10)
    assert result.value == 0.5
    assert 0.0 <= result.ci_low < 0.5 < result.ci_high <= 1.0
