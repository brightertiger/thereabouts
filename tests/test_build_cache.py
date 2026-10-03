"""Ensure uv invalidates the editable extension for its entire local crate graph."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_uv_keys_cover_linked_crates_and_embedded_resources() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    covered = {
        path.resolve()
        for key in config["tool"]["uv"]["cache-keys"]
        if "file" in key
        for path in ROOT.glob(key["file"])
    }
    pending = [ROOT / "core/thereabouts-py"]
    visited: set[Path] = set()
    while pending:
        crate = pending.pop().resolve()
        if crate in visited:
            continue
        visited.add(crate)
        manifest = crate / "Cargo.toml"
        required = {manifest, *(p for p in (crate / "src").rglob("*") if p.is_file())}
        assert required <= covered, sorted(
            str(p.relative_to(ROOT)) for p in required - covered
        )
        dependencies = tomllib.loads(manifest.read_text()).get("dependencies", {})
        pending.extend(
            crate / value["path"]
            for value in dependencies.values()
            if isinstance(value, dict) and "path" in value
        )
    assert ROOT / "core/thereabouts-cli-core" in visited
