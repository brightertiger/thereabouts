"""Source adapters consume a frozen pin and return published local artifacts."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pipeline.config.schema import H3, Paths
from pipeline.config.sources import SourceSettings
from pipeline.errors import InputIntegrityError
from pipeline.pins.models import PinFile, SourcePin
from pipeline.runtime.paths import located, relative
from pipeline.runtime.resources import ResourceGuard


@dataclass(frozen=True)
class UnitInputs:
    """`ctx.unit.inputs_hash`, kept until the plate adapters read `ctx.inputs_hash`."""

    inputs_hash: str


@dataclass(frozen=True)
class SourceContext:
    """What an adapter may use; never the ledger, the verifier or other config."""

    settings: SourceSettings
    pin: SourcePin
    # The unit's inputs hash names its output and work directories.
    inputs_hash: str
    root: Path
    paths: Paths
    grid: H3
    guard: ResourceGuard
    storage: Mapping[str, str]
    # Measurements such as timings go to the run log, never into outputs.
    log: Callable[[str], None]

    @property
    def unit(self) -> UnitInputs:
        return UnitInputs(self.inputs_hash)

    # Each access re-checks that the directory stays inside the workspace.
    @property
    def raw(self) -> Path:
        return located(
            self.root, (Path(self.paths.raw) / self.settings.name).as_posix()
        )

    @property
    def normalized(self) -> Path:
        return located(
            self.root, (Path(self.paths.normalized) / self.settings.name).as_posix()
        )

    @property
    def work(self) -> Path:
        return located(
            self.root, (Path(self.paths.work) / self.settings.name).as_posix()
        )

    def named(self, key: str) -> PinFile:
        matches = [
            pin for pin in self.pin.files if pin.metadata.get("key", pin.name) == key
        ]
        if len(matches) != 1:
            raise InputIntegrityError(
                f"Expected one pinned input {self.settings.name}/{key}"
            )
        return matches[0]

    def input(self, name: str) -> Path:
        """Pinned names resolve to content-addressed objects; others to raw files.

        Objects use the mirror's `sha256/<checksum>` address, so a new pin with
        the same logical name and new bytes is a new object.
        """
        for item in self.pin.files:
            if item.name == name:
                return located(self.raw, f"sha256/{item.sha256}")
        return located(self.raw, name)

    def ensure(self, path: Path) -> Path:
        relative(self.root, path)
        return path

    def relative(self, path: Path) -> str:
        return relative(self.root, path)


class Source(Protocol):
    def normalize(self, ctx: SourceContext) -> list[Path]:
        """Regenerate indexes, normalize bounded batches and publish a manifest."""
        ...


class Proposer(Protocol):
    """The module a source's `proposer:` names."""

    def propose(self, settings: SourceSettings) -> SourcePin:
        """Resolve upstream metadata and hashes without writing the lock."""
        ...
