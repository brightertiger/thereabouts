# PyOfflineGeocoder

An offline Python 3.11+ reference engine. It returns country/admin1 containment
against Natural Earth polygons at the original coordinate, plus the nearest
GeoNames cities1000 settlement and its spherical distance. These are cartographic
snapshot answers, not addresses or municipal boundaries.

## Install and build the data

From this checkout, using [uv](https://docs.astral.sh/uv/):

```sh
uv sync
uv run python -m build_data --output data/world
```

The builder checks pinned SHA256 hashes before reading sources. Existing archives
can be placed in `data/cache/{countries,admin1,land,cities1000}.zip`. GeoNames' daily
URL changes: if its hash no longer matches, supply the frozen **2026-10-01** archive
from an existing cache. The builder never silently updates a pin. An existing
output directory is not overwritten. `data/` is excluded from git.

The engine is also installable with `pip install .`; its only runtime dependencies
are NumPy, Shapely and SciPy. The source-checkout builder additionally needs the
`dev` dependency group. No import, constructor or lookup downloads data.

```python
from pyofflinegeocoder import Geocoder

with Geocoder("data/world") as geocoder:
    result = geocoder.reverse(50.85045, 4.34878)
    print(result.country, result.admin1)
    print(result.nearest_place, result.place_status)
    for result in geocoder.reverse_many([(52.37, 4.9), (49.61, 6.13)]):
        print(result)
```

Alternatively set `PYOFFLINEGEOCODER_DATA` to a pack directory and use
`pyofflinegeocoder.reverse(lat, lon)`. Missing data raises `DataNotInstalledError`
with the explicit build command.

## Meaning of nearest place

The nearest record is selected globally using a spherical metric (radius
6,371.0088 km), including cross-border settlements. It retains the source's feature
and administrative codes; it does not determine your containing country/admin1.
The catalog omits small villages and includes source-listed administrative seats
and populated-place sections. The default cutoff is **50 km**; pass
`max_place_distance_km=None` for unlimited search on mapped terrestrial points,
or `include_place=False` to disable it. Outside the terrestrial mask there is no
place result. Shared boundaries and overlapping polygons return candidates with
`ambiguous` status. Regional coverage gaps remain distinct from mapped sea.

## Data and validation

[Natural Earth 5.1.1](https://www.naturalearthdata.com/about/terms-of-use/) countries,
admin1 and land at 1:10 million are public domain. Made with Natural Earth.
[GeoNames cities1000](https://download.geonames.org/export/dump/readme.txt), frozen
2026-10-01, is [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Each pack includes provenance, hashes, transformation logs and `DATA_LICENSES.txt`.
Shapely uses GEOS; this reference stack is not the proposed permissive native runtime.

```sh
uv run pytest
PYOFFLINEGEOCODER_WORLD_DATA=data/world uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy
uv run python -m benchmarks.runtime --data data/world
```

The first test command uses the included **0.85 MB Benelux fixture**; world tests
require the environment variable. To reproduce a build and timings together, use
`uv run python -m benchmarks.runtime --build --data data/new-world`.
See [reference policies and measured limits](docs/REFERENCE_ENGINE.md) and
[benchmark results](benchmarks/results.json).
