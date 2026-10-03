"""Explicit core selection shared by fixture builders and conformance runners."""

import json
from pathlib import Path


def selection(pack: Path) -> dict[str, Path]:
    """Select the fixture core by release; production discovery uses the store."""
    manifest = json.loads((pack / "manifest.json").read_text())
    result = {manifest["family"]: pack}
    if manifest["family"] != "core":
        suffix = "synthetic" if manifest["data_version"] == "synthetic" else "sample"
        result["core"] = Path(__file__).parents[1] / f"fixtures/packs/core-{suffix}"
    return result
