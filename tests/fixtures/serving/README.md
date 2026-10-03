# Synthetic serving format example

This tiny, offline `thereabouts-pack-1` example has four logical H3 blocks,
33 stored ancestors at resolutions 3–8, and five retained places. Names,
assignments, country codes and quality records are synthetic. It is not geographic
data. It includes a pentagon, a polar block, an explicitly empty date-seam block,
all city-method encodings, nulls, Unicode, flat labels and uint8 dictionary labels.
The tests also generate uint16 dictionaries separately.

Validate with `python -m build_data.serve verify tests/fixtures/serving`.
The container and addressing specification is `docs/SERVING_FORMAT.md`.

`tests.serve.fixtures.golden(root)` generates its small golden input and release
metadata. Pass the returned paths to `build_data.serve.export.export`, with
`shard_bytes=1024`, and a **new** output directory. Copy the verified result here
when intentionally updating the fixture. Its checksummed manifest records the
exporter code/tool versions used; it need not match a later checkout's revision.
This README is outside the manifest inventory and is not consumed by readers.
