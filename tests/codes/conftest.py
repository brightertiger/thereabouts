"""Immutable client fixtures; pipeline does not generate binary formats."""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def code_packs() -> dict[str, Path]:
    root = Path(__file__).parents[1] / "fixtures/codes"
    return {family: root / family for family in ("reverse", "postal", "airports")}
