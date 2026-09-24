"""Run the data-quality checks.

    python -m src.quality.run                 # all layers
    python -m src.quality.run --layer clean
    python -m src.quality.run --no-save       # do not record results
Exit code 1 if any error-level check fails (so CI can use it).
"""
from __future__ import annotations

import argparse
import logging
import sys

from src.ops.logs import configure_logging
from src.quality.runner import run_checks, save_results, summarize


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--layer", choices=["raw", "clean", "dw", "ops"])
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()
    configure_logging()
    logging.getLogger(__name__).info("running data-quality checks", extra={"layer": args.layer or "all"})

    results = run_checks(args.layer)
    if not args.no_save:
        save_results(results)
    for r in results:
        label = "PASS" if r.passed else ("FAIL" if r.severity == "error" else "WARN")
        print(f"{label:<5}{r.name:<58}{r.detail}")
    summary = summarize(results)
    print(f"\n{summary['passed']}/{summary['total']} passed, "
          f"{len(summary['errors'])} errors, {len(summary['warnings'])} warnings")
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())