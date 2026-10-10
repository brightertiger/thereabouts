"""Human approvals remain bound to the exact policy values they reviewed."""

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from omegaconf import OmegaConf
from omegaconf.errors import OmegaConfBaseException

from pipeline.runtime.jsonio import digest

from .policies import Row, read

# A source and its record (`osm:r134579`); cells are H3 index strings.
ORIGIN = re.compile(r"[A-Za-z][\w-]*:\S+")
CELL = re.compile(r"[0-9a-f]{15}")


@dataclass
class BoundaryException:
    """One examined loss, named by evidence that survives a rebuild.

    `boundary_origins` are the upstream records of the lost boundary's source
    areas, never their build-local sequence IDs. `cells` maps each lost cell the
    report lists to the city that now answers it.
    """

    country: str = ""
    city_id: str = ""
    lost_cells: int = 0
    lost_to: dict[str, int] = field(default_factory=dict)
    boundary_origins: list[str] = field(default_factory=list)
    cells: dict[str, str] = field(default_factory=dict)
    reason: str = ""
    reference: str = ""


@dataclass
class Review:
    accepted: bool = False
    review: str = ""
    minimum_dev_correct: int = 0
    policy_fingerprint: str = ""
    boundary_exceptions: list[BoundaryException] = field(default_factory=list)
    unresolved_losses: list[dict[str, Any]] = field(default_factory=list)
    provenance: dict[str, str] = field(default_factory=dict)


def load(path: Path, policy: Row) -> Review:
    try:
        tree = OmegaConf.merge(OmegaConf.structured(Review), read(path))
        value = cast(Review, OmegaConf.to_object(tree))
    except OmegaConfBaseException as error:
        raise ValueError(f"Invalid review {path}: {error}") from error
    if not re.fullmatch(
        r"[a-f0-9]{64}", value.policy_fingerprint
    ) or value.policy_fingerprint != digest(policy):
        raise ValueError(f"Policy changed; obtain an updated review in {path}")
    if not value.accepted or not value.review or value.unresolved_losses:
        raise ValueError(f"Missing or unresolved approval in {path}")
    if value.minimum_dev_correct < 0:
        raise ValueError(f"Invalid development minimum in {path}")
    for exception in value.boundary_exceptions:
        if any(origin.isdigit() for origin in exception.boundary_origins):
            raise ValueError(f"Boundary exception names sequence IDs in {path}")
        if not complete(exception):
            raise ValueError(f"Incomplete boundary exception in {path}")
    return value


def complete(exception: BoundaryException) -> bool:
    origins, cells = exception.boundary_origins, exception.cells
    receivers = Counter(cells.values())
    return bool(
        exception.reason
        and exception.reference
        and exception.lost_cells > 0
        and sum(exception.lost_to.values()) == exception.lost_cells
        and origins
        and len(set(origins)) == len(origins)
        and all(ORIGIN.fullmatch(origin) for origin in origins)
        and 0 < len(cells) <= exception.lost_cells
        and all(CELL.fullmatch(cell) for cell in cells)
        and all(n <= exception.lost_to.get(city, 0) for city, n in receivers.items())
    )
