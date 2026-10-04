"""Measure an authorised local world export, then delete its pack."""

import argparse
import hashlib
import json
import platform
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from tests.benchmarks.core_read_path import ROOT

FLOOR = 5 * 1024**3
WORKTREE_LIMIT = 4_000_000_000
OUTPUT_LIMIT = 1_000_000_000
RSS_LIMIT = 2_000_000_000
# Stop with headroom for writes between samples. This is a guard, not a size estimate.
HEADROOM = 128 * 1024**2


def disk_bytes(path: Path) -> int:
    result = subprocess.run(
        ["du", "-sk", str(path)], text=True, capture_output=True, check=False
    )
    if not result.stdout.strip():
        raise RuntimeError(f"Cannot measure worktree: {result.stderr}")
    return int(result.stdout.split()[0]) * 1024


def ip_start_statistics(golden: Path) -> dict[str, int]:
    """Check the actual IPv6 low words; the format supports both zero and nonzero."""
    import pyarrow.parquet as pq

    manifest = json.loads((golden / "manifest.json").read_text())
    root = golden / manifest.get("data_root", ".")
    counts = {"ipv6_rows": 0, "ipv6_nonzero_low64": 0}
    for table in manifest["tables"]:
        if table["kind"] != "ip_ranges":
            continue
        for batch in pq.ParquetFile(root / table["path"]).iter_batches(
            batch_size=65536, columns=["ip_version", "ip_start_packed"]
        ):
            for version, address in zip(
                batch.column(0).to_pylist(), batch.column(1).to_pylist(), strict=True
            ):
                if version == 6:
                    if not isinstance(address, bytes) or len(address) != 16:
                        raise ValueError("Expected a packed IPv6 start")
                    counts["ipv6_rows"] += 1
                    counts["ipv6_nonzero_low64"] += (
                        int.from_bytes(address[8:], "big") != 0
                    )
    return counts


def child(
    golden: Path, family: str, output: Path, record: Path, core_pack: Path
) -> None:
    from thereabouts import _core

    extra = ip_start_statistics(golden) if family == "ip" else {}
    start = time.perf_counter()
    manifest = _core.write_pack(
        str(golden),
        family,
        str(output),
        {
            "data_version": "2026.10",
            "core_pack": str(core_pack),
            "sources": ["golden dataset; source manifest digest retained"],
            "attribution": "Golden sources; see dataset notices",
            "notices": {
                name: (golden / name).read_text()
                for name in ("DATA_LICENSES.md", "DATASET_CARD.md")
            },
        },
    )
    measurement = {
        "family": family,
        "export_seconds": time.perf_counter() - start,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * (1 if platform.system() == "Darwin" else 1024),
        "pack_bytes": sum(p.stat().st_size for p in output.iterdir()),
        "input_manifest_sha256": hashlib.sha256(
            (golden / "manifest.json").read_bytes()
        ).hexdigest(),
        "storage": manifest["storage"],
        **extra,
    }
    record.write_text(json.dumps(measurement, indent=2) + "\n")


def update_docs(measurement: dict[str, Any]) -> None:
    path = ROOT / "tests/benchmarks/measurements/CLIENT_CORE_MEASUREMENTS.json"
    data = json.loads(path.read_text())
    data.setdefault("world_exports", {})[measurement["family"]] = measurement
    path.write_text(json.dumps(data, indent=2) + "\n")
    start, end = "<!-- world-exports:start -->", "<!-- world-exports:end -->"
    lines = [
        "| Family | Measured pack bytes | Peak RSS bytes | Seconds | Output deleted |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for family, value in data["world_exports"].items():
        lines.append(
            f"| {family} | {value['pack_bytes']:,} | {value['peak_rss_bytes']:,} | "
            f"{value['export_seconds']:.3f} | {value['output_deleted']} |"
        )
    section = start + "\n" + "\n".join(lines) + "\n" + end
    status = ROOT / "docs/clients/status.md"
    text = status.read_text()
    if start in text:
        a, b = text.index(start), text.index(end) + len(end)
        text = text[:a] + section + text[b:]
    else:
        text += "\n## Measured world exports\n\n" + section + "\n"
    status.write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("family", choices=["ip", "postal"])
    parser.add_argument("--golden", type=Path, required=True)
    parser.add_argument("--core-pack", type=Path, required=True)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    parent = ROOT / ".tmp/world-exports"
    output = parent / f"{args.family}-world"
    stage = parent / f".{output.name}.building"
    record = parent / f"{args.family}-measurement.json"
    if args.child:
        child(args.golden, args.family, output, record, args.core_pack)
        return
    parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or stage.exists():
        parser.error("Refusing to reuse an existing export or staging directory")
    used = disk_bytes(ROOT)
    free = shutil.disk_usage(ROOT).free
    if used > 2_200_000_000 or free < FLOOR + 2_000_000_000:
        parser.error("Clear worktree build caches before this bounded measurement")
    # An exclusive marker prevents an accidental second real export.
    marker = parent / f"{args.family}-attempt.json"
    with marker.open("x") as stream:
        json.dump(
            {"family": args.family, "initial_bytes": used, "initial_free": free}, stream
        )
    start = time.perf_counter()
    peak_disk, peak_output, peak_rss, minimum_free = used, 0, 0, free
    log = parent / f"{args.family}.log"
    failure = ""
    with log.open("w") as stream:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests.benchmarks.world_export",
                args.family,
                "--golden",
                str(args.golden),
                "--core-pack",
                str(args.core_pack),
                "--child",
            ],
            cwd=ROOT,
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
        try:
            while process.poll() is None:
                used = disk_bytes(ROOT)
                free = shutil.disk_usage(ROOT).free
                current = stage if stage.exists() else output
                output_bytes = 0
                for artifact in current.glob("*"):
                    if artifact.name.startswith("."):
                        continue
                    try:
                        output_bytes += artifact.stat().st_size
                    except FileNotFoundError:
                        continue
                rss_text = subprocess.run(
                    ["ps", "-o", "rss=", "-p", str(process.pid)],
                    text=True,
                    capture_output=True,
                    check=False,
                ).stdout.strip()
                rss = int(rss_text) * 1024 if rss_text else 0
                peak_disk = max(peak_disk, used)
                peak_output = max(peak_output, output_bytes)
                peak_rss = max(peak_rss, rss)
                minimum_free = min(minimum_free, free)
                if (
                    used > WORKTREE_LIMIT - HEADROOM
                    or free < FLOOR + HEADROOM
                    or output_bytes > OUTPUT_LIMIT - HEADROOM
                    or rss > RSS_LIMIT - HEADROOM
                ):
                    failure = "Export stopped at the resource guard"
                    process.terminate()
                    break
                time.sleep(0.5)
            code = process.wait()
            if failure or code:
                raise RuntimeError(f"{failure or 'Export failed'}; inspect {log}")
            measurement = json.loads(record.read_text()) | {
                "monitored_peak_worktree_bytes": peak_disk,
                "monitored_peak_output_bytes": peak_output,
                "monitored_peak_rss_bytes": peak_rss,
                "minimum_free_bytes": minimum_free,
                "measurement_seconds": time.perf_counter() - start,
                "output_deleted": False,
            }
            if measurement["pack_bytes"] >= OUTPUT_LIMIT:
                raise RuntimeError("Output exceeds authorised size")
            manifests = ROOT / "tests/benchmarks/measurements"
            manifests.mkdir(exist_ok=True)
            shutil.copyfile(
                output / "manifest.json",
                manifests / f"{args.family}-world-manifest.json",
            )
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait()
            for owned in (stage, output):
                if owned.exists():
                    shutil.rmtree(owned)
    measurement["output_deleted"] = not output.exists() and not stage.exists()
    record.write_text(json.dumps(measurement, indent=2) + "\n")
    update_docs(measurement)
    print(json.dumps(measurement, indent=2))


if __name__ == "__main__":
    main()
