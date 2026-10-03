"""Load typed policies while preserving their exact JSON semantic fingerprints."""

import re
from pathlib import Path
from typing import Any, cast

import yaml
from omegaconf import OmegaConf
from omegaconf.errors import OmegaConfBaseException

from pipeline.runtime.jsonio import digest

from .city_policy import Cities
from .reconcile_policy import Reconcile

DIRECTORY = Path(__file__).parents[2] / "config/policies"
Row = dict[str, Any]


def read(path: Path) -> Row:
    value = yaml.load(path.read_bytes(), Loader=yaml.CSafeLoader)
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        raise ValueError(f"Policy must be a mapping with string keys: {path}")
    return cast(Row, value)


def validate(value: Row, schema: type[Cities] | type[Reconcile], path: Path) -> Row:
    try:
        OmegaConf.merge(OmegaConf.structured(schema), value)
    except OmegaConfBaseException as error:
        raise ValueError(f"Invalid policy {path}: {error}") from error
    # Do not inject optional defaults or coerce 1 to 1.0: retained policy hashes
    # bind the exact JSON value, including absent optional fields and numeric types.
    digest(value)
    return value


def reconcile(path: Path = DIRECTORY / "reconcile.yaml") -> Row:
    return validate(read(path), Reconcile, path)


def cities(directory: Path = DIRECTORY / "cities", country: str | None = None) -> Row:
    if country is not None and not re.fullmatch(r"[A-Z]{2}", country):
        raise ValueError(f"Invalid policy country: {country}")
    common = read(directory / "common.yaml")
    paths = (
        [directory / f"{country}.yaml"]
        if country is not None
        else sorted(p for p in directory.glob("*.yaml") if p.stem != "common")
    )
    countries = {}
    for path in paths:
        if not re.fullmatch(r"[A-Z]{2}", path.stem):
            raise ValueError(f"Invalid policy country filename: {path.name}")
        if path.is_file():
            countries[path.stem] = read(path)
    value = validate({**common, "countries": countries}, Cities, directory)
    for cc, rules in countries.items():
        parts = {**rules.get("parts", {}), **rules.get("identity_aliases", {})}
        for source in parts:
            seen = {source}
            target = parts[source]
            while target in parts:
                if target in seen:
                    raise ValueError(f"Cyclic city policy in {cc}")
                seen.add(target)
                target = parts[target]
    return value
