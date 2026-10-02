from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from h3.api import basic_int as h3

from build_data.acquire.lookup_schemas import LOOKUP_SCHEMAS
from build_data.serve.checkpoints import file_record
from build_data.serve.metadata import write_manifest
from build_data.serve.snapshot import Row, read_snapshot
from build_data.serve_codes.source import JOIN_FIELDS, cells
from thereabouts.packs.jsonio import parse

from ..client.test_api import BRANCHES, finest
from ..serve.fixtures import golden, write_table


def snapshot(root: Path) -> tuple[Path, Path]:
    manifest, release = golden(root)
    value = parse(manifest.read_bytes())
    record = next(
        row
        for row in value["tables"]
        if row["kind"] == "cells"
        and row["block"] == h3.int_to_str(h3.cell_to_parent(BRANCHES[0], 3))
    )
    path = root / record["path"]
    table = pq.ParquetFile(path).read()
    data = table.to_pylist()
    for row in data:
        if row["h3_uint64"] == BRANCHES[2]:
            row.update(
                city_id="city:synthetic:unused", city_method="rural_nearest_distant"
            )
    pq.write_table(pa.Table.from_pylist(data, schema=table.schema), path)
    record.update(file_record(path, root))
    write_manifest(manifest, value)
    reader = cells(read_snapshot(manifest))

    def observation(
        kind: str, identity: str, point: str | None, **fields: object
    ) -> Row:
        row: Row = {name: None for name in LOOKUP_SCHEMAS[kind].names}  # type: ignore[index]
        row.update(
            source="synthetic",
            source_id=identity,
            source_release="fixture",
            license="public-domain",
            provenance="{}",
        )
        row.update(fields)
        if point is not None:
            latitude, longitude = h3.cell_to_latlng(int(point, 16))
            row.update(
                latitude=latitude,
                longitude=longitude,
                h3=point,
                h3_uint64=int(point, 16),
                h3_resolution=8,
            )
        joined = reader.lookup(point)
        country_id = joined.get("country_id")
        country = None if country_id is None else country_id.removeprefix("country:")
        row.update(
            {name: joined.get(name) for name in ("country_id", "state_id", "city_id")}
        )
        row.update(
            cell_status=joined["cell_status"],
            cell_country_code=country,
            country_disagrees=None
            if country is None or row["country_code"] is None
            else country != row["country_code"],
        )
        return row

    first, second = finest(BRANCHES[0]), finest(BRANCHES[2])
    postal = [
        observation(
            "postal_codes",
            "p1",
            first,
            country_code="AA",
            postal_code="00100",
            place_name="Source town",
            variant="base",
        ),
        observation(
            "postal_codes",
            "p2",
            first,
            country_code="AA",
            postal_code="00100",
            place_name="Source town full",
            variant="full",
        ),
        observation(
            "postal_codes",
            "p3",
            first,
            country_code="AA",
            postal_code="AMB",
            place_name="One",
        ),
        observation(
            "postal_codes",
            "p4",
            second,
            country_code="AA",
            postal_code="AMB",
            place_name="Two",
        ),
        observation(
            "postal_codes",
            "p5",
            second,
            country_code="IN",
            postal_code="560001",
            place_name="Conflicting source label",
        ),
        observation(
            "postal_codes",
            "p6",
            None,
            country_code="AA",
            postal_code="VOID",
            place_name="Unlocated source",
        ),
        observation(
            "postal_codes",
            "p7",
            first,
            country_code="CA",
            postal_code="A1A 1A1",
            place_name="Unicode 東京",
        ),
    ]
    airports = [
        observation(
            "airports",
            "a1",
            first,
            country_code="AA",
            ident="AA01",
            iata_code="ZZZ",
            icao_code="AAAA",
            gps_code="GPS1",
            local_code="L1",
            type="heliport",
            name="First airport",
            municipality="Source municipality",
        ),
        observation(
            "airports",
            "a1",
            first,
            country_code="AA",
            ident="AA01",
            iata_code="ZZZ",
            type="heliport",
            name="First airport renamed",
            municipality="Source municipality",
        ),
        observation(
            "airports",
            "a2",
            None,
            country_code="BB",
            ident="BB02",
            iata_code="ZZZ",
            local_code="L1",
            type="closed",
            name="Closed airport",
        ),
        observation(
            "airports", "a3", None, country_code="AA", name="No codes", type="closed"
        ),
    ]
    for kind, rows in (("postal_codes", postal), ("airports", airports)):
        lookup_schema = pa.schema([*LOOKUP_SCHEMAS[kind], *JOIN_FIELDS])  # type: ignore[index]
        value["tables"].append(
            write_table(
                root,
                f"golden/lookups/{kind}/joined.parquet",
                rows,
                lookup_schema,
                kind=kind,
            )
        )
    write_manifest(manifest, value)
    return manifest, release
