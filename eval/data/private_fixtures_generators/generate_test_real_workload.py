"""Generates a REAL-KIND but entirely FICTIONAL workload under
data/private/ -- proves the real-data pipeline (pooling, denylist,
scrub, min-cell-n) works end to end using realistic-shaped content
before the actual voltage/sentinel wiki data is ever touched. Names
below are all fictional test stand-ins, not real people."""

from __future__ import annotations

import json
from pathlib import Path

_TRIAGE_EVENTS = [
    {
        "kind": "write",
        "at": 1.0,
        "fact_id": "triage_1_old",
        "fact_text": "Jordan Ashworth is the on-call SRE this week",
    },
    {
        "kind": "write",
        "at": 2.0,
        "fact_id": "triage_1_new",
        "fact_text": "Priya Nakamura is the on-call SRE this week",
    },
    {
        "kind": "query",
        "at": 3.0,
        "query_text": "who is on-call this week",
        "gold": {"exact_ids": ["triage_1_new"], "stale_ids_that_must_not_surface": ["triage_1_old"]},
    },
    {
        "kind": "write",
        "at": 4.0,
        "fact_id": "triage_2_old",
        "fact_text": "PR-4821 in webshop-checkout is blocked on review",
    },
    {"kind": "write", "at": 5.0, "fact_id": "triage_2_new", "fact_text": "PR-4821 in webshop-checkout was merged"},
    {
        "kind": "query",
        "at": 6.0,
        "query_text": "status of PR-4821",
        "gold": {"exact_ids": ["triage_2_new"], "stale_ids_that_must_not_surface": ["triage_2_old"]},
    },
]

_PR_REVIEW_EVENTS = [
    {"kind": "write", "at": 1.0, "fact_id": "pr_1_old", "fact_text": "Riverstone Analytics uses Terraform for infra"},
    {
        "kind": "write",
        "at": 2.0,
        "fact_id": "pr_1_new",
        "fact_text": "Riverstone Analytics migrated to Pulumi for infra",
    },
    {
        "kind": "query",
        "at": 3.0,
        "query_text": "what does Riverstone Analytics use for infra",
        "gold": {"exact_ids": ["pr_1_new"], "stale_ids_that_must_not_surface": ["pr_1_old"]},
    },
]


def build_workload(name: str, events: list[dict]) -> dict:
    return {"name": name, "kind": "real", "events": events}


if __name__ == "__main__":
    out_dir = Path(__file__).parent.parent / "private"
    triage = build_workload("test_real_triage", _TRIAGE_EVENTS)
    pr_review = build_workload("test_real_pr_review", _PR_REVIEW_EVENTS)
    (out_dir / "test_real_triage.json").write_text(json.dumps(triage, indent=2), encoding="utf-8")
    (out_dir / "test_real_pr_review.json").write_text(json.dumps(pr_review, indent=2), encoding="utf-8")
    print("wrote data/private/test_real_triage.json, data/private/test_real_pr_review.json")
