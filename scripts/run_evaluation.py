"""Runs the full evaluation: available backends x available workloads,
writes the private report (data/private/, never committed), builds and
renders the public report, scrubs it, and reports pass/fail. Does not
copy anything to techbots-dev -- that stays a manual, human-reviewed
step, on purpose."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backends.raw_history import RawHistoryBackend
from harness.publish_candidate import build_publish_candidate
from harness.render_public_report import render_public_report
from harness.replay import replay_workload
from harness.report_private import write_private_report
from harness.score import score_run
from harness.workload_loader import load_real_workload, load_synthetic_workload
from scripts.prepublish_scrub import load_denylist, scrub_bytes

REAL_WORKLOAD_NAMES = ["test_real_triage", "test_real_pr_review"]
SYNTHETIC_WORKLOAD_NAMES = ["contradiction_workload"]


def _available_backends() -> dict[str, object]:
    backends: dict[str, object] = {"RawHistoryBackend": RawHistoryBackend()}
    try:
        from backends.local_vector import LocalVectorBackend

        backends["LocalVectorBackend"] = LocalVectorBackend()
    except Exception as err:
        print(f"[skip] LocalVectorBackend unavailable: {err}", file=sys.stderr)
    return backends


def main() -> int:
    backends = _available_backends()
    print(f"backends available: {list(backends)}")

    run_logs = []
    metrics = []

    for backend_name, backend in backends.items():
        for name in SYNTHETIC_WORKLOAD_NAMES:
            workload = load_synthetic_workload(name)
            run_log = replay_workload(backend, workload)
            run_logs.append(run_log)
            metrics.append(score_run(run_log, workload))
            print(f"  {backend_name} / {name}: {run_logs[-1].incomplete=} n={metrics[-1].n}")

        # fresh backend instance per real workload group to avoid cross-workload contamination
        for name in REAL_WORKLOAD_NAMES:
            fresh_backend = type(backend)()
            workload = load_real_workload(name)
            run_log = replay_workload(fresh_backend, workload)
            run_logs.append(run_log)
            metrics.append(score_run(run_log, workload))
            print(f"  {backend_name} / {name} (real): incomplete={run_log.incomplete} n={metrics[-1].n}")

    write_private_report(run_logs, metrics)
    print("\nprivate report written to data/private/RESULTS_PRIVATE.md (never committed)")

    candidate = build_publish_candidate(metrics)
    rendered = render_public_report(candidate)
    result = scrub_bytes(rendered, load_denylist())

    out_path = Path("RESULTS_PUBLIC.md")
    if result.passed:
        out_path.write_text(rendered, encoding="utf-8")
        print(f"\nscrub: PASS -- wrote {out_path} ({len(candidate.cells)} published cells)")
        return 0

    print("\nscrub: FAIL -- RESULTS_PUBLIC.md NOT written")
    for reason in result.reasons:
        print(f"  - {reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
