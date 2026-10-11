# Thereabouts for Python

Offline geographic context through the shared Thereabouts Rust core: coordinates,
H3 cells, town names, postal codes, airports, UN/LOCODEs, phone numbers, IP
addresses and vehicle plates. Python 3.11+; abi3 wheels; NumPy is the only
mandatory dependency. The code is MIT licensed.

~~~sh
pip install thereabouts            # add the MCP server with: pip install "thereabouts[mcp]"
thereabouts data install core postal airports
~~~

No data is bundled. `data install` reads the project's GitHub releases by
default (set THEREABOUTS_RELEASE_TOKEN or GITHUB_TOKEN while the repository is
private), or an explicit local release directory or URL with `--from`;
`data install dataset` restores the Parquet dataset. Opening and querying never
download data. The families are core, postal, airports, locode, phone, ip and
plates; core is the largest (about 460 MB to download).

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
with Node. Guides in the repository: [Python client](https://github.com/brightertiger/thereabouts/blob/main/docs/clients/python.md),
[installing data](https://github.com/brightertiger/thereabouts/blob/main/docs/clients/data-install.md),
[command line](https://github.com/brightertiger/thereabouts/blob/main/docs/clients/cli.md) and
[MCP server](https://github.com/brightertiger/thereabouts/blob/main/docs/clients/mcp.md).

The MCP server also describes the dataset. Its read-only describe tool and the
thereabouts://dictionary resources (JSON, and /markdown) serve the data
dictionary of the installed core pack, or the copy packaged with this client.
The repository's [skills/thereabouts](https://github.com/brightertiger/thereabouts/blob/main/skills/thereabouts/SKILL.md) teaches agents to use both.
