"""Versioned acquisition pins and evidence-backed parsing policies."""

from pathlib import Path
from typing import Any

from .artifacts import read_json
from .io import fingerprint
from .plates_schemas import PLATE_KINDS
from .schemas import SCHEMA_HASHES

DATA = Path(__file__).with_name("plates_data")


def policy(name: str) -> dict[str, Any]:
    return read_json(DATA / f"{name}.json")


def configuration() -> dict[str, Any]:
    return dict(
        builder="plates-1",
        policy={
            name: fingerprint(policy(name))
            for name in ("sources", "rules", "survey", "formats")
        },
        schemas={kind: SCHEMA_HASHES[kind] for kind in PLATE_KINDS},
    )
