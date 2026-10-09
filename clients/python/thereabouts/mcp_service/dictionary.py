"""Serve the data dictionary from the installed core pack, else the packaged copy."""

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from ..store_files import parse, relative_file

JSON_NOTICE = "data_dictionary.json"
MARKDOWN_NOTICE = "DATA_DICTIONARY.md"
FORMAT_PREFIX = "thereabouts-data-dictionary-"


@dataclass(frozen=True, slots=True)
class Dictionary:
    """One consistent JSON and Markdown pair, and where it came from."""

    document: dict[str, Any]
    json_text: str
    markdown_text: str
    source: str


def notices(pack: Path) -> dict[str, str]:
    """Notice artifacts of a pack by name; each file starts with its name."""
    manifest = parse((pack / "manifest.json").read_bytes())
    found: dict[str, str] = {}
    for record in manifest.get("files", []):
        if record.get("kind") != "notice":
            continue
        name, _, text = relative_file(pack, record["path"]).read_text().partition("\n")
        found[name] = text.removeprefix("\n")
    return found


def parsed(text: str, source: str, markdown: str) -> Dictionary | None:
    try:
        document = json.loads(text)
    except ValueError:
        return None
    if not str(document.get("format", "")).startswith(FORMAT_PREFIX):
        return None
    return Dictionary(document, text, markdown, source)


def from_pack(pack: Path) -> Dictionary | None:
    """The pack's own pair, or None when it ships none or an unreadable one."""
    try:
        found = notices(pack)
    except (OSError, ValueError):
        return None
    if JSON_NOTICE not in found or MARKDOWN_NOTICE not in found:
        return None
    return parsed(found[JSON_NOTICE], "pack", found[MARKDOWN_NOTICE])


def packaged() -> Dictionary:
    """The copy released with this client; it describes the client's own build."""
    root = resources.files("thereabouts") / "dictionary"
    text = (root / JSON_NOTICE).read_text(encoding="utf-8")
    result = parsed(text, "packaged", (root / MARKDOWN_NOTICE).read_text("utf-8"))
    if result is None:
        raise ValueError("The packaged data dictionary is unreadable")
    return result


def load(pack: Path | None) -> Dictionary:
    """Prefer the installed data's dictionary: it matches the data being served."""
    return (from_pack(pack) if pack is not None else None) or packaged()
