"""Review upstream pin proposals, explicitly accept them, or check built evidence."""

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from pipeline.config import load
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.jsonio import digest, write_json
from pipeline.runtime.paths import located

from .lock import read_lock, write_lock
from .models import SourcePin
from .proposal import merge, upstream
from .workspace import from_manifest

LOCK = REPOSITORY / "pins.lock"
PROPOSAL = REPOSITORY / ".cache/pipeline/pins-proposal.yaml"


def check(saved: dict[str, SourcePin], names: list[str], root: Path | None) -> None:
    for name in names:
        if name not in saved:
            raise ValueError(f"Unpinned source: {name}")
        pin = saved[name]
        if root and pin.available:
            manifest_path = located(root, f"normalized/{name}/manifest.json")
            observed = from_manifest(root, json.loads(manifest_path.read_bytes()))
            if digest(asdict(observed)) != digest(asdict(pin)):
                raise ValueError(
                    f"Pinned source differs from retained manifest: {name}"
                )
        print(f"{name}: {pin.release or 'not built'}; {len(pin.files)} pinned files")


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("update", "check"))
    parser.add_argument("sources", nargs="*")
    parser.add_argument("--lock", type=Path, default=LOCK)
    parser.add_argument("--proposal", type=Path, default=PROPOSAL)
    parser.add_argument(
        "--accept",
        action="store_true",
        help="write the reviewed proposal into pins.lock",
    )
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--from-workspace", type=Path)
    inputs.add_argument(
        "--from-file",
        type=Path,
        help="candidate lock with explicit versions/checksums; no upstream access",
    )
    args = parser.parse_intermixed_args(argv)
    if args.command == "check":
        if args.from_file or args.accept or args.proposal != PROPOSAL:
            raise ValueError("Proposal and acceptance options require pins update")
        saved = read_lock(args.lock)
        check(saved, args.sources or sorted(saved), args.from_workspace)
        return 0
    if any(
        path.resolve() == args.lock.resolve()
        for path in (args.proposal, args.proposal.with_suffix(".diff.json"))
    ):
        raise ValueError("Proposal and diff paths must differ from the lock")
    if args.from_workspace:
        root = args.from_workspace.resolve()
        for output in (
            args.proposal,
            args.proposal.with_suffix(".diff.json"),
            args.lock,
        ):
            if output.resolve().is_relative_to(root):
                raise ValueError("Pin outputs must be outside the inspected workspace")
    previous = read_lock(args.lock) if args.lock.exists() else {}
    proposed: dict[str, SourcePin]
    if args.from_file:
        proposed = read_lock(args.from_file)
        names = args.sources or sorted(proposed)
    elif args.from_workspace:
        proposed = {}
        for path in sorted(
            (args.from_workspace / "normalized").glob("*/manifest.json")
        ):
            if not args.sources or path.parent.name in args.sources:
                proposed[path.parent.name] = from_manifest(
                    args.from_workspace, json.loads(path.read_bytes())
                )
        names = args.sources or sorted(proposed)
    else:
        config = load()
        names = args.sources or sorted(
            name for name, source in config.sources.items() if source.enabled
        )
        proposed = upstream(config, names)
    if not names:
        raise ValueError("No source pins were discovered")
    merged, changes = merge(previous, proposed, names)
    write_lock(args.proposal, merged)
    diff = args.proposal.with_suffix(".diff.json")
    write_json(diff, changes)
    if args.accept:
        write_lock(args.lock, merged)
    for name, change in changes.items():
        print(
            f"{name}: {change['old_release']} → {change['new_release']}; "
            f"{len(change['added'])} added, {len(change['removed'])} removed, "
            f"{len(change['changed_files'])} changed files"
        )
    print(f"Proposal: {args.proposal}; diff: {diff}")
    print(
        "Lock updated"
        if args.accept
        else "Lock unchanged; review then use --from-file PROPOSAL --accept"
    )
    return 0
