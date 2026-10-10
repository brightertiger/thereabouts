"""Registry drafts remain reviewable and retain pending owner decisions."""

import yaml

from pipeline.config import load
from pipeline.config.release import ReleaseSettings
from pipeline.release.registry import entry
from pipeline.runtime.fingerprints import REPOSITORY


def test_registry_contains_required_fields_and_owner_placeholders() -> None:
    result = yaml.safe_load(entry(ReleaseSettings(), "s3://owner-bucket/releases"))
    assert result["Resources"][0]["ARN"] == "arn:aws:s3:::owner-bucket/releases"
    assert result["License"].endswith("/odbl/1-0/")
    assert "OWNER DECISION" in result["Contact"]
    assert result["UpdateFrequency"] == "Monthly"
    assert result["DataAtWork"]["Tutorials"]


def test_registry_names_categories_and_a_managing_organisation() -> None:
    settings = load().release
    result = yaml.safe_load(entry(settings, "s3://owner-bucket"))
    # Required by the AWS Open Data Registry schema.
    assert result["ADXCategories"] == ["Geospatial Data"]
    # The registry asks for an organisation, not an individual's contact.
    assert result["ManagedBy"] == settings.managed_by != result["Contact"]
    assert result["ManagedBy"].startswith("[Thereabouts project](https://")


def test_committed_registry_draft_is_current() -> None:
    settings = load().release
    committed = (REPOSITORY / "docs/pipeline/release-registry.yaml").read_text()
    assert committed == entry(settings, "s3://OWNER-DECISION-BUCKET")
