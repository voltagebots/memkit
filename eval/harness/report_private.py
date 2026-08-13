from __future__ import annotations

import time
from pathlib import Path

from harness.models import Metrics, QueryLogEntry, RunLog, WriteLogEntry
from harness.workload_loader import PRIVATE_ROOT

RUNLOG_DIR = PRIVATE_ROOT / "runlogs"


def write_private_report(run_logs: list[RunLog], metrics: list[Metrics], out_dir: Path = PRIVATE_ROOT) -> Path:
    """This function is ALLOWED to see raw data by design -- it never
    writes outside the gitignored data/private/ tree. Note: it reads
    fields directly (entry.retrieved[i].text, not repr(entry)) --
    repr=False on those fields blocks accidental leaks via a stray
    print()/traceback, but also blocks repr() here, which is intentional
    everywhere except this one function."""
    out_dir.mkdir(parents=True, exist_ok=True)
    RUNLOG_DIR.mkdir(parents=True, exist_ok=True)

    lines = [f"# Private results -- generated {time.strftime('%Y-%m-%d %H:%M', time.gmtime())}\n\n"]
    lines.append("NEVER commit this file. Full per-example detail, including real content.\n\n")
    for m in metrics:
        lines.append(f"## {m.backend_name} / {m.workload_name} ({m.workload_kind}, state={m.state})\n")
        lines.append(f"- n={m.n}\n")
        for field_name in ("precision", "recall", "stale_rate", "contradiction_rate"):
            rate = getattr(m, field_name)
            if rate is not None:
                lines.append(f"- {field_name}: {rate.value} (n={rate.n}, CI=[{rate.ci_low}, {rate.ci_high}])\n")
        for field_name in ("tokens_used", "storage_bytes", "latency_ms_median", "update_cost_ms_median"):
            value = getattr(m, field_name)
            if value is not None:
                lines.append(f"- {field_name}: {value}\n")
        lines.append("\n")

    report_path = out_dir / "RESULTS_PRIVATE.md"
    report_path.write_text("".join(lines), encoding="utf-8")

    for run_log in run_logs:
        runlog_path = RUNLOG_DIR / f"{run_log.backend_name}_{run_log.workload_name}.txt"
        runlog_path.write_text(_render_runlog_full(run_log), encoding="utf-8")

    return report_path


def _render_runlog_full(run_log: RunLog) -> str:
    """Explicit field access, not repr() -- see module docstring."""
    lines = [f"backend={run_log.backend_name} workload={run_log.workload_name} incomplete={run_log.incomplete}\n"]
    for entry in run_log.entries:
        if isinstance(entry, WriteLogEntry):
            lines.append(f"WRITE at={entry.event_at} ok={entry.result.ok} error={entry.result.error}\n")
        elif isinstance(entry, QueryLogEntry):
            lines.append(f"QUERY at={entry.event_at} latency_ms={entry.latency_ms} error={entry.error}\n")
            for fact in entry.retrieved:
                lines.append(f"  retrieved: fact_id={fact.fact_id} score={fact.score} text={fact.text!r}\n")
    return "".join(lines)
