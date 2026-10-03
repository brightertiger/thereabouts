"""Compare every emitted stored row and catalogue field with its golden input."""

from pathlib import Path

from thereabouts.packs.address import address
from thereabouts.packs.catalogue import Catalogue
from thereabouts.packs.jsonio import parse
from thereabouts.packs.spatial import Spatial

from .catalogue import CatalogueIndex
from .cells import rows
from .snapshot import Row, Snapshot


def verify_source(
    snapshot: Snapshot, pack: Path, files: list[Row], index: CatalogueIndex
) -> None:
    places = index.records()
    tables = {address(int(r["block"], 16), 3)[0]: r for r in snapshot.tables("cells")}
    for record in files:
        if record["kind"] == "catalogue":
            catalogue = Catalogue(pack / record["path"], index.count)
            try:
                for ordinal in range(record["count"]):
                    ref, expected = next(places)
                    expected["evidence"] = parse(expected["evidence"])
                    actual = catalogue.record(ordinal)
                    if ref != record["first_id"] + ordinal or actual != expected:
                        raise ValueError("Serving catalogue differs from golden source")
            finally:
                catalogue.close()
        elif record["kind"] == "cells":
            spatial = Spatial(pack / record["path"], index.count)
            try:
                for block in spatial.blocks.values():
                    table = tables.pop(block.block)
                    expected_rows = rows(snapshot, table, index)
                    actual_rows = [
                        (key, spatial.label(block, i))
                        for i, key in enumerate(spatial.keys(block))
                    ]
                    if actual_rows != expected_rows:
                        raise ValueError("Serving cells differ from golden source")
            finally:
                spatial.close()
    if tables or next(places, None) is not None:
        raise ValueError("Serving pack omitted golden rows")
