# Thereabouts

Thereabouts adds geographic context to a place reference without a network
call or an API key. Give it a coordinate, an H3 cell, a town name, a postal
code, an airport code, a UN/LOCODE, a phone number, an IP address or a vehicle
plate. It returns the country, subdivision, city and timezone it belongs to,
with an explicit status when there is no answer or several. Queries run offline
against data you install once. One Rust core serves the Python and Node
libraries, the command line and an MCP server, and the same data is published
as an open Parquet dataset.

## What you can look up

| You have | Call | Data pack |
| --- | --- | --- |
| latitude and longitude | `reverse` | core |
| an H3 cell (resolution 0 to 8) | `h3` / `from_h3` / `fromH3` | core |
| a town or city name | `geocode` | core |
| a postal code and its country | `postal` | postal |
| an airport code (IATA, ICAO, GPS, local) | `airport` | airports |
| a UN/LOCODE | `locode` | locode |
| an international phone number | `phone` | phone |
| an IPv4 or IPv6 address | `ip` | ip |
| a vehicle registration plate | `plate` | plates |

Geocoding finds towns and cities, not street addresses. A phone result is a
calling-code prefix, an IP result is the provider's location for the range, and
a plate result is format evidence, not a vehicle register.

## Install

~~~sh
pip install thereabouts            # Python 3.11+, installs the thereabouts command
pip install "thereabouts[mcp]"     # adds the MCP server
npm install thereabouts            # Node 22 or 24, ESM, WebAssembly, no compiler needed
~~~

The npm package also provides `npx thereabouts`, the same command line. Nothing
is bundled: you install data explicitly, and no lookup ever downloads anything.

## Install data

~~~sh
thereabouts data install core postal airports
thereabouts data list
~~~

Packs download from this repository's GitHub Releases, are checked by SHA-256
and are activated atomically. While the repository is private, set
`THEREABOUTS_RELEASE_TOKEN` (or `GITHUB_TOKEN`) to a token with read access to
it. `--from DIR_OR_URL` installs from a local directory or another URL, and
`--data-dir` or `THEREABOUTS_DATA` chooses the store. See
[data installation](docs/clients/data-install.md).

| Pack | Answers | Download | Unpacked |
| --- | --- | ---: | ---: |
| `core` | reverse, H3 cells, city names, timezones | 460 MB | 2.9 GB |
| `postal` | postal codes | 31 MB | 42 MB |
| `ip` | IPv4 and IPv6 addresses | 34 MB | 42 MB |
| `airports` | airport codes | 3.3 MB | 6.4 MB |
| `locode` | UN/LOCODE | 3.3 MB | 6.5 MB |
| `phone` | phone calling-code prefixes | 1.2 MB | 4.4 MB |
| `plates` | vehicle plate formats | 1.2 MB | 3.8 MB |

Sizes are from the world build of release 2026.10. Forward packs work alone;
with `core` installed they also return the canonical city and timezone.

## Quick start

Python:

~~~python
from thereabouts import Geocoder

with Geocoder() as geo:
    r = geo.reverse(lat=48.8566, lon=2.3522)
    print(r.status, r.city.name, r.country.code, r.timezone)
    print(geo.geocode("Paris", country="FR").to_dict())
    print(geo.postal("75001", country="FR").to_dict())
    print(geo.airport("CDG").to_dict())
~~~

Node:

~~~js
import { Geocoder } from "thereabouts";

const geo = await Geocoder.open();
try {
  const r = await geo.reverse({ lat: 48.8566, lon: 2.3522 });
  console.log(r.status, r.city?.name, r.country?.code, r.timezone);
  console.log(await geo.geocode("Paris", { country: "FR" }));
  console.log(await geo.airport("CDG"));
} finally {
  await geo.close();
}
~~~

Command line:

~~~sh
thereabouts reverse --lat 48.8566 --lon 2.3522 --json
thereabouts geocode "Paris" --country FR
thereabouts airport CDG
thereabouts reverse points.csv --csv      # batch: input columns kept, results appended
~~~

Results use the same fields in every client. Check `status` first: `matched`,
`ambiguous` (ranked `candidates`), `not_found`, `invalid_input` or
`unsupported_granularity`. Add evidence to see why an answer or a miss happened.
Guides: [Python](docs/clients/python.md), [Node](docs/clients/node.md),
[command line](docs/clients/cli.md).

## MCP server and agent skill

`thereabouts mcp` runs a read-only MCP server on stdio with one tool per lookup
plus `describe` for the dataset tables; setup for Claude Desktop, Claude Code and
other clients is in [the MCP guide](docs/clients/mcp.md). The skill in
[`skills/thereabouts`](skills/thereabouts/SKILL.md) teaches an agent to pick the
right tool, read statuses correctly and answer questions about many places with
DuckDB over the dataset.

## Dataset

The same data is available as versioned Parquet tables (places, cells, names,
postal codes, airports, IP ranges and more) with provenance and licence notices,
restored by `thereabouts data install dataset` or read straight from the
release. See the [dataset guide](docs/dataset/README.md) and the
[data dictionary](docs/dataset/DATA_DICTIONARY.md).

## Licences

Code is MIT, see [LICENSE](LICENSE). Data carries its own notices: the dataset
is ODbL 1.0 with per-source attribution, and the plates data derives from
CC BY-SA sources. Details are in [docs/licenses.md](docs/licenses.md).

## Status

The first public release is in preparation. Packages and data are not yet
published, so the install commands above apply once the release is out. Until
then, build from this checkout as described in [CONTRIBUTING.md](CONTRIBUTING.md).

## Roadmap

Native coordinate frames (UTM/MGRS, geohash, plus codes, ECEF, NMEA and WKT) are
developed on a branch for a later release.

## More

- [Examples](examples/README.md)
- [Documentation index](docs/README.md)
- [Contributing](CONTRIBUTING.md)
