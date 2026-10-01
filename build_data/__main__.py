"""Explicitly acquire source data, then build a bounded-memory H3 table."""

import argparse
import json
from pathlib import Path

from .source_pack import build as build_reference
from .table import build_table


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/h3-world"))
    parser.add_argument("--reference", type=Path, default=Path("data/reference"))
    parser.add_argument("--cache", type=Path, default=Path("data/cache"))
    parser.add_argument("--resolution", type=int, choices=(6, 7, 8), default=8)
    parser.add_argument("--metrics", type=Path)
    args = parser.parse_args()
    if not args.reference.exists():
        build_reference(args.reference, args.cache, None)
    result = build_table(args.reference, args.output, args.resolution)
    if args.metrics:
        args.metrics.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
