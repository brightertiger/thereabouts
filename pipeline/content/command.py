"""Read-only logical comparison exposed through the pipeline command."""

import argparse
from collections.abc import Sequence
from pathlib import Path

from pipeline.config import load
from pipeline.engines.artifacts import read_json
from pipeline.runtime.jsonio import write_json

from .digest import digest_dataset


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--temp-dir", type=Path, required=True)
    parser.add_argument("overrides", nargs="*")
    args = parser.parse_intermixed_args(argv)
    config = load(overrides=args.overrides)
    dataset = args.dataset.resolve()
    for name, path in (("output", args.output), ("temp-dir", args.temp_dir)):
        if path.resolve().is_relative_to(dataset):
            raise ValueError(f"--{name} must be outside the read-only dataset")
    for original in (args.manifest, args.compare):
        if original and args.output.resolve() == original.resolve():
            raise ValueError("--output must not overwrite an input")
    value = digest_dataset(
        args.dataset,
        temp_dir=args.temp_dir,
        limits=config.content,
        manifest_path=args.manifest,
    )
    write_json(args.output, value)
    if args.compare and read_json(args.compare) != value:
        raise ValueError("Table contents differ; inspect the per-table digests")
    print(value["sha256"])
    return 0
