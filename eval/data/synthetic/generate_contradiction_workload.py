"""Deterministically generates data/synthetic/contradiction_workload.json --
run this, don't hand-edit the output. Fully synthetic: fictional entities,
no real names, public-safe by construction. Generates enough contradiction
scenarios to clear MIN_RATE_N (harness/constants.py) with real statistical
margin, not just barely.

CORRECTED (live smoke test on a real memkit instance, 2026-08-12): the
first version drew each template's old/new values from a pool of only 5
options shared across all 50 subjects, and identified subjects with a bare
"user_N" token. Both facts land in the same memkit operator namespace (the
harness's own MemoryBackend protocol has no per-subject scoping -- it
models one continuous operator memory, matching memkit's real one-operator
design), so weak subject tokens plus a 5-value pool meant many subjects'
facts were near-duplicates of each other's, causing real cross-subject
retrieval collisions unrelated to any backend's actual quality (confirmed
live: a query for one subject's "works at" fact returned nine *other*
subjects' still-active "Acme Corp" facts in the top 10). Fixed by giving
subjects distinctive names and widening each template's value pool so
cross-subject content collision becomes rare rather than near-certain.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

random.seed(20260811)  # fixed seed -- this file's output is deterministic, not re-rolled per run

_FIRST_NAMES = [
    "Wren",
    "Idris",
    "Marisol",
    "Callum",
    "Noor",
    "Thaddeus",
    "Ines",
    "Osei",
    "Petra",
    "Ronan",
    "Saoirse",
    "Kenji",
    "Amara",
    "Dmitri",
    "Yara",
    "Bastian",
    "Freya",
    "Tobias",
    "Nadia",
    "Emrys",
    "Solveig",
    "Kwame",
    "Ottilie",
    "Rafael",
    "Ingrid",
]
_LAST_NAMES = [
    "Achterberg",
    "Kowalczyk",
    "Nakashima",
    "Villanueva",
    "Ferreira",
    "Osgood",
    "Bratton",
    "Delacroix",
    "Adeyemi",
    "Hallgren",
    "Marchetti",
    "Okonkwo",
    "Vasilenko",
    "Larrabee",
    "Chowdhury",
    "Duplantis",
    "Ekstrom",
    "Bellweather",
    "Nazarov",
    "Osunde",
]
_SUBJECTS = random.sample([f"{first} {last}" for first in _FIRST_NAMES for last in _LAST_NAMES], 50)

_COMPANY_PREFIXES = [
    "Cinder",
    "Harbor",
    "Lumen",
    "Granite",
    "Auric",
    "Fenwick",
    "Bramble",
    "Sable",
    "Northwind",
    "Copperline",
    "Vantage",
    "Emberfield",
    "Truescale",
    "Ridgemark",
]
_COMPANY_SUFFIXES = ["Corp", "Industries", "LLC", "Inc", "Co", "Labs", "Group", "Partners"]
_COMPANIES = [f"{p} {s}" for p in _COMPANY_PREFIXES for s in _COMPANY_SUFFIXES]

_CITIES = [
    "Austin",
    "Denver",
    "Seattle",
    "Chicago",
    "Boston",
    "Portland",
    "Raleigh",
    "Albuquerque",
    "Providence",
    "Tucson",
    "Spokane",
    "Madison",
    "Savannah",
    "Boise",
    "Asheville",
]

_DRINKS = [
    "cortado",
    "cold brew",
    "espresso",
    "drip coffee",
    "matcha",
    "flat white",
    "americano",
    "chai latte",
    "pour-over",
    "yerba mate",
]

_EDITORS = [
    "Vim",
    "Emacs",
    "VS Code",
    "Sublime",
    "Neovim",
    "Zed",
    "Helix",
    "IntelliJ",
    "Xcode",
    "Nano",
]

_PROJECT_WORDS = [
    "Atlas",
    "Orion",
    "Nimbus",
    "Vertex",
    "Prism",
    "Halcyon",
    "Wayfinder",
    "Cinderpath",
    "Fathom",
    "Quillon",
    "Tessellate",
    "Driftwood",
]

_DEPLOY_TARGETS = [
    "Kubernetes",
    "Docker Swarm",
    "Nomad",
    "ECS",
    "bare metal",
    "Fly.io",
    "Railway",
    "Cloud Run",
    "Fargate",
    "Render",
]

_MANAGER_NAMES = [f"{first} {last}" for first, last in zip(_FIRST_NAMES[::-1], _LAST_NAMES[::-1], strict=False)]

_ALLERGIES = [
    "peanuts",
    "shellfish",
    "gluten",
    "dairy",
    "soy",
    "tree nuts",
    "eggs",
    "sesame",
    "strawberries",
    "latex",
]

_TEMPLATES = [
    ("works at {old}", "works at {new}", _COMPANIES),
    ("lives in {old}", "lives in {new}", _CITIES),
    ("'s favorite drink is {old}", "'s favorite drink is {new}", _DRINKS),
    ("uses {old} as their primary editor", "uses {new} as their primary editor", _EDITORS),
    ("is working on the {old} project", "is working on the {new} project", _PROJECT_WORDS),
    ("prefers {old} for deployments", "prefers {new} for deployments", _DEPLOY_TARGETS),
    ("'s manager is {old}", "'s manager is {new}", _MANAGER_NAMES),
    ("is allergic to {old}", "is allergic to {new}", _ALLERGIES),
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
        # fact_id/query_text are derived from `subject` verbatim -- distinct
        # per-subject ids/prose depend on subjects being globally unique
        subject_id = subject.replace(" ", "_").lower()
        for template_idx in range(len(_TEMPLATES)):
            writes, query = _build_pair(subject_id, template_idx, t)
            # swap the id-safe form back to the natural-language name in the
            # actual fact/query text, keep the id-safe form only in fact_id
            for w in writes:
                w["fact_text"] = w["fact_text"].replace(subject_id, subject, 1)
            query["query_text"] = query["query_text"].replace(subject_id, subject, 1)
            events.extend(writes)
            events.append(query)
            t += 10.0
    return {"name": "contradiction_workload", "kind": "synthetic", "events": events}


if __name__ == "__main__":
    workload = build_workload()
    n_queries = sum(1 for e in workload["events"] if e["kind"] == "query")

    fact_texts = [e["fact_text"] for e in workload["events"] if e["kind"] == "write"]
    n_duplicate_fact_texts = len(fact_texts) - len(set(fact_texts))
    if n_duplicate_fact_texts:
        raise SystemExit(f"refusing to write: {n_duplicate_fact_texts} duplicate fact_text values across subjects")

    out_path = Path(__file__).parent / "contradiction_workload.json"
    out_path.write_text(json.dumps(workload, indent=2), encoding="utf-8")
    print(f"wrote {out_path} -- {n_queries} query events (n={n_queries}), 0 duplicate fact_text values")
