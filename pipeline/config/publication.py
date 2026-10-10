"""Publication target settings, kept outside the dataset and packs identity.

`release.py` is hashed by the dataset and packs stages, so the publication target
extends it here and reaches the schema by subclassing. A token is never
configuration: the GitHub publisher reads it from the environment.
"""

import ipaddress
import math
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .release import PublishSettings, ReleaseSettings

TARGETS = ("fsspec", "github")
# GitHub refuses release assets of 2 GiB or more and releases over 1,000 assets.
MAX_ASSET_BYTES = 2**31 - 1
MAX_ASSETS = 1000
LOOPBACK_NAMES = ("localhost",)


@dataclass
class GithubSettings:
    repository: str = "brightertiger/thereabouts"
    tag_prefix: str = "v"
    api_url: str = "https://api.github.com"
    upload_url: str = "https://uploads.github.com"
    web_url: str = "https://github.com"
    max_assets: int = MAX_ASSETS
    max_asset_bytes: int = MAX_ASSET_BYTES
    timeout_seconds: float = 300.0


@dataclass
class PublicationSettings(PublishSettings):
    # fsspec writes storage.s3_release; github drafts, then publishes, a release.
    target: str = "fsspec"
    github: GithubSettings = field(default_factory=GithubSettings)


@dataclass
class Release(ReleaseSettings):
    publish: PublicationSettings = field(default_factory=PublicationSettings)


def loopback(host: str) -> bool:
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def service_url(value: str, name: str = "GitHub service URL") -> str:
    """An HTTPS base URL without credentials; plain HTTP only on loopback (tests)."""
    parts = urlsplit(value)
    if (
        parts.scheme not in {"https", "http"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or (parts.scheme == "http" and not loopback(parts.hostname))
    ):
        raise ValueError(
            f"{name} must be an HTTPS URL without credentials "
            "(plain HTTP only on loopback)"
        )
    return value.rstrip("/")


def validate(settings: PublicationSettings) -> None:
    if settings.target not in TARGETS:
        raise ValueError("release.publish.target must be fsspec or github")
    github = settings.github
    owner, _, name = github.repository.partition("/")
    if not (
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", owner)
        and re.fullmatch(r"[A-Za-z0-9._-]+", name)
        and name not in {".", ".."}
    ):
        raise ValueError("release.publish.github.repository must be owner/name")
    if not re.fullmatch(r"[A-Za-z0-9._-]*", github.tag_prefix):
        raise ValueError("release.publish.github.tag_prefix must be a plain tag prefix")
    for key in ("api_url", "upload_url", "web_url"):
        service_url(getattr(github, key), f"release.publish.github.{key}")
    if not 1 <= github.max_assets <= MAX_ASSETS:
        raise ValueError(f"A GitHub release holds at most {MAX_ASSETS} assets")
    if not 1 <= github.max_asset_bytes <= MAX_ASSET_BYTES:
        raise ValueError("GitHub release assets must be under 2 GiB")
    if not math.isfinite(github.timeout_seconds) or github.timeout_seconds <= 0:
        raise ValueError(
            "release.publish.github.timeout_seconds must be a positive timeout"
        )
