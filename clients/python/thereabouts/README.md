# Thereabouts for Python

Offline geographic context through the shared Thereabouts Rust core.
Python 3.11+; abi3 wheels; NumPy is the only mandatory Python dependency.
Version 0.1.0 is a release draft, not yet published. The PyPI 0.0.1 placeholder
is superseded only when the owner publishes 0.1.0. Code licensing is pending.

Install a release wheel or build with Rust 1.99 using:

~~~sh
python -m pip install .
thereabouts --data-dir ./store data install core postal airports --from ./release --yes
~~~

No data is bundled. The default release URL is a placeholder; use an explicit
local release directory or configured release URL. Opening and querying never
download data.

~~~python
from thereabouts import Geocoder

with Geocoder(data_dir="./store") as geo:
    result = geo.reverse(lat=48.8566, lon=2.3522)
    print(result.to_dict())
    print(geo.from_h3("881fb46625fffff"))
    print(geo.geocode("Paris", country="FR", limit=5))
    print(geo.postal("75001", country="FR"))
    print(geo.airport("CDG", scheme="iata"))
    print(geo.locode("FRPAR"))
    print(geo.phone("+33 1 2345 6789"))
    print(geo.ip("8.8.8.8"))
    print(geo.plate("AB-123-CD", country="FR"))
~~~

Install the corresponding family before a forward lookup. Core also provides
city-name lookup: **finds towns and cities by name; street addresses are not
supported**. Country and subdivision filters are hard filters.
prefer="population" explicitly selects the population ranking.

reverse_many accepts mappings with lat/lon or objects with those attributes,
yielding results in order. It rejects bare coordinate pairs.
reverse_columns(lat, lon) accepts NumPy arrays and returns dictionary-encoded
string columns, fixed-width numeric arrays and validity masks. Candidates are
omitted from columnar output; reverse never has candidates.

Geocoder("/path/to/pack") opens one pack. Geocoder(packs={"core": "...",
"postal": "..."}) selects explicit packs; verify=True requests full verification.
Geocoder() discovers data_dir, THEREABOUTS_DATA, then the platform user-data
directory. The module-level reverse(lat=, lon=) lazily opens this default store.
close() is idempotent.

Result objects are frozen and remain usable after close. Fields are status,
kind, match, point, cell, city, state, country, timezone, distance_band,
rank_basis and candidates, plus optional evidence. Ambiguity retains common
flat fields and ranked candidates. Invalid query values return invalid_input;
data/discovery/lifecycle failures raise exceptions with stable code strings:
DataNotInstalledError, IncompatibleDataError, CorruptPackError,
ClosedGeocoderError, PackNotFoundError, WriterError and WriterInputError,
all derived from GeocoderError. Missing data names the exact install command.

The thereabouts console provides reverse, h3, geocode, postal, airport, locode,
phone, ip, plate, data management, info and optional MCP. Install the mcp extra
to run thereabouts mcp. Table, JSON, NDJSON and CSV output share Rust logic
with Node. See the repository's docs/clients/cli.md and docs/dataset/pack-format.md for the
normative contracts, and docs/clients/status.md for coverage and measurements.
