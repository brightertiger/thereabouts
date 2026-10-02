"""Build, verify or score a golden v2 snapshot without publishing externally."""

import argparse
from pathlib import Path

from build_data.acquire import Workspace

from .run import run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "verify", "score"])
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("data/golden-v2"))
    parser.add_argument(
        "--gate", type=Path, default=Path("data/work/v2-pilot/gate.json")
    )
    parser.add_argument(
        "--points", type=Path, default=Path("eval/city_points/points.csv")
    )
    parser.add_argument("--split", choices=["dev", "holdout"], default="dev")
    args = parser.parse_args()
    workspace = Workspace(args.data_dir.resolve())
    if args.command == "run":
        run(workspace, args.output.resolve(), args.gate)
    elif args.command == "verify":
        from .verify import verify

        verify(workspace, args.output.resolve())
    else:
        from .score import score

        score(args.output.resolve(), args.points, args.split)


if __name__ == "__main__":
    main()
