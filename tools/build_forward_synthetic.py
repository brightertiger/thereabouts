"""Rebuild the original code fixture without changing legacy expectations."""

import json
import shutil
from pathlib import Path

from tests.codes.fixtures import snapshot
from thereabouts import _core
from tools.build_sample_pack import sha

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"


def build(family: str) -> None:
    root = FIXTURES / "datasets/forward-synthetic"
    manifest_path, _ = snapshot(root)
    manifest = json.loads(manifest_path.read_text())
    side = FIXTURES / "datasets/core-synthetic/golden"
    original = json.loads((side / "manifest.json").read_text())
    for table in original["tables"]:
        if table["kind"] not in {"countries", "subdivisions"}:
            continue
        path = side / original["data_root"] / table["path"]
        destination = root / table["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        manifest["tables"].append(
            table | {"sha256": sha(destination), "size": destination.stat().st_size}
        )
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n")
    _core.write_pack(
        str(manifest_path.parent),
        family,
        str(FIXTURES / f"packs/{family}-synthetic"),
        {
            "core_pack": str(ROOT / "tests/fixtures/packs/core-synthetic"),
            "data_version": "synthetic",
            "sources": ["legacy synthetic fixture"],
            "attribution": "Synthetic fixture; public domain",
            "notices": {"LICENSE": "Synthetic fixture: public domain."},
        },
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("family", choices=["postal", "airports"])
    build(parser.parse_args().family)
