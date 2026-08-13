import json

import pytest

from harness.workload_loader import WorkloadLoadError, load_real_workload, load_synthetic_workload

VALID_SYNTHETIC = {
    "name": "contradiction_smoke",
    "kind": "synthetic",
    "events": [
        {"kind": "write", "at": 1.0, "fact_id": "f1", "fact_text": "User works at Acme"},
        {
            "kind": "query",
            "at": 2.0,
            "query_text": "Where does the user work?",
            "gold": {"exact_ids": ["f1"]},
        },
    ],
}


def _write(root, name, data):
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


def test_load_synthetic_workload_happy_path(tmp_path):
    _write(tmp_path, "smoke", VALID_SYNTHETIC)
    workload = load_synthetic_workload("smoke", root=tmp_path)
    assert workload.name == "contradiction_smoke"
    assert workload.kind == "synthetic"
    assert len(workload.events) == 2
    assert workload.events[1].gold.exact_ids == frozenset({"f1"})


def test_load_real_workload_path_traversal_raises(tmp_path):
    private_root = tmp_path / "private"
    private_root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({**VALID_SYNTHETIC, "kind": "real"}), encoding="utf-8")
    with pytest.raises(WorkloadLoadError, match="outside"):
        load_real_workload("../outside", root=private_root)


def test_load_real_workload_kind_mismatch_raises(tmp_path):
    private_root = tmp_path / "private"
    _write(private_root, "mislabeled", VALID_SYNTHETIC)  # kind="synthetic" in a "real" load
    with pytest.raises(WorkloadLoadError, match="refusing to guess"):
        load_real_workload("mislabeled", root=private_root)


def test_load_synthetic_workload_kind_mismatch_raises(tmp_path):
    real_shaped = {**VALID_SYNTHETIC, "kind": "real"}
    _write(tmp_path, "mislabeled", real_shaped)
    with pytest.raises(WorkloadLoadError, match="refusing to guess"):
        load_synthetic_workload("mislabeled", root=tmp_path)


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(WorkloadLoadError, match="not found"):
        load_synthetic_workload("nonexistent", root=tmp_path)
