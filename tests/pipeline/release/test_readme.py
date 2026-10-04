"""The committed public README is reproducible without a built workspace."""

import hashlib
import json

from pipeline.config import load
from pipeline.release.metadata import licences
from pipeline.release.readme import render
from pipeline.release.tables import schema_description
from pipeline.runtime.fingerprints import REPOSITORY


def test_committed_readme_matches_template_and_measured_subset() -> None:
    evidence = json.loads(
        (
            REPOSITORY / "docs/measurements" / "PIPELINE_RELEASE_MEASUREMENTS.json"
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
    assert generated == (REPOSITORY / "docs/DATASET_README.md").read_bytes()
    assert hashlib.sha256(generated).hexdigest() == evidence["readme_sha256"]
