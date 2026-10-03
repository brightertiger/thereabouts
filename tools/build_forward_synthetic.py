"""Rebuild the original code fixture without changing legacy expectations."""

from pathlib import Path

from thereabouts import _core

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"


def build(family: str) -> None:
    root = FIXTURES / "datasets/forward-synthetic"
    _core.write_pack(
        str(root / "golden"),
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
