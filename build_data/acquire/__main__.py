"""Explicit source dispatch for python -m build_data.acquire."""

import argparse
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path

from . import geoboundaries, geonames, osm_land, overture
from .lookup_catalog import LOOKUP_SOURCES
from .lookup_download import download as lookup_download
from .lookup_normalize import normalize as lookup_normalize
from .lookup_timezones import normalize as timezone_normalize
from .manifests import load_manifest
from .offload import offload, restore, state
from .status import print_status
from .workspace import Workspace

ADAPTERS: dict[str, tuple[Callable[[Workspace], None], Callable[[Workspace], None]]] = {
    "osm_land": (osm_land.download, osm_land.normalize),
    "overture": (overture.download, overture.normalize),
    "geonames": (geonames.download, geonames.normalize),
    "geoboundaries": (geoboundaries.download, geoboundaries.normalize),
    **{
        source: (
            partial(lookup_download, source=source),
            partial(lookup_normalize, source=source),
        )
        for source in LOOKUP_SOURCES
    },
}

ADAPTERS["timezones"] = (
    partial(lookup_download, source="timezones"),
    timezone_normalize,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch sequential source stages; adapters own per-unit checkpoint decisions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source", choices=[*ADAPTERS, "all", "status", "offload", "restore"]
    )
    parser.add_argument("--sources", nargs="+", choices=list(ADAPTERS))
    parser.add_argument("--remote", help="gs://bucket/raw prefix; source appended")
    parser.add_argument("--record-existing", action="store_true")
    parser.add_argument(
        "--stage", choices=["download", "normalize", "all"], default="all"
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args(argv)
    workspace = Workspace(args.data_dir)
    if args.source == "status":
        print_status(workspace)
        return 0
    if args.source in ("offload", "restore"):
        if not args.sources or (args.source == "offload" and not args.remote):
            parser.error("offload/restore require --sources; offload needs --remote")
        for source in args.sources:
            if args.source == "offload":
                offload(
                    workspace,
                    source,
                    f"{args.remote.rstrip('/')}/{source}",
                    record_existing=args.record_existing,
                )
            else:
                restore(workspace, source)
        return 0
    workspace.prepare()
    selected = list(ADAPTERS) if args.source == "all" else [args.source]
    for source in selected:
        if state(workspace, source):
            load_manifest(workspace, source)
            print(
                f"{source}: raw offloaded; verified normalized outputs; "
                "restore to rebuild"
            )
            continue
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
