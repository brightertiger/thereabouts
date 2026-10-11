# Python client

Offline geographic context for Python 3.11+. The wheel is abi3 and contains the
shared Rust core; NumPy is the only mandatory dependency. No data is bundled.

~~~sh
pip install thereabouts
thereabouts data install core postal airports     # see data-install.md
~~~

Add the MCP server with `pip install "thereabouts[mcp]"`; see [mcp.md](mcp.md).

## Open a geocoder

~~~python
from thereabouts import Geocoder

with Geocoder() as geo:                       # discovers the installed store
    print(geo.reverse(lat=48.8566, lon=2.3522).to_dict())
~~~

| Call | Opens |
| --- | --- |
| `Geocoder()` | the store found through `THEREABOUTS_DATA`, then the platform data directory |
| `Geocoder(data_dir="./store")` | that store |
| `Geocoder("/path/to/pack")` | one pack, standalone |
| `Geocoder(packs={"core": "...", "postal": "..."})` | explicit packs from one dataset |
| `Geocoder(..., verify=True)` | the same, with full checksum and structure verification |

Opening checks manifests, inventory and sizes. `close()` is idempotent, and
results remain usable after it. Keep pack files unchanged while open.

## Lookups

Keyword arguments name every option. Every lookup accepts `evidence=True`.

~~~python
geo.reverse(lat=48.8566, lon=2.3522)
geo.from_h3("881fb46625fffff")                    # ancestor at resolution 0 to 8
geo.geocode("Paris", country="FR", limit=5)       # also subdivision=, prefer="population"
geo.postal("75001", country="FR")                 # country is required
geo.airport("CDG", scheme="iata")                 # iata, icao, gps, local, ident; country=
geo.locode("FRPAR")                               # or a 3-character code with country=
geo.phone("+33 1 2345 6789")                      # leading + required; country=
geo.ip("8.8.8.8")
geo.plate("AB-123-CD", country="FR")              # series=
~~~

Each forward verb needs its pack: `postal`, `airports`, `locode`, `phone`, `ip`
or `plates`. Geocoding needs `core` and finds towns and cities, not street
addresses. Country and subdivision are hard filters. With `core` installed, a
forward result also carries the canonical city and timezone; a standalone
forward pack keeps its own source fields and leaves city and timezone empty.

The module-level `thereabouts.reverse(lat=, lon=)` opens the default store on
first use.

## Results

A `Result` is a frozen dataclass with `status`, `kind`, `match`, `point`, `cell`,
`city`, `state`, `country`, `timezone`, `distance_band`, `rank_basis`,
`candidates` and optional `evidence` and `hint`. `to_dict()` gives the JSON form
shared with Node and the command line.

| `status` | Meaning |
| --- | --- |
| `matched` | one answer; read `match` and `distance_band` for how exact it is |
| `ambiguous` | ranked `candidates`; the flat fields hold only what they share |
| `not_found` | a normal miss, such as open water; evidence says why |
| `invalid_input` | the query cannot be interpreted; `hint` names the fix |
| `unsupported_granularity` | a street address or finer |

A `matched` reverse result can still be approximate: `nearest_distant` means the
city is the nearest settlement and more than the distant threshold away.

## Batches

~~~python
points = [{"lat": 48.8566, "lon": 2.3522}, {"lat": 1.3521, "lon": 103.8198}]
for result in geo.reverse_many(points):           # in order, one at a time
    print(result.country.code if result.country else None)

import numpy as np
cols = geo.reverse_columns(np.array([48.8566, 1.3521]), np.array([2.3522, 103.8198]))
~~~

`reverse_many` takes mappings with `lat` and `lon`, or objects with those
attributes, and rejects bare coordinate pairs. `reverse_columns` returns
dictionary-encoded string columns, fixed-width numeric arrays and validity masks;
candidates are omitted. Forward verbs have `*_columns` forms, such as
`postal_columns` and `ip_columns`.

## Errors

Invalid query values return `status="invalid_input"`. Data, discovery and
lifecycle failures raise subclasses of `GeocoderError`, each with a stable `code`.

| Exception | Code |
| --- | --- |
| `DataNotInstalledError` | `data_not_installed`; the message names the install command |
| `IncompatibleDataError` | `incompatible_data` |
| `CorruptPackError` | corrupt checksum, record or inventory |
| `ClosedGeocoderError` | `closed_geocoder` |
| `PackNotFoundError` | a selected pack is missing |

Nothing here downloads data. Install it with the command line, then open the store.

## Command line

The `thereabouts` console installs with the package. Its grammar and exit codes
are in [cli.md](cli.md). Table, JSON, NDJSON and CSV output are shared with Node.
