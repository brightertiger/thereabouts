# Thereabouts command and store contract

This is the normative package-3 grammar for the Rust CLI and the later Node
command tree. **Implementation is incomplete:** native store transactions and
the new MCP verbs are available; the console command still runs the legacy
interface. The clap command runner, HTTP transport and command examples below
await offline dependency sources. See [CLIENT_STATUS.md](CLIENT_STATUS.md).

## Commands

No verb guesses the input domain. Options shown below belong to their command;
global options may appear before or after a command.

| Command | Arguments and options | Result |
| --- | --- | --- |
| reverse | --lat LAT --lon LON | Geographic context at a coordinate |
| reverse | FILE or -; --lat-col COLUMN --lon-col COLUMN | CSV/NDJSON stream |
| h3 | CELL | Stored ancestor at resolutions zero through eight |
| geocode | TEXT; --country CC --subdivision CODE --limit N --prefer population | Towns and cities |
| postal | CODE --country CC | Postal-code context; country is required |
| airport | CODE; --scheme iata\|icao\|gps\|local\|ident | Airport context |
| locode | CODE | Five-character country/location code |
| ip | ADDRESS | IPv4 or IPv6 literal |
| phone | NUMBER; --country CC | Telephone prefix context |
| plate | TEXT; --country CC | Registration format context |
| data install | PACK…; --version V --from URL\|DIR --yes | Explicit install transaction |
| data list | --remote | Local inventory or available releases |
| data verify | --full | Sizes; hashes with --full |
| data remove | PACK; --yes | Remove the named family |
| data path | none | Resolved data directory |
| data update | --check | Compare active version with the release index |
| info | none | Installed data identities and capabilities |

PACK is core, postal, airports, locode, phone, ip or plates. Names are part of
core. Reverse coordinates and batch input are mutually exclusive; both
coordinate flags are required. Negative coordinates are values.

The first line of geocode help is:
“Finds towns and cities by name. Street addresses are not supported.”
Country/subdivision are hard filters, limit bounds candidates, and population
preference explicitly chooses the population-ranked winner. Airport without a
scheme searches IATA/ICAO according to the core's ambiguity policy.

## Global options

| Flag | Meaning |
| --- | --- |
| --data-dir PATH | Override environment and platform discovery |
| --format table\|json\|ndjson\|csv | Explicit output encoding |
| --json | Shorthand for --format json |
| --csv | Shorthand for --format csv |
| --fields a,b.c | Select named result fields, including dotted paths |
| --fields | List available result fields without opening data |
| --evidence | Include source evidence in results |
| --quiet | Suppress progress diagnostics, preserving result output and errors |
| --no-input | Never prompt; destructive commands require --yes |
| --strict | Exit 1 for a completed lookup with no match |
| --version | Print client version without opening data |
| --help | Print command-specific help without opening data |

Conflicting output selectors are usage errors. Unknown commands, flags or
field paths are usage errors. No lookup invokes installation or release checks.

## Output and batch input

TTY output defaults to a human table. Piped output defaults to NDJSON, one
object per result. --json produces one pretty JSON object. Result keys and
nulls are the exact snake_case public result contract in the design and
[PACK_FORMAT.md](PACK_FORMAT.md). NO_COLOR disables terminal colour; plain
tables need no colour to convey status.

reverse FILE reads a file; reverse - reads stdin. CSV has a header. Automatic
coordinate header names are exactly lat/latitude and lon/longitude/lng,
case-sensitive. Any other names require --lat-col and --lon-col. Multiple
eligible coordinate columns require explicit selection. NDJSON objects use
lat and lon. Input columns pass through, and result columns are appended with
the prefix thereabouts_. Bad rows emit invalid_input and processing continues
in input order. CSV quoting must preserve commas, quotes and embedded newlines.

Single-query examples:

    thereabouts reverse --lat 48.8566 --lon 2.3522 --json
    thereabouts h3 881fb46625fffff
    thereabouts geocode "Springfield" --country US --prefer population
    thereabouts postal 75001 --country FR --fields city.name,country.code,status
    thereabouts airport CDG --scheme iata
    thereabouts locode BEANR
    thereabouts ip 8.8.8.8
    thereabouts phone "+32 2 555 1234"
    thereabouts plate "AB-123-CD" --country FR

Batch and management examples:

    thereabouts reverse points.csv --csv
    thereabouts reverse - --format ndjson
    thereabouts reverse points.csv --lat-col north --lon-col east
    thereabouts --data-dir ./store data install core postal --from ./release --yes
    thereabouts data list
    thereabouts data verify --full
    thereabouts data update --check
    thereabouts data remove postal --yes
    thereabouts data path

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success, including an ordinary miss without --strict |
| 1 | No match with --strict |
| 2 | Usage or input-shape error |
| 3 | Required data is not installed |
| 4 | Incompatible/corrupt data, transfer/integrity or store IO failure |
| 5 | One or more batch rows failed; remaining rows were processed |

Missing-data diagnostics are the exact command
thereabouts data install core, or the required forward family name. Human
prompts and diagnostics go to stderr. Result output goes to stdout. An
interactive removal asks for confirmation; non-interactive removal requires
--yes. --no-input never implies consent.

## Data store

Resolution is --data-dir, THEREABOUTS_DATA, then the platform user-data path.
Python and native discovery use the same pin validation. The native path
policy is tested against the platformdirs implementation bundled with the
existing setuptools development dependency.

| Platform | Default |
| --- | --- |
| macOS | ~/Library/Application Support/Thereabouts |
| Linux/Unix | $XDG_DATA_HOME/thereabouts, otherwise ~/.local/share/thereabouts |
| Windows | %LOCALAPPDATA%/Thereabouts |

The installed layout is:

    <data-dir>/
      active.json
      .install.lock
      .downloads/<archive-sha256>.part
      .staging/<archive-sha256>/
      packs/<family>/<dataset-version>/
        manifest.json
        .archive.json
        <inventoried artifacts>

Versions are portable components of up to 128 ASCII letters/digits, dot,
underscore or hyphen, cannot start/end with a dot, and cannot use Windows
reserved device names. Family names are enumerated.
Pack-relative paths reject traversal, absolute paths, backslashes, colons and
symlinks. The installed manifest's family and data_version must agree with the
selection.

active.json contains:

    {
      "data_version": "2026.10",
      "packs": {
        "core": {
          "path": "packs/core/2026.10",
          "manifest_sha256": "<64 lowercase hexadecimal characters>"
        }
      }
    }

The active pointer is authoritative when present: omitted families are
uninstalled for discovery even if another version remains on disk. The
manifest hash is checked before reading each selected identity. All entries
share one dataset version. Installing another version selects only its
requested families; installing more families at the active version retains
the existing pin entries.

Without active.json, discovery accepts the existing
packs/<family>/current.json pointer and its immutable
packs/<family>/v-<URL-escaped-version>/<manifest-digest>/ directory. Installing
the first pin carries over other compatible old pointers of the same dataset
version. Format-1 reverse pointers produce IncompatibleDataError; they are not
read as format 2.

An OS advisory lock on .install.lock serializes install/remove operations.
The lock is released by closing its file handle, including on process exit;
a leftover lock filename does not block future operations. A concurrent
operation fails explicitly instead of proceeding without a lock.

## Release index and install transaction

The source is a directory containing index.json and archives, or a configured
base URL. The placeholder default is https://thereabouts-releases.invalid;
no service is currently published. --from overrides the source for install.
The release index schema is:

    {
      "format": 2,
      "datasets": {
        "2026.10": {
          "packs": {
            "core": {
              "url": "core.tar",
              "bytes": 123456,
              "sha256": "<64 lowercase hexadecimal characters>",
              "format_minor": 0
            },
            "postal": {
              "url": "postal.tar",
              "bytes": 234567,
              "sha256": "<64 lowercase hexadecimal characters>",
              "format_minor": 1
            }
          }
        }
      }
    }

Index JSON is limited to 16 MiB. Archive size is positive and at most 1 GiB.
Unknown fields are rejected. The default release is the newest whose requested
families exist and have supported format minors: core 0, forward families 1.
Dotted numeric version components compare numerically; other components
compare bytewise. Explicit unavailable/incompatible versions fail.

Archives are uncompressed POSIX ustar: pack blocks are already compressed.
manifest.json and its inventoried artifacts are at the archive root. Only
regular files and directories are permitted. Extraction rejects duplicate or
unsafe paths, links, special files, invalid header checksums, malformed
lengths, missing two-block terminators and nonzero trailing payload. Expansion
is bounded by the advertised archive length; archives cannot supply the
reserved installer .archive.json receipt.

Before download the installer reserves twice the requested archive byte sum
plus a 5 GiB free-space floor. Each transfer chunk rechecks that floor. Partial
downloads remain in .downloads and resume at their exact byte offset. HTTP
transport must send Range and validate the returned Content-Range before
appending; this transport is pending implementation. The implemented Source
interface and local directory source enforce exact-offset reads.

The full archive length and SHA-256 are checked before extraction. Then every
pack checksum and structure is verified, and family, dataset version and minor
format are checked against the index. The pack is renamed from staging into
its immutable destination on the same filesystem. A receipt records archive
identity; a repeated install cannot change that identity for an existing
version.

active.json is written and synced to a temporary sibling, then replaced
atomically only after all requested packs verify. A failed transaction keeps
the previous pin. Already verified, unactivated directories may remain for a
retry; failed extraction staging is removed. Hash failures discard their
partial archive. No lookup contacts the index or any transfer source.

## MCP

The current optional server is available with:

    THEREABOUTS_DATA=./store python -m thereabouts.mcp_service.server

It provides reverse, h3, geocode, postal, airport, locode, phone, ip and plate,
returning the same result JSON as Python, including evidence when requested.
There are no install or arbitrary-path tools. The old CLI's MCP route remains
on the preserved catalogue server until the native console runner replaces it.
