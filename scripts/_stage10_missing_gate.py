#!/usr/bin/env python3
"""Explicit, honest failure marker for a Stage 10 acceptance gate that has no
real implementation or proof yet.

`scripts/validate_stage.py 10` wires this in as a normal Step wherever the
STAGE_10_PRODUCT_COMPLETION_SECURITY_ACCEPTANCE.md matrix requires an
acceptance area (bot audit, privacy/purge, global E2E, performance fixtures,
failure/chaos matrix, RC packaging, Discord live, ...) that this
acceptance-tooling-only pass did not implement. It always exits non-zero so
the Stage 10 validator can never silently report a false PASS for an
acceptance area with no genuine evidence behind it. Once the real gate is
implemented, its Step should replace the corresponding call to this script.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", required=True, help="Short, stable name of the missing gate.")
    parser.add_argument(
        "--reason",
        required=True,
        help="Why this gate is not implemented yet and what it still requires.",
    )
    args = parser.parse_args(argv)
    print(f"[STAGE 10 GATE NOT YET IMPLEMENTED] {args.gate}", file=sys.stderr)
    print(f"  {args.reason}", file=sys.stderr)
    print(
        "  This step intentionally fails until real Stage 10 product/acceptance "
        "work closes it; it is not a false PASS.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
