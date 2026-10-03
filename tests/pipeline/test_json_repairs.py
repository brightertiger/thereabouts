"""Metadata repairs change scalar tokens, never incidental JSON formatting."""

import json
from typing import cast

import pytest

from pipeline.migration.json_patch import patch
from pipeline.runtime.jsonio import JSON


@pytest.mark.parametrize(
    "original",
    [
        b'{"z": 9, "path": "/old/data/file", "a": "\\u00E9"}',
        b'{\r\n\t"z" : 9,\r\n\t"path" : "/old/data/file", "a":"\\u00E9"\r\n}\r\n',
        b'{\n  "z": 9,\n  "path": "/old/data/file",\n  "a": "\\u00E9"\n}\n',
    ],
)
def test_paths_keep_whitespace_key_order_and_unchanged_escapes(original: bytes) -> None:
    old = json.loads(original)
    new = {**old, "path": "file"}
    rendered, counts = patch(original, old, new)
    assert rendered == original.replace(b'"/old/data/file"', b'"file"')
    assert counts["paths_rewritten"] == 1


def test_hash_cascades_and_table_repointing_are_counted_separately() -> None:
    original = (
        b'{"tables": [{"path":"golden/file","size":1,"sha256":"old"}], "same":"old"}\n'
    )
    old = json.loads(original)
    new: JSON = {
        "tables": [{"path": "base_cells/file", "size": 2, "sha256": "new"}],
        "same": "old",
    }
    rendered, counts = patch(original, old, new)
    assert rendered == original.replace(b"golden/file", b"base_cells/file").replace(
        b'"size":1,"sha256":"old"', b'"size":2,"sha256":"new"'
    )
    assert counts == {
        "paths_rewritten": 1,
        "tables_repointed": 1,
        "hashes_cascaded": 1,
        "sizes_cascaded": 1,
    }


def test_repair_refuses_structural_changes() -> None:
    with pytest.raises(ValueError, match="reshape"):
        patch(b'{"a":1}', {"a": 1}, {"a": 1, "b": 2})
    original = b'{"a": [1, null, false, "\\u002f" ] }\n\n'
    value = cast(JSON, json.loads(original))
    assert patch(original, value, value)[0] == original
