"""Eval Runner — deterministic evals and judges, deployed apart from the pipeline (design §4).

Stub: the entry point and process shape are real; the work loop lands in a later phase.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from sortyard.services import _stub

SUMMARY = (
    "Eval Runner — deterministic evals and judges, deployed apart from the pipeline (design §4)."
)


def main(argv: Sequence[str] | None = None) -> int:
    return _stub.run("eval-runner", SUMMARY, argv)


if __name__ == "__main__":
    sys.exit(main())
