# Installing data and using the CLI

> Historical format-1 installation documentation. Current commands, data store and
> MCP are documented in [CLI.md](CLI.md); the current Python API is in
> [CLIENT_STATUS.md](CLIENT_STATUS.md). Legacy console examples require
> `python -m thereabouts.commandline.application` in place of `thereabouts`.

Thereabouts installs data explicitly. Queries, imports and opening a reader never
contact a data host. Install the Python project with its NumPy/H3 dependencies;
the `thereabouts` command and `python -m thereabouts` call the same Python API.
No serving data is bundled in the wheel.

For the committed synthetic fixture, this command uses its known manifest digest:

```sh
thereabouts --data-dir .cache/example-store data install \
  --from tests/fixtures/serving --offline \
  --sha256 83104c7ddd477b6de593db81d6416248e64748f6ec0883eda2b68ab1c476a03b
thereabouts --data-dir .cache/example-store reverse 12.97 77.59
thereabouts --data-dir .cache/example-store data list
thereabouts --data-dir .cache/example-store data verify --full
```

This fixture has invented labels; it demonstrates the contract, not geography.
Select a directly unpacked, verified directory with `--pack /path/to/pack`.
`--pack` and `--data-dir` precede the command and are mutually exclusive.

## Pack sources and trust

`data install --from` accepts an unpacked directory or a full HTTPS URL to
`manifest.json`. Other files are resolved relative to that URL. Configure a
Hugging Face or mirror location by supplying its immutable revision URL; there
is no built-in host, release index or published dataset. HTTP is accepted only
for loopback testing. HTTPS redirects may not downgrade to HTTP. URLs containing
credentials or fragments are refused; there is no custom credential manager.

Supply a trusted `--sha256` for every manifest. URL sources additionally require
`--manifest-bytes N`, from the same trusted release information. The downloader
reads exactly those bytes, hashes before parsing, then bounds each payload by
its manifest byte count and SHA256. A digest downloaded beside untrusted data
does not establish publisher authenticity. Signed release indexes and key rotation
remain release work; there is no automatic "latest" or update service.

```python
from thereabouts.installing.install import install

# manifest_sha256 comes from the release information you trust.
pack = install(
    "/media/thereabouts-pack",
    manifest_sha256="83104c7ddd477b6de593db81d6416248e64748f6ec0883eda2b68ab1c476a03b",
    data_dir=".cache/example-store",
    offline=True,
)
```

Remote calls also accept `timeout` / CLI `--timeout` (30 seconds by default).
A failed transfer returns an installation error; rerun the same pinned install
to resume. Resume is at **whole verified file boundaries**. Partial files are
removed and restarted, and every retained file is rehashed. There is no byte-range
resume, retry loop or archive extraction contract. Using independently listed
shards avoids an unbounded decompression step.

The installer streams with a 1 MiB I/O buffer. It checks available disk space
against the pinned remaining bytes, then fully verifies the completed pack's
hashes, structures and references before activation. It rejects absolute paths,
traversal, symlinks and duplicate/reserved payload names. A per-family OS lock
refuses concurrent installers; process exit releases that lock. Failed downloads
leave verified staging artifacts reusable, without changing the active pointer.

## Stores and lifecycle

`Geocoder(data_dir=...)` selects the active reverse installation. With neither
`pack` nor `data_dir`, it uses `THEREABOUTS_DATA`, then the platform default:

| Platform | Default persistent location |
| --- | --- |
| Linux | `$XDG_DATA_HOME/thereabouts` or `~/.local/share/thereabouts` |
| macOS | `~/Library/Application Support/Thereabouts` |
| Windows | `%LOCALAPPDATA%\Thereabouts` |

An explicit pack directory bypasses discovery. Missing data raises
`DataNotInstalledError` with the explicit installation action; lookup does not
try to repair or download anything.

A store contains `packs/reverse/v-<escaped-version>/<manifest-sha256>/` and
`packs/reverse/current.json`. The version is UTF-8 percent-encoded with a `v-`
prefix, protecting path separators and Windows device names. The pointer contains
a relative path and the manifest digest, written using atomic replacement.
Installations remain immutable, and earlier versions are retained. Open handles
keep using their original pack after activation changes. Listing includes all
versions and which one is active. Pruning and automated upgrades are deliberately
absent: remove an unused old directory only after its readers have closed.

The activation and file-lock paths were tested on macOS; Windows locking is
implemented but not executed here. Power-loss durability and concurrent hostile
filesystem mutation were not qualified. This is an application-owned immutable
store, not a shared directory accepting arbitrary writers.

`data verify` checks the inventory, compatibility and sizes. `data verify --full`
also verifies every payload checksum, binary structure and global invariants.
A normal reader performs quick opening checks and assumes an immutable verified
installation. `info` includes pinned source versions, attribution and notice paths;
include the pack notices with a redistributed installation.

## JSON lookup and streams

```sh
thereabouts --pack tests/fixtures/serving h3 8860145b49fffff
thereabouts --pack tests/fixtures/serving resolve coordinates 12.97 77.59
thereabouts --pack tests/fixtures/serving explain h3 8860145b49fffff
thereabouts --pack tests/fixtures/serving info
```

`batch` reads stdin and emits one JSON object per input row in order. By default
it expects JSON Lines objects with `latitude` and `longitude` numeric fields.
`--kind h3` uses the `h3` string field. CSV requires a header; set `--format csv`
and optionally `--latitude-column`, `--longitude-column` or `--h3-column`.
Duplicate CSV headers and malformed rows are invalid. Output is always JSON
Lines, preserving candidates and nulls; there is no implicit CSV flattening.

`--errors collect` emits invalid-row results and continues. `--chunk-size` controls
bounded iteration (default 4,096); output from earlier chunks may precede a later
error. Diagnostics go to stderr, results to stdout. Broken pipes exit quietly.

| Exit code | Meaning |
| --- | --- |
| 0 | Completed operation, including ordinary no-match results |
| 2 | Invalid usage or input |
| 3 | Missing, corrupt or unsupported data |
| 4 | Installation, network or I/O failure |
| 5 | Completed batch with collected invalid rows |

## Air-gapped use and qualification

Prepare a wheel directory on a connected machine for the target Python/platform,
including Thereabouts, NumPy and H3. Transfer those exact wheels and a verified
unpacked pack with its trusted manifest digest. Install dependencies with
`python -m pip install --no-index --find-links /media/wheels thereabouts`, then
run `data install --from /media/pack --offline --sha256 ...`. Lookup needs neither
a compiler nor a network when suitable dependency wheels have been prepared.

The test suite blocks external DNS/network access and exercises local installation,
loopback HTTP, failed transfer/activation, resume, retained readers, symlinks,
corrupt pins, disk preflight, discovery, JSONL/CSV, exit codes and broken pipes.
No Hugging Face endpoint, external network service, Windows installation or
published wheel was tested.

[CLIENT_INSTALL_MEASUREMENTS.json](CLIENT_INSTALL_MEASUREMENTS.json) records one
local install of the 208,592-byte synthetic sample on Apple M2, 8 GiB, macOS 27,
Python 3.12.8: **0.427 seconds**, including full verification, with process peak
RSS **41,992,192 bytes**. No cache eviction or world-scale inference is implied.
Reproduce with `python -m benchmarks.install SOURCE --store FRESH_STORE --output REPORT`.


## Optional code families

The same local/pinned-URL installer accepts `postal` and `airports`. Each family
has its own immutable path and active pointer. Transfer staging is locked by
manifest digest, then publication/activation is locked by family. `data list`
reports all families; `data verify --family postal --full` verifies an installed
optional pack without reverse data. See [CODE_PACKS.md](CODE_PACKS.md) for exact
resolver and multi-pack selection examples. No code pack has been hosted.
