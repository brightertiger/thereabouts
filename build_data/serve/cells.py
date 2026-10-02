"""Encode exact stored ancestors, choosing flat or dictionary labels per block."""

from pathlib import Path

import pyarrow.parquet as pq
from h3.api import basic_int as h3

from thereabouts.packs.address import address
from thereabouts.packs.layout import (
    BLOCKS,
    DIRECTORY,
    KEYS,
    LABEL,
    LABELS,
    MAX_BLOCK_ROWS,
    SPATIAL,
    U16,
    VALUES,
    check_label,
    encode_flags,
)

from .catalogue import CatalogueIndex
from .encoding import write_container
from .snapshot import Row, Snapshot

Label = tuple[int, int, int, int]


def rows(
    snapshot: Snapshot, table: Row, catalogue: CatalogueIndex
) -> list[tuple[int, Label]]:
    if table["rows"] > MAX_BLOCK_ROWS:
        raise ValueError("Golden block exceeds its number of resolution-8 descendants")
    source = pq.ParquetFile(snapshot.file(table)).read().to_pylist()
    refs = catalogue.references(
        {
            r[k]
            for r in source
            for k in ("country_id", "state_id", "city_id")
            if r[k] is not None
        }
    )
    result = []
    root = int(table["block"], 16)
    for row in source:
        cell, resolution = row["h3_uint64"], row["h3_resolution"]
        if (
            not h3.is_valid_cell(cell)
            or not 3 <= resolution <= 8
            or resolution != h3.get_resolution(cell)
            or h3.int_to_str(cell) != row["h3"]
            or h3.cell_to_parent(cell, 3) != root
        ):
            raise ValueError("Golden H3 key disagrees with its block or resolution")
        country, state, city = (
            refs[row[k]] if row[k] is not None else 0
            for k in ("country_id", "state_id", "city_id")
        )
        flags = encode_flags(
            row["city_method"],
            row["country_method"],
            row["state_method"],
            row["land_method"],
        )
        label = country, state, city, flags
        check_label(label, catalogue.count)
        result.append((address(cell, resolution)[1], label))
    return sorted(result)


def write_cells(
    snapshot: Snapshot, tables: list[Row], catalogue: CatalogueIndex, path: Path
) -> None:
    sections: dict[int, bytearray] = {
        k: bytearray() for k in (BLOCKS, KEYS, VALUES, LABELS)
    }
    for table in tables:
        block = address(int(table["block"], 16), 3)[0]
        values = rows(snapshot, table, catalogue)
        labels = sorted({label for _, label in values})
        width = 1 if len(labels) <= 256 else 2
        if len(labels) * LABEL.size + len(values) * width >= len(values) * LABEL.size:
            width = 0
        sections[BLOCKS].extend(
            DIRECTORY.pack(
                block,
                len(values),
                len(sections[KEYS]),
                width,
                len(labels) if width else 0,
                len(sections[VALUES]),
                len(sections[LABELS]),
            )
        )
        selectors = {label: i for i, label in enumerate(labels)}
        for key, label in values:
            sections[KEYS].extend(U16.pack(key))
            sections[VALUES].extend(
                selectors[label].to_bytes(width, "little")
                if width
                else LABEL.pack(*label)
            )
        if width:
            for label in labels:
                sections[LABELS].extend(LABEL.pack(*label))
    write_container(path, SPATIAL, sections)
