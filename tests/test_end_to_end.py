"""Full pipeline, real backends, no mocking -- proves the whole thing
actually works end to end: load workload -> replay -> score -> publish
candidate -> render -> scrub. Uses a small slice of the real generated
synthetic workload (not the full 400 pairs) to keep this fast; the full
file is what the actual evaluation run uses, not this test."""

from dataclasses import replace

import pytest

from backends.raw_history import RawHistoryBackend
from harness.publish_candidate import build_publish_candidate
from harness.render_public_report import render_public_report
from harness.replay import replay_workload
from harness.score import score_run
from harness.workload_loader import load_synthetic_workload
from scripts.prepublish_scrub import scrub_bytes


def _small_slice(workload, n_events: int):
    return replace(workload, events=workload.events[:n_events])


def test_full_synthetic_run_raw_history_backend():
    workload = _small_slice(load_synthetic_workload("contradiction_workload"), n_events=30)
    backend = RawHistoryBackend(return_last_n=10)

    run_log = replay_workload(backend, workload)
    assert not run_log.incomplete

    metrics = score_run(run_log, workload)
    assert metrics.state == "reported"
    assert metrics.n > 0

    candidate = build_publish_candidate([metrics])
    rendered = render_public_report(candidate)
    assert "not a benchmark" in rendered

    with open("scripts/denylist.txt") as f:
        denylist = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    result = scrub_bytes(rendered, denylist)
    assert result.passed, result.reasons


@pytest.mark.slow
def test_full_synthetic_run_local_vector_backend():
    try:
        from backends.local_vector import LocalVectorBackend
    except Exception as err:
        pytest.skip(f"sentence-transformers model unavailable: {err}")

    workload = _small_slice(load_synthetic_workload("contradiction_workload"), n_events=15)
    backend = LocalVectorBackend(top_k=3)

    run_log = replay_workload(backend, workload)
    metrics = score_run(run_log, workload)
    assert metrics.state == "reported"
