"""Explicit ledger records and independently retained unit recipes."""

from dataclasses import dataclass, field
from typing import cast

from .jsonio import JSON, Object
from .paths import validate_relative


@dataclass(frozen=True)
class Output:
    path: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        validate_relative(self.path)
        if self.size < 0 or len(self.sha256) != 64:
            raise ValueError(f"Invalid output record: {self.path}")
        if any(char not in "0123456789abcdef" for char in self.sha256):
            raise ValueError(f"Invalid SHA256: {self.path}")


@dataclass(frozen=True)
class Dependency:
    stage: str
    unit_id: str
    paths: tuple[str, ...] = ()
    control: bool = False

    def __post_init__(self) -> None:
        if self.control and self.paths:
            raise ValueError("A control dependency cannot consume output paths")

    @property
    def key(self) -> tuple[str, str]:
        return self.stage, self.unit_id


@dataclass(frozen=True)
class Recipe:
    stage: str
    unit_id: str
    parameters: Object = field(default_factory=dict)
    dependencies: tuple[Dependency, ...] = ()

    @property
    def key(self) -> tuple[str, str]:
        return self.stage, self.unit_id


@dataclass(frozen=True)
class Completion:
    stage: str
    unit_id: str
    inputs_hash: str
    outputs: tuple[Output, ...]
    metadata: Object
    completed_at: str

    @property
    def key(self) -> tuple[str, str]:
        return self.stage, self.unit_id


def outputs_from_json(value: JSON) -> tuple[Output, ...]:
    items = cast(list[Object], value)
    return tuple(
        Output(str(item["path"]), cast(int, item["size"]), str(item["sha256"]))
        for item in items
    )


def recipe_from_json(value: Object) -> Recipe:
    dependencies = cast(list[Object], value["dependencies"])
    return Recipe(
        str(value["stage"]),
        str(value["unit_id"]),
        cast(Object, value["parameters"]),
        tuple(
            Dependency(
                str(d["stage"]),
                str(d["unit_id"]),
                tuple(cast(list[str], d["paths"])),
                cast(bool, d.get("control", False)),
            )
            for d in dependencies
        ),
    )
