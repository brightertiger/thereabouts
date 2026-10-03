# Thereabouts

The current Python API uses the Rust core: `from thereabouts import Geocoder`.
It reads installed format-2 core packs and format-2.1 forward packs without
implicit downloads. The `thereabouts` console exposes explicit lookup verbs,
batch reverse lookup and transactional data management. Optional MCP tools
return the same result JSON.

Start with the [command and data-store contract](docs/CLI.md) and the
[Python API, measurements and qualification](docs/CLIENT_STATUS.md).
The current Node/WASM binding is the next work package; the retained
[Node reader](clients/node/README.md) describes the older format-1 client.
Nothing has been published.

```python
from thereabouts import Geocoder

with Geocoder("tests/fixtures/packs/core-sample") as geo:
    print(geo.reverse(lat=50.8503, lon=4.3517).to_dict())
```

## Original runtime retained during pipeline integration

The API, examples and measurements below are historical first-table-format
documentation. They do not describe the current top-level Python API or CLI.
The retained code and old clients remain for pipeline compatibility until the
scheduled cleanup; use the current documentation linked above.

Give a latitude/longitude, get city, state and country, entirely offline.
Python 3.11+; runtime dependencies are **H3 and NumPy only**.

```python
from thereabouts import Geocoder

with Geocoder("data/h3-world") as geocoder:
    print(geocoder.reverse(52.37, 4.9))
    # Location(city='Amsterdam', state='Noord-Holland',
    #          country='Netherlands', country_code='NL')
    locations = list(geocoder.reverse_many([(50.85, 4.35), (49.61, 6.13)]))
```

`Location` is frozen and slotted. Each field is `str | None`; the whole result is
`None` over ocean or absent data. `info()` returns provenance and build policy.
Alternatively set `THEREABOUTS_DATA` and call `thereabouts.reverse`.
Explicit paths take precedence; missing data raises `DataNotInstalledError`.
Imports, opening and lookups never download data.

## One table lookup

Queries map to **H3 resolution 8**, then search the cell's logical ancestors in a
combined mmap table. Uniform subtrees collapse to coarser cells, preserving exact
equivalence to a flat table labelled at every resolution-8 centre. Country/state
come independently from Natural Earth polygons at that centre; overlapping
identities choose the lexically smallest source ID in each layer.

City is the nearest eligible GeoNames settlement within **50 km**, including
across borders. The current-settlement allowlist is **PPL, PPLA, PPLA2, PPLA3,
PPLA4, PPLA5, PPLC, PPLF, PPLG, PPLL, PPLR, PPLS, STLMT**. Sections (`PPLX`),
historical (`PPLCH`, `PPLH`), abandoned (`PPLQ`) and destroyed (`PPLW`) places are
excluded, as are unknown codes. The rule follows the [GeoNames code list](https://www.geonames.org/export/codes.html)
and is recorded in both reference and table manifests.

Lower Manhattan `(40.7128, -74.0060)` returns **New York City**; central Tokyo at
its catalogue point `(35.6895, 139.6917)` returns **Tokyo**. At
`(35.6762, 139.6503)`, Eifuku is removed but **Asagaya-minami** still wins because
GeoNames labels it `PPL` (ID 1865090). There are no city-name exceptions.
These are snapshot settlement labels, not municipal boundaries or addresses.

The mask includes Natural Earth land or country coverage, inland water, ice and
Antarctica; admin1 alone cannot create a row. Missing country/state/city fields
remain `None`. There are no runtime polygon or nearest-neighbour searches.
The owner accepts resolution-8 centre quantization.

## Final-pack measurements

Against the source oracle at the **original point**, 100,000 samples per workload:

| Workload | Country mismatch | State mismatch | City mismatch | No row |
| --- | ---: | ---: | ---: | ---: |
| Area-uniform land | 0.083% | 0.212% | 0.763% | 57 |
| Within 5 km of a uniformly selected settlement, on land | 0.235% | 0.606% | 5.212% | 169 |

These measure quantization against the same sources, including missing labels;
they do not measure independent geographic truth or population-weighted accuracy.

Apple M2 / macOS arm64 / CPython 3.12.8, warm OS cache; decimal MB:

| Measurement | Result |
| --- | ---: |
| Complete world table / ZIP | 53.06 / 21.35 MB |
| Combined build plus full verification | 687.93 s |
| Warm open median / first query excluding open | 0.837 / 1.262 ms |
| Scalar median / p99 | 13.54 / 241.33 µs |
| Single-point vector baseline median / p99, same final pack | 74.33 / 91.00 µs |
| Public batch throughput, including H3 and result objects | 436,159 points/s |
| Runtime peak RSS, including harness | 101.91 MB |

The build enumerated 691,776,122 centres and directly labelled 40,319,034
unresolved leaf centres, plus certificate midpoint work. Source-pack creation and
ZIP time are excluded from build timing. Runtime uses 10,000 saved land points;
each scalar path has its own fresh instance and 1,000 warmup calls. Cold-cache and
other-platform measurements were not run. The three reports identify the same
final pack by manifest hash: [accuracy](benchmarks/accuracy.json),
[runtime](benchmarks/runtime.json), [build size](benchmarks/build.json).

## Build and validate

The wheel (`pip install .`) contains the engine. Build tools and tests run from
this checkout with the `dev` dependency group:

```sh
uv sync
uv run python -m benchmarks.build_size --reference data/reference --data data/h3-world
uv run python -m benchmarks.accuracy
uv run python -m benchmarks.runtime
uv run pytest
THEREABOUTS_WORLD_DATA=data/h3-world uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy
```

The build-size benchmark constructs and verifies the table, and writes its one
result file. For a plain build use
`uv run python -m build_data --reference data/reference --output data/h3-world`.
The reference source pack is **data/reference**; the exported table is
**data/h3-world**, which is committed to this repository so a clone can run
lookups without building. Existing outputs are not overwritten: use fresh paths or remove
previous generated outputs before rebuilding. The reference pack is created if
absent. Retain pinned source archives in `data/cache`: GeoNames' daily URL may no
longer serve the frozen **2026-10-01** snapshot. A hash mismatch is an error.
Accuracy saves reproducible runtime input under `data/benchmarks/points.npy`.
Explicit full verification is `uv run python -m build_data.verify data/h3-world`.

The offline fixtures occupy **2.18 MB** and retain the original Benelux region.
Tests brute-force **all 554,631 resolution-8 centres**, comparing the reference,
builder certificates, and both scalar and batch table lookup. The
[design note](docs/DESIGN.md) documents the format, exact-equivalence proof,
lifecycle and fixture rebuild commands. [Evaluation](docs/EVALUATION.md) records
measurement details and limits.

`reverse_many` preserves order with bounded read-ahead of 4,096 pairs. Inputs must
be finite real numbers within WGS84 latitude/longitude bounds; strings and
booleans are rejected. Closing invalidates subsequent calls and buffered iterators.

Natural Earth 5.1.1 is public domain. Made with Natural Earth.
GeoNames cities1000, frozen 2026-10-01, is CC BY 4.0. Each pack includes source URLs,
hashes, attribution and `DATA_LICENSES.txt`; filtering and hierarchy compression
are recorded transformations.
