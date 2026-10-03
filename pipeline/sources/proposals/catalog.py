"""Small declarative proposal catalogs, separate from the immutable version lock."""

from dataclasses import dataclass, field
from typing import Any, cast

from omegaconf import OmegaConf
from omegaconf.errors import OmegaConfBaseException

from pipeline.config.sources import SourceSettings
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.paths import located


@dataclass
class File:
    name: str = ""
    url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Selector:
    name: str = ""
    kind: str = ""
    url: str = ""


@dataclass
class Tree:
    url: str = ""
    raw: str = ""
    prefixes: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Catalog:
    release: str = ""
    selectors: list[Selector] = field(default_factory=list)
    files: list[File] = field(default_factory=list)
    trees: list[Tree] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)


def load(settings: SourceSettings) -> Catalog:
    name = settings.upstream.get("proposal", "")
    if not name:
        raise ValueError(f"No proposal catalog configured for {settings.name}")
    path = located(REPOSITORY, name)
    try:
        tree = OmegaConf.merge(OmegaConf.structured(Catalog), OmegaConf.load(path))
        result = cast(Catalog, OmegaConf.to_object(tree))
    except OmegaConfBaseException as error:
        raise ValueError(f"Invalid proposal catalog {name}: {error}") from error
    for item in result.selectors:
        if not item.name or item.kind not in {
            "github_commit",
            "github_release",
            "text",
        }:
            raise ValueError(f"Invalid release selector in {name}: {item.name}")
    return result
