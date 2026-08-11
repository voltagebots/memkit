from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

DENYLIST_PATH = Path(__file__).parent / "denylist.txt"


@dataclass(frozen=True)
class ScrubResult:
    passed: bool
    reasons: tuple[str, ...] = ()


def load_denylist() -> list[str]:
    """Fails closed if the denylist is missing or empty -- an empty
    denylist and a clean scan must not look the same (worf/sentinel
    finding: an empty file silently passing everything is the exact
    failure mode a security gate must never have)."""
    if not DENYLIST_PATH.exists():
        raise FileNotFoundError(f"denylist not found: {DENYLIST_PATH} -- refusing to scrub without one")
    entries = [line.strip() for line in DENYLIST_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not entries:
        raise ValueError(f"denylist at {DENYLIST_PATH} is empty -- refusing to scrub, this is not a clean pass")
    return entries


def scrub_bytes(content: str, denylist: list[str]) -> ScrubResult:
    """Scans the EXACT bytes destined for the public site -- this runs on
    the rendered RESULTS_PUBLIC.md, not on the upstream PublishCandidate
    dataclass (the corrected design after the BLOCKER finding: the
    dataclass being clean does not mean the rendered file is)."""
    reasons = []
    for entry in denylist:
        if re.search(re.escape(entry), content, re.IGNORECASE):
            reasons.append(f"denylist match: {entry!r}")

    # Independent min-cell-size re-check on the rendered table, separate
    # from build_publish_candidate's own filter -- two independent checks,
    # not trusting the same logic twice.
    from harness.constants import MIN_REAL_CELL_N

    for match in re.finditer(r"\|\s*[^|]+\|\s*[^|]+\|\s*(\d+)\s*\|", content):
        n = int(match.group(1))
        if 0 < n < MIN_REAL_CELL_N:
            reasons.append(f"cell with n={n} is below MIN_REAL_CELL_N={MIN_REAL_CELL_N}")

    return ScrubResult(passed=not reasons, reasons=tuple(reasons))


def scrub_file(path: Path) -> ScrubResult:
    if not path.exists():
        return ScrubResult(passed=False, reasons=(f"file not found: {path}",))
    denylist = load_denylist()
    return scrub_bytes(path.read_text(encoding="utf-8"), denylist)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: prepublish_scrub.py <path-to-RESULTS_PUBLIC.md>", file=sys.stderr)
        return 2
    result = scrub_file(Path(sys.argv[1]))
    if result.passed:
        print("scrub: PASS")
        return 0
    print("scrub: FAIL")
    for reason in result.reasons:
        print(f"  - {reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
