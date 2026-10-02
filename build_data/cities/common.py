"""Normalization policy and content-addressed country artifacts."""

from importlib.metadata import version
from pathlib import Path

from build_data.acquire.artifacts import read_json
from build_data.acquire.io import fingerprint, sha256_file
from build_data.reconcile.common import Row

POLICY = Path(__file__).with_name("policy.json")


def policy(path: Path = POLICY) -> Row:
    value = read_json(path)
    for cc, rules in value["countries"].items():
        parts = rules.get("parts", {})
        for source in parts:
            seen = {source}
            target = parts[source]
            while target in parts:
                if target in seen:
                    raise ValueError(f"Cyclic city policy in {cc}")
                seen.add(target)
                target = parts[target]
    return value


def builder() -> str:
    directory = Path(__file__).parent
    names = (
        "common.py",
        "candidates.py",
        "footprints.py",
        "policy_areas.py",
        "engine.py",
        "urban.py",
        "radius.py",
        "rural.py",
        "projection.py",
        "build.py",
        "mapping.py",
        "schemas.py",
    )
    helpers = (
        "golden/geometry.py",
        "golden/nearest.py",
        "golden/windows.py",
        "golden/offshore.py",
        "reconcile/land.py",
        "reference/sphere.py",
        "reconcile/spatial.py",
        "reconcile/classification.py",
    )
    return fingerprint(
        {
            "code": {n: sha256_file(directory / n) for n in names},
            "helpers": {n: sha256_file(directory.parent / n) for n in helpers},
            "libraries": {
                n: version(n) for n in ("numpy", "scipy", "shapely", "h3", "pyarrow")
            },
        }
    )
