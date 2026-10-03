"""Measure one local verified install into a fresh worktree-local store."""

import argparse
import platform
import resource
import sys
import time
from pathlib import Path

from thereabouts.installing.install import install
from thereabouts.packs.jsonio import canonical, sha256


def measure(source: Path, store: Path) -> dict[str, object]:
    if store.exists():
        raise ValueError("Measurement requires a fresh store")
    digest = sha256(source / "manifest.json")
    started = time.perf_counter()
    pack = install(source, manifest_sha256=digest, data_dir=store, offline=True)
    elapsed = time.perf_counter() - started
    return {
        "machine": platform.platform(),
        "processor": platform.machine(),
        "python": platform.python_version(),
        "manifest_sha256": digest,
        "installed_bytes": sum(
            p.stat().st_size for p in pack.rglob("*") if p.is_file()
        ),
        "store_bytes": sum(p.stat().st_size for p in store.rglob("*") if p.is_file()),
        "install_seconds": elapsed,
        "peak_process_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * (1 if sys.platform == "darwin" else 1024),
        "limitations": [
            "One local synthetic pack; copying and full verification included.",
            "No cache eviction, remote service or world data measurement.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = canonical(measure(args.source, args.store)) + b"\n"
    args.output.write_bytes(report)
    print(report.decode(), end="")
