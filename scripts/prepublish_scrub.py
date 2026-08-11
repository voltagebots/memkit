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
    failure mode a security gate must never have).

    CORRECTED (worf HIGH, code review): comment lines (starting with '#')
    were being loaded as literal patterns -- including a bare '#', which
    matches every markdown heading in every rendered report, making the
    shipped scrub permanently fail-closed on a report that was actually
    clean. A separate ad-hoc loader in the test suite already skipped
    comments correctly, which meant the "passing" test never exercised
    this real code path -- the exact vacuous-test shape this project's
    own shared conventions warn about."""
    if not DENYLIST_PATH.exists():
        raise FileNotFoundError(f"denylist not found: {DENYLIST_PATH} -- refusing to scrub without one")
    entries = [
        line.strip()
        for line in DENYLIST_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not entries:
        raise ValueError(
            f"denylist at {DENYLIST_PATH} has no real entries -- refusing to scrub, this is not a clean pass"
        )
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
    # not trusting the same logic twice. Scoped to rows containing
    # "pooled real data" -- after the BLOCKER fix in publish_candidate.py,
    # that literal is the ONLY way real data reaches a published row, so
    # checking every row (including synthetic ones, published at
    # threshold=0 by design) would false-positive on a small synthetic
    # test run and push toward hand-editing this gate to publish.
    #
    # CORRECTED (spock MEDIUM x2): (a) this check used to be case-
    # sensitive while the denylist grep above is case-insensitive -- a
    # differently-cased label ("POOLED REAL DATA") bypassed this backstop
    # entirely. (b) the n-column regex only captured \d+; a non-integer n
    # (e.g. "09.0") failed the match and was silently SKIPPED (fail-open)
    # instead of treated as a violation -- broadened to capture the whole
    # cell and fail closed on anything that isn't a clean small integer.
    from harness.constants import MIN_REAL_CELL_N

    for line in content.splitlines():
        if "pooled real data" not in line.lower():
            continue
        cell_match = re.search(r"\|\s*[^|]+\|\s*[^|]+\|\s*([^|]+?)\s*\|", line)
        if cell_match is None:
            reasons.append(f"real-data row has no parseable n column: {line!r}")
            continue
        raw_n = cell_match.group(1).strip()
        if not re.fullmatch(r"\d+", raw_n):
            reasons.append(f"real-data row's n column is not a clean integer: {raw_n!r}")
            continue
        if 0 < int(raw_n) < MIN_REAL_CELL_N:
            reasons.append(f"real-data cell with n={raw_n} is below MIN_REAL_CELL_N={MIN_REAL_CELL_N}")

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
