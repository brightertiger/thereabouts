"""The committed public README is reproducible without a built workspace."""

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest
from h3.api import basic_int as h3

from pipeline.config import load
from pipeline.release.assemble import assemble
from pipeline.release.metadata import licences
from pipeline.release.readme import closure, render
from pipeline.release.source import external
from pipeline.release.tables import schema_description
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.resources import ResourceGuard

from .synthetic import snapshot

# A Paris cell the synthetic dataset stores at resolution 7.
PARIS = int("871fb4662ffffff", 16)


def test_committed_readme_matches_template_and_measured_subset() -> None:
    evidence = json.loads(
        (
            REPOSITORY
            / "tests/benchmarks/measurements"
            / "PIPELINE_RELEASE_MEASUREMENTS.json"
        ).read_text()
    )["readme_render"]
    config = load(profile=evidence["profile"], overrides=evidence["overrides"])
    generated = render(
        config,
        evidence["statistics"],
        schema_description(REPOSITORY / config.release.schema),
        licences(config, set(evidence["sources"])),
        evidence["policy"],
        {},
        REPOSITORY / config.release.readme_template,
    ).encode()
    # The recorded readme_sha256 is the 2026-10-04 render, before the template
    # gained the dictionary, world wording, versioned _SUCCESS receipts and the
    # quality gates and place closure, which that export did not record.
    assert generated == (REPOSITORY / "docs/dataset/README.md").read_bytes()
    # Tables added after that export are documented, without invented counts.
    text = generated.decode()
    for name in schema_description(REPOSITORY / config.release.schema):
        section = text.split(f"### `{name}`\n")[1].split("\n### ")[0]
        unmeasured = "Not measured in this export." in section
        assert unmeasured == (name not in evidence["statistics"])


def test_worked_examples_answer_from_an_assembled_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = load()
    config.release.enabled = True
    config.release.version = "2026.10"
    latitude, longitude = h3.cell_to_latlng(PARIS)
    config.release.example_latitude = latitude
    config.release.example_longitude = longitude
    output = tmp_path / "dataset/2026.10"
    source = external(snapshot(tmp_path / "input"), config.h3)
    assemble(source, output, config, ResourceGuard(tmp_path, config.resources), "x")
    examples = re.findall(
        r"```python\n(.*?)```", (output / "README.md").read_text(), re.S
    )
    assert len(examples) == 3
    monkeypatch.setenv("DATASET", str(output))
    for example in examples:
        if "import pandas" in example and importlib.util.find_spec("pandas") is None:
            continue  # pandas hands these filters to the PyArrow reader used above.
        assert "block" in example
        exec(compile(example, "README.md", "exec"), {})
    printed = capsys.readouterr().out
    assert "city:geonames:2988507" in printed and "Paris" in printed


def test_the_closure_paragraph_follows_the_manifest_record() -> None:
    assert "predates this record" in closure(None)
    record: dict[str, Any] = {"unknown_places": "fail", "aliased": [], "excluded": []}
    assert closure(record) == (
        "This export needed neither: `manifest.json.closure` lists no alias and "
        "no exclusion."
    )
    record["aliased"] = [
        {
            "table": "phone_prefixes",
            "column": "country_codes",
            "place": "country:TA",
            "to": "country:SH",
            "rows": 1234,
        }
    ]
    record["excluded"] = [
        {"table": "airports", "column": "state_id", "place": "state:x", "rows": 2}
    ]
    text = closure(record)
    assert text.startswith("This export rewrote 1,234 rows and dropped 2 rows:")
    assert text.splitlines()[-2:] == [
        "| `phone_prefixes` | `country_codes` | `country:TA` | `country:SH` | 1,234 |",
        "| `airports` | `state_id` | `state:x` | row dropped | 2 |",
    ]
