# Thereabouts examples

Runnable scripts that try every lookup family in about five minutes: reverse geocoding
(coordinates and H3 cells), city names, postal codes, airports, UN/LOCODEs, phone numbers,
IP addresses and vehicle plates. Everything runs offline against installed packs.

| Folder | What it holds |
| --- | --- |
| `python/` | `reverse.py`, `forward.py` and `batch_csv.py` using the Python client |
| `node/` | The same three as `.mjs` scripts using the Node client |
| `cli/` | `quickstart.sh` (one command per family) and `batch.sh` (the sample CSVs through the CLI) |
| `mcp/` | A client config snippet and three example prompts for the MCP server |
| `data/` | Small sample inputs with expected answers; see `data/README.md` for provenance |

## Prerequisites

1. Install a client. The 0.1.0 packages are not published yet, so install from this
   repository or a built archive.
   - Python 3.11+: `python -m pip install .` from the repository root (add `".[mcp]"` for MCP).
   - Node 22 or 24: `npm install /path/to/thereabouts-0.1.0.tgz` inside `examples/node`.
2. Install the data packs. This is the only step that uses the network, and the lookups
   never download anything:

   ```sh
   thereabouts data install core postal airports locode phone ip plates
   ```

   Use `--data-dir ./store` (or set `THEREABOUTS_DATA`) to keep the packs in a directory of
   your choice, and `--from DIR_OR_URL` for a local release. While the repository is private,
   set `THEREABOUTS_RELEASE_TOKEN` or `GITHUB_TOKEN`.
3. Check with `thereabouts data list`. A script whose pack is missing prints the exact
   install command and skips that family.

## Running the examples

Every script finds the default store on its own. Pass `--data-dir DIR` (or a directory as the
first argument to the shell scripts) to use another one.

| Example | Command |
| --- | --- |
| Reverse geocoding | `python examples/python/reverse.py` or `node examples/node/reverse.mjs` |
| Names, postal, airports, LOCODE, phone, IP, plates | `python examples/python/forward.py` or `node examples/node/forward.mjs` |
| Sample CSVs against expected answers | `python examples/python/batch_csv.py` or `node examples/node/batch_csv.mjs` |
| One CLI command per family | `bash examples/cli/quickstart.sh` |
| Sample CSVs through the CLI | `bash examples/cli/batch.sh` |
| MCP server | see `examples/mcp/README.md` |

`batch_csv` accepts `--csv-dir` to read your own copies of the CSV files, and `--limit N` to
read only the first N rows of each file.

## Reading the output

Every lookup returns one result with a `status`: `matched`, `ambiguous`, `not_found`,
`invalid_input` or `unsupported_granularity`. A miss is an ordinary answer, not an error.
Ambiguity is kept, never resolved: a postal code, airport code or plate that fits several
places returns ranked `candidates`. Read `match` as well: `contained` is inside a boundary,
`nearest` and `nearest_distant` are approximate and come with a `distance_band`.

## Where the expected answers come from

The city points and plates in `data/` are taken from the evaluation ground truth in `eval/`
(`eval/city_points/points.csv` and `eval/plate_country/evaluation.yaml`), which is not moved or
changed. The postal codes, airports, UN/LOCODEs, phone numbers and IP addresses are
hand-picked, well-known examples, not evaluation data. Expected answers are a first-run
smoke check: the batch examples print `MISMATCH` rows instead of failing, and a given release
can legitimately differ, especially for coverage subsets.
