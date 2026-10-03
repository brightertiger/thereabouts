"""Internal hierarchy manifests use the explicitly supplied grid contract."""

from pathlib import Path

import pytest

from pipeline.config.schema import H3
from pipeline.geometry.errors import DamagedPackError
from pipeline.geometry.format import CITY_CUTOFF_KM
from pipeline.geometry.manifest import SCHEMA, read_manifest
from pipeline.runtime.jsonio import write_json


def test_manifest_requires_configured_finest_resolution(tmp_path: Path) -> None:
    grid = H3(cell_resolution=7)
    value = {
        "schema_version": SCHEMA,
        "resolution": grid.cell_resolution,
        "layout": "combined",
        "city_cutoff_km": CITY_CUTOFF_KM,
        "files": {},
    }
    write_json(tmp_path / "manifest.json", value)
    assert read_manifest(tmp_path, grid=grid) == value
    with pytest.raises(DamagedPackError, match="finest resolution"):
        read_manifest(tmp_path, grid=H3(cell_resolution=8))
