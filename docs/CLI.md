# Thereabouts command and store contract

This is the normative grammar for the Rust CLI and the Node command
tree. The console entry and python -m thereabouts invoke the same Rust
run(argv, io) function. Both hosts use the JSON command description in
[grammar.json](../core/thereabouts-cli-core/src/grammar/grammar.json) through its shared argument parser,
help renderer and diagnostic policy; WASM exports the description verbatim.
Native clap provides typed dispatch after shared validation. Node calls
thereabouts-cli-core through WASM for batch parsing, rendering, field projection
and lookup exit policy, and owns filesystem and HTTP operations. Native argv
includes its program name; Io owns standard
streams, environment and TTY detection. Python supplies the optional MCP host.
See [CLIENT_STATUS.md](CLIENT_STATUS.md) for qualification and measurements.

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
| airport | CODE; --scheme iata\|icao\|gps\|local\|ident --country CC | Airport context |
| locode | CODE; --country CC | Five-character code or country plus three-character location |
| ip | ADDRESS | IPv4 or IPv6 literal |
| phone | NUMBER; --country CC | Telephone prefix context |
| plate | TEXT; --country CC --series NAME | Registration format context |
| data install | PACK…; --version V --from URL\|DIR --yes | Explicit install transaction |
| data list | --remote | Local inventory or available releases |
| data verify | --full | Sizes; hashes with --full |
| data remove | PACK; --yes | Remove the named family |
| data path | none | Resolved data directory |
| data update | --check | Compare active version with the release index |
| info | none | Installed data identities and capabilities |
| mcp | none | Optional read-only Python MCP server on stdio |

PACK is core, postal, airports, locode, phone, ip or plates. Names are part of
core. Reverse coordinates and batch input are mutually exclusive; both
coordinate flags are required. Negative coordinates are values.

The first line of geocode help is:
“Finds towns and cities by name. Street addresses are not supported.”
Country/subdivision are hard filters, limit bounds candidates, and population
preference explicitly chooses the population-ranked winner. Airport without a
scheme searches IATA/ICAO according to the core's ambiguity policy. Schemes
are case-insensitive. Airport --country supplies required local-code context.
LOCODE country context is validated even for a full five-character code.
Plate --series selects a published series, such as historic-geographic.
Phone requires international E.164 input; --country narrows matching countries
and does not infer a national dialing plan. Geocode limit defaults to 5 and
must be between 1 and 100. These context flags mirror library semantics.

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
Use thereabouts --fields to list result paths without query arguments. Available
paths are status, kind, match, country (code, code3, name), state (code, name),
city (id, name, name_en, kind, population, point.lat, point.lon), timezone,
point (lat, lon), cell, distance_band (greater_than_km, at_most_km), candidates,
rank_basis, hint and evidence. Container paths, including city.point, are also
selectable. Selections use literal dotted keys in output, for example
"city.name". Named field selection and evidence apply to lookup results.
Data/info output retains its documented structure. --version works at every
command except data install, where --version V selects the dataset.

Install is explicit consent to transfer; --yes is accepted for automation and
does not change this behavior. There is currently no progress output, so --quiet
preserves results and error diagnostics while producing no progress text.

## Output and batch input

TTY output defaults to a human table. Piped output defaults to NDJSON, one
object per result. --json produces one pretty JSON object. Result keys and
nulls are the exact snake_case public result contract in the design and
[PACK_FORMAT.md](PACK_FORMAT.md). NO_COLOR disables terminal colour; plain
tables need no colour to convey status. The implementation emits no ANSI
colour sequences in any mode, including with NO_COLOR. Table cells replace
control characters with spaces and truncate wide values with … (at most 28
characters per cell). Each place occupies one line; candidates appear as indented
lines beneath the query. The header appears once. Default scalar columns are
status, country, state, city, timezone, point, match, omitting fields absent from
the result and its candidates. Batches keep all seven summary fields to support
rows with differing coverage. --fields uses exactly the requested column order.
Evidence is never printed in tables; use --json --evidence.

Scalar JSON/NDJSON is one result object. Batch --json streams one object with
a results array; it does not retain the whole batch. CSV preserves input header order, then appends thereabouts_* columns in public
result order (or --fields order). Scalar CSV uses that same result order; object/array values are compact JSON in quoted CSV cells, null
is an empty cell, and quoting follows RFC 4180. Scalar JSON/NDJSON uses public
result field order, or --fields order. Batch structured rows preserve their
input key/header order before the appended result fields. Nested object order
is not a contract; consumers address keys by name.

Management outputs are objects: data path returns {"path": ...}; data list
returns {"packs": [...]} with family, data_version, path, active and
format_minor; data install returns {"installed": <active pointer>}; data verify
returns {"verified": "inventory" or "full", "packs": count}; remove returns
{"removed": family}; update returns active_version, available_version and
update_available. The latter is true only for a newer supported version or
an empty store. Info includes client_version and active pack manifests. Local
inventory and verify include retained inactive versions. Table/CSV inventory
has one row per pack; table info gives identity and attribution columns.
Remote listing emits the release index schema below.

reverse FILE reads a file; reverse - reads stdin. CSV has a header. Automatic
coordinate header names are exactly lat/latitude and lon/longitude/lng,
case-sensitive. Any other names require --lat-col and --lon-col. Multiple
eligible coordinate columns require explicit selection. NDJSON objects use
lat and lon. Input columns pass through, and result columns are appended with
the prefix thereabouts_. Bad rows emit invalid_input and processing continues
in input order. CSV quoting preserves commas, quotes and embedded newlines.
CSV header errors (duplicates, empty names, ambiguous coordinates) are usage
errors. Input names beginning thereabouts_ are reserved and rejected. JSON
numeric lat/lon must be numbers, not strings or booleans; CSV fields parse as
floating-point numbers. Out-of-range coordinates produce invalid_input.
Malformed NDJSON records retain their raw text in an input field.

Input encoding is independent of --format, which selects output. Files ending
in .ndjson or .jsonl (case-insensitive) use NDJSON; otherwise the first nonblank
line beginning with { or [ selects NDJSON. Other input uses comma-separated CSV. Single-column and semicolon-separated
input produces a usage error explaining CSV headers and NDJSON objects. Empty input emits no rows (or
{"results": []} with --json).

NDJSON-to-CSV/table needs the union of input keys, in first-seen order, before
writing a header.
It spools input to an automatically removed temporary file, retaining at most
4,096 keys and 1 MiB of key names. Disk exhaustion during spooling reports “not enough disk” (exit 2). JSON/NDJSON output and CSV input stream directly. Missing input fields
become null tabular cells. Batch hint is always present (nullable), and evidence
is nullable when requested, so failed rows cannot change the CSV result schema.

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
| 2 | Usage, input-shape or environment/stream IO error |
| 3 | Required data is not installed |
| 4 | Incompatible/corrupt data or transfer/store integrity failure |
| 5 | One or more batch rows failed; remaining rows were processed |

Missing-data diagnostics are the exact command
thereabouts data install core, or the required forward family name. Human
prompts and diagnostics go to stderr. Result output goes to stdout. An
interactive removal asks for confirmation; non-interactive removal requires
--yes. --no-input never implies consent. A declined prompt exits 2. Remove
deletes all versions of the named family under the install lock; a missing
family is harmless. Missing data, corrupt data and usage errors are not hidden
by --quiet. A broken stdout pipe exits 0 without a traceback. Other stream/OS IO failures
exit 2 without suggesting pack repair. Both Node sinks write all UTF-8 bytes,
retrying partial writes, EINTR and EAGAIN while a slow reader drains the pipe.

An invalid scalar query emits its result and exits 2; invalid command arguments
emit a diagnostic without result JSON. Unsupported granularity also exits 2.
In batches, row failures take precedence over strict misses: exit 5 if any row
failed, otherwise 1 if --strict found a not_found result. Ambiguous is not
not_found and does not itself trigger --strict.

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
      .lock
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
share one dataset version. Installing another version requires all active families in the request; installing more families at the active version retains
the existing pin entries.

Without active.json, discovery accepts the existing
packs/<family>/current.json pointer and its immutable
packs/<family>/v-<URL-escaped-version>/<manifest-digest>/ directory. Installing
the first pin carries over other compatible old pointers of the same dataset
version. Format-1 reverse pointers produce IncompatibleDataError; they are not
read as format 2.

Install/remove operations acquire `<data-dir>/.lock` with exclusive file creation
(`O_EXCL`/`create_new`). Its immutable JSON record is `{pid, created_ms, token}`:
a positive OS PID, Unix milliseconds and a unique 32-hex-character incarnation.
Both hosts use the same Rust wire validation and recovery-name policy. No port
or network access is involved. Contention reports “Another install is running;
retry after it finishes” and exits 2. A corrupt/unsafe lock path exits 4.

A live owner never expires by age. A dead PID permits immediate takeover;
permission failures count as live. An incomplete record has a 30-second creation
grace period, measured against file mtime; backwards clock movement defers
recovery. Reads are capped at 1 KiB. Takeovers acquire a per-incarnation sibling
`.lock-reap-<sha256>` lease, reread/recheck the old record, then unlink it and
retry exclusive creation. This serializes competing reapers so they cannot
unlink a successor. The same protocol recovers dead reapers, bounded to eight
nested recoveries; exhausted contention exits 2. Normal release removes only
its own token. Completed recovery leases are removed on scope exit.

## Release index and install transaction

The source is a directory containing index.json and archives, or a configured
base URL. The placeholder default is https://thereabouts-releases.invalid;
no service is currently published. THEREABOUTS_RELEASE_URL configures the
source for install, remote list and update --check; it may also be a local
directory. --from overrides it for install. URLs are HTTP(S) base URLs;
index.json is appended. An archive URL may be absolute or base-relative.
Local indexes use relative artifact paths.
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
              "format_minor": 2
            },
            "postal": {
              "url": "postal.tar",
              "bytes": 234567,
              "sha256": "<64 lowercase hexadecimal characters>",
              "format_minor": 2
            }
          }
        }
      }
    }

Index JSON is limited to 16 MiB. Archive size is positive and at most 1 GiB.
Unknown fields are rejected. The default release is the newest whose requested
families exist and have supported format minors: minor 2 for every family.
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
plus a 64 MiB bookkeeping margin. Insufficient space is an environment error
(exit 2); there is no fixed free-space floor in the product. Partial
downloads remain in .downloads and resume at their exact byte offset. The native HTTP
host uses ureq with rustls and certificate verification enabled. Node uses
fetch with undici environment-proxy support and normal TLS verification. Initial
transfers require HTTP 200; resumes send Range: bytes=N- and require HTTP 206
with Content-Range: bytes N-(total-1)/total. If supplied, Content-Length must
equal the remaining advertised length. Ignored/mismatched ranges fail and
retain the partial file for retry. No bytes are appended before these checks.
Requests use Accept-Encoding: identity; encoded responses are rejected.
HTTPS requests follow at most five HTTPS-only redirects; downgrade to HTTP is
rejected. HTTP sources (including loopback tests) do not follow redirects.
HTTPS_PROXY/HTTP_PROXY/ALL_PROXY and NO_PROXY use native ureq environment semantics.
Node honors HTTPS_PROXY/HTTP_PROXY and NO_PROXY through undici; ALL_PROXY is
used as a fallback when HTTP_PROXY/HTTPS_PROXY are absent. Connections and headers
have 30-second deadlines; each transport read has a fresh 60-second stall limit.
There is no total download timeout. Failures retain verified-offset partial bytes
for the next explicit install to resume. Tests use only loopback HTTP and local directories.

The full archive length and SHA-256 are checked before extraction. Then every
pack checksum and structure is verified, and family, dataset version and minor
format are checked against the index. The pack is renamed from staging into
its immutable destination on the same filesystem. A receipt records archive
identity; a repeated install cannot change that identity for an existing
version.

active.json is written and synced to a temporary sibling, then replaced
atomically only after all requested packs verify. A failed transaction keeps
the previous pin. Already verified, unactivated directories may remain for a
retry; failed extraction staging is removed. Archive hash failures discard their
partial archive. No lookup contacts the index or any transfer source.

## MCP

The current optional server is available with:

    thereabouts --data-dir ./store mcp
    # Equivalent direct Python host:
    THEREABOUTS_DATA=./store python -m thereabouts.mcp_service.server

It provides reverse, h3, geocode, postal, airport, locode, phone, ip and plate,
returning the same result JSON as Python, including evidence when requested.
There are no install or arbitrary-path tools. The optional thereabouts[mcp]
extra is imported only for mcp; startup without it exits 2 with an explicit
installation hint. No banner is printed on the MCP protocol stream.
The old Python CLI and catalogue MCP modules have been retired. The public
console delegates directly to the native Rust command tree.

## Conformance boundaries

The current bundle has 411 vectors. The real console runs 405; six of these
invalid grammar cases assert exit 2 without a result object. Five NUL-containing
cases run through _core.run_cli because operating systems forbid NUL in argv.
One integer-type postal input is asserted through the typed API and rejected
by the run_cli argument conversion: OS arguments cannot preserve integer types.
The 19 legacy forward cases retain their original assertions and explicit
migration allowances: 18 run through the console, and one integer-type
rejection remains at the typed API boundary. No expected snapshots are replaced
with the new CLI's output.

### Optional core enrichment for forward packs

Forward format 2.2 pins the core dataset version, catalogue digest and place
count. Installing core alongside a forward family enables canonical city,
state/country metadata and catalogue timezone projection. The active release
must agree and the catalogue digest must match; otherwise lookup exits 4.
Forward lookup never installs core implicitly. With only the forward pack
installed it still returns its keys, source points and published country/state
context; city detail and timezone are null. A partial core sample supplies
only the places it contains. Python explicit paths select enrichment with
`Geocoder(packs={"core": core_path, "postal": postal_path})`; a lone forward
`Geocoder(path)` is deliberately standalone. Names lookups continue to use core.

### Bounded fuzzy search

Exact and prefix name lookup remain exhaustive. The fuzzy fallback uses the
pack-wide key/row budgets documented in PACK_FORMAT.md. On large name indexes,
otherwise eligible fuzzy cities may be omitted; population ranks the admitted
candidates. Country and subdivision filters remain hard constraints on every
returned result.

A dataset version change must include every active family in the install
transaction. Otherwise installation exits 2 before downloading, preserves the
active pointer and prints the complete install command with --version. Installing
another family at the current version retains all other active families.

Until a release service is published, the default placeholder fails locally
with exit 2 and instructions to set --from DIR|URL or THEREABOUTS_RELEASE_URL;
it never performs DNS or HTTP. Missing input files are usage/environment errors
(exit 2) naming the path. Unusable installed packs report their path, family,
thereabouts data verify --full, and remove/reinstall commands (exit 4).

Missing data exits 3 with a short sentence on stderr followed by the exact
install command alone on the last line. Library exception messages remain the
exact command.

Bare invocation writes help to stderr and exits 2. Explicit --help writes to
stdout and exits 0. Reverse help shows coordinate and FILE|- forms separately.
Python and Node discovery delegate directory selection to the same portable
store policy (native and WASM respectively);
macOS, Linux and Windows rules are compared with platformdirs in tests.

The Rust thereabouts-cli-core crate owns batch detection/parsing, result-field
selection, table/JSON/NDJSON/CSV rendering and the exit-code policy. It builds
for wasm32-unknown-unknown and has no clap, HTTP or filesystem dependency.
Hosts supply input/output streams, terminal columns and seekable temporary storage; table width
is measured in terminal cells (including wide Unicode text). The native crate
owns clap, files, temporary-file lifetimes, process environment and downloads.
The Node binding uses this same portable policy through WASM.


## Node implementation

The ESM package supports Node 22 and 24. Scalar library methods are async and
return the same snake_case result objects. reverseMany is an async iterable.
The host supplies stable file descriptors, sizes and exact positioned reads;
the WASM module owns every pack decoder and lookup. There is no native addon.

Build the ignored pkg/ artifact with npm run build (Rust 1.99,
wasm32-unknown-unknown and wasm-bindgen-cli 0.2.129). npm prepack invokes this
reproducible build and includes the result; no generated WASM is committed.
The package contains no data and makes no implicit downloads.

Node mcp delegates stdio to python3 -m thereabouts.mcp_service.server;
THEREABOUTS_PYTHON can select the Python executable. The optional Python
MCP installation remains required. JS command help describes the same flags;
text wrapping need not match clap. Node scalar invalid values and CLI batch
errors use the shared Rust result and exit mapping.

Node library conformance asserts all current and synthetic vectors and all
54 original legacy mappings. The actual bin asserts every representable query;
NUL values use the same JS runner and typed non-string values remain library
assertions. Numeric comparison uses the Rust runner's 1e-10 absolute tolerance
for target-specific transcendental arithmetic in H3 cell centres. No expected
geography, statuses or candidate ordering is changed for Node.

## Building a local release

The pipeline release packs command produces packs/<version>/index.json and
one deterministic ustar archive per family, after all requested packs verify.
Pass that version directory to data install --from. Core must be included when
building forward packs so their catalogue pins have a concrete dependency.
See [DATA_PIPELINE.md](DATA_PIPELINE.md) for prepared-dataset commands and
[CLIENT_RELEASE.md](CLIENT_RELEASE.md) for package artifact workflows.

Interrupted transfers (including connection resets, short EOF and per-read
stalls) retain partial archives and exit 2 with “Download interrupted; run the
same data install again to resume”. A retry validates the exact Range response
before appending. Checksum and protocol identity failures still exit 4.

## Terminal width and numeric equality

Tables use COLUMNS when it is a positive integer (at most 10,000), otherwise
the stdout terminal's width (ioctl on native hosts), otherwise 80 columns.
Column widths reflect the first query row and its candidates, capped at 28.
The widest columns shrink first until the table fits; headers remain readable.
Batch table result headers omit the thereabouts_ prefix; JSON/NDJSON/CSV keep
it. Separators compact to two spaces when needed. Very wide input schemas
that cannot retain readable headers require --fields or --json. A stream keeps
one header and fixed column widths; later wide values use …, including Unicode.

Results are semantically equal across native and WASM hosts. H3-derived cell
centres can differ in the last floating-point digits because target math
implementations differ. Compare these latitude/longitude values with absolute
tolerance 1e-10 degrees, not byte-identical JSON or CSV text. Stored coordinate
values, IDs, statuses, ordering and other fields retain exact conformance.
No extra output rounding is applied.

User-selected batch files may be regular files, named pipes or process
substitution paths; they are sequential streams, not pack artifacts. Pack
artifacts still require immutable regular files and positioned reads.
Version-switch refusal prints commands retaining --from and --data-dir, both
for switching all active families and for adding a family at the active version.
Resume requests always send Accept-Encoding: identity. Node fetch adds this
header for Range requests itself; the host sets it for other requests to avoid
a duplicated wire value. Loopback tests assert the actual resumed header. Repository npm config
and the Node benchmark keep cache/log files under .cache and scratch under .tmp.
