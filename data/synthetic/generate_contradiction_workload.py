"""Deterministically generates data/synthetic/contradiction_workload.json --
run this, don't hand-edit the output. Fully synthetic: fictional entities,
no real names, public-safe by construction. Generates enough contradiction
scenarios to clear MIN_RATE_N (harness/constants.py) with real statistical
margin, not just barely."""

from __future__ import annotations

import json
import random
from pathlib import Path

random.seed(20260811)  # fixed seed -- this file's output is deterministic, not re-rolled per run

_SUBJECTS = [f"user_{i}" for i in range(50)]

_TEMPLATES = [
    ("works at {old}", "works at {new}", ["Acme Corp", "Beta Industries", "Gamma LLC", "Delta Inc", "Epsilon Co"]),
    ("lives in {old}", "lives in {new}", ["Austin", "Denver", "Seattle", "Chicago", "Boston"]),
    (
        "'s favorite drink is {old}",
        "'s favorite drink is {new}",
        ["cortado", "cold brew", "espresso", "drip coffee", "matcha"],
    ),
    (
        "uses {old} as their primary editor",
        "uses {new} as their primary editor",
        ["Vim", "Emacs", "VS Code", "Sublime", "Neovim"],
    ),
    (
        "is working on the {old} project",
        "is working on the {new} project",
        ["Atlas", "Orion", "Nimbus", "Vertex", "Prism"],
    ),
    (
        "prefers {old} for deployments",
        "prefers {new} for deployments",
        ["Kubernetes", "Docker Swarm", "Nomad", "ECS", "bare metal"],
    ),
    (
        "'s manager is {old}",
        "'s manager is {new}",
        ["Alex Rivera", "Sam Chen", "Jordan Lee", "Taylor Kim", "Morgan Diaz"],
    ),
    ("is allergic to {old}", "is allergic to {new}", ["peanuts", "shellfish", "gluten", "dairy", "soy"]),
]


def _build_pair(subject: str, template_idx: int, t: float) -> tuple[list[dict], dict]:
    old_phrase, new_phrase, options = _TEMPLATES[template_idx]
    old_val, new_val = random.sample(options, 2)
    old_id = f"{subject}_{template_idx}_old"
    new_id = f"{subject}_{template_idx}_new"

    old_write = {
        "kind": "write",
        "at": t,
        "fact_id": old_id,
        "fact_text": f"{subject} {old_phrase.format(old=old_val)}",
    }
    new_write = {
        "kind": "write",
        "at": t + 1,
        "fact_id": new_id,
        "fact_text": f"{subject} {new_phrase.format(new=new_val)}",
    }
    query = {
        "kind": "query",
        "at": t + 2,
        "query_text": f"what is true about {subject} regarding {old_phrase.split('{')[0].strip()}",
        "gold": {"exact_ids": [new_id], "stale_ids_that_must_not_surface": [old_id]},
    }
    return [old_write, new_write], query


def build_workload() -> dict:
    events: list[dict] = []
    t = 0.0
    for subject in _SUBJECTS:
        for template_idx in range(len(_TEMPLATES)):
            writes, query = _build_pair(subject, template_idx, t)
            events.extend(writes)
            events.append(query)
            t += 10.0
    return {"name": "contradiction_workload", "kind": "synthetic", "events": events}


if __name__ == "__main__":
    workload = build_workload()
    n_queries = sum(1 for e in workload["events"] if e["kind"] == "query")
    out_path = Path(__file__).parent / "contradiction_workload.json"
    out_path.write_text(json.dumps(workload, indent=2), encoding="utf-8")
    print(f"wrote {out_path} -- {n_queries} query events (n={n_queries})")
