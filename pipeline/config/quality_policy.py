"""Schema for which countries' measured spatial failures stop the lookups manifest.

Only `lookups/manifest/current` reads this policy, as a unit parameter, so an
edit re-runs that unit and nothing upstream.
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import cast

from omegaconf import OmegaConf
from omegaconf.errors import OmegaConfBaseException

from .policies import Row, read

SCOPES = ("reviewed", "all")


@dataclass
class Gates:
    # `reviewed` blocks only on reviewed countries; `all` on every country.
    blocking_scope: str = "reviewed"


@dataclass
class Quality:
    gates: Gates = field(default_factory=Gates)


def load(path: Path) -> Row:
    try:
        tree = OmegaConf.merge(OmegaConf.structured(Quality), read(path))
        value = cast(Quality, OmegaConf.to_object(tree))
    except OmegaConfBaseException as error:
        raise ValueError(f"Invalid quality policy {path}: {error}") from error
    if value.gates.blocking_scope not in SCOPES:
        raise ValueError(
            f"Invalid quality policy {path}: blocking_scope must be one of {SCOPES}"
        )
    return asdict(value)
