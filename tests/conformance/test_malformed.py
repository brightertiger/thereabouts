import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from thereabouts.packs.errors import CorruptPackError, UnsupportedPackError
from thereabouts.packs.verify import verify

from .generate import FIXTURES

CASES = json.loads((FIXTURES / "malformed.json").read_text())["cases"]


def mutate(target: Path, case: dict[str, Any]) -> None:
    manifest = target / "manifest.json"
    value = json.loads(manifest.read_bytes())
    if "manifest" in case:
        parent = value
        for part in case["manifest"][:-1]:
            parent = parent[part]
        parent[case["manifest"][-1]] = case["value"]
    elif "kind" in case:
        record = next(r for r in value["files"] if r["kind"] == case["kind"])
        path = target / record["path"]
        content = bytearray(path.read_bytes())
        patch = bytes.fromhex(case["hex"])
        content[case["offset"] : case["offset"] + len(patch)] = patch
        path.write_bytes(content)
        if case["rehash"]:
            record["sha256"] = hashlib.sha256(content).hexdigest()
    serialized = json.dumps(value, ensure_ascii=False)
    if case.get("duplicate"):
        serialized = '{"schema":"duplicate",' + serialized[1:]
    manifest.write_text(serialized)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_shared_malformed(case: dict[str, Any], tmp_path: Path) -> None:
    target = tmp_path / "pack"
    shutil.copytree(FIXTURES / case["pack"], target)
    mutate(target, case)
    with pytest.raises((CorruptPackError, UnsupportedPackError)) as caught:
        verify(target)
    assert type(caught.value).__name__ == case["error"]
