"""Runs the full evaluation: available backends x available workloads,
writes the private report (data/private/, never committed), builds and
renders the public report, scrubs it, and reports pass/fail. Does not
copy anything to techbots-dev -- that stays a manual, human-reviewed
step, on purpose."""

from __future__ import annotations

import sys
from collections.abc import Callable
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

REAL_WORKLOAD_NAMES = [
    "test_real_triage",
    "test_real_pr_review",
    "real_agent_rails_ops",
    "real_agent_guard_fixes",
]
SYNTHETIC_WORKLOAD_NAMES = ["contradiction_workload"]

MEMKIT_URL = "http://localhost:8080"
MEMKIT_API_KEY = "dev-key"


def _memkit_reachable() -> bool:
    try:
        import httpx

        httpx.get(f"{MEMKIT_URL}/healthz", timeout=1.0).raise_for_status()
        return True
    except Exception:
        return False


def _ollama_has(model: str) -> bool:
    try:
        import httpx

        resp = httpx.get("http://localhost:11434/api/tags", timeout=1.0)
        resp.raise_for_status()
        return any(m["name"].startswith(model) for m in resp.json().get("models", []))
    except Exception:
        return False


def _available_backends() -> dict[str, Callable[[str], object]]:
    """Each factory takes a run-scoped `user_id` -- MemkitBackend and
    Mem0Backend persist to an external store keyed by user_id, so a fresh
    Python instance alone does not isolate one workload's writes from the
    next the way it does for the two in-memory backends. A distinct
    user_id per workload run is the actual isolation boundary."""
    backends: dict[str, Callable[[str], object]] = {
        "RawHistoryBackend": lambda _user_id: RawHistoryBackend(),
    }

    try:
        from backends.local_vector import LocalVectorBackend

        backends["LocalVectorBackend"] = lambda _user_id: LocalVectorBackend()
    except Exception as err:
        print(f"[skip] LocalVectorBackend unavailable: {err}", file=sys.stderr)

    if _memkit_reachable():
        from backends.memkit_backend import MemkitBackend

        backends["MemkitBackend"] = lambda user_id: MemkitBackend(
            base_url=MEMKIT_URL, api_key=MEMKIT_API_KEY, user_id=user_id
        )
    else:
        print(f"[skip] MemkitBackend unavailable: no server at {MEMKIT_URL}", file=sys.stderr)

    if _ollama_has("llama3.1") and _ollama_has("nomic-embed-text"):
        try:
            import mem0  # noqa: F401

            from backends.mem0_backend import Mem0Backend

            backends["Mem0Backend(local)"] = lambda user_id: Mem0Backend(mode="local", user_id=user_id)
        except ImportError as err:
            print(f"[skip] Mem0Backend(local) unavailable: {err}", file=sys.stderr)
    else:
        print("[skip] Mem0Backend(local) unavailable: missing llama3.1/nomic-embed-text ollama models", file=sys.stderr)

    return backends


def main() -> int:
    backend_factories = _available_backends()
    print(f"backends available: {list(backend_factories)}")

    run_logs = []
    metrics = []

    for backend_name, make_backend in backend_factories.items():
        synthetic_backend = make_backend(f"memkit-eval-{backend_name}-synthetic")
        for name in SYNTHETIC_WORKLOAD_NAMES:
            workload = load_synthetic_workload(name)
            run_log = replay_workload(synthetic_backend, workload)
            run_logs.append(run_log)
            metrics.append(score_run(run_log, workload))
            print(f"  {backend_name} / {name}: {run_logs[-1].incomplete=} n={metrics[-1].n}")

        # fresh backend instance + unique user_id per real workload: the actual
        # isolation boundary for MemkitBackend/Mem0Backend, which persist to an
        # external store keyed by user_id rather than in Python-object memory.
        for name in REAL_WORKLOAD_NAMES:
            fresh_backend = make_backend(f"memkit-eval-{backend_name}-{name}")
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
