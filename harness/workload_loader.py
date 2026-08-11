from __future__ import annotations

import json
from pathlib import Path

from .models import GoldAnswer, Workload, WorkloadEvent

REPO_ROOT = Path(__file__).parent.parent
PRIVATE_ROOT = (REPO_ROOT / "data" / "private").resolve()
SYNTHETIC_ROOT = (REPO_ROOT / "data" / "synthetic").resolve()


class WorkloadLoadError(Exception):
    pass


def _resolve_within(root: Path, name: str) -> Path:
    """Fails closed on path traversal: the resolved path must stay inside
    `root`. A name like '../synthetic/x' must not escape the private root."""
    candidate = (root / f"{name}.json").resolve()
    if root not in candidate.parents and candidate != root:
        raise WorkloadLoadError(f"workload name '{name}' resolves outside {root}")
    if not str(candidate).startswith(str(root)):
        raise WorkloadLoadError(f"workload name '{name}' resolves outside {root}")
    return candidate


def _parse_event(raw: dict) -> WorkloadEvent:
    gold = None
    if raw.get("gold") is not None:
        g = raw["gold"]
        gold = GoldAnswer(
            exact_ids=frozenset(g["exact_ids"]) if g.get("exact_ids") is not None else None,
            stale_ids_that_must_not_surface=(
                frozenset(g["stale_ids_that_must_not_surface"])
                if g.get("stale_ids_that_must_not_surface") is not None
                else None
            ),
        )
    return WorkloadEvent(
        kind=raw["kind"],
        at=raw["at"],
        fact_id=raw.get("fact_id"),
        fact_text=raw.get("fact_text"),
        query_text=raw.get("query_text"),
        gold=gold,
    )


def _load(path: Path, expected_kind: str) -> Workload:
    if not path.exists():
        raise WorkloadLoadError(f"workload file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    file_kind = data.get("kind")
    if file_kind != expected_kind:
        # Fail closed on ambiguity -- a mismatch between a workload file's
        # declared kind and the directory it was loaded from must never be
        # silently guessed, even toward the "less dangerous" label.
        raise WorkloadLoadError(
            f"workload '{path.name}' declares kind={file_kind!r} but was loaded "
            f"as {expected_kind!r} -- refusing to guess"
        )
    events = tuple(_parse_event(e) for e in data["events"])
    return Workload(name=data["name"], kind=file_kind, events=events)


def load_real_workload(name: str, root: Path = PRIVATE_ROOT) -> Workload:
    """Only ever reads from data/private/ -- refuses to load a 'real'
    workload from anywhere else, including via a crafted name. `root` is
    overridable for tests only; production callers use the default."""
    path = _resolve_within(root, name)
    return _load(path, expected_kind="real")


def load_synthetic_workload(name: str, root: Path = SYNTHETIC_ROOT) -> Workload:
    path = _resolve_within(root, name)
    return _load(path, expected_kind="synthetic")
