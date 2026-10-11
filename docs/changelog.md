# Changelog

## Dataset 2026.10 — 2026-10-11

- `cells.block` holds each row's resolution-3 block as lowercase hex. It is
  constant per Parquet row group, so `WHERE block = ?` reads one row group in
  DuckDB and PyArrow; key statistics alone admit almost every row group.
- New `blocks` table: every covered block with its cells file, row group, row
  count and resolution-8 reference cells, including blocks without cells.
- Declared and enforced keys: `(source, source_id)` on airports, postal_codes,
  ip_ranges, trade_locations, phone_metadata, phone_prefixes, timezone_cells and
  zone_tables; `country_code` on countries; `code` on subdivisions. Assembly
  refuses a repeated key, and every relationship references a declared key.
- `countries.region_code` is documented as the UN M49 region code it holds.
- The committed dataset README documents every table.
- Planned for the next major schema, breaking: one H3 key per table (hex `h3` or
  signed `int64`, never `uint64`); per-row `provenance` split into a `sources`
  table and `<table>_evidence` tables; cells `group=` directories renamed or
  replaced by files sorted by `block`.

## 0.1.0 — 2026-10-11

- One Rust core owns format 2.2, results, reverse and all forward lookups.
- Python abi3 bindings and Node ESM/WASM expose the same result semantics.
- Explicit CLI verbs, streaming batch input, four output formats and shared stores.
- Resumable explicit installation, checksums, catalogue pins and atomic activation.
- Dictionary-coded, compressed forward blocks; shared core catalogue; lazy evidence.
- Grouped and legacy cell-layout inputs; real pipeline writer integration and
  deterministic installable release archives.
- Retired the v1 runtime, Python binary reader, Cython extension and hand-written
  Node reader. Old binary packs require rebuilding; they are not silently converted.
- Ambiguity keeps agreed flat fields. Reverse reports distance bands.
- Generated data dictionary (tables, joins, enumerations, tools, result fields),
  served by the MCP server, plus an executable agent skill in skills/thereabouts.
- Added wheel, sdist, npm and synthetic pipeline workflows. Publication is gated
  by an explicit manual run on a matching tag and release-environment approval.

The owner publishes 0.1.0 to supersede the PyPI/npm 0.0.1 placeholders.
No registry release has been made by this work. Code licensing and public release
endpoint remain owner decisions; the real names and plate-table gaps are recorded
in docs/clients/status.md.
