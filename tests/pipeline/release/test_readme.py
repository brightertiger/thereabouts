"""The committed public README is reproducible without a built workspace."""

import json

from pipeline.config import load
from pipeline.release.metadata import licences
from pipeline.release.readme import render
from pipeline.release.tables import schema_description
from pipeline.runtime.fingerprints import REPOSITORY


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
        REPOSITORY / config.release.readme_template,
    ).encode()
    # The recorded readme_sha256 is the 2026-10-04 render, before the template
    # gained the dictionary, world wording and versioned _SUCCESS receipts.
    assert generated == (REPOSITORY / "docs/dataset/README.md").read_bytes()
