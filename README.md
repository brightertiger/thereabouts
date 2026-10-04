# Thereabouts

Thereabouts adds geographic context to coordinates, H3 cells, town and city
names, postal codes, airports, UN/LOCODEs, telephone numbers, IP addresses and
vehicle plates. Queries run offline against explicitly installed data.

The product has three parts:

- **Dataset:** versioned Parquet tables with canonical places, source observations,
  H3 cell assignments, provenance and licence notices.
- **Clients:** Python 3.11+, Node 22/24 and a command line, backed by one Rust core.
  Small binary packs serve queries without loading a world database into memory.
- **Pipeline:** explicit, resumable acquisition and geographic stages, followed
  by dataset preparation and pack export. It is maintained in this repository.

This is the **0.1.0 release draft**. The owner has not published these artifacts.
The existing PyPI/npm 0.0.1 placeholders do not contain this client.
Code is released under the [MIT licence](LICENSE); data notices are separate, see [docs/licenses.md](docs/licenses.md).

## Install and add data

From a checkout with Rust 1.99 and Python 3.11+:

~~~sh
python -m pip install .
thereabouts --version
thereabouts --data-dir ./store data install core postal airports \
  --from /path/to/release --yes
~~~

Alternatively install a wheel produced by the Python workflow. A local release
directory contains index.json and family tar archives. The default public
release endpoint is still a placeholder; select --from or THEREABOUTS_RELEASE_URL.
No import, lookup or missing-data error downloads anything.

For Node, build a package from this checkout (Rust's wasm32-unknown-unknown
target and wasm-bindgen-cli 0.2.129 are required):

~~~sh
cd clients/node
npm ci --ignore-scripts
npm pack
npm install /path/to/thereabouts-0.1.0.tgz
~~~

The installed npm package includes WASM; consumers need no Rust compiler.
Both clients read the same store and dataset-version pin.

## Python

~~~python
from thereabouts import Geocoder

with Geocoder(data_dir="./store") as geo:
    result = geo.reverse(lat=48.8566, lon=2.3522)
    print(result.status, result.city, result.country, result.timezone)
    print(geo.geocode("Paris", country="FR").to_dict())
    print(geo.postal("75001", country="FR").to_dict())
    print(geo.airport("CDG").to_dict())
~~~

Use keyword arguments for coordinates. reverse_many streams named coordinate
objects; reverse_columns accepts NumPy arrays. Results are frozen dataclasses.
[Python details](clients/python/thereabouts/README.md).

## Node

~~~js
import { Geocoder } from "thereabouts";

const geo = await Geocoder.open({ dataDir: "./store" });
try {
  console.log(await geo.reverse({ lat: 48.8566, lon: 2.3522 }));
  console.log(await geo.geocode("Paris", { country: "FR" }));
  for await (const result of geo.reverseMany([{ lat: 48.8566, lon: 2.3522 }])) {
    console.log(result.country);
  }
} finally {
  await geo.close();
}
~~~

Results use the same snake_case JSON fields as Python and the CLI.
[Node details](clients/node/README.md).

## Command line

~~~sh
thereabouts --data-dir ./store reverse --lat 48.8566 --lon 2.3522 --json
thereabouts --data-dir ./store geocode "Paris" --country FR
thereabouts --data-dir ./store reverse points.csv --csv
thereabouts --data-dir ./store data verify --full
~~~

Explicit verbs select the input type. Tables are the TTY default; piped output
defaults to NDJSON. CSV/NDJSON batches preserve input columns and append results.
The optional Python MCP extra exposes the same lookup verbs.
[Normative grammar and store contract](docs/clients/cli.md).

## Semantics and coverage

Geocode finds towns and cities, not street addresses. Ambiguous queries retain
the flat fields shared by all ranked candidates. Reverse uses the dataset's
stored H3 ancestor and method; nearest results report a distance band, not an
invented exact distance. Missing or unsupported input has an explicit status.
Evidence is optional and never replaces provenance in the dataset.

Core includes reverse and city-name lookup. Each forward family is a separate
pack. Matching core data adds canonical city and timezone detail; standalone
forward packs retain their own source fields. Coverage depends on the selected
release: committed samples and the MY/SG release proof are subsets.

## Build and release

Start with [pipeline operations](docs/pipeline/README.md),
[the dataset](docs/dataset/README.md), [pack format 2.2](docs/dataset/pack-format.md),
[client status and measurements](docs/clients/status.md), and
[release engineering](docs/clients/release.md).
The [documentation index](docs/README.md) lists every current document.
The [0.1.0 changelog](CHANGELOG.md) describes the migration from the retired readers.
Data notices are separate from the MIT code licence.
