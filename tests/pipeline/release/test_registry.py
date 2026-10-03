"""Registry drafts remain reviewable and retain pending owner decisions."""

import yaml

from pipeline.config.release import ReleaseSettings
from pipeline.release.registry import entry


def test_registry_contains_required_fields_and_owner_placeholders() -> None:
    result = yaml.safe_load(entry(ReleaseSettings(), "s3://owner-bucket/releases"))
    assert result["Resources"][0]["ARN"] == "arn:aws:s3:::owner-bucket/releases"
    assert result["License"].endswith("/odbl/1-0/")
    assert "OWNER DECISION" in result["Contact"]
    assert result["UpdateFrequency"] == "Monthly"
    assert result["DataAtWork"]["Tutorials"]
