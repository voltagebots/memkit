"""Standalone diagnostic pass: MemkitClaudeResolverBackend only, against
memkit running with the Claude resolver enabled (localhost:8080). Writes a
private-only report -- deliberately does not touch RESULTS_PRIVATE.md /
RESULTS_PUBLIC.md, which the main run_evaluation.py background run still
owns until it finishes and the two results get merged in one pass."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backends.memkit_backend import MemkitClaudeResolverBackend
from harness.replay import replay_workload
from harness.report_private import write_private_report
from harness.score import score_run
from harness.workload_loader import load_real_workload, load_synthetic_workload

MEMKIT_URL = "http://localhost:8080"
MEMKIT_API_KEY = "dev-key"

REAL_WORKLOAD_NAMES = [
    "test_real_triage",
    "test_real_pr_review",
    "real_agent_rails_ops",
    "real_agent_guard_fixes",
]
SYNTHETIC_WORKLOAD_NAMES = ["contradiction_workload"]


def main() -> int:
    run_logs = []
    metrics = []

    for name in SYNTHETIC_WORKLOAD_NAMES:
        backend = MemkitClaudeResolverBackend(
            base_url=MEMKIT_URL, api_key=MEMKIT_API_KEY, user_id=f"memkit-eval-resolver-{name}"
        )
        workload = load_synthetic_workload(name)
        run_log = replay_workload(backend, workload)
        run_logs.append(run_log)
        m = score_run(run_log, workload)
        metrics.append(m)
        print(f"MemkitClaudeResolverBackend / {name}: incomplete={run_log.incomplete} n={m.n}")
        print(f"  precision={m.precision} recall={m.recall}")
        print(f"  stale_rate={m.stale_rate} contradiction_rate={m.contradiction_rate}")

    for name in REAL_WORKLOAD_NAMES:
        backend = MemkitClaudeResolverBackend(
            base_url=MEMKIT_URL, api_key=MEMKIT_API_KEY, user_id=f"memkit-eval-resolver-{name}"
        )
        workload = load_real_workload(name)
        run_log = replay_workload(backend, workload)
        run_logs.append(run_log)
        m = score_run(run_log, workload)
        metrics.append(m)
        print(f"MemkitClaudeResolverBackend / {name} (real): incomplete={run_log.incomplete} n={m.n}")

    out_dir = Path(__file__).parent.parent / "data" / "private" / "resolver_pass"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = write_private_report(run_logs, metrics, out_dir=out_dir)
    print(f"\nprivate report written to {report_path} (never committed) -- kept separate from the")
    print("main run_evaluation.py's data/private/RESULTS_PRIVATE.md to avoid a write collision")
    print("with the still-running background pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
