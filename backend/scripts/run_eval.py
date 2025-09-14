#!/usr/bin/env python
"""CLI report for the adversarial eval suite.

Run from backend/: `python scripts/run_eval.py`

Exits non-zero only if a 'must_pass' case under-triages — that's the
signal this is meant to gate a release on. 'known_gap' cases are always
reported but never fail the exit code; they're tracked separately (see
docs/phase3-adversarial-eval.md) and via xfail in
tests/test_adversarial_eval.py, which will loudly complain if one starts
passing without the docs being updated.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.eval.harness import run_all  # noqa: E402


def main() -> int:
    outcomes = run_all()

    must_pass_failures = []
    known_gap_lines = []

    print(f"{'ID':<22} {'CLASS':<11} {'EXPECTED':<11} {'ACTUAL':<11} RESULT")
    print("-" * 80)

    for o in outcomes:
        if o.case.cls == "must_pass":
            if o.under_triaged:
                status = "FAIL (UNDER-TRIAGED)"
                must_pass_failures.append(o)
            elif o.over_triaged:
                status = "FAIL (OVER-TRIAGED)"
                must_pass_failures.append(o)
            else:
                status = "OK"
        else:
            status = (
                "still a known gap"
                if not o.exact_match
                else "GAP APPEARS FIXED — update docs + case class"
            )
            known_gap_lines.append((o, status))

        print(
            f"{o.case.id:<22} {o.case.cls:<11} {o.case.expected_tier.value:<11} "
            f"{o.actual_tier.value:<11} {status}"
        )

    total = len(outcomes)
    must_pass_total = sum(1 for o in outcomes if o.case.cls == "must_pass")
    known_gap_total = total - must_pass_total

    print("-" * 80)
    print(
        f"must_pass: {must_pass_total - len(must_pass_failures)}/{must_pass_total} passing | "
        f"known_gap: {known_gap_total} tracked (informational)"
    )

    if must_pass_failures:
        print("\nCRITICAL: the following must-pass cases failed:")
        for o in must_pass_failures:
            if o.under_triaged:
                print(
                    f"  - {o.case.id}: UNDER-triaged — expected >= {o.case.expected_tier.value}, "
                    f"got {o.actual_tier.value}"
                )
            else:
                print(
                    f"  - {o.case.id}: OVER-triaged — expected <= {o.case.max_tier.value}, "
                    f"got {o.actual_tier.value}"
                )
            print(f"    text: {o.case.text!r}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
