"""CLI for additive plate country evidence and the reference resolver."""

import argparse
import json
from pathlib import Path

from .build import build, verify
from .evaluation import evaluate
from .policy import Row
from .resolver import Resolver
from .sources import pins


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("fetch", "build", "status", "resolve", "evaluate")
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--plate")
    parser.add_argument("--country")
    parser.add_argument("--series")
    args = parser.parse_args()
    root = args.data_dir / "normalized" / "plates_country"
    result: Row
    if args.command == "fetch":
        result = dict(verified_sources=len(pins(args.data_dir, offline=False)))
    elif args.command == "build":
        result = build(args.data_dir)["counts"]
    elif args.command == "evaluate":
        result = evaluate(args.data_dir)["metrics"]
    else:
        resolver = Resolver.load(root)
        if args.command == "status":
            verify(args.data_dir)
            result = dict(
                status="verified",
                formats=len(resolver.formats),
                countries=len({r["country_code"] for r in resolver.formats}),
                priors=len(resolver.priors),
            )
        else:
            if args.plate is None:
                parser.error("resolve requires --plate")
            result = resolver.resolve(args.plate, args.country, series=args.series)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
