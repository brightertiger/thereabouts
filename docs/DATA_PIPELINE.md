# Thereabouts pipeline

The `pipeline` package supplies configuration, resumable source acquisition,
normalization, and verified migration for the Thereabouts data build. Download
and normalize discover units from source YAML and `pins.lock`; geographic
engines remain retained stages until package 3. The old `build_data` entry points
remain usable only on their original unmigrated workspaces.
[PIPELINE_STATUS.md](PIPELINE_STATUS.md) records the implemented boundary,
measurements, and remaining work.

A **stage** owns one kind of work. A **unit** is a resumable item within a stage,
such as a source, country or H3 block. The **ledger** records a completed unit's
input fingerprint and the size and SHA256 of every output. Unit definitions are
retained separately from completions so that invalidating a completion schedules
work instead of removing it from the plan.

## Inspect an existing workspace

Install dependencies in this checkout, then use its interpreter. Every relative
`data/pipeline-work/` path below belongs to this checkout, never to the existing
workspace passed with `--root`:

```sh
mkdir -p data/pipeline-work/tmp
export TMPDIR="$PWD/data/pipeline-work/tmp"
UV_CACHE_DIR="$PWD/data/pipeline-work/cache" uv sync --all-extras --locked
.venv/bin/python -m pipeline plan --root /path/to/existing/data
.venv/bin/python -m pipeline status --root /path/to/existing/data
```

`plan` reads the ledger and verifies output hashes. It reports current, stale and
new units, with `--details` explaining noncurrent units. Intentionally absent
reconciliation outputs and offloaded raw files have a separate `absent` count.
Their recorded hashes keep unchanged consumers current; a consumer that must run
first requires its missing direct inputs to be materialized. Remote custody is
recorded evidence; migration validation does not check remote objects.

For a legacy ledger, `plan` prints **SIMULATED ADOPTION** and verifies the proposed
migration in memory. It does not alter the saved identities or any workspace
file. After real migration, the same command compares the saved identities with
the current declarations and reports changes normally. `--ledger /path/to/copy`
selects another completion database for read-only inspection; artifact paths
still belong to `--root`.

`status` reports recorded units, recorded output bytes, locally present bytes and
missing files per ledger stage. It does not hash payloads or assert completion.
Read-only commands open SQLite with `mode=ro&immutable=1`, create no sidecars, and
refuse a nonempty WAL rather than silently ignore recent commits. Stop and
checkpoint any existing writer before inspection. No command here discovers or
contacts an upstream service.

Use `--report /path/outside/data/plan.json` to save a plan or status report. Dry-run
migration reports default to `.cache/pipeline/migration.json` in the current
working directory. Reports must remain outside the inspected data workspace.

## Configuration and identity

Structured defaults are merged with `config/sources/*.yaml`, then
`config/pipeline.yaml`, an optional `config/profiles/<name>.yaml`, and `key=value`
overrides. Source adapters declare a typed `Options` dataclass; unknown adapter
options fail during configuration loading:

```sh
.venv/bin/python -m pipeline plan --profile laptop \
  --root /path/to/existing/data resources.workers=2
```

Unknown keys, invalid types, invalid paths, missing stage packages, dependency
cycles and invalid resource limits are errors. The schema lives in
`pipeline/config`. Only the workspace root can be absolute; its configured
subdirectories and persisted artifact paths are relative to it. Paths cannot
escape through `..` or a symlink. Read-time symlink containment checks do not
replace persisted logical paths with resolved machine paths.

Each stage declares its production package files, configuration sections,
source pins and native-library dependencies. SHA256 of those inputs is its
identity. Native versions must match `uv.lock`; Shapely's GEOS version is also
included. Tests, fixtures, documentation and client source files are excluded.
The explicit `thereabouts.format.CELL_FORMAT_VERSION` participates where the cell
codec matters. Adding that constant does not change the encoding.

A unit hashes that identity, its parameters and the recorded hashes of the
upstream outputs it reads. A code change may make a consumer provisionally stale
in a plan; if rebuilding the upstream unit produces identical bytes, execution
can still skip that consumer. Migration retains original input digests as
adoption evidence while source/engine-specific discovery is being ported.

## Sources and frozen versions

Each `config/sources/<name>.yaml` declares a name, adapter module, schema family,
upstream, attribution, byte limits, and typed normalization options. Adding a
source does not require editing a source-name list. The thirteen retained sources
are enabled. `plate_country` is declared but disabled because the retained
workspace has no build or payload inventory for it; enabling it requires an
explicit reviewed pin proposal.

`pins.lock` records exact input names, sizes, SHA256, upstream metadata, and the
inventory used by the retained source manifest. An inventory found later under
the same raw directory is not assumed to describe the built output. In particular,
the committed geoBoundaries lock uses the manifest's resolved inventory.

```sh
# Read-only: compare the lock with an already-built workspace's exact manifests.
.venv/bin/python -m pipeline pins check --from-workspace /path/to/existing/data
# Import explicitly reviewed versions/checksums; this command writes only the lock.
.venv/bin/python -m pipeline pins update ghsl --from-file reviewed-pins.yaml
# Bootstrap exact versions from built manifests, without downloading or running stages.
.venv/bin/python -m pipeline pins update --from-workspace /path/to/existing/data
```

`pins update` requires `--from-file` or `--from-workspace`; neither it nor a stage
silently selects latest. A proposal uses the same typed format as `pins.lock`.
`pins check` without `--from-workspace` checks the lock structure and hashes only;
it does not claim that upstream or remote mirror payloads were verified.

On a separate writable workspace, `run --through normalize` downloads every
enabled source and publishes its normalized manifest. Configure
`storage.gcs_raw=gs://BUCKET/raw` for future production execution; local tests use
`storage.gcs_raw=file:///absolute/path/to/a/mirror` or `memory://mirror`.
The fsspec GCS driver is pinned in `uv.lock`. No cloud operation was used to test
this implementation.

Downloads reuse verified local files, then try the mirror, then the frozen
upstream URL. Each payload is copied to `sha256/<checksum>` in the mirror and
rehashed before the download unit can complete. Historical offload prefixes are
retained as fallback restore locations, with their original custody evidence;
restored bytes must match the recorded size and SHA256. Adoption itself does
not contact these locations. Interrupted downloads resume at file boundaries,
not by appending an unverified HTTP response to a partial file.

Normalize streams bounded partitions and retains source identities, licences,
and rejection evidence. GeoNames extraction/index and Overture parent-index
caches are regenerated before row conversion and remain tracked normalize
outputs. Plate parsing rules now live in YAML. PDF evidence requires the
configured Poppler `pdftotext` version (25.11.0 was measured on this laptop);
this is a prerequisite for future PDF normalization, not evidence of the version
used by every historical build.

## Migration and its boundary

First review a dry run:

```sh
.venv/bin/python -m pipeline migrate --dry-run --root /path/to/existing/data \
  --report .cache/pipeline/migration.json
```

The report identifies every retained/dropped legacy row, path relocation, JSON
rewrite and proposed JSON evidence copy, with before/after checksums. The mapping
rules are in `pipeline/migration/mapping.py`; unrecognized stages, conflicting
artifacts and missing/corrupt outputs stop adoption. The migration never repairs
a discrepancy by rebuilding.

Base-cell records are matched to the selected immutable base by block/country,
original table identity and content hash. They cannot be verified through an
active `golden` symlink that now points at normalized cells. Superseded pilot,
normalization and lookup receipts are dropped; the old ledger remains backed up.
GeoNames extraction/index and Overture index outputs remain owned by normalize.
Present bytes must re-verify. Deliberately deleted caches are adopted as absent
only under `work/geonames/` and `work/overture/`, tied to the matching normalize
source. A future normalize rebuild must regenerate those caches first. Reconciliation
absence is allowed only under `reconciled/` and `work/reconcile/`; those units
retain recorded hashes and `outputs_absent`.
Missing raw payloads require an offload receipt bound to the exact source
manifest. Present corrupt files are never excused by either mechanism.

Six plate-source auxiliary JSON files originally lived in the repository. The
migration verifies their original recorded hashes, proposes byte-identical
copies under `raw/plates/configuration/<sha256>/`, and makes their references
portable. JSON repairs preserve indentation, separators, key order and unchanged
tokens, and update file-record hashes only when the original bytes match;
a historical review whose hashes do not match current evidence is not silently
rebound to that evidence. Parquet and SQLite data payloads are never rewritten.

The reviewer, after reviewing the proposed changes, applies the combined steps:

```sh
.venv/bin/python -m pipeline migrate --root /path/to/existing/data \
  --report .cache/pipeline/migration-applied.json
.venv/bin/python -m pipeline migrate check --root /path/to/existing/data
.venv/bin/python -m pipeline plan --root /path/to/existing/data
```

`migrate paths` performs the optional path-only step; `migrate adopt` also performs
any remaining path changes. Prefer the combined command. A path-only ledger is
still legacy and its printed stage counts describe the subsequent adoption.
`migrate check` is read-only. Applying the migration again checks the existing
adoption and makes no further workspace changes.

When a ported implementation replaces a retained stage, run
`migrate handover --dry-run` against its adopted ledger. It requires identical
independently discovered unit keys and re-verifies every present output. Only
identity, unit parameters and input hash may change; outputs and completion
history stay intact. A real `migrate handover` applies that one-time proposal.
The command refuses a second identity change after handover. Against a legacy
ledger, its dry run first simulates adoption; it cannot apply a handover until
adoption has actually been applied. Simulated zero-stale results check mapping
and hashes only, not engine equivalence.

Apply and recovery first check write permission on every target directory and
print exact commands to enable and restore it. They make no workspace changes
when permission is missing. An existing backup must match the original ledger
hash, including across separate paths/adopt operations.

The apply operation saves `work/ledger.pre-migration.sqlite3`, journals the
original JSON metadata, publishes changed JSON atomically, and replaces the
prepared ledger last. A subsequent apply recovers an interrupted transaction
before preparing another one. Recovery refuses metadata that was manually
changed after interruption. Stop old builders before migrating, and do not run
them against an adopted workspace. Removing the old checkout-name symlink is a
separate reviewer action after migration verification; the migration does not
remove it because it lies outside the worktree.

The real workspace is read-only for migration implementation and validation.
The opt-in world test applies migration to a copied ledger and copied JSON
inside this worktree, then checks that ledger using the original payloads as read-only evidence. It
copies no Parquet tree and creates no hard links.

## Execution and resource limits

The runtime runner implements `run [--through STAGE | --only STAGE]`. Download
and normalize execute frozen source pins. Engine declarations still support
retained-output inspection and refuse rebuilding until package 3. Use source
execution only on a separate writable workspace, never the protected existing
workspace used for this redesign.

Before each unit starts, the resource guard requires at least 5,000,000,000 free
disk bytes, the configured workspace allowance and process RSS headroom. It
pauses and logs its reason instead of failing on resource pressure. Concurrent
workers share declared disk reservations. Workspace size is measured at most
once per `resources.workspace_scan_seconds` (60 seconds by default), outside the
admission lock; completed output bytes and active reservations are accounted for
between scans. Streaming source normalizers account for each allocation and
refresh the measured total at their unit boundary, including removed scratch
files. Free disk and RSS are checked before every admission.
These admission checks do not impose limits on arbitrary stage code.
The laptop profile defaults to one worker, one DuckDB thread, 1 GB DuckDB memory
and a 2 GB RSS allowance. Engine-specific limits and measurements follow with
their ports.

Run logs and summaries go in `work/runs/<UTC timestamp>/`. Atomic outputs use a
sibling `.part` file, fsync and replacement; failed publication does not complete
a unit. Stage finalization is idempotent and retried even when every unit was
already committed, so an interrupted manifest publication is recoverable.
`--only` refreshes the selected stage's declared ancestors when needed; it does
not run unrelated units. `invalidate STAGE [--units ID ...]` removes completion
records only, retaining unit definitions and payloads. It requires an adopted ledger and a
workspace writer lock. Do not use either write command against the real workspace
during migration validation.

## Validation and historical evidence

```sh
.venv/bin/pytest --basetemp=data/pipeline-work/pytest
.venv/bin/ruff check
.venv/bin/ruff format --check
.venv/bin/mypy
# Explicit opt-in; reads real payloads and writes only copies in this worktree.
THEREABOUTS_PIPELINE_DATA=/path/to/existing/data .venv/bin/pytest \
  tests/pipeline/test_world_adoption.py --basetemp=data/pipeline-work/world-proof -s
```

The ordinary tests use small synthetic inputs and the existing network guard.
The world proof has the existing `world` marker, enforces a worktree-local test
output and checks disk before copying. It is excluded unless the environment
variable is supplied. Leave capacity for its copied ledger/metadata in addition
to any concurrently running scratch job.

The [historical acquisition guide](history/source-and-golden-pipeline.md),
[normalization results](history/city-normalization-results.md),
[policy investigation](history/city-normalization-plan.md) and
[content-neutral integration proof](history/rename-integration.md) retain the
original measurements and commands. They are historical evidence rather than
instructions to rebuild the protected workspace. [SERVING_FORMAT.md](SERVING_FORMAT.md)
still defines the unchanged pack format. [GOLDEN_DATASET.md](GOLDEN_DATASET.md)
is the current golden table schema until the release README replaces it. The new release README layout draft is
[DATASET_README.md](DATASET_README.md); dataset and pack generation are package 4.
