"""Structured source declarations, loaded independently from the version lock."""

import importlib
import importlib.util
import math
import re
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, cast

from omegaconf import OmegaConf
from omegaconf.errors import OmegaConfBaseException

from pipeline.errors import ConfigError


@dataclass
class Licence:
    id: str = ""
    url: str = ""
    attribution: str = ""


@dataclass
class SourceLimits:
    download_bytes: int = 0
    batch_rows: int = 512
    batch_bytes: int = 12_000_000
    row_group_bytes: int = 32_000_000
    row_overhead: int = 256
    scalar_bytes: int = 16
    part_bytes: int = 48_000_000
    row_bytes: int = 8_000_000
    parquet_bytes: int = 128_000_000
    chunk_bytes: int = 32_000_000
    read_bytes: int = 1_048_576
    # Jittered backoff doubles from backoff_seconds up to timeout_seconds; twenty
    # retries span about the fifteen minutes of patience a stalled file gets.
    retries: int = 20
    timeout_seconds: float = 60.0
    backoff_seconds: float = 1.0
    patience_seconds: float = 900.0


# Transfer budgets bound how bytes are fetched, never what normalization makes of
# them; patience_seconds is the download retry budget.
DOWNLOAD_LIMITS = (
    "download_bytes",
    "retries",
    "timeout_seconds",
    "backoff_seconds",
    "patience_seconds",
)


@dataclass
class SourceSettings:
    name: str = ""
    adapter: str = ""
    # A module whose propose(settings) resolves upstream into a SourcePin.
    proposer: str = ""
    options_schema: str = ""
    kind: str = ""
    enabled: bool = True
    upstream: dict[str, str] = field(default_factory=dict)
    licence: Licence = field(default_factory=Licence)
    limits: SourceLimits = field(default_factory=SourceLimits)
    options: dict[str, Any] = field(default_factory=dict)
    policies: dict[str, str] = field(default_factory=dict)


def normalize_settings(source: SourceSettings) -> dict[str, Any]:
    """Settings a normalizer reads; how upstream is found and fetched is excluded."""
    values = asdict(source)
    for name in ("upstream", "proposer", "enabled"):
        values.pop(name)
    values["limits"] = {
        name: value
        for name, value in values["limits"].items()
        if name not in DOWNLOAD_LIMITS
    }
    return values


def load_sources(directory: Path) -> dict[str, SourceSettings]:
    result: dict[str, SourceSettings] = {}
    for path in sorted(directory.glob("*.yaml")):
        try:
            tree = OmegaConf.merge(
                OmegaConf.structured(SourceSettings), OmegaConf.load(path)
            )
            source = cast(SourceSettings, OmegaConf.to_object(tree))
        except OmegaConfBaseException as error:
            raise ValueError(
                f"Invalid source configuration {path.name}: {error}"
            ) from error
        if source.name != path.stem or not re.fullmatch(
            r"[a-z][a-z0-9_]*", source.name
        ):
            raise ValueError(f"Source name must match its YAML filename: {path.name}")
        validate_source(source)
        result[source.name] = source
    return result


def validate_source(source: SourceSettings) -> None:
    if not re.fullmatch(r"pipeline\.sources\.[a-z][a-z0-9_.]*", source.adapter):
        raise ValueError(f"Invalid source adapter: {source.adapter}")
    if not re.fullmatch(r"pipeline\.sources\.[a-z][a-z0-9_.]*", source.proposer):
        raise ConfigError(f"Invalid source proposer: {source.proposer!r}")
    if not source.kind or not all(
        (source.licence.id, source.licence.url, source.licence.attribution)
    ):
        raise ValueError(f"Source {source.name} needs kind and licence attribution")
    for name, policy in source.policies.items():
        if not name or Path(policy).is_absolute() or ".." in Path(policy).parts:
            raise ValueError(
                f"{source.name}.policies.{name} must be repository-relative"
            )
    limits = source.limits
    for name in (
        "download_bytes",
        "batch_rows",
        "batch_bytes",
        "row_group_bytes",
        "row_overhead",
        "scalar_bytes",
        "part_bytes",
        "row_bytes",
        "parquet_bytes",
        "chunk_bytes",
        "read_bytes",
    ):
        value = getattr(limits, name)
        if value < 0 or (value == 0 and (name != "download_bytes" or source.enabled)):
            raise ValueError(
                f"{source.name}.limits.{name} must be positive for an enabled source"
            )
    if (
        limits.batch_bytes > limits.part_bytes
        or limits.part_bytes > limits.parquet_bytes
    ):
        raise ValueError(
            f"{source.name} requires batch_bytes <= part_bytes <= parquet_bytes"
        )
    if (
        limits.retries < 0
        or limits.backoff_seconds < 0
        or limits.timeout_seconds <= 0
        or limits.patience_seconds <= 0
    ):
        raise ValueError(f"Invalid download retry limits for {source.name}")
    if not all(
        math.isfinite(value)
        for value in (
            limits.backoff_seconds,
            limits.timeout_seconds,
            limits.patience_seconds,
        )
    ):
        raise ValueError(f"Nonfinite download retry limits for {source.name}")


def resolve_options(source: SourceSettings) -> None:
    module, _, name = source.options_schema.rpartition(".")
    if not module.startswith("pipeline.") or not name:
        raise ValueError(f"{source.name}.options_schema must name a pipeline dataclass")
    try:
        for path in (source.adapter, source.proposer):
            if importlib.util.find_spec(path) is None:
                raise ImportError(path)
        schema = getattr(importlib.import_module(module), name)
    except (ImportError, AttributeError) as error:
        raise ValueError(
            f"Cannot load {source.name} adapter, proposer or options schema: {error}"
        ) from error
    if not isinstance(schema, type) or not is_dataclass(schema):
        raise ValueError(f"{source.options_schema} must declare a dataclass")
    try:
        tree = OmegaConf.merge(OmegaConf.structured(schema), source.options)
        resolved = OmegaConf.to_object(tree)
    except OmegaConfBaseException as error:
        raise ValueError(f"Invalid {source.name} options: {error}") from error
    if not is_dataclass(resolved) or isinstance(resolved, type):
        raise ValueError(f"Invalid options schema for {source.name}")
    for item in fields(resolved):
        value = getattr(resolved, item.name)
        if isinstance(value, int) and value <= 0:
            raise ValueError(f"{source.name}.options.{item.name} must be positive")
        if isinstance(value, (str, dict, list)) and not value:
            raise ValueError(f"{source.name}.options.{item.name} must not be empty")
    source.options = asdict(resolved)
