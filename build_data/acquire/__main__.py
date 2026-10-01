"""Explicit source dispatch for python -m build_data.acquire."""

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

from . import geoboundaries, geonames, osm_land, overture
from .status import print_status
from .workspace import Workspace

ADAPTERS: dict[str, tuple[Callable[[Workspace], None], Callable[[Workspace], None]]] = {
    "osm_land": (osm_land.download, osm_land.normalize),
    "overture": (overture.download, overture.normalize),
    "geonames": (geonames.download, geonames.normalize),
    "geoboundaries": (geoboundaries.download, geoboundaries.normalize),
}


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch sequential source stages; adapters own per-unit checkpoint decisions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=[*ADAPTERS, "all", "status"])
    parser.add_argument(
        "--stage", choices=["download", "normalize", "all"], default="all"
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args(argv)
    workspace = Workspace(args.data_dir)
    if args.source == "status":
        print_status(workspace)
        return 0
    workspace.prepare()
    selected = list(ADAPTERS) if args.source == "all" else [args.source]
    for source in selected:
        download, normalize = ADAPTERS[source]
        stages = {
            "download": (download,),
            "normalize": (normalize,),
            "all": (download, normalize),
        }
        for function in stages[args.stage]:
            workspace.check_budget()
            function(workspace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
