"""Explicit geographic inputs; stage discovery owns ledger and policy identity."""

from dataclasses import dataclass, field
from pathlib import Path

from pipeline.config.engines import EngineLimits
from pipeline.engines.reconcile.common import Row


@dataclass
class Inputs:
    countries: dict[str, Row]
    land: Row
    policy: Row
    expected: set[str] | None = None
    limits: EngineLimits = field(default_factory=EngineLimits)

    @property
    def paths(self) -> dict[str, Path]:
        # Absolute paths exist only in this in-memory engine input view.
        return {cc: Path(record["path"]) for cc, record in self.countries.items()}
