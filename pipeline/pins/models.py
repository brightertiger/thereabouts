"""Immutable upstream records and the evidence needed to reproduce a source."""

from dataclasses import dataclass, field
from typing import Any

from pipeline.runtime.paths import validate_relative


@dataclass
class PinFile:
    name: str = ""
    url: str = ""
    size: int = 0
    sha256: str = ""
    etag: str | None = None
    last_modified: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not isinstance(self.name, str) or not isinstance(self.url, str):
            raise ValueError("Pinned file names and URLs must be strings")
        if (
            type(self.size) is not int
            or not isinstance(self.sha256, str)
            or not isinstance(self.metadata, dict)
            or any(
                value is not None and not isinstance(value, str)
                for value in (self.etag, self.last_modified)
            )
        ):
            raise ValueError(f"Invalid pinned file types: {self.name}")
        validate_relative(self.name)
        if (
            self.size < 0
            or len(self.sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.sha256)
        ):
            raise ValueError(f"Invalid size or SHA256 for pinned file {self.name}")
        if not self.url or "://" not in self.url:
            raise ValueError(f"Pinned file needs an upstream URL: {self.name}")


@dataclass
class SourcePin:
    release: str = ""
    pinned_at: str = ""
    available: bool = True
    files: list[PinFile] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if (
            type(self.available) is not bool
            or not isinstance(self.release, str)
            or not isinstance(self.pinned_at, str)
            or not isinstance(self.metadata, dict)
        ):
            raise ValueError("Invalid source pin types")
        if not self.available:
            if self.files:
                raise ValueError("Unavailable source must not claim pinned payloads")
            return
        if not self.release or not self.pinned_at or not self.files:
            raise ValueError("A source pin needs release, pin date and files")
        names = set()
        for item in self.files:
            item.validate()
            if item.name in names:
                raise ValueError(f"Duplicate pinned file: {item.name}")
            names.add(item.name)
