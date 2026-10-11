"""Read geographic records and evaluation fixtures without workspace mutation."""

from pathlib import Path
from typing import Any

from pipeline.runtime.jsonio import read_object

EVALUATION = Path(__file__).parents[2] / "eval"


def read_json(path: Path) -> dict[str, Any]:
    return read_object(path)
