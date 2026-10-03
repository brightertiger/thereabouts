"""Source adapters consume a frozen pin and return published local artifacts."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pipeline.config.sources import SourceSettings
from pipeline.pins.models import PinFile, SourcePin
from pipeline.runtime.paths import located, relative
from pipeline.stages.contract import Context, Unit


@dataclass(frozen=True)
class SourceContext:
    runtime: Context
    settings: SourceSettings
    pin: SourcePin
    unit: Unit

    @property
    def raw(self) -> Path:
        return located(
            self.runtime.root,
            (Path(self.runtime.config.paths.raw) / self.settings.name).as_posix(),
        )

    @property
    def normalized(self) -> Path:
        return located(
            self.runtime.root,
            (
                Path(self.runtime.config.paths.normalized) / self.settings.name
            ).as_posix(),
        )

    @property
    def work(self) -> Path:
        return located(
            self.runtime.root,
            (Path(self.runtime.config.paths.work) / self.settings.name).as_posix(),
        )

    def named(self, key: str) -> PinFile:
        matches = [
            pin for pin in self.pin.files if pin.metadata.get("key", pin.name) == key
        ]
        if len(matches) != 1:
            raise ValueError(f"Expected one pinned input {self.settings.name}/{key}")
        return matches[0]

    def input(self, name: str) -> Path:
        return located(self.raw, name)

    def ensure(self, path: Path) -> Path:
        relative(self.runtime.root, path)
        return path

    def relative(self, path: Path) -> str:
        return relative(self.runtime.root, path)


class Source(Protocol):
    def normalize(self, ctx: SourceContext) -> list[Path]:
        """Regenerate indexes, normalize bounded batches and publish a manifest."""
        ...
