"""Stream GeoJSON feature IDs without allocating coordinate arrays."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import IO

CHUNK_BYTES = 1024 * 1024
MAX_STRING_BYTES = 8_000_000
STRUCTURE = re.compile(rb'[{}\[\]:"]')
STRING = re.compile(rb'"(?:[^"\\]|\\.)*"')


def _tokens(stream: IO[bytes]) -> Iterator[bytes]:
    pending = b""
    while block := stream.read(CHUNK_BYTES):
        buffer = pending + block
        pending = b""
        position = 0
        while token := STRUCTURE.search(buffer, position):
            position = token.end()
            if token.group() != b'"':
                yield token.group()
                continue
            string = STRING.match(buffer, token.start())
            if string is None:
                pending = buffer[token.start() :]
                if len(pending) > MAX_STRING_BYTES:
                    raise ValueError("GeoJSON string exceeds bounded audit limit")
                break
            yield string.group()
            position = string.end()
    if pending:
        raise ValueError("Unterminated GeoJSON string")


def feature_ids(stream: IO[bytes]) -> list[str]:
    """Read properties.shapeID from each top-level FeatureCollection feature.

    This is a structural/identity audit, not a coordinate JSON validator. Geometry
    validation uses the matching unsimplified shapefile and the shared writer.
    """
    stack: list[bytes] = []
    last_string = b""
    field = b""
    features_depth = 0
    feature_depth = 0
    properties_depth = 0
    current_id: str | None = None
    found_features = False
    ids: list[str] = []
    for token in _tokens(stream):
        if token.startswith(b'"'):
            if (
                properties_depth
                and len(stack) == properties_depth
                and field == b'"shapeID"'
            ):
                value = json.loads(token)
                if not isinstance(value, str) or not value:
                    raise ValueError("Expected nonempty GeoJSON shapeID")
                current_id = value
            last_string = token
            field = b""
        elif token == b":":
            field = last_string
            last_string = b""
        elif token in (b"{", b"["):
            if len(stack) == 1 and token == b"[" and field == b'"features"':
                features_depth = 2
                found_features = True
            elif features_depth and len(stack) == features_depth and token == b"{":
                feature_depth = len(stack) + 1
                current_id = None
            elif (
                feature_depth
                and len(stack) == feature_depth
                and token == b"{"
                and field == b'"properties"'
            ):
                properties_depth = len(stack) + 1
            stack.append(token)
            field = last_string = b""
        else:
            expected = b"{" if token == b"}" else b"["
            if not stack or stack[-1] != expected:
                raise ValueError("Unbalanced GeoJSON containers")
            if len(stack) == properties_depth:
                properties_depth = 0
            if len(stack) == feature_depth:
                if current_id is None:
                    raise ValueError("Feature is missing properties.shapeID")
                ids.append(current_id)
                feature_depth = 0
            if len(stack) == features_depth:
                features_depth = 0
            stack.pop()
            field = last_string = b""
    if stack or not found_features:
        raise ValueError("Incomplete GeoJSON FeatureCollection")
    return ids
