import dataclasses
import time

import pytest

from harness.constants import MIN_RATE_N, MIN_REAL_CELL_N
from harness.models import Metrics, PublishCandidate, PublishCell, RateMetric
from harness.publish_candidate import assert_numbers_only, build_publish_candidate
from harness.render_public_report import render_public_report
from scripts.prepublish_scrub import scrub_bytes


def _rate(value, n):
    return RateMetric(value=value, n=n, ci_low=max(0, value - 0.1), ci_high=min(1, value + 0.1))


def test_real_workload_rate_metrics_never_published():
    """Direct regression test for the BLOCKER (code review): a real
    workload's rate metrics (precision/recall/stale_rate/contradiction_
    rate) must never publish, per-workload or pooled -- rate metrics live
    on synthetic data only, per the original C1 design. Named after the
    exact scenario the reviewer reproduced: a real workload whose NAME
    itself is sensitive."""
    sensitive_named_metrics = Metrics(
        backend_name="MemkitBackend",
        workload_name="exchange_prod_cutover_PR6733",
        workload_kind="real",
        state="reported",
        n=12,
        stale_rate=_rate(0.083, 12),
    )
    candidate = build_publish_candidate([sensitive_named_metrics])
    assert candidate.cells == ()
    rendered = render_public_report(candidate)
    assert "exchange_prod_cutover_PR6733" not in rendered
    assert "6733" not in rendered


def test_no_published_label_ever_contains_a_real_workload_name():
    """Broader version of the above: real measurement metrics DO publish
    (pooled), but their label must be the fixed 'pooled real data'
    literal, never the operator-chosen workload_name."""
    m1 = Metrics(
        backend_name="MemkitBackend",
        workload_name="acme_corp_incident_log",
        workload_kind="real",
        state="reported",
        n=8,
        tokens_used=40,
    )
    m2 = Metrics(
        backend_name="MemkitBackend",
        workload_name="beta_industries_triage",
        workload_kind="real",
        state="reported",
        n=8,
        tokens_used=45,
    )
    candidate = build_publish_candidate([m1, m2])
    assert len(candidate.cells) > 0
    for cell in candidate.cells:
        assert "acme_corp_incident_log" not in cell.label
        assert "beta_industries_triage" not in cell.label
        assert "pooled real data" in cell.label


def test_assert_numbers_only_rejects_bool():
    """bool is an int subclass in Python -- isinstance(True, int) is
    True -- so this must be checked explicitly, not left to isinstance
    against (int, float) alone (code-review MEDIUM)."""
    bad_cell = PublishCell(label="x", value=0.5, n=100)
    object.__setattr__(bad_cell, "value", True)
    candidate = PublishCandidate(cells=(bad_cell,), generated_at=time.time())
    with pytest.raises(ValueError, match="bool"):
        assert_numbers_only(candidate)


def test_load_denylist_skips_comment_lines():
    """Direct regression test for the HIGH (code review): a bare '#'
    comment line was previously loaded as a literal denylist pattern,
    matching every markdown heading in every rendered report -- the
    shipped scrub was permanently fail-closed on genuinely clean input.
    This test calls the REAL load_denylist(), not a reimplemented
    loader, which is exactly what let the bug ship undetected the first
    time."""
    import tempfile
    from pathlib import Path

    import scripts.prepublish_scrub as mod

    original = mod.DENYLIST_PATH
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "denylist.txt"
            path.write_text("# a comment\n\nRealName\n# another comment\n", encoding="utf-8")
            mod.DENYLIST_PATH = path
            entries = mod.load_denylist()
            assert entries == ["RealName"]
    finally:
        mod.DENYLIST_PATH = original


def test_load_denylist_comment_only_file_fails_closed():
    """A denylist containing only comments must fail closed exactly like
    an empty file -- comments alone provide zero real protection."""
    import tempfile
    from pathlib import Path

    import scripts.prepublish_scrub as mod

    original = mod.DENYLIST_PATH
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "denylist.txt"
            path.write_text("# only comments\n# nothing real\n", encoding="utf-8")
            mod.DENYLIST_PATH = path
            with pytest.raises(ValueError, match="no real entries"):
                mod.load_denylist()
    finally:
        mod.DENYLIST_PATH = original


def test_real_scrub_gate_passes_on_genuinely_clean_report():
    """Runs the REAL load_denylist() (not a reimplementation) against a
    genuinely clean, numbers-only rendered report -- this is the
    end-to-end proof the shipped gate isn't permanently red."""
    from scripts.prepublish_scrub import load_denylist

    candidate = PublishCandidate(
        cells=(PublishCell(label="MemkitBackend / contradiction_workload / precision", value=0.8, n=100),),
        generated_at=time.time(),
    )
    rendered = render_public_report(candidate)
    result = scrub_bytes(rendered, load_denylist())
    assert result.passed, result.reasons


def test_scrub_rejects_non_numeric_field():
    bad_cell = PublishCell(label="x", value=0.5, n=100)
    # bypass normal construction to inject a stray string where a number belongs
    bad_cell = dataclasses.replace(bad_cell)
    object.__setattr__(bad_cell, "value", "some real name")
    candidate = PublishCandidate(cells=(bad_cell,), generated_at=time.time())
    with pytest.raises(ValueError, match="not numeric"):
        assert_numbers_only(candidate)


def test_scrub_scans_rendered_bytes_not_dataclass():
    """Direct regression test for the BLOCKER finding: a name inserted
    into the RENDERED report must be caught even though the upstream
    PublishCandidate is entirely clean (numbers only)."""
    clean_candidate = PublishCandidate(
        cells=(PublishCell(label="MemKit / synthetic / precision", value=0.8, n=100),),
        generated_at=time.time(),
    )
    rendered = render_public_report(clean_candidate)
    # Simulate exactly the leak vector worf named: a future template bug
    # inserting a real name into otherwise-clean rendered output.
    tampered = rendered + "\n\nExample: Franklin Okpako's PR #4821 was flagged as stale.\n"

    result = scrub_bytes(tampered, denylist=["Franklin Okpako"])
    assert not result.passed
    assert any("Franklin Okpako" in r for r in result.reasons)

    clean_result = scrub_bytes(rendered, denylist=["Franklin Okpako"])
    assert clean_result.passed


def test_runlog_repr_never_shows_raw_content():
    from harness.models import QueryLogEntry, RetrievedFact, RunLog

    run_log = RunLog(backend_name="MemkitBackend", workload_name="real_triage", workload_kind="real")
    run_log.entries.append(
        QueryLogEntry(
            event_at=1.0,
            retrieved=(RetrievedFact(fact_id="f1", text="Real Person Name works on Real Project X", score=0.9),),
            latency_ms=5.0,
        )
    )
    rendered = repr(run_log)
    assert "Real Person Name" not in rendered
    assert "Real Project X" not in rendered
    # entries themselves must also not leak via repr, since a caller could repr() them directly
    assert "Real Person Name" not in repr(run_log.entries[0])


def test_min_real_cell_n_enforced():
    below = Metrics(
        backend_name="MemkitBackend",
        workload_name="real_a",
        workload_kind="real",
        state="reported",
        n=MIN_REAL_CELL_N - 1,
        tokens_used=100,
    )
    at_threshold = Metrics(
        backend_name="MemkitBackend",
        workload_name="real_b",
        workload_kind="real",
        state="reported",
        n=MIN_REAL_CELL_N,
        tokens_used=100,
    )
    # below-threshold real data is pooled, not dropped outright -- pooled_n must still clear the bar
    candidate_below_only = build_publish_candidate([below])
    assert candidate_below_only.cells == ()

    candidate_at_threshold = build_publish_candidate([at_threshold])
    assert any("pooled real data" in c.label for c in candidate_at_threshold.cells)


def test_min_rate_n_enforced():
    below = Metrics(
        backend_name="MemkitBackend",
        workload_name="synthetic_a",
        workload_kind="synthetic",
        state="reported",
        n=MIN_RATE_N - 1,
        precision=_rate(0.8, MIN_RATE_N - 1),
    )
    at_threshold = Metrics(
        backend_name="MemkitBackend",
        workload_name="synthetic_b",
        workload_kind="synthetic",
        state="reported",
        n=MIN_RATE_N,
        precision=_rate(0.8, MIN_RATE_N),
    )
    assert build_publish_candidate([below]).cells == ()
    at_cells = build_publish_candidate([at_threshold]).cells
    assert any("precision" in c.label for c in at_cells)


def test_real_measurement_metrics_pooled_before_publish():
    """C.5 condition 5: two real workloads, each individually below
    MIN_REAL_CELL_N, still publish as ONE pooled cell if their combined n
    clears the bar -- and the label never names the individual workload."""
    m1 = Metrics(
        backend_name="MemkitBackend",
        workload_name="real_triage",
        workload_kind="real",
        state="reported",
        n=6,
        tokens_used=50,
    )
    m2 = Metrics(
        backend_name="MemkitBackend",
        workload_name="real_pr_review",
        workload_kind="real",
        state="reported",
        n=6,
        tokens_used=60,
    )
    candidate = build_publish_candidate([m1, m2])
    pooled = [c for c in candidate.cells if "pooled real data" in c.label]
    assert len(pooled) > 0
    assert pooled[0].n == 12
    assert "real_triage" not in pooled[0].label
    assert "real_pr_review" not in pooled[0].label


def test_scrub_fails_closed_on_empty_denylist():
    import tempfile
    from pathlib import Path

    import scripts.prepublish_scrub as mod

    original = mod.DENYLIST_PATH
    try:
        with tempfile.TemporaryDirectory() as tmp:
            empty_path = Path(tmp) / "denylist.txt"
            empty_path.write_text("", encoding="utf-8")
            mod.DENYLIST_PATH = empty_path
            with pytest.raises(ValueError, match="no real entries"):
                mod.load_denylist()
    finally:
        mod.DENYLIST_PATH = original
