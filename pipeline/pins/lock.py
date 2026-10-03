"""Load exact source pins without probing, refreshing or contacting upstream."""

import re
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

import yaml

from pipeline.runtime.jsonio import atomic_output, encode

from .models import PinFile, SourcePin


def _object(value: Any, allowed: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"Expected an object for {label}")
    extra = set(value) - allowed
    if extra:
        raise ValueError(f"Unknown fields in {label}: {sorted(extra)}")
    return value


def read_lock(path: Path) -> dict[str, SourcePin]:
    # Pin inventories are large evidence documents, not interpolated configuration.
    # The C safe loader avoids a second graph of OmegaConf nodes for every receipt.
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.CSafeLoader)
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid pin YAML: {error}") from error
    if not isinstance(data, dict):
        raise ValueError("pins.lock must be an object keyed by source name")
    result = {}
    for name, raw in data.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise ValueError("Pin source names must be strings")
        spec = _object(raw, {field.name for field in fields(SourcePin)}, name)
        payloads = spec.get("files", [])
        if not isinstance(payloads, list):
            raise ValueError(f"{name}.files must be a list")
        files = [
            PinFile(**_object(item, {field.name for field in fields(PinFile)}, name))
            for item in payloads
        ]
        pin = SourcePin(**{**spec, "files": files})
        pin.validate()
        encode(asdict(pin))  # Reject non-JSON metadata, dates and nonfinite floats.
        result[name] = pin
    return result


def write_lock(path: Path, sources: dict[str, SourcePin]) -> None:
    for pin in sources.values():
        pin.validate()
    payload = yaml.safe_dump(
        {name: asdict(sources[name]) for name in sorted(sources)},
        sort_keys=False,
        allow_unicode=True,
    )
    with atomic_output(path) as temporary:
        temporary.write_text(payload, encoding="utf-8")
