"""Explicitly acquire, verify and build an immutable local data directory."""

import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path

from .normalize import Audit, BBox, administration, features, normalize
from .pack import write_pack
from .reference.pack import Pack
from .settlements import read_settlements, regional_candidates
from .sources import acquire


def build(output: Path, cache: Path, bounds: BBox | None) -> None:
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite immutable pack: {output}")
    started = time.perf_counter()
    paths = acquire(cache)
    audit: Audit = []
    countries, admin1 = administration(paths, bounds, audit)
    land = [
        part
        for i, (_, geometry) in enumerate(features(paths["land"]))
        for part in normalize(geometry, f"land:{i}", audit, bounds)
    ]
    places = regional_candidates(read_settlements(paths["cities1000"]), bounds)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".pack-", dir=output.parent))
    try:
        pack = temporary / "pack"
        region = (
            "world" if bounds is None else "bbox-" + "-".join(f"{v:g}" for v in bounds)
        )
        write_pack(
            pack,
            countries,
            admin1,
            land,
            places,
            bounds,
            audit,
            snapshot_id=f"ne5.1.1-geonames2026-10-01-{region}-v1",
        )
        reader = Pack(pack)
        try:
            reader.verify()
        finally:
            reader.close()
        pack.rename(output)
    finally:
        shutil.rmtree(temporary)
    print(
        json.dumps(
            {
                "output": str(output),
                "build_seconds": time.perf_counter() - started,
                "pack_bytes": sum(p.stat().st_size for p in output.iterdir()),
                "countries": len(countries),
                "admin1": len(admin1),
                "places": len(places),
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/reference"))
    parser.add_argument("--cache", type=Path, default=Path("data/cache"))
    parser.add_argument(
        "--bbox", type=float, nargs=4, metavar=("WEST", "SOUTH", "EAST", "NORTH")
    )
    args = parser.parse_args()
    bounds: BBox | None = None
    if args.bbox:
        w, s, e, n = args.bbox
        if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
            parser.error(
                "bbox must satisfy -180 <= WEST < EAST <= 180 "
                "and -90 <= SOUTH < NORTH <= 90"
            )
        bounds = (w, s, e, n)
    build(args.output, args.cache, bounds)


if __name__ == "__main__":
    main()
