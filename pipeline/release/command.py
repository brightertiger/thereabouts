"""Prepare from a read-only snapshot, upload explicitly, or render registry YAML."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from pipeline.config import load
from pipeline.runtime.context import context
from pipeline.runtime.jsonio import write_json
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.paths import located
from pipeline.runtime.resources import ResourceGuard
from pipeline.runtime.runner import exclusive
from pipeline.stages.dataset import DatasetStage

from . import pins as release_pins
from . import prepared, registry
from .assemble import assemble
from .publish import inventory, publish
from .source import external


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "packs", "upload", "registry"))
    parser.add_argument("overrides", nargs="*")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--from", dest="source", type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_intermixed_args(argv)
    config = load(
        profile=args.profile,
        overrides=[
            *args.overrides,
            f"paths.root={args.root}",
            f"release.version={json.dumps(args.version)}",
            "release.enabled=true",
        ],
    )
    root = args.root.absolute()
    dataset = located(root, config.paths.dataset) / args.version
    if args.dry_run and args.command != "upload":
        raise ValueError(
            "--dry-run is an upload option; preparation writes its separate output root"
        )
    if args.source and args.command != "prepare":
        raise ValueError("--from is a prepare option")
    if args.report and args.report.resolve().is_relative_to(
        args.source.resolve() if args.source else dataset.resolve()
    ):
        raise ValueError("Report must be outside the input dataset")
    if args.command == "registry":
        if args.report is None:
            raise ValueError("Registry requires --report for the draft YAML")
        text = registry.entry(config.release, config.storage.get("s3_release", ""))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text)
        return 0
    if args.command == "prepare":
        if args.source is None:
            raise ValueError("Prepare requires --from completed input dataset")
        source = external(args.source, config.h3)
        if args.report and args.report.resolve().is_relative_to(source.root.resolve()):
            raise ValueError("Report must be outside the read-only input root")
        if root.resolve().is_relative_to(source.root.resolve()):
            raise ValueError(
                "Preparation output root must be outside the read-only input root"
            )
        release_pins.verify(
            source.root, config.paths.normalized, release_pins.selected(config)
        )
        guard = ResourceGuard(root, config.resources)
        identity = DatasetStage(
            next(stage for stage in config.stages if stage.name == "dataset")
        )
        # Standalone preparation consumes an explicit immutable snapshot, not a ledger.
        # The same assembler is used by the registered dataset stage.
        with Ledger(root, None) as ledger:
            ctx = context(config, root, ledger)
            parameters = {**identity.parameters(ctx), "input": source.content_identity}
            unit = identity.unit(ctx, args.version, parameters, ())
            fingerprint = unit.inputs_hash
        previous = (
            located(root, config.paths.dataset) / config.release.previous_version
            if config.release.previous_version
            else None
        )
        with exclusive(located(root, config.paths.work) / "pipeline.lock"):
            paths = assemble(source, dataset, config, guard, fingerprint, previous)
        result = {
            "version": args.version,
            "files": len(paths),
            "bytes": sum(path.stat().st_size for path in paths),
        }
    elif args.command == "packs":
        result = prepared.packs(config, root)
    else:
        destination = config.storage.get("s3_release")
        if not destination:
            raise ValueError("Configure storage.s3_release before upload")
        packs = {
            family: located(root, config.paths.packs) / args.version / family
            for family in config.release.packs.families
        }
        result = publish(
            inventory(dataset, packs, args.version),
            destination,
            args.version,
            config.release.publish,
            dry_run=args.dry_run,
        )
    if args.report:
        write_json(args.report, result)
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key != "files" or not isinstance(value, list)
            },
            indent=2,
        )
    )
    return 0
