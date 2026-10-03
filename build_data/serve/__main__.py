"""Local-only serving export and integrity verification."""

import argparse
from pathlib import Path

from thereabouts.packs.layout import DEFAULT_SHARD_BYTES
from thereabouts.packs.verify import verify

from .export import export


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("export")
    build.add_argument(
        "--family", choices=("reverse", "postal", "airports"), default="reverse"
    )
    build.add_argument("--manifest", type=Path, required=True)
    build.add_argument("--release", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--shard-bytes", type=int, default=DEFAULT_SHARD_BYTES)
    check = commands.add_parser("verify")
    check.add_argument("pack", type=Path)
    args = parser.parse_args()
    if args.command == "verify":
        value = verify(args.pack)
        print(
            f"Verified {value['family']} {value['data_version']}: "
            f"{value['manifest_sha256']}"
        )
    else:
        print(
            export(
                args.manifest,
                args.release,
                args.output,
                shard_bytes=args.shard_bytes,
                family=args.family,
            )
        )


if __name__ == "__main__":
    main()
