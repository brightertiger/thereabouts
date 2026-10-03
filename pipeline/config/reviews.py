"""Human approvals remain bound to the exact policy values they reviewed."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from omegaconf import OmegaConf
from omegaconf.errors import OmegaConfBaseException

from pipeline.runtime.jsonio import digest

from .policies import Row, read


@dataclass
class BoundaryException:
    country: str = ""
    city_id: str = ""
    lost_cells: int = 0
    lost_to: dict[str, int] = field(default_factory=dict)
    reason: str = ""
    reference: str = ""
    boundary_references: list[str] | None = None


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
        if (
            not exception.reason
            or not exception.reference
            or exception.lost_cells <= 0
            or sum(exception.lost_to.values()) != exception.lost_cells
        ):
            raise ValueError(f"Incomplete boundary exception in {path}")
    return value
