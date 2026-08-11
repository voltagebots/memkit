from __future__ import annotations

import time

from harness.models import PublishCandidate
from harness.publish_candidate import assert_numbers_only

_HEADER = """# MemKit vs baselines -- single-operator case study

**This is not a benchmark.** Three disclosures, read before any number below:

1. We evaluated our own system (MemKit) against baselines we selected ourselves.
2. Sample sizes are small by design -- real-data cells are capped at a
   handful to protect the privacy of real people whose data this touches
   (see the privacy note at the bottom). Claims here are direction/effect-
   size observations, not statistically significant population claims.
3. This is one operator's own long-lived usage, not a population sample.
   MemKit itself only ever claims to serve one operator -- this evaluation
   is scoped to match that claim, not to prove something bigger.

Generated automatically from numbers-only data -- this file has no
hand-authored prose in its body, by construction, so a real name or
example can't slip in here even by accident.

---

"""

_FOOTER = """

---

*Privacy note: real-data workloads in this study are sourced from the
author's own private operational records. No raw record, example, or
free-text excerpt from that data appears anywhere in this report or in
this project's public repository -- only aggregate numbers meeting a
minimum sample-size floor are shown above. Full methodology:
github.com/agent-rails/memkit-eval (private).*
"""


def render_public_report(candidate: PublishCandidate) -> str:
    """The only function that produces RESULTS_PUBLIC.md's bytes.
    Deterministic function of numbers-only PublishCandidate + this
    static template -- no free-text parameter exists on this function's
    signature for a caller to inject prose through."""
    assert_numbers_only(candidate)

    lines = [_HEADER]
    lines.append(f"Generated: {time.strftime('%Y-%m-%d', time.gmtime(candidate.generated_at))}\n\n")
    lines.append("| Metric | Value | n | 95% CI |\n|---|---|---|---|\n")
    for cell in candidate.cells:
        ci = f"[{cell.ci_low:.3f}, {cell.ci_high:.3f}]" if cell.ci_low is not None else "--"
        value_str = f"{cell.value:.3f}" if isinstance(cell.value, float) else str(cell.value)
        lines.append(f"| {cell.label} | {value_str} | {cell.n} | {ci} |\n")
    lines.append(_FOOTER)
    return "".join(lines)
