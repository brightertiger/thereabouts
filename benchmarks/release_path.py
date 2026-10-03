"""Measure MY/SG preparation, the real packs runner, local install and queries."""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Direct execution puts benchmarks/, rather than the repository, on sys.path.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psutil

from pipeline.runtime.jsonio import sha256_file
from pipeline.runtime.resources import workspace_bytes

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = ["core", "postal", "airports", "locode", "phone", "ip"]
BLOCKS = ["836505fffffffff", "836500fffffffff", "836526fffffffff"]
DISK_FLOOR = 5_000_000_000
WORKSPACE_LIMIT = 4_000_000_000
RSS_LIMIT = 2_000_000_000
OUTPUT_LIMIT = 1_000_000_000


def record(measurements: dict[str, Any], output: Path, *, write: bool) -> None:
    """Retain a local report; update tracked history only on explicit request."""
    text = json.dumps(measurements, indent=2) + "\n"
    (output / "measurements.json").write_text(text)
    if write:
        (ROOT / "docs/CLIENT_RELEASE_MEASUREMENTS.json").write_text(text)
    print(text, end="")


def measure(
    command: list[str], output: Path, name: str, baseline: int
) -> dict[str, Any]:
    """Sample the child process tree every 100 ms; check output/disk admission."""
    start = time.perf_counter()
    peak = 0
    with (
        (output / f"{name}.stdout").open("w") as stdout,
        (output / f"{name}.stderr").open("w") as stderr,
    ):
        child = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr)
        process = psutil.Process(child.pid)
        while child.poll() is None:
            try:
                processes = [process, *process.children(recursive=True)]
                rss = sum(p.memory_info().rss for p in processes if p.is_running())
                peak = max(peak, rss)
            except psutil.NoSuchProcess:
                pass
            size = workspace_bytes(output)
            if (
                peak > RSS_LIMIT
                or size > OUTPUT_LIMIT
                or baseline + size > WORKSPACE_LIMIT
                or shutil.disk_usage(ROOT).free < DISK_FLOOR
            ):
                child.terminate()
                child.wait()
                raise RuntimeError("Release measurement exceeded its resource boundary")
            time.sleep(0.1)
        if child.returncode:
            detail = (output / f"{name}.stdout").read_text() + (
                output / f"{name}.stderr"
            ).read_text()
            raise RuntimeError(f"{name} failed: {detail}")
    return {"seconds": time.perf_counter() - start, "sampled_peak_rss_bytes": peak}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Also update docs/CLIENT_RELEASE_MEASUREMENTS.json",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT) or output.exists():
        parser.error("--output must be a new directory within this worktree")
    baseline = workspace_bytes(ROOT)
    output.mkdir(parents=True)
    common = [
        "--root",
        str(output),
        "--version",
        "2026.10",
        "paths.dataset=dataset",
        "paths.packs=packs",
        "paths.work=work",
        "resources.max_workspace=1000000000",
    ]
    measurements: dict[str, Any] = {
        "machine": "Apple M2, 8 GB",
        "source_manifest_sha256": sha256_file(args.source / "manifest.json"),
        "countries": ["MY", "SG"],
        "blocks": BLOCKS,
        "rss_method": "100 ms samples of child process tree; not an allocator bound",
    }
    measurements["prepare"] = measure(
        [
            sys.executable,
            "-m",
            "pipeline",
            "release",
            "prepare",
            *common,
            "--from",
            str(args.source),
            "release.countries=[MY,SG]",
            "release.blocks=[" + ",".join(BLOCKS) + "]",
            "release.dataset.max_output_bytes=412318215",
            "release.packs.families=[]",
        ],
        output,
        "prepare",
        baseline,
    )
    measurements["packs"] = measure(
        [
            sys.executable,
            "-m",
            "pipeline",
            "release",
            "packs",
            *common,
            "resources.workers=2",
            "release.packs.families=[" + ",".join(FAMILIES) + "]",
        ],
        output,
        "packs",
        baseline,
    )
    console = str(Path(sys.executable).parent / "thereabouts")
    release = output / "packs/2026.10"
    command = [console, "--data-dir", str(output / "store")]
    measurements["install"] = measure(
        [
            *command,
            "data",
            "install",
            *FAMILIES,
            "--from",
            str(release),
            "--yes",
        ],
        output,
        "install",
        baseline,
    )
    queries = [
        (["reverse", "--lat", "3.139", "--lon", "101.6869"], "MY"),
        (["reverse", "--lat", "1.3521", "--lon", "103.8198"], "SG"),
        (["geocode", "Kuala Lumpur", "--country", "MY"], "MY"),
        (["postal", "50000", "--country", "MY"], "MY"),
        (["airport", "SIN"], "SG"),
        (["locode", "SGCHG"], "SG"),
        (["phone", "+60321234567"], "MY"),
        (["ip", "1.9.0.1"], "MY"),
    ]
    measurements["lookups"] = []
    for number, (query, country) in enumerate(queries):
        name = f"lookup-{number}"
        timing = measure([*command, "--json", *query], output, name, baseline)
        answer = json.loads((output / f"{name}.stdout").read_text())
        assert answer["status"] == "matched", answer
        assert answer["country"]["code"] == country, answer
        measurements["lookups"].append({"argv": query, "result": answer, **timing})
    dataset = output / "dataset/2026.10"
    manifest = json.loads((dataset / "manifest.json").read_text())
    measurements["dataset"] = {
        "bytes": workspace_bytes(dataset),
        "tables": manifest["statistics"],
        "manifest_sha256": sha256_file(dataset / "manifest.json"),
    }
    measurements["families"] = {}
    for family in FAMILIES:
        pack = release / family
        measurements["families"][family] = {
            "bytes": workspace_bytes(pack),
            "archive_bytes": (release / f"{family}.tar").stat().st_size,
            "manifest_sha256": sha256_file(pack / "manifest.json"),
        }
    measurements["plates"] = (
        "Unavailable: golden has no plate tables; normalized/plates_country is absent."
    )
    measurements["output_bytes"] = workspace_bytes(output)
    record(measurements, output, write=args.write)


if __name__ == "__main__":
    main()
