"""Read the frozen Wikipedia parse response and its revision identity."""

import json
from pathlib import Path


def wiki_document(path: Path) -> tuple[str, int]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if "error" in value:
        raise ValueError(f"Wikipedia: {value['error']}")
    parsed = value["parse"]
    return str(parsed["text"]["*"]), int(parsed["revid"])
