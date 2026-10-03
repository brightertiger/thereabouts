# Thereabouts data pipeline redesign

Status: draft for owner review, 2026-10-03.

## 1. Purpose

Thereabouts ships an open dataset: for every H3 resolution‑8 cell on land, the
country, subdivision and canonical city, plus lookup tables (postal codes,
airports, IP ranges, phone prefixes, time zones, trade locations). The code
that builds it grew stage by stage over two weeks under `build_data/` and
works, but a full rerun today needs a human at the keyboard, a symlink with the
old project name, and luck with upstream servers.

This document describes the pipeline we want instead. Success means:

1. **Re-runnable from scratch, unattended.** One command on a fresh machine
   with the pinned inputs produces the same dataset, byte for byte in content.
2. **Idempotent and resumable.** Rerunning does nothing when nothing changed;
   after a crash it continues; a changed rule rebuilds exactly what depends on it.
3. **Config-driven.** Every tunable, pin, path and policy lives in a typed
   configuration tree, not in code constants.
4. **Extensible.** A new source is one directory and one YAML file. A new
   derived table is one stage class.
5. **Publishable.** A release stage writes a versioned dataset with licences,
   dataset card and checksums to S3 for the AWS Open Data registry.

Decisions already made by the owner: plain Python, no workflow framework; the
final dataset goes to AWS Open Data, raw inputs stay mirrored in GCS; a GCP
virtual machine is the reference environment, the laptop is for development on
samples; releases roughly monthly, tracking upstream; the package is renamed
from `build_data` to `pipeline`; and the dataset already built on the laptop
is kept and adopted — the refactor is validated by dry runs, never by
regenerating it (section 9).

## 2. What stays and what goes

Keep, because it works and is tested:

- the sqlite ledger (units keyed by stage and unit id, inputs hash, output
  sizes and sha256) and its "complete only if every output re-hashes" rule;
- atomic publishing through `.part` files and `os.replace`;
- the DuckDB-based reconcile, golden-cell, city and normalize engines, and the
  rules they encode (`docs/CITY_NORMALIZATION_PLAN.md`, `docs/GOLDEN_V2.md`);
- the serving-pack format (`docs/SERVING_FORMAT.md`) and exporter;
- the evaluation points (`eval/city_points`) and the test suite's approach
  (synthetic fixtures, loopback HTTP, network guard).

Replace:

- six code-fingerprint styles with one rule (section 6);
- hard-coded lists of sources, limits and tables with a registry read from
  configuration (section 4);
- absolute paths in ledger rows, manifests and receipts with root-relative
  paths, plus a one-off migration (section 7);
- the `rebuild_golden` controller, which skips stages by checking for files,
  with a runner that asks each stage whether it is current (section 5);
- hand-written review heredocs and `release.json` with committed YAML;
- discover-latest downloads with a committed pin lock (section 4.2).

Remove:

- the legacy v0 runtime and builder (`build_data/__main__.py`, `sources.py`,
  `source_pack.py`, `normalize.py`, `settlements.py`, `table.py`, `pack.py`,
  `verify.py`, `manifest.py`, `records.py`, `reference/`), after moving the
  two pieces the live pipeline still uses (`reference/sphere.py` geometry and
  the `oracle`/`schema` helpers imported by `hierarchy.py`) into `pipeline/`;
- version-named paths and state (`golden-v2`, `v2-pilot`, `v2-dev.json`,
  `golden-v1` rename on activation).

## 3. Layout

```
pipeline/                      the package (was build_data/)
  __main__.py                  python -m pipeline <command>
  cli.py                       argument parsing, config overrides
  config/                      dataclass schemas (OmegaConf structured configs)
  runtime/                     ledger, atomic io, fingerprints, storage, resources
  sources/                     one module or package per source + the adapter contract
  stages/                      one module or package per stage + the stage contract
  engines/                     reconcile, cells, cities, normalize (moved, not rewritten)
  release/                     dataset assembly, licences, card, registry entry, upload
config/                        YAML read at run time (committed)
  pipeline.yaml                paths, storage, resources, h3
  sources/<name>.yaml          one per source
  policies/reconcile.yaml
  policies/cities/common.yaml
  policies/cities/<CC>.yaml    per-country rules
  reviews/*.yaml               human gate approvals bound to policy fingerprints
  release.yaml                 version, bucket, card text, maintainers
pins.lock                      resolved upstream versions (committed, updated by a command)
data/                          workspace (configurable root)
  raw/<source>/                downloads and inventory
  normalized/<source>/         Parquet partitions and manifest
  reconciled/                  per-country SQLite
  cells/                       base cells
  cities/                      canonical cities and place→city maps
  dataset/<version>/           the publishable dataset
  packs/<version>/             serving packs
  work/                        ledger, logs, scratch
```

Modules stay under about 250 lines, one job each, strict mypy, ruff clean,
in the style of `src/thereabouts/` and the newer stages.

## 4. Configuration

### 4.1 Tree and loading

Configuration is OmegaConf. Each file has a dataclass schema in
`pipeline/config/`; loading merges defaults → YAML → command-line overrides
(`python -m pipeline run resources.workers=2 paths.root=/mnt/data`) and
validates against the schema, so a typo in a key or a string where an integer
belongs fails before anything runs. No Hydra: it brings job directories,
logging takeover and multirun, none of which we need.

`pipeline.yaml` holds:

- `paths`: workspace root and the subdirectories above, all relative to root;
- `storage`: named backends (`local`, `gcs_raw: gs://…/raw`, `s3_release:
  s3://…`) used by the download mirror and the release stage, through fsspec;
- `resources`: `duckdb_memory`, `duckdb_threads`, `workers`, `rss_limit`,
  `disk_floor` (5 GB, the owner's rule; the runner refuses to start a unit
  below it), `max_workspace`;
- `h3`: `block_resolution: 3`, `cell_resolution: 8`.

Profiles: `config/profiles/laptop.yaml` and `config/profiles/vm.yaml` override
`resources` and `paths`; a run names one with `--profile`.

### 4.2 Sources and pins

`config/sources/<name>.yaml`:

```yaml
name: ghsl
adapter: pipeline.sources.ghsl          # module exposing the Source protocol
kind: urban_centres                     # schema family
upstream:
  url: https://jeodpp.jrc.ec.europa.eu/.../GHS_UCDB_GLOBE_R2024A.gpkg
licence: {id: CC-BY-4.0, url: ..., attribution: "European Commission, JRC"}
limits: {download_bytes: 2_000_000_000, batch_rows: 50_000}
```

What a source is (name, where, licence, limits) lives here. What version of
it we built from lives in `pins.lock`, one entry per source, written only by
`python -m pipeline pins update [source…]`:

```yaml
ghsl:      {release: R2024A, sha256: 6c3f…, size: 1_287_332_864, pinned_at: 2026-09-29}
overture:  {release: 2026-09-23.1, counts: {...}}
geonames:  {dump_date: 2026-09-30, files: {allCountries.zip: {sha256: …}}}
osm_land:  {release: ..., etag: "...", last_modified: "..."}
geoboundaries: {commits: {GBR/ADM1: 9469f09, ...}}
```

A run never discovers "latest". If the pinned bytes are gone upstream, the
download stage reads them from the GCS mirror (`storage.gcs_raw`), where every
successful download is copied as part of the same unit. A release therefore
reproduces from the lock plus the mirror alone.

### 4.3 Policies and reviews

Reconcile and city rules move from `policy.json` to YAML with schemas.
City rules split into `common.yaml` and one `<CC>.yaml` per country with
overrides; a country's unit hashes `common` plus its own file, so editing
Belgium's rule rebuilds Belgium. Evaluation fixtures (probes, regressions,
expectations) move under `tests/` or `eval/` and are never hashed.

Human approvals become committed files in `config/reviews/`, for example
`cities-pilot.yaml` with the reviewer's reasoning, the minimum development
score, and the fingerprint of the policy it approved. The gate compares that
fingerprint with the current policy identity; a policy change invalidates the
approval and the runner stops with a message naming the file to update.
Nothing in a review refers to a machine path.

## 5. Stages and the runner

### 5.1 Stage contract

```python
class Stage(Protocol):
    name: str                         # ledger stage prefix, e.g. "cities"
    needs: tuple[str, ...]            # upstream stage names
    def identity(self, ctx) -> str    # fingerprint, see §6
    def units(self, ctx) -> list[Unit]        # work items with their inputs hash
    def run(self, ctx, unit) -> list[Path]    # writes outputs atomically, returns them
    def finish(self, ctx) -> None     # writes the stage manifest after all units
```

`ctx` carries the loaded config, the workspace, the ledger, the storage
backends and a resource guard. A unit's inputs hash is the stage identity plus
the hashes of the upstream outputs it reads (taken from the ledger, not
recomputed), so an upstream change propagates exactly as far as it is read.

Stages, in dependency order: `download` (per source), `normalize` (per
source), `reconcile`, `cells`, `cities`, `normalize_cells`, `lookups`,
`dataset`, `packs`, `publish`. `plates`, `plate_country` and `ghsl` become
ordinary sources; `plate_country` outputs become a normal table. Evaluation
(`cities.dev`, pilot scoring) is a stage too, so its receipts are ledger units.

### 5.2 Runner

`python -m pipeline`:

- `run [--through STAGE] [--only STAGE] [--profile P] [key=value…]` — walks
  the graph, skips current units, runs stale ones with the configured worker
  count, writes `work/runs/<timestamp>/` logs and a summary;
- `plan` — the same walk without running: prints each stage, how many units
  are current, stale or new, and for stale ones *why* (identity changed, an
  upstream unit changed, an output missing or corrupt);
- `status` — ledger summary and disk use per stage;
- `invalidate STAGE [--units …]` — drops ledger rows so the next run rebuilds;
- `pins update|check`, `mirror push|pull`, `release prepare|upload|registry`.

The runner enforces `resources.disk_floor` before each unit and pauses
rather than failing when below it, logging what it is waiting for. The
external guard script is no longer needed.

## 6. One fingerprint rule

A stage's identity is the sha256 of: the source files of its own package
under `pipeline/` (and `pipeline/engines/<engine>/` if it uses one), the
config sections it declares, the pins it reads, and the pinned versions of
the native libraries whose output it depends on (DuckDB, Shapely/GEOS, h3).
Nothing else: not tests, not fixtures, not documentation, not the client
package. `src/thereabouts/format.py` is currently hashed by the cell builder
because both encode cell ids. Instead, `format.py` declares an explicit
`CELL_FORMAT_VERSION` and the pipeline hashes that constant: the encoding
stays in the client package (the pipeline may depend on the client, never the
reverse), and only a deliberate format bump invalidates the dataset.

Manual version strings go away. The existing outputs are **adopted**, not
rebuilt: the migration in section 7 records them in the ledger under their new
identities after verifying their content hashes, so the first `plan` under the
new rule reports everything current. The first real rebuild happens when the
owner bumps pins for the next release, not as part of this refactor.

## 7. Paths and the ledger

One `Ledger` class. Every path it stores is relative to the workspace root;
every manifest and receipt the pipeline writes uses the same rule; nothing
calls `resolve()` on a path that is then persisted. The workspace root comes
from configuration, so the same ledger and manifests work after a move or on
a different machine.

Migration (`python -m pipeline migrate`), run once on the current workspace
and never touching a data file's content:

1. **paths** — rewrites absolute prefixes in ledger rows, the 13 normalized
   manifests, the city manifest, the pilot gate receipt and the GHSL inventory
   to root-relative form, then verifies every rewritten row still re-hashes.
   After it passes, the `PyOfflineGeocoder` symlink is removed.
2. **adopt** — for every unit of every new stage, finds the corresponding
   output of the old stage (the mapping from old stage and unit names to new
   ones is a table in the migration module), verifies size and sha256 against
   the old ledger row, and records the unit as complete under its new identity
   and inputs hash. Units whose files are gone on purpose (`reconcile.*`, since
   `data/reconciled` was deleted) are adopted from their recorded hashes alone,
   marked `outputs_absent`, so the stages that read them stay current but a
   future `run` of those downstream stages knows it must regenerate reconcile
   first. Stale rows from superseded runs (`golden-v2.*`, old `golden.lookup`)
   are dropped.
3. **check** — `plan` must then report zero stale or new units. Any
   discrepancy is a bug in the mapping, fixed before the package merges; the
   migration never falls back to rebuilding.

The old ledger is copied to `work/ledger.pre-migration.sqlite3` first, and
the migration is idempotent (a second run finds nothing to change).

## 8. Release

`dataset` assembles `data/dataset/<version>/` from the normalize_cells and
lookup outputs: Parquet tables with the agreed schemas, `manifest.json` with
per-file checksums and row counts, `DATA_LICENSES.md` generated from the
source configs actually used, `DATASET_CARD.md` from `release.yaml` plus
measured statistics, and `CHANGES.md` comparing with the previous version's
digest. Versions are `YYYY.MM[.patch]`.

`packs` runs the existing serving exporter from the dataset directory.

`publish` uploads `dataset/<version>/` and `packs/<version>/` to
`storage.s3_release` with multipart uploads, verifies checksums, skips objects
already present with the right hash (so it is idempotent), and writes
`<version>/_SUCCESS` last. `release registry` emits the YAML entry for a pull
request to `awslabs/open-data-registry` (name, description, licence, update
frequency, contact, resources, tutorials).

Cell files are 41k objects of ~15 KB; the dataset stage coalesces them to one
Parquet file per resolution‑3 block group (about 1,000 files) so the published
layout is S3-friendly while the ledger keeps the fine-grained units.

Licence: the dataset includes ODbL inputs (OSM land, Overture divisions,
timezone boundaries) and is therefore published as a derivative database under
ODbL 1.0, with CC BY, PDDL and public-domain attributions listed. AWS Open
Data hosts ODbL datasets (OpenStreetMap among them). The owner has agreed to
this; it is recorded here so the card and registry entry can state it.

## 9. Validation and migration path

**The existing data is the asset; the refactor must not cost it.** No work
package may trigger a rebuild of the workspace. Validation is by dry run and
by tests on synthetic fixtures, never by regenerating real stages:

- `pytest`, `ruff`, `ruff format --check`, `mypy --strict` pass;
- `python -m pipeline plan` on the laptop workspace reports **zero** stale or
  new units after each package (the adopted outputs stay current);
- engine moves are verified by running the moved engine on the synthetic
  fixtures in `tests/` and on the committed pilot blocks under `data/work`,
  comparing digests with the outputs already on disk — small, read-only on the
  real workspace, seconds to minutes;
- `digest_golden` of `data/golden` is recomputed once at the end and must
  equal today's `0e543e65…` (14 tables, 98,077,250 rows), proving nothing was
  disturbed.

The release stage is validated the same way: `dataset` and `packs` run
*from* the existing `data/golden` (they read, they do not rebuild), and
`publish` is exercised against a local fsspec backend and then a staging S3
prefix with `--dry-run` first.

A from-scratch run on the GCP VM is **not** part of this refactor. It is the
procedure for the next release, when the owner bumps `pins.lock`; package 5
delivers the VM script and documents that procedure without executing it.

Work packages, in order (each is one implementation plan):

1. **Runtime core**: `pipeline/` package, config schemas and loader, one
   ledger with relative paths, fingerprint rule, resource guard, runner with
   `plan`/`status`, path migration, symlink removal. No engine changes.
2. **Sources**: adapter contract, source YAML and `pins.lock`, migrate the
   13 sources (simple ones to single modules), GCS mirror in the download
   stage, retire the hard-coded lists.
3. **Engines as stages**: reconcile, cells, cities, normalize_cells wrapped in
   the stage contract; policies to YAML with per-country splitting; reviews
   to `config/reviews`; evaluation as a stage; legacy v0 removed.
4. **Release**: dataset assembly, licences and card generation, packs, S3
   publish, registry entry.
5. **Release procedure**: VM setup script, the documented monthly procedure
   (`pins update` → `plan` → `run --through publish` → registry entry), a
   staging publish of today's dataset from the laptop, and the registry pull
   request text drafted for the owner. No full run.

Throughout, the briefs to implementing agents state: do not run `pipeline run`
on the real workspace, do not delete or rewrite files under `data/` other than
through the migration command, and keep free disk above 5 GB.

## 10. Out of scope

Changes to the geographic rules or the dataset's content; the client
packages (`src/thereabouts/client`, `clients/node`) beyond the shared
cell-encoding module; renaming the GCS bucket; the GitHub repository's
public visibility, PyPI and npm releases, and the registry pull request
itself, which the owner submits.
