"""Resume support for run_evaluation.py -- a killed multi-hour run (mem0-local
in particular) previously had to restart from zero, discarding hours of real
LLM calls. Checkpoints only Metrics (numbers, no raw fact content) per
completed (backend_name, workload_name) pair, written incrementally as each
pair finishes -- not just at the end -- so a kill mid-run loses at most one
in-flight pair, not the whole run."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from harness.models import Metrics, RateMetric

CHECKPOINT_PATH = Path(__file__).parent.parent / "data" / "private" / "checkpoint.jsonl"


def checkpoint_key(backend_name: str, workload_name: str) -> str:
    return f"{backend_name}::{workload_name}"


def append_checkpoint(path: Path, key: str, metrics: Metrics) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"key": key, "metrics": dataclasses.asdict(metrics)}) + "\n")


def load_checkpoint(path: Path) -> dict[str, Metrics]:
    if not path.exists():
        return {}
    out: dict[str, Metrics] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        out[row["key"]] = _metrics_from_dict(row["metrics"])
    return out


def _rate_metric_from_dict(d: dict | None) -> RateMetric | None:
    return RateMetric(**d) if d is not None else None


def _metrics_from_dict(d: dict) -> Metrics:
    return Metrics(
        backend_name=d["backend_name"],
        workload_name=d["workload_name"],
        workload_kind=d["workload_kind"],
        state=d["state"],
        n=d["n"],
        precision=_rate_metric_from_dict(d.get("precision")),
        recall=_rate_metric_from_dict(d.get("recall")),
        stale_rate=_rate_metric_from_dict(d.get("stale_rate")),
        contradiction_rate=_rate_metric_from_dict(d.get("contradiction_rate")),
        tokens_used=d.get("tokens_used"),
        storage_bytes=d.get("storage_bytes"),
        latency_ms_median=d.get("latency_ms_median"),
        latency_ms_iqr_low=d.get("latency_ms_iqr_low"),
        latency_ms_iqr_high=d.get("latency_ms_iqr_high"),
        update_cost_ms_median=d.get("update_cost_ms_median"),
    )
