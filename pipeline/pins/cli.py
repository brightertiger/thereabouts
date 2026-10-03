"""Explicit lock updates from reviewed proposals or an already-built workspace."""

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.jsonio import digest
from pipeline.runtime.paths import located

from .lock import read_lock, write_lock
from .models import SourcePin
from .workspace import from_manifest

LOCK = REPOSITORY / "pins.lock"


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("update", "check"))
    parser.add_argument("sources", nargs="*")
    parser.add_argument("--lock", type=Path, default=LOCK)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--from-workspace", type=Path)
    inputs.add_argument(
        "--from-file",
        type=Path,
        help="reviewed candidate lock with explicit versions/checksums",
    )
    args = parser.parse_intermixed_args(argv)
    if args.command == "check":
        if args.from_file:
            raise ValueError(
                "Use pins update --from-file to accept a reviewed proposal"
            )
        saved = read_lock(args.lock)
        selected = args.sources or sorted(saved)
        for name in selected:
            if name not in saved:
                raise ValueError(f"Unpinned source: {name}")
            pin = saved[name]
            if args.from_workspace and pin.available:
                manifest_path = located(
                    Path(args.from_workspace), f"normalized/{name}/manifest.json"
                )
                observed = from_manifest(
                    Path(args.from_workspace), json.loads(manifest_path.read_bytes())
                )
                if digest(asdict(observed)) != digest(asdict(pin)):
                    raise ValueError(
                        f"Pinned source differs from retained manifest: {name}"
                    )
            print(
                f"{name}: {pin.release or 'not built'}; {len(pin.files)} pinned files"
            )
        return 0
    if not args.from_workspace and not args.from_file:
        raise ValueError(
            "pins update requires --from-file or --from-workspace; "
            "choose versions explicitly"
        )
    previous = read_lock(args.lock) if args.lock.exists() else {}
    proposed: dict[str, SourcePin]
    if args.from_file:
        proposed = read_lock(args.from_file)
    else:
        root = Path(args.from_workspace)
        proposed = {}
        for path in sorted((root / "normalized").glob("*/manifest.json")):
            manifest = json.loads(path.read_bytes())
            proposed[path.parent.name] = from_manifest(root, manifest)
    names = args.sources or sorted(proposed)
    if not names:
        raise ValueError("No source pins were discovered")
    for name in names:
        if name not in proposed:
            raise ValueError(f"No candidate pin for source: {name}")
        # Reject source names as well as any accidental lock source path escape.
        located(REPOSITORY, name)
        previous[name] = proposed[name]
    write_lock(args.lock, previous)
    print(f"Pinned {len(names)} source(s); no source data was downloaded or normalized")
    return 0
