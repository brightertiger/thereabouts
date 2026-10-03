# Postal and airport packs

> The format descriptions remain current. Historical `build_data` commands in
> this document refer to the retired implementation. Current build instructions
> are in [DATA_PIPELINE.md](DATA_PIPELINE.md); release stages arrive in package 4.

Postal and airport packs provide offline exact-code lookups with original source
observations and canonical geographic context. Each includes its own minimal
place catalogue and attribution. Install either without a reverse pack:

```python
from thereabouts.client import Geocoder

with Geocoder("/path/to/postal-pack") as geo:
    result = geo.postal("00100", country="AA")
    print(result.to_dict())

with Geocoder(data_dir="/path/to/store", packs=["postal", "airports"]) as geo:
    airport = geo.airport("ZZZ", scheme="iata")
    for candidate in airport.candidates:
        print(candidate.place, candidate.observations)
```

These example codes/countries are synthetic, not claims about real locations.
Explicit local paths can be combined with
`Geocoder(packs={"reverse": reverse_path, "postal": postal_path, "airports": airport_path})`.
All selected packs must share their catalogue epoch, golden snapshot, policy
and H3 version; mismatches raise `IncompatibleDataError`. `info()["packs"]` and
`info()["cache"]` are keyed by family. The configured decoded-cache byte budget
is divided among the selected packs and shared by places and immutable decoded
code candidates. Lookups do not install or download data.

Postal input is a string, retaining leading zeros, and requires country.
Airport input requires `scheme="iata"|"icao"|"ident"|"gps"|"local"`; local codes
also require country. Optional country scopes other airport schemes by the
source country. Scheme is never inferred. Missing context raises
`ContextRequiredError`, a subclass of `InvalidInputError`.

Source editions are all retained with no precedence. Postal observations with
the same canonical city form one candidate; observations lacking a city keep a
source-qualified identity. Distinct city candidates produce `ambiguous`, a null
`selected` and all candidates. `require_one()` raises on ambiguity. Airport
identity is its source airport identity, independent of its municipality label
or associated city. Closed sites, heliports and unlocated observations remain
queryable. No first-row choice or location correction is made.

Every candidate carries immutable `observations`, including source release,
licence, original labels, fields, country disagreement, methods and per-source
H3 reference. `SourcePlace` is the airport source entity; canonical geographic
slots are `Place` records. Conflicting aggregate fields become null, while all
observations remain available. A code result is `matched` even when its source
entity has no spatial location. `not_found` means the exact key was absent.
Postal accuracy codes remain source fields, not invented metre estimates.

Normalization is stored in the pack. The current exporter trims ASCII edge
whitespace and uppercases ASCII letters, additionally removing internal spaces
for CA/GB postal keys. It retains punctuation and leading zeros. See the complete
byte/semantic contract in [SERVING_FORMAT.md](SERVING_FORMAT.md).

## Export, install and query

Package 4 will expose pack export through the pipeline release stages. The
ported export helpers are exercised on synthetic fixtures. For already-built
local packs, install and query with:

```sh
.venv/bin/python -m thereabouts --data-dir /path/to/store data install \
  --from /path/to/new-postal-pack --sha256 TRUSTED_MANIFEST_SHA256 --offline
.venv/bin/python -m thereabouts --data-dir /path/to/store postal 00100 --country AA
.venv/bin/python -m thereabouts --pack /path/to/new-airport-pack airport ZZZ --scheme iata
.venv/bin/python -m thereabouts --data-dir /path/to/store data verify --family postal --full
```

`resolve postal CODE --country CC`, `resolve airport CODE --scheme SCHEME` and
`explain` support the same explicit context. `data list` includes all installed
families. The same pinned URL installer works for these packs; tests use local
sources, and no release has been hosted. See [DATA_INSTALLATION.md](DATA_INSTALLATION.md).
The first API supplies scalar code resolvers; coordinate/H3 batch and column APIs
remain available when a reverse pack is selected.

The exporter verifies source hashes/schemas and existing joined assignments,
recovers stored methods, preserves source row multiplicity and builds only the
needed catalogue closure. Source rows without a queryable code are counted in
`unindexed_rows`. Per-shard checkpoints resume verified files; completed output
is immutable and repeating the same inputs verifies it without rewriting it.
Changed exporter code—including the new code-family modules—changes serving
fingerprints. This does not change original pipeline hashes or require a spatial
rebuild. Whole-world code exports and independent geographic quality evaluation
have not been run; synthetic fixture parity is construction evidence only.

## Measured synthetic fixtures

[CLIENT_CODE_MEASUREMENTS.json](CLIENT_CODE_MEASUREMENTS.json) records the small
sample, source identities, pack inventories and timings on Apple M2 / 8 GiB /
macOS 27 / CPython 3.12.8. Seven postal observations and four airport observations
exercise repeated editions, collisions, leading zeros, source-country disagreement,
unlocated records and closed sites. This is construction evidence, not a world
capacity or geographic quality benchmark.

* postal: 10,917 installed bytes; export 0.066 s; warm two-candidate lookup median 3.042 µs, p99 3.958 µs.
* airports: 16,739 installed bytes; export 0.074 s; warm two-candidate lookup median 2.625 µs, p99 6.917 µs.

Combined peak process RSS was 85,409,792 bytes. Timings exclude JSON serialization; the first query primes the bounded candidate cache. The report also reruns the larger reverse benchmark: shuffled warm median **10.291 µs Cython / 12.750 µs Python**, column throughput **531,994 / 530,437 points/s**. Both requested reverse targets remain met.

Reproduce with `python -m benchmarks.code_packs --output .cache/new-code-sample` from the worktree using the local environment and temporary-directory settings in `CLIENT_STATUS.md`. No main-checkout golden data was read.
