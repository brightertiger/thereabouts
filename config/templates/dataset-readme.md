# Thereabouts dataset {{version}}

Thereabouts is an offline geocoding database: it relates locations on land and the retained near-shore band to a country, subdivision and canonical city, and preserves place names and observations such as postal codes, airports, telephone prefixes, IP ranges and timezones. The files are ordinary Parquet tables; they can be queried directly without installing the Thereabouts client.

This release is an immutable, measured export of completed normalization outputs. Geographic decisions and original observations are retained. {{coverage}} It is intended for search, exploration and offline applications; source coverage and city conventions vary, and these labels do not determine legal boundaries. Binary client packs are distributed separately and are not part of this directory.

## Directory layout

```text
dataset/{{version}}/
{{tree}}
```

The tree lists every logical entry; `*` denotes partitions. Paths in `manifest.json` are relative to this directory. Each table entry records its path, SHA256, compressed bytes and row count. Cell partitions group resolution-3 blocks by their resolution-{{group_resolution}} parent (up to {{blocks_per_group}} blocks per group); this changes file packaging only. Country catalogues use `country=<code>` partitions. Other observations share one file per table. Empty tables retain a schema-bearing Parquet file. Partition labels route files; they are not stored columns. DuckDB and PyArrow detect `country=` and `group=` directories as Hive partitions and add `country` and `group` columns, so the examples below turn that off (`hive_partitioning=false` in DuckDB). `group` is a reserved SQL word: quote it as `"group"` if you keep the partition column.

## Cell keys and result semantics

Convert a WGS84 latitude/longitude to an H3 resolution-8 index. Its resolution-3 **parent** is the block; its resolution-{{group_resolution}} parent selects the coalesced file. The directory `group=<r{{group_resolution}} hex>` contains that parent's lowercase hexadecimal H3 index, without `0x` (for example, `group=81653ffffffffff`). Do not independently quantize the coordinate at a coarser resolution: H3 grids at different resolutions do not exactly nest geometrically. Stored cells are losslessly compacted: look for the resolution-8 index and then its ancestors down to resolution 3, choosing the finest match. No match means this {{scope}} has no result there, including outside its land coverage.

`h3` is lowercase hexadecimal text without `0x`; `h3_uint64` is the same unsigned 64-bit H3 index, with resolution in bits 52–55 and base-cell/child digits in the standard H3 representation. These are global H3 indexes, not a client pack's local integer offsets. `h3_resolution` says how many levels that stored row represents. Resolution 8 is the reference precision; coarser rows encode identical assignments for their descendant centres.

Each coalesced cells file contains **one Parquet row group per retained resolution-3 block**, ordered by ascending block ID. All rows of a block occupy that single row group, even when the input spans several files or batches. Blocks with no selected rows have no row group; an empty cells file has no row groups. Every cells row stores its block ID in the `block` column, which is therefore constant within a row group: a `block = '<r3 hex>'` filter lets DuckDB, PyArrow and other Parquet readers skip every other row group by its statistics. A filter on `h3_uint64` alone cannot, because H3 integers order by resolution before location and a row group holding several resolutions spans most of the key range. The `blocks` table lists every covered block with the cells file that holds it (`path`), its `row_group`, its `row_count` and the resolution-8 `reference_cells` its rows stand for. A covered block with `row_count` 0 stores no cells, and lookups there find no land; a block missing from `blocks` is outside this {{scope}}'s coverage. `manifest.json` carries the same index: every cells entry in both `manifest.json.tables` and `manifest.json.files` includes `blocks: [{"block": "<r3 hex>", "row_group": 0, "rows": n}, ...]` and `empty_blocks: ["<r3 hex>", ...]`. Block IDs are lowercase hexadecimal without `0x`, `row_group` is the zero-based Parquet row-group index, and `rows` is that group's row count. Readers and the client pack writer locate the coordinate's resolution-3 parent in this index, read that row group, then match the stored ancestors described above. The file's `rows` equals the sum of its block counts; no row group contains multiple blocks.

Cell `country_id`, `state_id` and `city_id` link to `places.place_id`. The `canonical_cities` table contains eligible city/town anchors that can absorb other settlements; it is not a catalogue of every rural result. Standalone villages and other rural settlements can retain their own place IDs in `city_id`. `places.normalized_city_id` and `place_to_city.city_id` expose the reviewed mapping, including self-mappings and nulls for non-settlements. Source city/municipality strings are retained independently. The selected settlement can differ from the nearest named place or an administrative district. Legacy `city:` ID prefixes do not prove an entity is a city; inspect its `role` and `settlement_kind`.

IDs carry an entity namespace and its source identity: `country:MY` uses the country code, `state:overture:<uuid>` identifies a subdivision derived from Overture, and `city:geonames:<decimal id>` identifies a GeoNames-derived settlement. Other source namespaces and policy-defined IDs also occur; treat the complete string as opaque. IDs are deterministic for unchanged source identities and policy, but are **not guaranteed stable across monthly versions**. Source merges, removals, role changes and reviewed canonicalization can retire or redirect IDs. Store the release version with an ID, and compare `places` and `place_to_city` across versions before joining historical records; a matching name is not an identity guarantee.

Method columns explain the evidence or fallback used. `city_method = 'rural_nearest_distant'` is the distant-nearest flag: the policy's distant threshold is {{distant_m}} metres, and its nearest-city cutoff is {{nearest_m}} metres. The full method set is `city_polygon`, `policy_polygon`, `urban_allocation`, `town_radius`, `rural_polygon`, `rural_nearest`, `rural_nearest_distant`, or null. Town radius is disabled in this snapshot; consult the exact policy in `manifest.json`. Null city means no qualifying assignment. An identifier lookup with `link_status = 'ambiguous'` preserves candidates in `place_ids`; `place_id` is populated only for a unique match. Spatial observations keep `cell_status` and nullable `country_disagrees`, so source disagreement is visible rather than silently corrected. Every place reference resolves to a `places` row: assembly refuses a dangling reference, as the client pack writer does.

Timezone membership is independent of eligible land. `timezone_cells` can store resolutions 0–8 and overlapping source memberships; query all ancestors down to resolution 0 for that table. In a spatial subset, a timezone row coarser than resolution 3 is retained whole when it overlaps a selected block, so its represented area can extend outside the subset.

## Quality gates

Before export, the pipeline checks every country's city boundaries and footprints. {{quality_gates}}

## Tables and columns

Arrow types and physical nullability below are checked during assembly. “None” for units means an identifier, category, text or dimensionless value. Required logical keys are listed separately from Arrow nullability. Observation tables are keyed by `source` and `source_id`, one row per source record, so duplicate observations of one code or place are retained as separate rows. Assembly refuses a release that repeats any declared key. Counts and bytes are for this exact export, not a world estimate.

`places.place_id` is a required, non-null logical primary key. Its retained Arrow field is physically nullable, as are some other logical keys; assembly rejects null values in every declared logical primary-key column. “Yes in Arrow; no for the logical key” distinguishes these two contracts without changing the retained field schema.

{{tables}}

## Worked coordinate reads

Install `duckdb`, `h3`, `pyarrow` and `pandas` in your analysis environment. Set `DATASET` to this directory. These three examples use {{latitude}}, {{longitude}}, inside this {{scope}}, and print the matched cell's country, state, canonical city and method. All three query the same stored H3 ancestors and filter on the point's block first, so each reads one row group of one cells file.

### DuckDB SQL over local Parquet

```python
import os
from pathlib import Path
import duckdb
import h3

root = Path(os.environ["DATASET"])
cell = h3.latlng_to_cell({{latitude}}, {{longitude}}, 8)
block = h3.cell_to_parent(cell, 3)
keys = [int(h3.cell_to_parent(cell, level), 16) for level in range(3, 9)]
pattern = str(root / "cells" / "**" / "*.parquet")
connection = duckdb.connect()
connection.execute("SET memory_limit='256MB'")
connection.execute("SET threads=1")
result = connection.execute(
    """WITH cell AS (
    SELECT country_id, state_id, city_id, city_method
    FROM read_parquet(?, hive_partitioning=false)
    WHERE block = ? AND h3_uint64 IN (SELECT unnest(?::UBIGINT[]))
    ORDER BY h3_resolution DESC LIMIT 1
  )
  SELECT c.country_id, c.state_id, c.city_id, p.name AS city_name, c.city_method
  FROM cell c LEFT JOIN read_parquet(?, hive_partitioning=false) p
    ON c.city_id = p.place_id""",
    [pattern, block, keys, str(root / "places" / "**" / "*.parquet")],
).fetchall()
assert len(result) == 1
assert result[0][3]  # A catalogue name for this example's selected settlement.
print(result)
connection.close()
```

{{remote}} The name join uses `places`, which includes rural settlements; join `canonical_cities` separately for eligible city/town anchor details.

### PyArrow

```python
import os
from pathlib import Path
import h3
import pyarrow as pa
import pyarrow.dataset as ds

root = Path(os.environ["DATASET"])
cell = h3.latlng_to_cell({{latitude}}, {{longitude}}, 8)
block = h3.cell_to_parent(cell, 3)
keys = pa.array(
    [int(h3.cell_to_parent(cell, level), 16) for level in range(3, 9)], type=pa.uint64()
)
table = ds.dataset(root / "cells", format="parquet").to_table(
    filter=(ds.field("block") == block) & ds.field("h3_uint64").isin(keys),
    columns=["country_id", "state_id", "city_id", "city_method", "h3_resolution"],
)
rows = sorted(table.to_pylist(), key=lambda row: row["h3_resolution"], reverse=True)
assert rows
print(
    {key: rows[0][key] for key in ("country_id", "state_id", "city_id", "city_method")}
)
```

### pandas with Parquet filter pushdown

```python
import os
from pathlib import Path
import h3
import pandas as pd

root = Path(os.environ["DATASET"])
cell = h3.latlng_to_cell({{latitude}}, {{longitude}}, 8)
block = h3.cell_to_parent(cell, 3)
keys = [int(h3.cell_to_parent(cell, level), 16) for level in range(3, 9)]
frame = pd.read_parquet(
    root / "cells",
    engine="pyarrow",
    filters=[("block", "==", block), ("h3_uint64", "in", keys)],
    columns=["country_id", "state_id", "city_id", "city_method", "h3_resolution"],
)
frame = frame.sort_values("h3_resolution", ascending=False)
assert not frame.empty
print(frame.iloc[0][["country_id", "state_id", "city_id", "city_method"]].to_dict())
```

## Versions and integrity

Versions use `YYYY.MM[.patch]`: the monthly release and, when required, a positive patch number. A published version is immutable. `CHANGES.md` compares each table's logical digest and row count with the previous version. `content.json` hashes logical values and duplicate counts independently of partitioning, row order, Parquet metadata and compression. It covers every table except `blocks`, which indexes the packaging of `cells`. A packaging change can change file SHA256 without changing the logical digest.

Before using a downloaded release, verify every `manifest.json.files` entry by its byte size and SHA256; every Parquet entry also has its row count. The manifest itself is committed by the publication's `dataset/{{version}}/_SUCCESS` receipt (the same receipt is written to `packs/{{version}}/_SUCCESS`), written only after every dataset and requested pack object verifies. A directory without that remote receipt may be an incomplete upload. Locally assembled datasets are complete when their verified `manifest.json` is present. SHA256 detects corruption; it is not an authenticity signature.

The manifest's top-level keys are `schema_version`, `completed`, `data_root`, `version`, `inputs_hash`, `reference_resolution`, `block_resolution`, `normalization`, `sources`, `statistics`, `schemas`, `selection`, `input_manifest_sha256`, `logical_sha256`, `quality_gates`, `tables` and `files`. `tables` is the Parquet inventory; `files` also covers the generated documents and logical digest. File entries contain `path`, `size` (bytes) and `sha256`; table entries add `kind` and `rows`, and cells entries add the `blocks` row-group index and `empty_blocks` defined above. `sources` ships the exact pins and their per-file licence metadata. `schemas` describes columns and logical keys; `normalization` records the applied policy; `selection` declares subset countries and blocks; `quality_gates` summarizes the quality gates above.

With Python 3.11 or newer and `DATASET` set, verify local bytes without loading the tables:

```sh
python - <<'PY'
import hashlib
import json
import os
from pathlib import Path

root = Path(os.environ["DATASET"]).resolve()
manifest = json.loads((root / "manifest.json").read_text())
for entry in manifest["files"]:
    path = (root / entry["path"]).resolve()
    assert path.is_relative_to(root), entry["path"]
    assert path.stat().st_size == entry["size"], entry["path"]
    with path.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == entry["sha256"], entry["path"]
print(f"Verified {len(manifest['files'])} files")
PY
```

## Next major schema

This release only adds to the schema: `cells.block`, the `blocks` table and declared keys. The next major schema version is planned to change the following, which will break queries that rely on the current shape.

- **One H3 key per table.** Tables keep a single H3 key column: the hexadecimal `h3` text or a signed `int64`, never both and never unsigned. Athena, BigQuery, Spark and pandas with nulls cannot hold unsigned 64-bit keys. Prefer `h3` and `block` in new queries.
- **Provenance split.** The per-row `provenance` JSON leaves the main tables. Source-level facts move to a `sources` table, and row-specific evidence to `<table>_evidence` tables keyed by `source` and `source_id`.
- **`group=` directories renamed.** Cells folders stop using the reserved word `group` as their partition label, or give way to files sorted by `block`. Reach a block's rows through the `block` column or the `blocks` table, not directory names.

## Licences, contact and citation

{{licences}}

This derived database is licensed under ODbL 1.0, including its attribution and share-alike requirements for publicly used derivative databases. Preserve the source attribution in `DATA_LICENSES.md`; individual source terms still apply. The code's licence does not replace data licences. Pin identifiers, source checksums and provenance are in the manifest.

Contact: {{contact}}

Citation: {{citation}}

Public documentation: {{documentation}}
