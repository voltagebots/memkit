"""Regression: run_evaluation.py's Mem0Backend(local) reached the publish step
for the first time and crashed on _assert_label_allowed -- the backend-name
allowlist still had the pre-fix bare "Mem0Backend" from before the
backend_name-conflation fix (replay.py's explicit override param), never
updated when the mode-qualified names were introduced. A backend that scores
real workloads for weeks before ever reaching a real-data publish path is
exactly how this kind of gap survives -- this test makes the allowlist
structurally track every name the driver can actually produce, so a future
new backend variant can't silently repeat it."""

import re

from harness.publish_candidate import _KNOWN_BACKENDS

RUN_EVALUATION_PATH = "scripts/run_evaluation.py"


def test_every_backend_name_the_driver_can_produce_is_in_the_allowlist():
    source = open(RUN_EVALUATION_PATH, encoding="utf-8").read()
    driver_backend_names = set(re.findall(r'backends\["([^"]+)"\]\s*=', source))

    assert driver_backend_names, "regex found nothing -- driver's backend-registration pattern changed"

    missing = driver_backend_names - _KNOWN_BACKENDS
    assert not missing, f"backend name(s) the driver can produce are missing from _KNOWN_BACKENDS: {missing}"
