"""Replace changed JSON scalars while preserving all original layout bytes."""

import json
import re
from dataclasses import dataclass, field

from pipeline.runtime.jsonio import JSON

SPACE = re.compile(r"\s*")


@dataclass
class Patcher:
    text: str
    cursor: int = 0
    copied: int = 0
    chunks: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(
        default_factory=lambda: {
            "paths_rewritten": 0,
            "hashes_cascaded": 0,
            "sizes_cascaded": 0,
            "tables_repointed": 0,
        }
    )

    def whitespace(self) -> None:
        match = SPACE.match(self.text, self.cursor)
        if match is None:
            raise ValueError("Invalid JSON whitespace")
        self.cursor = match.end()

    def punctuation(self, value: str) -> None:
        self.whitespace()
        if self.text[self.cursor : self.cursor + 1] != value:
            raise ValueError(f"Expected JSON punctuation {value}")
        self.cursor += 1

    def scalar(self, old: JSON, new: JSON, path: tuple[str, ...]) -> None:
        self.whitespace()
        start = self.cursor
        parsed, self.cursor = json.JSONDecoder().raw_decode(self.text, start)
        if parsed != old:
            raise ValueError("JSON token disagrees with the original value")
        if old == new and type(old) is type(new):
            return
        token = self.text[start : self.cursor]
        replacement = json.dumps(new, ensure_ascii="\\u" in token, allow_nan=False)
        if "\\/" in token:
            replacement = replacement.replace("/", "\\/")
        self.chunks.extend((self.text[self.copied : start], replacement))
        self.copied = self.cursor
        key = path[-1] if path else ""
        if key in {"sha256", "manifest_sha256"}:
            self.counts["hashes_cascaded"] += 1
        elif key == "size":
            self.counts["sizes_cascaded"] += 1
        elif isinstance(old, str) and isinstance(new, str):
            self.counts["paths_rewritten"] += 1
            if path[:1] == ("tables",) and key == "path":
                self.counts["tables_repointed"] += 1

    def value(self, old: JSON, new: JSON, path: tuple[str, ...] = ()) -> None:
        if isinstance(old, dict):
            if not isinstance(new, dict) or len(old) != len(new):
                raise ValueError("Metadata repair cannot reshape an object")
            self.punctuation("{")
            for index, ((old_key, old_value), (new_key, new_value)) in enumerate(
                zip(old.items(), new.items(), strict=True)
            ):
                if index:
                    self.punctuation(",")
                self.scalar(old_key, new_key, (*path, "key"))
                self.punctuation(":")
                self.value(old_value, new_value, (*path, old_key))
            self.punctuation("}")
        elif isinstance(old, list):
            if not isinstance(new, list) or len(old) != len(new):
                raise ValueError("Metadata repair cannot reshape an array")
            self.punctuation("[")
            for index, (left, right) in enumerate(zip(old, new, strict=True)):
                if index:
                    self.punctuation(",")
                self.value(left, right, (*path, str(index)))
            self.punctuation("]")
        else:
            if isinstance(new, (list, dict)):
                raise ValueError(
                    "Metadata repair cannot replace a scalar with a container"
                )
            self.scalar(old, new, path)


def patch(original: bytes, old: JSON, new: JSON) -> tuple[bytes, dict[str, int]]:
    value = Patcher(original.decode("utf-8"))
    value.value(old, new)
    value.whitespace()
    if value.cursor != len(value.text):
        raise ValueError("Unexpected trailing JSON content")
    value.chunks.append(value.text[value.copied :])
    result = "".join(value.chunks).encode("utf-8")
    if json.loads(result) != new:
        raise ValueError("Patched JSON disagrees with the proposed metadata")
    return result, value.counts
