"""Full checksum and structural verification with one mapped shard at a time."""

from pathlib import Path
from typing import Any

from h3.api import basic_int as h3

from .address import address
from .catalogue import Catalogue
from .code_records import payload
from .errors import CorruptPackError
from .exact import Exact
from .jsonio import relative_file
from .keys import check_key
from .layout import PLACES
from .metadata import read_manifest
from .spatial import Spatial


def verify(root: Path) -> dict[str, Any]:
    value = read_manifest(root, full=True)
    previous = b""
    blocks: set[int] = set()
    try:
        for record in value["files"]:
            path = relative_file(root, record["path"])
            if record["kind"] == "catalogue":
                catalogue = Catalogue(path, value["place_count"])
                try:
                    if catalogue.sections[PLACES].count != record["count"]:
                        raise ValueError("Catalogue shard row count mismatch")
                    catalogue.verify()
                    for index in range(record["count"]):
                        identity = catalogue.record(index)["place_id"].encode("utf-8")
                        if identity <= previous:
                            raise ValueError(
                                "Public place IDs are not globally unique and sorted"
                            )
                        previous = identity
                finally:
                    catalogue.close()
            elif record["kind"] == "exact":
                exact = Exact(path, record["max_record_bytes"])
                try:
                    if (
                        exact.count != record["count"]
                        or exact.key(0).decode("utf-8") != record["first_key"]
                        or exact.key(exact.count - 1).decode("utf-8")
                        != record["last_key"]
                    ):
                        raise ValueError("Exact-key directory differs from manifest")
                    for index in range(exact.count):
                        check_key(
                            exact.key(index).decode("utf-8"),
                            value["family"],
                            value["key_normalization"],
                        )
                        payload(exact.payload(index), value["place_count"])
                finally:
                    exact.close()
            elif record["kind"] == "cells":
                spatial = Spatial(path, value["place_count"])
                try:
                    if (
                        spatial.ids[0] != record["first_block"]
                        or spatial.ids[-1] != record["last_block"]
                    ):
                        raise ValueError("Spatial shard range mismatch")
                    spatial.verify()
                    blocks.update(spatial.ids)
                finally:
                    spatial.close()
        if value["coverage"] == "world":
            expected = {
                address(c, 3)[0]
                for base in h3.get_res0_cells()
                for c in h3.cell_to_children(base, 3)
            }
            if blocks != expected:
                raise ValueError(
                    "World coverage lacks explicit blocks, including ocean"
                )
    except (ValueError, KeyError, TypeError) as exc:
        raise CorruptPackError(f"Invalid serving payload: {exc}") from exc
    return value
