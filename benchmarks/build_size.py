"""Rebuild and verify the combined table, then measure its complete pack and ZIP."""

import argparse
import json
import platform
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from pipeline.runtime.jsonio import sha256_file as sha256
from tests.support.table import build_table


def report(path: Path, build_metrics: dict[str, Any]) -> dict[str, Any]:
    """Add distribution sizes and provenance to this build's measured metrics."""
    manifest = json.loads((path / "manifest.json").read_text())
    with tempfile.TemporaryFile() as archive:
        with zipfile.ZipFile(
            archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9
        ) as target:
            for file in sorted(path.iterdir()):
                target.write(file, file.name)
        archive_bytes = archive.tell()
    return {
        **build_metrics,
        "snapshot_id": manifest["snapshot_id"],
        "manifest_sha256": sha256(path / "manifest.json"),
        "pack_bytes": sum(p.stat().st_size for p in path.iterdir()),
        "archive_bytes": archive_bytes,
        "archive_contents": "all files in the pack; ZIP deflate level 9",
        "build_scope": (
            "combined table plus full verification; excludes source pack and ZIP"
        ),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/h3-world"))
    parser.add_argument("--reference", type=Path, default=Path("data/reference"))
    parser.add_argument("--output", type=Path, default=Path("benchmarks/build.json"))
    args = parser.parse_args()
    if not args.reference.exists():
        parser.error("--reference must name an existing reference fixture")
    metrics = build_table(args.reference, args.data)
    text = json.dumps(report(args.data, metrics), indent=2) + "\n"
    args.output.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
