"""The inference bundle and tables use portable paths and verify all evidence."""

import csv
from pathlib import Path
from typing import cast

import pytest

from pipeline.engines.artifacts import read_json
from pipeline.engines.plate_country import build, evidence, formats, priors
from pipeline.engines.plate_country.policy import Row
from pipeline.engines.plate_country.resolver import Resolver
from pipeline.runtime.jsonio import write_json
from tests.pipeline.sources.test_plate_country_sources import wiki


def test_plate_build_move_and_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    countries = root / "countries.csv"
    with countries.open("w", newline="") as stream:
        fields = [
            "ISO3166-1-Alpha-2",
            "ISO3166-1-Alpha-3",
            "CLDR display name",
            "Region Name",
            "official_name_en",
            "UNTERM English Short",
        ]
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerow(
            dict(
                zip(
                    fields,
                    ["XY", "XYZ", "Example", "Test", "Example", "Example"],
                    strict=True,
                )
            )
        )
    stock = wiki(
        root / "stock.json",
        "<table><tr><th>Name</th><th>Rate</th><th>Vehicles</th>"
        "<th>People</th><th>Year</th></tr><tr><td>Example</td><td>10</td>"
        "<td>1234</td><td>12340</td><td>2020</td></tr></table>",
    )
    rules: Row = {
        "prior_aliases": {},
        "formats": [],
        "supplemental_formats": [],
        "templates": [],
        "state_tables": [],
    }

    def policy(name: str) -> Row | list[Row]:
        return cast(Row | list[Row], rules[name])

    monkeypatch.setattr(priors, "policy", policy)
    monkeypatch.setattr(formats, "policy", policy)
    monkeypatch.setattr(formats, "base_policy", lambda _: {})
    monkeypatch.setattr(evidence, "policy", policy)
    outputs = build.build(
        root,
        root / "plate_country",
        {"partitions": []},
        {"countries.csv": {"path": str(countries)}, "vehicle-stock.json": stock},
        2,
    )
    path = root / "plate_country/manifest.json"
    saved = read_json(path)
    assert len(saved["tables"]) == 3
    assert len(outputs) == 6
    assert all(not row["path"].startswith("/") for row in saved["tables"])
    moved = tmp_path / "moved"
    root.rename(moved)
    resolver = Resolver.load(moved, moved / "plate_country/manifest.json")
    assert resolver.resolve("VANITY", "XY")["level"] == "country"
    write_json(moved / "plate_country/coverage.json", {})
    with pytest.raises(ValueError, match="Corrupt resolver artifact"):
        Resolver.load(moved, moved / "plate_country/manifest.json")
