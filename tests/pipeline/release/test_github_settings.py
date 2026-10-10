"""GitHub publication settings: selected by config, token from the environment only."""

import pytest

from pipeline.config import load
from pipeline.runtime.fingerprints import closures


def test_defaults_keep_fsspec_and_name_the_owner_repository() -> None:
    publish = load().release.publish
    assert publish.target == "fsspec"
    github = publish.github
    assert (github.repository, github.tag_prefix) == ("brightertiger/thereabouts", "v")
    assert (github.api_url, github.upload_url, github.web_url) == (
        "https://api.github.com",
        "https://uploads.github.com",
        "https://github.com",
    )
    assert (github.max_assets, github.max_asset_bytes) == (1000, 2**31 - 1)


def test_the_target_and_repository_come_from_overrides() -> None:
    publish = load(
        overrides=[
            "release.publish.target=github",
            "release.publish.github.repository=someone/fork",
            "release.publish.github.api_url=http://127.0.0.1:9",
        ]
    ).release.publish
    assert publish.target == "github"
    assert publish.github.repository == "someone/fork"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ("release.publish.target=s3", "fsspec or github"),
        ("release.publish.github.repository=thereabouts", "owner/name"),
        ("release.publish.github.repository=a/b/c", "owner/name"),
        ("release.publish.github.tag_prefix=v/", "tag prefix"),
        ("release.publish.github.api_url=http://api.example.com", "HTTPS"),
        ("release.publish.github.web_url=https://user@github.com", "HTTPS"),
        ("release.publish.github.upload_url=https://up.example.com/?x=1", "HTTPS"),
        ("release.publish.github.max_assets=1001", "1000 assets"),
        ("release.publish.github.max_asset_bytes=2147483648", "under 2 GiB"),
        ("release.publish.github.max_asset_bytes=0", "under 2 GiB"),
        ("release.publish.github.timeout_seconds=0", "timeout"),
    ],
)
def test_invalid_settings_are_refused(override: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load(overrides=[override])


def test_a_token_is_never_configuration() -> None:
    with pytest.raises(ValueError, match="token"):
        load(overrides=["release.publish.github.token=secret"])


def test_publication_code_stays_outside_dataset_and_packs_identity() -> None:
    hashed = closures(load())
    for stage in ("dataset", "packs"):
        assert not any(
            name.endswith(("publication.py", "github.py", "github_api.py", "zips.py"))
            or name == "pipeline/release/publish.py"
            for name in hashed[stage]
        ), stage
