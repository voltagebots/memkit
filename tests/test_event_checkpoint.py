from pathlib import Path

from harness.models import GoldAnswer, RetrievedFact, Workload, WorkloadEvent, WriteResult
from harness.replay import replay_workload


class CountingBackend:
    """Same shape as FakeBackend in test_replay_and_score.py, plus a call
    counter -- the whole point of resume is that a resumed event does NOT
    call the backend again."""

    def __init__(self) -> None:
        self.write_calls = 0
        self.query_calls = 0

    def write(self, fact_id, text, at):
        self.write_calls += 1
        return WriteResult(ok=True, latency_ms=1.0, token_count=1)

    def query(self, text, at):
        self.query_calls += 1
        return [RetrievedFact(fact_id="f_new", text="current", score=1.0)]

    def storage_bytes(self):
        return 0


def _workload() -> Workload:
    return Workload(
        name="resume_test",
        kind="real",
        events=(
            WorkloadEvent(kind="write", at=1.0, fact_id="f_old", fact_text="old fact"),
            WorkloadEvent(kind="write", at=2.0, fact_id="f_new", fact_text="new fact"),
            WorkloadEvent(
                kind="query",
                at=3.0,
                query_text="what is true",
                gold=GoldAnswer(exact_ids=frozenset({"f_new"}), stale_ids_that_must_not_surface=frozenset({"f_old"})),
            ),
        ),
    )


def test_resume_skips_already_checkpointed_events(tmp_path: Path):
    checkpoint_path = tmp_path / "event_checkpoint.jsonl"
    workload = _workload()

    # First pass: only process the first write, simulating a kill after
    # event 0 by only feeding a one-event slice.
    partial_workload = Workload(name=workload.name, kind=workload.kind, events=workload.events[:1])
    backend1 = CountingBackend()
    replay_workload(backend1, partial_workload, checkpoint_path=checkpoint_path, resume_key="Backend::resume_test")
    assert backend1.write_calls == 1

    # Second pass: full workload, same checkpoint file/key -- event 0 must
    # be loaded from checkpoint, not re-sent to the backend.
    backend2 = CountingBackend()
    run_log = replay_workload(backend2, workload, checkpoint_path=checkpoint_path, resume_key="Backend::resume_test")

    assert backend2.write_calls == 1  # only the second write (event 1) hit this fresh backend
    assert backend2.query_calls == 1
    assert len(run_log.entries) == 3
    assert run_log.incomplete is False


def test_resume_reconstructs_correct_scoring(tmp_path: Path):
    """The resumed run must score identically to a full uninterrupted run
    -- resume is a performance optimization, not a scoring shortcut."""
    from harness.score import score_run

    checkpoint_path = tmp_path / "event_checkpoint.jsonl"
    workload = _workload()

    partial_workload = Workload(name=workload.name, kind=workload.kind, events=workload.events[:2])
    replay_workload(CountingBackend(), partial_workload, checkpoint_path=checkpoint_path, resume_key="k")

    run_log = replay_workload(CountingBackend(), workload, checkpoint_path=checkpoint_path, resume_key="k")
    metrics = score_run(run_log, workload)

    assert metrics.state == "reported"
    assert metrics.n == 1
    assert metrics.stale_rate is not None and metrics.stale_rate.value == 0.0


def test_without_checkpoint_path_every_event_replays_live():
    """No checkpoint_path/resume_key -- the default, used for in-memory
    backends -- must behave exactly as before: no resume, full replay."""
    workload = _workload()
    backend = CountingBackend()
    run_log = replay_workload(backend, workload)
    assert backend.write_calls == 2
    assert backend.query_calls == 1
    assert len(run_log.entries) == 3
