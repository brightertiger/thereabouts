# Thereabouts pipeline

The `pipeline` package builds Thereabouts from frozen sources through verified
geographic and lookup tables. All stages share configuration, a relative-path
ledger, resource admission, and one fingerprint rule. The former `build_data`
package has been removed. Versioned release assembly and fsspec publication are
implemented; real pack writing awaits the Rust client merge.

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

Pipeline runtime libraries are declared in the `pipeline` dependency group;
`dev` includes that group plus test, lint and typing tools. A runtime-only checkout
can use `uv sync --group pipeline --no-default-groups --locked`. The development
command above remains appropriate for running the full gate. Keep the locked
native library versions unchanged when combining this branch with the client.

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

Structured defaults are merged with `config/sources/*.yaml`, `config/engines.yaml`, `config/release.yaml`, then
`config/pipeline.yaml`, an optional `config/profiles/<name>.yaml`, and `key=value`
overrides. Each source declares an `options_schema` dataclass, loaded without importing
its normalizer. Unknown adapter options fail during configuration loading:

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

Each stage declares production entry modules, configuration sections and
native-library dependencies. Its identity hashes the transitive closure of local
Python imports, including shared helpers and package initializers. Runtime
implementation, the stage contract and the configuration schema are excluded.
The source stages share only their controller identity; each source unit adds
its own adapter import closure, settings, pin and policy-file hashes. A pin or
adapter edit therefore invalidates that source and consumers of its outputs. Native versions must match `uv.lock`; Shapely's GEOS version is also
included. Stages that use SQLite also hash its actual runtime library version,
because SQLite ships with Python rather than as a lockfile distribution. The
committed `.python-version` selects Python 3.12.8, used by the retained SQLite
artifacts; reproduction was measured with SQLite 3.47.1. Tests, fixtures, documentation and client source files are excluded.
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

`pins.lock` records, per source, exactly what its proposer produces: logical
input names, sizes, SHA256, ETag and Last-Modified validators, the release
string and the proposer's metadata. An unchanged refresh therefore merges as
unchanged. It stores no duplicate inventory document. Download inventories are
reconstructed from those file records and metadata. Large plate policies live in
`config/policies/plates/`, outside the structured configuration graph, and are
hashed only into the units that use them. An inventory found later under
the same raw directory is not assumed to describe the built output. In particular,
the committed geoBoundaries lock uses the manifest's resolved inventory.

```sh
# Read-only: compare the lock with an already-built workspace's exact manifests.
.venv/bin/python -m pipeline pins check --from-workspace /path/to/existing/data
# Resolve upstream, keep each payload in the workspace raw store (and the
# storage.gcs_raw mirror), and write a candidate lock plus a file-level diff.
.venv/bin/python -m pipeline pins update ghsl --root /path/to/workspace
# Review .cache/pipeline/pins-proposal.yaml and pins-proposal.diff.json.
# Accept those exact bytes without contacting upstream again.
.venv/bin/python -m pipeline pins update ghsl \
  --from-file .cache/pipeline/pins-proposal.yaml --accept
# Bootstrap from a built workspace's manifests, without upstream access.
.venv/bin/python -m pipeline pins update \
  --from-workspace /path/to/existing/data --accept
```

Only `pins update` resolves upstream versions. Without `--accept`, it writes a
proposal and a JSON diff while leaving `pins.lock` unchanged. `--proposal PATH`
selects the candidate output; its companion diff uses `.diff.json`. Inspect the
candidate before accepting it with `--from-file ... --accept`; running a fresh
upstream proposal with `--accept` accepts freshly resolved bytes instead.
An unchanged inspection preserves the previous pin, including its timestamp.

Adapters expose `propose(settings)`. Catalogs in `config/proposals/` declare file
selections, GitHub commit/release selectors, IANA versions and Overture listing
prefixes. geoBoundaries resolves every selected layer to a complete commit and
repairs contradictory ALL records through the country's API. GeoNames and OSM
release dates come from publisher Last-Modified evidence. GHSL's reviewed
release URL is explicit in its catalog; its checksum is recomputed. Plate URLs
remain the reviewed evidence set in the plate policy, including frozen Wikipedia
revisions; changing that set requires policy review. The disabled plate-country
catalog is empty until the owner selects evidence URLs.

Upstream proposals require the workspace that keeps their payloads (`--root` or
`--profile`). Each payload is HEADed, then streamed once into
`raw/<source>/sha256/<sha256>` while it is hashed, and copied to
`storage.gcs_raw` when one is configured, so the later download is a local or
mirror restore even if upstream has rewritten the file since. Per-file progress
(`raw/<source>/proposal-progress.json`) lets an interrupted proposal reuse every
payload whose strong ETag or Last-Modified and size are unchanged. Conditional
requests and size/ETag checks reject an upstream object changing during
inspection. Publisher checksums are verified where they exist: the DB-IP MD5
reviewed in its catalog, and the geoBoundaries Git LFS object id, which must
equal the SHA256. Requests name the project and its URL in `User-Agent`. Tests
use only loopback HTTP. No real upstream proposal has been exercised yet.
`pins check` without `--from-workspace` checks lock structure and hashes only;
it does not verify upstream availability or remote mirror custody.

On a separate writable workspace, `run --through normalize` downloads every
enabled source and publishes its normalized manifest. Configure
`storage.gcs_raw=gs://BUCKET/raw` for future production execution; local tests use
`storage.gcs_raw=file:///absolute/path/to/a/mirror` or `memory://mirror`.
The fsspec GCS driver is pinned in `uv.lock`. No cloud operation was used to test
this implementation.

Raw inputs are content-addressed: `raw/<source>/sha256/<sha256>`, with
`raw/<source>/inventory.json` mapping each logical name to its object.
Normalizers read by logical name through `SourceContext.input`, so a new pin
with the same name and new bytes is a new object; names that pin identical
bytes share one. Downloads reuse a verified local object (one that fails
verification is deleted and fetched again), then restore from
`storage.gcs_raw/sha256/<sha256>`, then fetch the frozen upstream URL with the
pinned conditional headers. Historical offload prefixes are retained as
fallback restore locations, with their original custody evidence; restored
bytes must match the recorded size and SHA256. Each object is then mirrored;
an existing mirror object is vouched for by its size and the service's MD5 or
CRC32C rather than read back.

Transfers write to a `.part` file while hashing. A body that ends early, a reset
connection, 408, 429 and 5xx are retried with jittered backoff (doubling from
`limits.backoff_seconds` up to `limits.timeout_seconds`) until `limits.retries`
consecutive failures or `limits.patience_seconds` (15 minutes) pass without new
bytes; any progress resets both. Retries resume the part with HTTP `Range`
when the publisher answers 206, and restart from byte 0 when it ignores the
range, answers 416, or the resumed object fails its checksum. Other 4xx
statuses, such as 404 and 412, fail at once. Mirror reads and writes use the
same retry rules.

Normalize streams bounded partitions and retains source identities, licences,
and rejection evidence. GeoNames extraction/index and Overture parent-index
caches are regenerated before row conversion and remain tracked normalize
outputs. Plate parsing rules now live in YAML. PDF evidence requires the
configured Poppler `pdftotext` version (25.11.0 was measured on this laptop);
this is a prerequisite for future PDF normalization, not evidence of the version
used by every historical build.

## Geographic stages

Each geographic stage supplies its own parameter callback. Shared runtime code
only applies the returned policy, reservation and discovery-refresh decision.
`config/engines.yaml` names the land, urban-centre, registration and plate-country
source roles; source `kind` selects place/area inventory and lookup behavior.
Changing a source's name does not change those decisions. Unknown role references
and incompatible source kinds fail configuration loading before workspace writes.

Reconciliation extracts and links each country, builds canonical entities and
land, then verifies country quality. Cells index resolution-3 blocks, derive
compact resolution-8 answers, and retain an immutable base manifest. Cities
build canonical city indexes and mappings; evaluate checks the pilot and its
policy-bound review. Normalize-cells applies city semantics and checks stored
output. Lookups preserve every source row while adding code or spatial links,
then enforce cross-table references and publish the final manifest.

```sh
# Use a separate writable workspace with reviewed pins and local inputs/mirror.
.venv/bin/python -m pipeline plan --root /path/to/new/workspace
.venv/bin/python -m pipeline run --root /path/to/new/workspace --through reconcile
.venv/bin/python -m pipeline run --root /path/to/new/workspace --through lookups
```

These are future build commands, never commands run against the protected data
for this refactor. The default selection is worldwide. For a small development
workspace, `engines.countries=[ZZ] engines.blocks=[83754efffffffff]` selects units;
every country required by a selected block must be included. Full pilot
acceptance still requires all configured pilot countries. A newly built block
index refreshes discovery during the same run. Corruption invalidates its unit;
unchanged verified outputs are skipped. Missing adopted inputs regenerate before
a consumer actually runs, including the deliberately deleted source caches and
reconciliation outputs.

`config/policies/reconcile.yaml` holds reconciliation conventions. City policy
is `config/policies/cities/common.yaml` plus country files. The
[city granularity rules](city-policy.md#city-granularity-rules) define their
city-part and independent-neighbour conventions. Their exact resolved
canonical fingerprints match the previous JSON; tests cover every two-letter
country projection. `config/reviews/cities-pilot.yaml` retains the historical
owner approval and two precisely scoped boundary exceptions. Editing the policy
requires a matching reviewed fingerprint. Review validation occurs before any
writable workspace opens. Evaluation fixtures live under `eval/`, outside build
identities; changing a fixture alone does not regenerate geographic data.
Evaluation is an execution prerequisite for normalization: a failed gate stops
the run. Its receipt is not consumed as geographic data, so a changed review
alone does not rebuild unaffected countries. Country units hash their resolved
common and country policy; blocks hash the policies of their contributing countries.

The optional `plate_country` stage derives syntax, priors, coverage and an
inference bundle from normalized pinned evidence. It has zero units while its
source is disabled. Its resolver preserves ambiguity and verifies bundle/table
checksums before use. The retained workspace has no reviewed plate-country raw
inventory, so only synthetic inputs exercise this engine here.

New outputs use configured `reconciled/`, `cities/`, `cells/` and `work/` paths,
with immutable input-hash subdirectories. `cells/base/current.json` points to the
base manifest; `cells/current.json` points to the verified normalized manifest.
Every artifact record is relative to the workspace root. The release schema and
worked reads are in [../dataset/README.md](../dataset/README.md). The pack stage calls the client-owned
`thereabouts._core.write_pack(dataset_dir, family, output_dir, options)` binding.
The old pipeline pack format and exporters have been removed; real pack builds
require the Rust client branch to merge.

The old controller-specific tests were retired with their controllers. Their
shared-runtime replacements and preserved source/engine decisions are tested
under `tests/pipeline/`. To reproduce the bounded read-only pilot proof, keep
scratch in this checkout:

```sh
THEREABOUTS_PIPELINE_DATA=/path/to/existing/data TMPDIR="$PWD/data/pipeline-work/tmp" \
  .venv/bin/pytest tests/pipeline/test_pilot_equivalence.py -q \
  --basetemp data/pipeline-work/pilot-proof
```

This reads existing normalized sources, reconstructs only Malaysia and the
complete land features intersecting one block's search window, writes locally,
and compares both radius settings with the retained pilot Parquets. It does not
execute a stage against the existing workspace.

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
and normalize execute frozen source pins, followed by the ported geographic
engines and release stages. Use execution only on a separate writable workspace,
never the protected existing workspace used for this redesign.

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
and a 2 GB RSS allowance. Engine-specific limits live in `config/engines.yaml`; the completed pilot
measurements are in the status report.

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

The client owns the current [binary format](../dataset/pack-format.md) and
writer. The [dataset README](../dataset/README.md) is the rendered release
schema, measured inventory and runnable reader guide.

Logical table comparisons are available through `python -m pipeline digest
DATASET --output REPORT.json --temp-dir SCRATCH [--compare BASELINE.json]`.
The command reads the dataset and writes only to the explicitly separate report
and scratch directories. Row order, partitioning and Parquet metadata do not
change its digest.

Engine grid sizes, batch counts, SQLite caches and DuckDB budgets are supplied
from configuration. Engines no longer construct fallback limits. The table
contract still requires H3 resolution 8 and the shared block codec requires 3;
configuration validation rejects incompatible changes before execution.

Each enabled source's `download_bytes` allows twice the bytes in its retained
pin. The source YAML records that measured baseline. This is a capacity allowance
for one release up to twice the retained size, not a prediction of upstream growth;
review the proposal's sizes before accepting a larger release. Disabled
`plate_country` remains at zero until its inputs are chosen. The VM profile sets
`storage.gcs_raw` to the retained raw-mirror bucket; no bucket access was made
while validating these changes.

## Versioned releases

`dataset`, `packs` and `publish` are registered stages but discover no units until
`release.enabled=true` and a version is configured. Versions use `YYYY.MM[.patch]`;
quote numeric-looking strings in YAML or dot-list arguments, for example
`'release.version="2026.10"'`. A version's contents cannot be replaced in place.
Fill the contact, citation, documentation and release bucket region in
`config/release.yaml` before a public release.

The dataset stage consumes the completed `lookups/manifest/current` unit, whose
manifest includes normalized cells and country catalogues. It checks each input's
SHA256, row count and schema before and after reading. Cell files group resolution-3
blocks by a resolution-1 parent (up to 49 blocks); the world routing has at most
842 groups. Within each file, every retained block occupies one Parquet row
group, sorted by block. The cells manifest entry's `blocks` list maps each block
to its zero-based `row_group` and `rows`. Empty blocks are omitted. Buffering is
bounded by one block's reference-cell count; `row_group_rows` controls other
tables. The full reader contract is in the dataset README's Cell keys section.
`config/dataset.yaml` declares all fourteen retained table schemas, their keys,
column meanings, units and physical nullability. Additional optional plate tables
must be given reviewed schemas there before release; those sources are disabled.

Parquet, documents, per-table logical digests and the manifest are built in an
owned temporary directory, then published together. The output cap applies before
each write, including Parquet footers. Resource admission accounts for output
bytes and reserves digest scratch. Logical digests preserve duplicates and do not
depend on row order, compression or file boundaries. `CHANGES.md` compares with
`release.previous_version` when supplied; the prior release is verified first.
The prior digest is an explicit unit parameter. The current manifest references
all output files and is the last local publication boundary.

`release prepare` is a standalone use of the same assembler for an existing,
completed snapshot. It requires a separate output root; it neither migrates nor
creates a ledger for the input. Its identity uses the same stage fingerprint and
an explicit input manifest hash. Both entry points verify the lock against the
normalized input inventories; changing pins without rebuilding cannot silently
relabel that input evidence. Prepare only from a completed snapshot of the same
build: this command does not run the source workspace or repair stale stages.
For the measured read-only subset:

```sh
.venv/bin/python -m pipeline release prepare \
  --from /path/to/existing/data/golden --root "$PWD" --version 2026.10 \
  paths.dataset=data/dataset paths.work=data/pipeline-work/work \
  'release.countries=[MY,SG]' \
  'release.blocks=[836505fffffffff,836500fffffffff,836526fffffffff]' \
  release.dataset.max_output_bytes=412318215 resources.max_workspace=3000000000 \
  'release.packs.families=[]' --report data/pipeline-work/release-prepare.json
.venv/bin/python scripts/verify_dataset_readme.py data/dataset/2026.10
```

The example runner needs the reader's optional `pandas`, `pyarrow`, `duckdb` and
`h3` packages. Pandas is not a pipeline runtime dependency. This task tested it
using worktree-local copies of already-installed pandas 2.2.2 and NumPy 1.26.4;
the pipeline environment retains its locked NumPy 2.3.5. No package was fetched.
The README template is `config/templates/dataset-readme.md`; the rendered copy
is committed as [../dataset/README.md](../dataset/README.md).

`packs` delegates each configured family to
`thereabouts._core.write_pack(dataset_dir, family, output_dir, options)`. The
adapter adds source notices and input provenance and re-verifies returned files.
The writer is now exercised through the runner with grouped synthetic Parquet,
including core-before-forward dependencies, full verification, local console
installation, idempotence and corrupt archive rejection. The real MY/SG proof
is recorded in [CLIENT_RELEASE_MEASUREMENTS.json](../../tests/benchmarks/measurements/CLIENT_RELEASE_MEASUREMENTS.json).

For an already prepared dataset, run only its local release stages:

```sh
python -m pipeline release packs --root /path/to/release-workspace --version 2026.10 \
  paths.dataset=dataset paths.packs=packs paths.work=work \
  'release.packs.families=[core,postal,airports,locode,phone,ip]'
thereabouts --data-dir /path/to/store data install core postal airports locode phone ip \
  --from /path/to/release-workspace/packs/2026.10 --yes
```

This command registers the verified prepared dataset in a local ledger and runs
the packs stage; it never schedules acquisition or geographic stages. Core is
an explicit prerequisite for every forward family. Its path is supplied as the
writer's core_pack option, so forward manifests pin its exact catalogue.
A final index unit depends on every requested family and produces index.json.
Each family also produces a deterministic POSIX ustar archive. Their hashes and
sizes are the client release-index records; --from accepts this local directory.
Publication inventories include the index and archives at packs/<version>/.

The real snapshot has no plate tables, and normalized/plates_country is absent.
Plates remains unavailable in this release proof; no empty or invented
plate pack is substituted. Core includes the city-name index. The default
six-pack selection is core plus five forward packs. Writer/schema changes must
update the release identity; client source bytes are not hashed as native versions.

Publication reads a verified dataset and the configured pack-family manifests.
Each object is uploaded through an fsspec transaction, re-hashed from the backend,
and skipped if already present with the correct size and checksum. Conflicting
objects are refused before uploading; investigate them instead of overwriting a
published version. The `<version>/_SUCCESS` inventory is committed last.
`release upload --dry-run` performs inventory and remote checks without creating
objects or a success marker. The runner's `publish` stage performs the upload;
`release upload` is its explicit standalone counterpart.

```sh
.venv/bin/python -m pipeline release upload --root "$PWD" --version 2026.10 \
  paths.dataset=data/dataset 'release.packs.families=[]' \
  "storage.s3_release=file://$PWD/data/pipeline-work/local-release" --dry-run
# Omit --dry-run only for the explicitly selected destination.
.venv/bin/python -m pipeline release registry --root "$PWD" --version 2026.10 \
  storage.s3_release=s3://OWNER-DECISION-BUCKET \
  --report docs/pipeline/release-registry.yaml
```

The same generic upload implementation supports `memory://` and local files in
tests. Actual S3 use requires an installed fsspec S3 driver (`s3fs`) compatible with
the locked fsspec version; that optional driver is not installed or locked in this
checkout. Its dependency resolution and real multipart behavior remain owner
validation before cloud publication. GCS raw-mirror support is separate and uses
the existing locked `gcsfs` dependency. No remote backend was contacted here.

The owner-run [release procedure](release-procedure.md) covers migration and
symlink removal, GCP provisioning, the monthly pin/build cycle, staging checks and
registry submission. The VM scripts and registry PR text are drafts for future
execution; no VM or cloud publication was performed during this task.
