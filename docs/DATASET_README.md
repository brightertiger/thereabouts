# Thereabouts dataset

Thereabouts connects coordinates and location identifiers to country,
subdivision and canonical city identities. Its land-cell table represents H3
resolution-8 cell centres, including the retained near-shore coverage. Supporting
tables describe places, postal observations, airports, trade locations, IP ranges,
phone prefixes and time zones. The tables retain source evidence so that readers
can distinguish a geographic assignment from an upstream label.

A canonical city is the identity chosen by the published geographic policy.
Neighbourhoods may map to that city; independent municipalities and rural
settlements can keep their own identities. Assignment methods remain explicit:
an accepted polygon, an inferred urban allocation and a nearest settlement are
different kinds of evidence. This is a dataset of policy-based geographic
answers, not a guarantee of surveyed municipal boundaries or exact address
accuracy.

## Release layout (implementation draft)

This is the planned public layout for work package 4. The dataset generator,
column reference, measured counts, examples, attribution and citation have not
yet been implemented. This document is not a release inventory. A completed
release will generate its README and measurements from its own manifest.
The tree covers the current fourteen table families. Package 3 must define the
plate-country table before package 4 adds it to this inventory.

```text
dataset/<version>/                      Immutable release, YYYY.MM or YYYY.MM.patch.
  README.md                             Purpose, schema reference and runnable examples.
  manifest.json                         Complete inventory, row counts, bytes and SHA256s.
  DATA_LICENSES.md                      Licences and attribution for the inputs used.
  DATASET_CARD.md                       Coverage, provenance, policy and limitations.
  CHANGES.md                            Content comparison with the preceding release.
  cells/block_group=<group>/*.parquet   Consecutive resolution-3 blocks grouped for reads.
  places/country=<CC>/*.parquet         Canonical place identities and retained evidence.
  canonical_cities/country=<CC>/*.parquet Absorbing city/town identities and footprints.
  place_to_city/country=<CC>/*.parquet  Place identities mapped to their reported city.
  postal_codes/*.parquet               Source postal observations and geographic links.
  airports/*.parquet                   Airport identities, codes and geographic links.
  trade_locations/*.parquet            UN/LOCODE observations and geographic links.
  ip_ranges/*.parquet                  Inclusive IP intervals and source estimates.
  countries/*.parquet                  Country codes and canonical identity links.
  subdivisions/*.parquet               Explicit subdivision code systems and links.
  timezone_cells/*.parquet             Compacted H3 membership in source time zones.
  zone_tables/*.parquet                IANA zone metadata and reference coordinates.
  phone_prefixes/*.parquet             Localized descriptions and candidate countries.
  phone_metadata/*.parquet             Territory/service numbering metadata.
```

Read only files listed by `manifest.json`. A directory listing can include files
from an interrupted transfer; the completed publication marker is written last.
Serving packs are a separate product under `packs/<version>/`; they preserve
the dataset's answers in a compact format for offline clients.

For a coordinate query, compute its H3 resolution-8 cell once, then its logical
resolution-3 ancestor to locate the block group. Some stored rows are compacted
ancestors between resolutions 3 and 8: search the query's ancestor keys from
resolution 8 down to 3. Recomputing H3 from the original coordinate at each
resolution is a different operation and can return the wrong row.

The full reference must explain the stored cell encoding, canonical city joins,
nullable answers, distant-nearest method, and ambiguity without hiding source
disagreements. It will include local/S3 DuckDB, PyArrow and pandas examples
executed against the measured release subset. Until then, the historical schema
and measurements remain in [the golden-dataset documentation](history/golden-dataset.md).
