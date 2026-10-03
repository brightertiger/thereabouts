"""Verify content on each command, caching only unchanged files in that command."""

import hashlib
from pathlib import Path

from .jsonio import sha256_file
from .paths import located
from .records import Completion, Output


class Verifier:
    def __init__(self, root: Path, overlay: dict[str, bytes] | None = None) -> None:
        self.root = root
        self.overlay = overlay or {}
        self.cache: dict[tuple[str, int, int, int], str] = {}
        self.bytes_hashed = 0

    def problem(self, record: Output) -> str | None:
        if record.path in self.overlay:
            data = self.overlay[record.path]
            size, digest = len(data), hashlib.sha256(data).hexdigest()
        else:
            path = located(self.root, record.path)
            try:
                stat = path.stat()
            except FileNotFoundError:
                return f"output missing: {record.path}"
            size = stat.st_size
            if size != record.size:
                return f"output size changed: {record.path}"
            key = (record.path, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            if key not in self.cache:
                self.cache[key] = sha256_file(path)
                self.bytes_hashed += size
            digest = self.cache[key]
        if size != record.size or digest != record.sha256:
            return f"output corrupt: {record.path}"
        return None

    def completion_problem(self, record: Completion) -> str | None:
        absent = record.metadata.get("absent_paths", [])
        for output in record.outputs:
            if (
                isinstance(absent, list)
                and output.path in absent
                and not located(self.root, output.path).exists()
            ):
                continue
            if problem := self.problem(output):
                return problem
        return None
