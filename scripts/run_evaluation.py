"""Runs the full evaluation: available backends x available workloads,
writes the private report (data/private/, never committed), builds and
renders the public report, scrubs it, and reports pass/fail. Does not
copy anything to techbots-dev -- that stays a manual, human-reviewed
step, on purpose.

Resumable: a killed run (mem0-local's real-LLM-per-write cost makes this a
real risk, not hypothetical -- it happened twice) picks back up rather than
restarting from zero. Two layers: a finished (backend, workload) pair is
skipped entirely on the next run (harness/checkpoint.py); an in-flight pair
for an externally-persisted backend (MemkitBackend, Mem0Backend -- state
survives a process restart on its own, keyed by user_id) resumes from its
last completed event rather than losing the whole pair
(harness/event_checkpoint.py, wired through replay_workload)."""

from __future__ import annotations

import os

# Must be set before ANY `import mem0` in the process -- mem0.memory.telemetry
# reads this at module import time. backends/mem0_backend.py also sets it,
# but too late here: _available_backends()'s own `import mem0` (an early
# availability probe, see below) runs first and already imports the
# telemetry module with the default (on) before that module-level line fires.
os.environ.setdefault("MEM0_TELEMETRY", "False")

import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backends.raw_history import RawHistoryBackend
from harness.checkpoint import CHECKPOINT_PATH, append_checkpoint, checkpoint_key, load_checkpoint
from harness.event_checkpoint import EVENT_CHECKPOINT_PATH
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

# Backends whose state survives a process restart on its own (external
# store keyed by user_id) -- only these are safe to resume event-by-event.
# A pure in-memory backend has nothing to resume from.
_EXTERNALLY_PERSISTED_BACKENDS = {"MemkitBackend", "Mem0Backend(local)", "Mem0Backend(hybrid)"}


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

    skip_local = os.environ.get("MEMKIT_EVAL_SKIP_MEM0_LOCAL") == "1"
    if skip_local:
        print("[skip] Mem0Backend(local) skipped via MEMKIT_EVAL_SKIP_MEM0_LOCAL=1", file=sys.stderr)
    elif _ollama_has("llama3.1") and _ollama_has("nomic-embed-text"):
        try:
            import mem0  # noqa: F401

            from backends.mem0_backend import Mem0Backend

            backends["Mem0Backend(local)"] = lambda user_id: Mem0Backend(mode="local", user_id=user_id)
        except ImportError as err:
            print(f"[skip] Mem0Backend(local) unavailable: {err}", file=sys.stderr)
    else:
        print("[skip] Mem0Backend(local) unavailable: missing llama3.1/nomic-embed-text ollama models", file=sys.stderr)

    if os.environ.get("ANTHROPIC_API_KEY") and _ollama_has("nomic-embed-text"):
        try:
            import mem0  # noqa: F401

            from backends.mem0_backend import Mem0Backend

            backends["Mem0Backend(hybrid)"] = lambda user_id: Mem0Backend(mode="hybrid", user_id=user_id)
        except ImportError as err:
            print(f"[skip] Mem0Backend(hybrid) unavailable: {err}", file=sys.stderr)
    else:
        print("[skip] Mem0Backend(hybrid) unavailable: needs ANTHROPIC_API_KEY + nomic-embed-text", file=sys.stderr)

    return backends


def _close_backend(backend) -> None:
    """Not every backend needs closing (RawHistoryBackend/LocalVectorBackend
    are pure in-memory), so this is a no-op for those rather than a
    Protocol requirement every backend must implement."""
    close = getattr(backend, "close", None)
    if callable(close):
        close()


def _run_pair(backend_name, backend, workload, done_metrics):
    """Runs one (backend, workload) pair, or reuses it from the pair-level
    checkpoint if already finished. Returns (metrics, run_log_or_None).

    CORRECTED (live run): a checkpointed pair with state="incomplete" is a
    *failed* attempt, not a finished one -- e.g. every hybrid-mode write
    failing on an Anthropic billing error. Treating it as done would cache
    the failure forever, silently skipping retry even after the underlying
    problem (low API credit, a transient outage) is fixed. Only a
    state="reported" (successful) result is safe to skip."""
    key = checkpoint_key(backend_name, workload.name)
    if key in done_metrics and done_metrics[key].state == "reported":
        print(f"  {backend_name} / {workload.name}: [resumed from checkpoint] n={done_metrics[key].n}")
        return done_metrics[key], None

    resumable = backend_name in _EXTERNALLY_PERSISTED_BACKENDS
    run_log = replay_workload(
        backend,
        workload,
        checkpoint_path=EVENT_CHECKPOINT_PATH if resumable else None,
        resume_key=key if resumable else None,
        backend_name=backend_name,
    )
    metrics = score_run(run_log, workload)
    append_checkpoint(CHECKPOINT_PATH, key, metrics)
    return metrics, run_log


def main() -> int:
    backend_factories = _available_backends()
    print(f"backends available: {list(backend_factories)}")

    done_metrics = load_checkpoint(CHECKPOINT_PATH)
    if done_metrics:
        print(f"resuming: {len(done_metrics)} (backend, workload) pairs already checkpointed")

    run_logs = []
    metrics = []

    for backend_name, make_backend in backend_factories.items():
        synthetic_backend = None
        for name in SYNTHETIC_WORKLOAD_NAMES:
            workload = load_synthetic_workload(name)
            key = checkpoint_key(backend_name, name)
            if key not in done_metrics and synthetic_backend is None:
                synthetic_backend = make_backend(f"memkit-eval-{backend_name}-synthetic")
            m, run_log = _run_pair(backend_name, synthetic_backend, workload, done_metrics)
            metrics.append(m)
            if run_log is not None:
                run_logs.append(run_log)
            print(f"  {backend_name} / {name}: incomplete={run_log.incomplete if run_log else 'N/A'} n={m.n}")
        _close_backend(synthetic_backend)

        # fresh backend instance + unique user_id per real workload: the actual
        # isolation boundary for MemkitBackend/Mem0Backend, which persist to an
        # external store keyed by user_id rather than in Python-object memory.
        # Closed immediately after each pair -- some (e.g. mem0 local/hybrid's
        # on-disk Qdrant) hold an exclusive file lock for the instance's whole
        # lifetime; an unclosed prior instance crashes the next one.
        for name in REAL_WORKLOAD_NAMES:
            workload = load_real_workload(name)
            key = checkpoint_key(backend_name, name)
            fresh_backend = None if key in done_metrics else make_backend(f"memkit-eval-{backend_name}-{name}")
            m, run_log = _run_pair(backend_name, fresh_backend, workload, done_metrics)
            metrics.append(m)
            if run_log is not None:
                run_logs.append(run_log)
            print(f"  {backend_name} / {name} (real): incomplete={run_log.incomplete if run_log else 'N/A'} n={m.n}")
            _close_backend(fresh_backend)

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
