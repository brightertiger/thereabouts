# Postal and airport packs

Postal and airport packs support offline code lookups. Their format and result
semantics are specified in [pack-format.md](pack-format.md), and current sizes
and measurements are in [../clients/status.md](../clients/status.md).

```python
from thereabouts import Geocoder

with Geocoder(data_dir="/path/to/store") as geo:
    result = geo.postal("75001", country="FR")
    print(result.to_dict())
    airport = geo.airport("CDG", scheme="iata")
    for candidate in airport.candidates:
        print(candidate.country, candidate.city)
```

Postal input requires a country and retains leading zeros. Airport defaults to
IATA/ICAO search; scheme can be iata, icao, gps, local or ident. Country narrows
ambiguous codes and is required for local codes. Invalid input returns
`status: invalid_input` with a hint. Ambiguity returns ranked candidates and
fills flat fields only where all candidates agree. Request `evidence=True` for
source details; there is no invented precision or distance.

Use `Geocoder(pack="/path/to/postal-pack")` for a standalone pack, or
`Geocoder(packs={"core": core_path, "postal": postal_path, "airports": airport_path})`
for explicit paths. Forward manifests pin the core dataset version and catalogue
digest. Matching core supplies canonical city and timezone detail; standalone
forward packs retain their own fields and leave unavailable detail null.
Lookups never install data.

Install locally built release archives and query them with:

```sh
thereabouts --data-dir /path/to/store data install core postal airports --from /path/to/release --yes
thereabouts --data-dir /path/to/store postal 75001 --country FR
thereabouts --data-dir /path/to/store airport CDG --scheme iata
thereabouts --data-dir /path/to/store data verify --full
```

The source directory contains an index.json and pack archives, as specified in
[../clients/cli.md](../clients/cli.md). The pipeline release stages call the Rust writer; see
[../pipeline/README.md](../pipeline/README.md). Historical Python/Cython code-pack timings
are retained in CLIENT_CODE_MEASUREMENTS.json and do not describe the current
Rust client.
