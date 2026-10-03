"""Measure a synthetic serving export; never reads or builds world data."""

import argparse
import platform
import resource
import statistics
import sys
import threading
import time
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from h3.api import basic_int as h3

from build_data.golden.schemas import CELLS
from build_data.serve.checkpoints import file_record
from build_data.serve.export import export
from build_data.serve.metadata import write_manifest
from tests.serve.fixtures import cell, golden
from thereabouts.packs.address import address
from thereabouts.packs.jsonio import parse
from thereabouts.packs.layout import CITY_METHODS
from thereabouts.packs.spatial import Spatial
from thereabouts.packs.verify import verify


def measure(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    source, release = golden(output / "input")
    value = parse(source.read_bytes())
    ordinary = next(
        r for r in value["tables"] if r["kind"] == "cells" and r["rows"] > 1
    )
    roots = [
        int(ordinary["block"], 16),
        *[h3.latlng_to_cell(a, b, 3) for a, b in ((0, 0), (45, 45), (-45, -45))],
    ]
    value["tables"].remove(ordinary)
    for root in roots:
        rows = [
            cell(key, CITY_METHODS[i % len(CITY_METHODS)])
            for i, key in enumerate(h3.cell_to_children(root, 8))
        ]
        path = release.parent / "golden/cells" / (h3.int_to_str(root) + ".parquet")
        pq.write_table(pa.Table.from_pylist(rows, schema=CELLS), path)
        value["tables"].append(
            file_record(
                path,
                release.parent,
                kind="cells",
                block=h3.int_to_str(root),
                rows=len(rows),
            )
        )
    write_manifest(source, value)
    peak_scratch = 0
    done = threading.Event()

    def observe() -> None:
        nonlocal peak_scratch
        while not done.wait(0.02):
            size = 0
            for path in output.glob(".serve-*/*"):
                try:
                    if path.is_file():
                        size += path.stat().st_size
                    elif path.name == "pack":
                        size += sum(
                            p.stat().st_size for p in path.rglob("*") if p.is_file()
                        )
                except FileNotFoundError:
                    continue  # Atomic publication/cleanup can race this observation.
            peak_scratch = max(peak_scratch, size)

    observer = threading.Thread(target=observe)
    observer.start()
    started = time.perf_counter()
    try:
        pack = export(source, release, output / "pack")
    finally:
        elapsed = time.perf_counter() - started
        done.set()
        observer.join()
    manifest = verify(pack)
    archive = output / "pack.zip"
    with zipfile.ZipFile(
        archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as zipped:
        for path in sorted(pack.rglob("*")):
            if path.is_file():
                info = zipfile.ZipInfo(
                    path.relative_to(pack).as_posix(), date_time=(1980, 1, 1, 0, 0, 0)
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                zipped.writestr(info, path.read_bytes(), compresslevel=6)
    record = next(r for r in manifest["files"] if r["kind"] == "cells")
    spatial = Spatial(pack / record["path"], manifest["place_count"])
    try:
        keys = [
            address(c, 8) for root in roots for c in h3.cell_to_children(root, 8)[::67]
        ]
        times = []
        for i in range(10000):
            block, key = keys[i % len(keys)]
            start = time.perf_counter_ns()
            assert spatial.lookup(block, key) is not None
            times.append(time.perf_counter_ns() - start)
    finally:
        spatial.close()
    report = {
        "machine": platform.platform(),
        "processor": platform.machine(),
        "python": platform.python_version(),
        "h3": h3.versions(),
        "pyarrow": pa.__version__,
        "golden_sha256": manifest["golden_sha256"],
        "manifest_sha256": manifest["manifest_sha256"],
        "stored_rows": sum(r["rows"] for r in value["tables"] if r["kind"] == "cells"),
        "blocks": sum(r["kind"] == "cells" for r in value["tables"]),
        "places": manifest["place_count"],
        "export_seconds": elapsed,
        "installed_bytes": sum(
            p.stat().st_size for p in pack.rglob("*") if p.is_file()
        ),
        "zip_bytes": archive.stat().st_size,
        "payload_bytes": {
            kind: sum(r["size"] for r in manifest["files"] if r["kind"] == kind)
            for kind in ("cells", "catalogue", "notice")
        },
        "sampled_peak_scratch_bytes": peak_scratch,
        "peak_process_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * (1 if sys.platform == "darwin" else 1024),
        "warm_label_lookup_median_ns": statistics.median(times),
        "warm_label_lookup_p99_ns": sorted(times)[9899],
        "limitations": [
            "Synthetic labels and five retained places; not a size forecast.",
            "Lookup excludes coordinate conversion, public results "
            "and catalogue decoding.",
            "RSS includes input generation; scratch sampled every 20 ms.",
            "ZIP is a measurement artifact; "
            "no installer or archive contract exists yet.",
        ],
    }
    write_manifest(output / "measurement.json", report)
    print((output / "measurement.json").read_text())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    measure(parser.parse_args().output)
