# Thereabouts client status

Work packages 1 and 2 are implemented on `feat/rust-core`, including the
package-2 prerequisite fixes. The plate-country release was unavailable; the
explicit sample fallback and remaining verification limit are described below.
Package 3 has not started. The contract is the
[approved design](superpowers/specs/2026-10-03-client-redesign-design.md);
[PACK_FORMAT.md](PACK_FORMAT.md) is the normative version-2 specification.

## Rework and package-2 changes

The writer is a separate crate. The reader retains shard file handles, uses
positioned reads, and coalesces a catalogue miss into three reads. Ordinary
lookups exclude the evidence reference and JSON parsing; evidence-bearing places
have a separate cache identity.
Its LRU caches have O(1) operations, with IO and decoding outside locks.
Timezone narrowing falls back to the original set when no country-compatible
zone survives. Overlap never makes reverse ambiguous. Result enums follow the
specification; distance_band replaces invented distances, and selected is absent.
Writer hot scans use typed Arrow fields and typed SQLite columns.

The package-2 format rework converts forward data to format 2.1: bounded
LZ4-compressed integer columns, pack-level string dictionaries, separate cold
evidence and smaller referenced metadata. Postal, airports and LOCODE use FST
keys; airports have one record per source identity. Phone uses an FST of prefixes;
IP uses sorted starts with implicit ends and explicit uncovered gap rows.
Old forward packs are rejected and must be rebuilt. Remaining review fixes,
updated runtime measurements and the later semantic fixes are still in progress. Plates carry source rules and
registration evidence. Canonical-city names now live in core, with FST exact
and prefix search plus trigram fallback. Name rules and Unicode versions are
pack data. The refreshed core sample retains its previous reverse expectations.

## Python API

The top-level exports remain Geocoder, reverse, Result and the current coded
error classes. Results and nested geographic values are frozen dataclasses.
Queries never download data. Select a family directly, or select several packs:

```python
from pathlib import Path
from thereabouts import Geocoder

root = Path("tests/fixtures/packs")
with Geocoder(packs={
    "core": root / "core-names-sample",
    "postal": root / "postal-sample",
    "airports": root / "airports-sample",
}) as geo:
    city = geo.geocode("Springfield", country="US", subdivision="US-IL")
    postal = geo.postal("75001", country="FR", evidence=True)
    airport = geo.airport("CDG")
    columns = geo.geocode_columns(["Lyon", "Springfield", "75001"])
```

All selected packs must share a dataset version. Geocoder() uses explicit
data_dir, then THEREABOUTS_DATA, then the platform user-data directory, retaining
the existing packs/<family>/v-<version>/<digest>/ layout and current.json pointer.
Explicit mappings open queried families lazily; default discovery opens the
first installed family and opens other families on demand. A missing family names its exact
`thereabouts data install <family>` command. The new installer is package 3.

| Verb | Arguments and behavior |
| --- | --- |
| reverse | Keyword-only lat, lon; optional evidence |
| from_h3 | H3 resolutions 0–8; resolves a stored ancestor, never a descendant |
| postal | code, country required, optional evidence |
| airport | code; default IATA and ICAO, or scheme IATA/ICAO/GPS/local/ident; local requires country |
| locode | full five-character code, or three characters plus country |
| phone | E.164 number with leading +; longest published prefix, including metadata fallbacks |
| ip | IPv4 or IPv6 literal; ports, CIDRs and zones are invalid |
| plate | serial; optional country, series and evidence; a country hint is exact |
| geocode | name; country/subdivision hard filters, limit 1–100, prefer="population", scope="cities", evidence |

Geocode finds towns and cities only. Code-shaped requests include a hint naming
the appropriate verb; street addresses return unsupported_granularity. Ranking
is population, reported in rank_basis. Multiple cities remain ambiguous with
null flat geography and ranked candidates, even with limit=1. prefer="population"
opts into selection. Prefix matches and typo fallback report fuzzy; English and
alternate exact spellings report alternate_name.

Every forward verb also has a <verb>_columns batch method. String columns are
int32 dictionary codes plus <field>_categories; -1 is null. Nullable numerics
have <field>_valid masks. Forward columns include candidate_offsets and flattened
candidate_* columns. Reverse columns omit candidates. Both omit evidence, fill
fixed-width buffers while iterating, and release the GIL. reverse_many remains
an ordered iterator. Coordinate arrays may be strided.

Missing queries and invalid values are statuses; missing, incompatible, corrupt
or closed packs raise coded exceptions. State fields use subdivisions by code,
falling back to published place fields only when that table has no row.
Canonical city fields follow published associations. Postal/admin, airport,
LOCODE, phone-description and IP city text remain available in evidence rather
than being guessed into new canonical cities.

## Writer, runtime and reproducible samples

The mixed maturin project contains thereabouts-core, thereabouts-writer and
thereabouts-py. Core is wasm-compatible and has no Arrow/Parquet/SQLite dependency.
Its direct dependencies are fst, h3o, lz4_flex, regex, serde, serde_json, sha2, thiserror,
unicode-casefold and unicode-normalization. The Python writer feature owns
dataset export; no application Rust unsafe was introduced.

`_core.write_pack(dataset_dir, family, output_dir, options)` selects table kinds
from a verified golden manifest. Required geographic and family tables are
strict; deliberate fixture omissions must be listed explicitly. Inputs and
counts are verified, no source defaults are guessed, and changed inputs never
overwrite an existing output. The 512 MiB admission design covers bounded scans, shards, ID selection and
SQLite staging; process peak RSS is measured separately. Forward writers select
only referenced catalogue ancestry, and the large IP/postal sorts stage
dictionary IDs. Temporary SQLite writes share one transaction through emission. Preflight retains
a 5 GiB floor plus an input-based estimate. Staging defaults to the output parent;
SQLite scratch may use a separately checked filesystem.

Default opening reads search indexes/directories and metadata. Spatial and
catalogue payloads validate on demand. Full hashes and structural checks use
verify=True or _core.verify_pack. Caches retain at most 8 MiB of decoded blocks,
4 MiB of places, 4 MiB of observations, and 1 MiB of repeated IP-address hits;
active calls may retain evicted values. Name FSTs/postings and plate rules are
resident indexes. Open files must remain immutable.

Sample builders live in tools/build_sample_pack.py, build_forward_samples.py
(postal/airports/LOCODE), build_phone_sample.py, build_ip_sample.py,
build_plates_sample.py and build_names_sample.py. They read explicit source
paths, select BE/NL/LU/FR/TR/IN/US where available, and write only worktree
fixtures. Manifests retain source digests, dataset version, selection rules and
Parquet settings; repeatability requires the recorded PyArrow version.

The reverse core sample is 4,636,487 bytes over 29 resolution-3 blocks: continental
Belgium, Netherlands, Luxembourg, plus Paris, Istanbul, Mumbai, Delhi, Springfield
(Illinois) and a Montana distant-nearest block. The dataset label is 2026.10.
The names-only core sample selects 101 cities, including every selected
Springfield and named normalization examples. It is a test subset with explicit
spatial-table omissions, not a separately installable geocode family.
New family/name pack fixtures, including synthetic packs, total 2,878,705 bytes
under the 10 MB budget; their breakdown is in CLIENT_FORWARD_MEASUREMENTS.json.

## Conformance

The original 54-vector bundle is asserted with explicit mappings, not described
as unchanged snapshots. Rust and Python both check the following:

- 35 legacy reverse requests: 19 matches; 1 unassigned, 4 no-land and 2
  outside-coverage misses; 8 invalid inputs; one intentional change accepting
  the r3 query and returning no_stored_ancestor. The only other allowance is
  the synthetic canonical city's display name.
- 8 legacy postal requests: 4 matched, 1 ambiguous, 1 not_found, 2 invalid_input.
- 11 legacy airport requests: 7 matched, 2 ambiguous, 1 not_found, 1 invalid_input.
  Legacy case 52 now searches IATA/ICAO and asserts the original case 32
  candidates. Source identity/geography assertions and the canonical-name
  allowance remain explicit. Code matches now use exact.

The 19 forward legacy cases therefore assert 11 matched, 3 ambiguous, 2 not_found
and 3 invalid_input results against original expectations. They run in addition
to new shared snapshots and offline independent source checks.

There are 139 real reverse vectors. Offline pytest independently checks 131 r8
requests (123 matches) against committed golden-cell extracts, ancestry, state
and timezone rows. Every forward family has at least 20 shared real vectors;
the table below lists counts. Additional synthetic vectors cover the 19 legacy
forward cases, six phone cases and seven name cases. Independent forward checks
use committed source observations, canonical links, inclusive IP boundaries,
plate reference semantics and city population ordering. The real name subset
has no differing English names; English and future alternate-table behavior is
explicitly synthetic. Tests require no access to real data. Node execution
awaits its binding package; the JSON is shared.

## Measurements

All numbers come from benchmarks/core_read_path.py,
benchmarks/multishard_read_path.py and benchmarks/forward_read_path.py, recorded
in CLIENT_CORE_MEASUREMENTS.json and CLIENT_FORWARD_MEASUREMENTS.json.
Machine: Apple M2, 8 GiB, macOS arm64, Python 3.12.8.

The prerequisite multi-shard workload has 256 catalogue shards, 16,384 places
and 36,678,465 bytes, generated locally rather than committed. It uses 100,000
seeded random requests and seven batch repetitions. Before → after N2–N3:
median 18.459 → 13.209 µs; p99 53.166 → 107.750 µs; batch
39,707 → 140,439 rows/s. The tail regression is real in this measurement;
improved throughput did not establish improved p99 or world performance. The
catalogue-read rework measurements below supersede that regression.

The refreshed core sample, now including names, opens in 11.806 ms with
2,359,296 bytes RSS delta. Hot median/p99 are 7.833/23.750 µs and batch
657,440 rows/s; seeded random median/p99 are 4.583/18.667 µs and batch
617,282 rows/s. The historical pre-name rework measurement was 2.950 ms and
1,048,576 bytes at open, and the eager baseline was 59.041 ms / 21,872,640 bytes.
Those historical samples and code differ; the JSON preserves them.
Old-reader synthetic figures (a different workload) were 10.291 µs / 531,994
rows/s with Cython and 12.750 µs / 530,437 rows/s with Python.

The following measurements use the public Python API, with a single matched hot
key and seeded random queries visiting every published sample key. Misses and
the default airport path are separate workloads in the JSON. Postal and airport
batch calls are grouped by their required country/scheme options. Plates here
cover every code/country assertion; format inference is measured separately.
Size estimates scale data artifacts only and add the measured sample catalogue
and metadata, so they do not model growth of the catalogue. Earlier repeated-US
query numbers remain historical records in the measurements JSON.

<!-- forward-measurements:start -->
| Family | Sample bytes / rows | Real vectors | Scalar median / p99 (µs) | Random median / p99 (µs) | Random batch rows/s | Estimated world bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| postal | 105,111 / 897 | 28 | 8.042 / 8.875 | 8.500 / 363.136 | 146,026 | 143,127,131 |
| airports | 75,947 / 213 | 33 | 7.666 / 13.000 | 8.167 / 12.958 | 394,943 | 7,219,281 |
| locode | 76,930 / 225 | 31 | 7.750 / 8.292 | 7.834 / 10.208 | 459,627 | 8,823,901 |
| phone | 70,425 / 389 | 29 | 4.542 / 4.833 | 5.750 / 6.917 | 411,426 | 10,075,099 |
| ip | 45,523 / 449 | 58 | 7.292 / 9.667 | 7.417 / 8.000 | 563,711 | 215,105,432 |
| plates | 48,499 / 521 | 36 | 4.834 / 5.083 | 5.167 / 17.833 | 246,194 | 4,570,923 |
| geocode | 210,397 / 101 | 51 | 7.875 / 13.584 | 8.334 / 42.583 | 367,764 | 11,846,553 |
<!-- forward-measurements:end -->

## Plates source limitation and remaining work

The requested normalized/plates_country release and vehicle-prior inputs were
absent. The plate sample uses read-only normalized/plates tables, the pinned
India state table and committed format rules, with the fallback recorded in its
manifest. plate_priors is explicitly omitted and that score term is disabled;
rank_basis is plate_evidence_without_vehicle_prior. The reduced sample retains
selected registration-unit evidence plus one entity association per code.
It does not claim the unavailable release's full prior ranking.

The builder supports a verified plate-country release when supplied. The
pipeline's future plates dataset table will replace this adapter without changing
the wire model. Complete real release ingestion and vehicle-prior ranking remain
unverified. Phone's real sample has country-only links; synthetic cases cover
regional/city links, and strict world handling of unlinked territories is untested.

The real names table is pending; the writer already accepts its tested canonical
alternate-name shape. Full-place names and scope="places" remain optional later
work. The new CLI, installer, MCP integration and Node/WASM host adapter are
later packages. Legacy Python modules and suites remain until package 5.
IP and postal world-size measurements are recorded below. Linux/Windows and
other Python versions were not run.

## Validation and boundaries

Full gates run before each local commit: cargo fmt --check;
cargo clippy --all-targets --all-features -- -D warnings; cargo test;
uv run pytest; uv run ruff check; uv run ruff format --check; uv run mypy.
The wasm target is also compile-checked. Old reader and pipeline tests remain
in the gate. Current rework checks and final counts are recorded after the
remaining ordered fixes.

Only worktree files and normal shared Git metadata were written. The real data
tree was read-only, build_data source was unchanged, and nothing was pushed,
published or uploaded. Disk use remained below the 4 GB additional-use budget,
with more than 5 GB free.

The format table below is generated by benchmarks/forward_sizes.py. Query
blocks exclude the separate evidence payload; “all compressed” includes it.
Neither column includes FST/container overhead or catalogue/metadata. The old
column counts complete legacy data shards. The pack column includes every
artifact and manifest. Historical speed/size estimates above predate this rework.

## Forward format measurements

<!-- forward-format:start -->
| Family | Old data-shard B/row | Query blocks B/row | All compressed B/row | Sample pack bytes | Estimated world bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| postal | 129.99 | 10.25 | 25.93 | 105,111 | 143,127,131 |
| airports | 403.32 | 15.42 | 65.99 | 75,947 | 7,219,281 |
| locode | 257.08 | 13.23 | 65.48 | 76,930 | 8,823,901 |
| phone | 266.83 | 2.07 | 19.06 | 70,425 | 10,075,099 |
| ip | 194.68 | 11.81 | 24.73 | 45,523 | 215,105,432 |
| plates | 654.10 | 25.88 | 29.65 | 48,499 | 4,570,923 |
<!-- forward-format:end -->

## Measured world exports

<!-- world-exports:start -->
| Family | Measured pack bytes | Peak RSS bytes | Seconds | Output deleted |
| --- | ---: | ---: | ---: | --- |
| ip | 94,643,648 | 1,086,291,968 | 233.533 | True |
| postal | 134,347,594 | 902,545,408 | 190.210 | True |
<!-- world-exports:end -->

The two authorised world measurements are complete; their outputs were deleted
and their exact manifests are retained under docs/measurements/. The measured
postal total exceeds the design's approximate size estimate: its supporting
catalogue is a substantial part of the complete pack. The measurements include
cold evidence, all supporting tables and notices. Per-family query-block gates
are separate from that complete-pack accounting. The IPv6 measurement counts
nonzero low address words; the format preserves them instead of assuming /64
alignment. Neither export qualifies a core world pack or the other families.

## Catalogue read measurements

<!-- catalogue-reads:start -->
| Catalogue read path | Median µs | p99 µs | Batch rows/s |
| --- | ---: | ---: | ---: |
| before | 13.291 | 120.875 | 144578.55712150357 |
| after | 7.25 | 18.667 | 298081.435803999 |
<!-- catalogue-reads:end -->

## Query performance rework (review fix 4)

Exact name rows are reused, and H3 cells are computed only for returned cities.
Fuzzy lookup uses bounded per-key counters, cached trigram cardinalities, a
minimum Dice overlap and prepared bit-parallel edit distance. It never truncates
potential matches before hard filters and population ranking. Property tests
compare both the candidate set and edit-distance result against exhaustive
reference implementations. A symbol-bearing Rust sampling loop is reproducible
with `python -m benchmarks.geocode_profile`; its native attribution is retained
in `docs/measurements/geocode-profile.txt`. Projection dominates the mixed exact,
ambiguous and fuzzy sample workload; Unicode normalization is retained unchanged.

Generate scale fixtures using `cargo run --release -p thereabouts-core --example
forward_scale -- ../.tmp/forward-scale` from `core`, then run
`python -m benchmarks.forward_scale`. They contain 7.8M single-address intervals
with gaps, split evenly between IPv4 and IPv6, and 90k cities/name keys in three
FST shards. The IP location dictionary is deliberately hot; random addresses
exercise the bounded decoded-block cache. Common synthetic name trigrams stress
fuzzy counting, including many legitimate candidates. These fixtures measure
search scale, not real-world compression or accuracy. Their generated binaries
remain uncommitted inside this worktree.

## Synthetic search scale

<!-- forward-scale:start -->
| Synthetic workload | Median / p99 (µs) | Batch rows/s |
| --- | ---: | ---: |
| ip | 139.667 / 313.293 | 7,374 |
| ip_gap | 3.084 / 4.500 | 2,724,780 |
| names_exact | 7.792 / 15.500 | 379,427 |
| names_random | 15.875 / 124.293 | 86,983 |
| names_fuzzy_common_grams | 11553.167 / 22356.124 | 83 |
| names_miss | 10.584 / 48.218 | 114,410 |
<!-- forward-scale:end -->

## All-rule plate inference

<!-- plates-rules:start -->
| All-rule inference | Median / p99 (µs) | Batch rows/s |
| --- | ---: | ---: |
| before (704 rules) | 83.166 / 205.750 | 15,167 |
| after (704 rules) | 27.500 / 155.333 | 67,086 |
<!-- plates-rules:end -->

Plate matching now uses one anchored RegexSet across exact and relaxed patterns
to select eligible rule ordinals before capture extraction and scoring. Original
rule order, exact-before-relaxed precedence and evidence remain unchanged. The
all-rule benchmark uses every committed base, extension, supplemental and
template rule, sample code assertions, the complete fixture country universe
and no vehicle priors. Its before/after results have identical evidence-inclusive
result digests over the same requests. This measures rule-count scaling, not
world code-table coverage or plate-country accuracy.
