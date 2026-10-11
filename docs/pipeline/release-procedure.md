# Building and releasing Thereabouts

This procedure is for the owner after reviewing the pipeline changes and merging
the client writer. It preserves the completed workspace, builds a new immutable
monthly version, validates it in staging, and then publishes that exact version.
The commands below were written for future execution. No VM was provisioned, no
real migration was applied, and no cloud upload was made during this task.

The measured development sample is an Apple M2 with 8 GiB RAM. The release proof
contains Malaysia/Singapore catalogues and three spatial blocks, not a world
release: 181,548 rows, 14 tables and 8,802,046 bytes. Its three reader examples and
local/memory publication tests passed. See
[PIPELINE_RELEASE_MEASUREMENTS.json](https://github.com/brightertiger/thereabouts/blob/main/tests/benchmarks/measurements/PIPELINE_RELEASE_MEASUREMENTS.json) and the
[dataset README](../dataset/README.md). VM capacity and cloud throughput have not been
measured.

## Finish the merge prerequisites

Merge the reviewed pipeline and Rust client work together. The pipeline calls
`thereabouts._core.write_pack(dataset_dir, family, output_dir, options)` and owns
no pack-format implementation. The release groups blocks under their r1 parent,
with one row group per retained r3 block, sorted by block. Each cells manifest
entry's `blocks` index gives the block ID, zero-based `row_group` and `rows`.
Update the Rust writer to route through that index, then validate its packs
and clients against a complete release. The small dataset subset validates
Parquet readers; it is not a proof of every pack's catalogue-reference closure.

Resolve and commit a compatible `s3fs` dependency and its transitive lock with the
owner's approved package access. The current checkout has locked fsspec but no S3
driver. Repeat the local and memory tests, then validate real S3 multipart and
checksum behavior in the owner's staging bucket. Do not infer cloud support was
exercised from the local tests. Real upstream `pins update` availability likewise
needs owner validation; automated tests use loopback HTTP only.

Fill `config/release.yaml` with the public contact, citation, documentation URL
and release bucket region. Choose separate staging and public destinations and
an AWS identity allowed to create and read the release objects. Replace all
`OWNER DECISION` placeholders before a public release. Keep the database under
ODbL 1.0 and preserve the generated per-source attribution.

## Apply migration on the existing workspace

Do this once, before moving the workspace to the build machine. Stop and checkpoint old
builders first. Keep the main checkout and its data in place until verification
passes. The [migration contract](README.md#migration-and-its-boundary) describes the
approved repair classes; inspect the fresh dry-run report for its file inventory. The current proposal repairs 588
existing JSON files, imports 6 evidence files and adopts 85,577 units. It does not
rewrite Parquet payloads. The four absent GeoNames/Overture caches total
3,260,159,017 bytes; future normalization must regenerate them.

Run from the reviewed pipeline checkout. Keep reports and temporary files here.
The permission list currently contains 302 existing directories; derive it again
from a fresh dry run rather than using a stale list.

```sh
set -eu
PIPELINE_DATA="$PWD/data"
mkdir -p data/pipeline-work/tmp .cache/pipeline
export TMPDIR="$PWD/data/pipeline-work/tmp"
export UV_CACHE_DIR="$PWD/data/pipeline-work/cache"
.venv/bin/python -m pipeline migrate --dry-run --root "$PIPELINE_DATA" \
  --report .cache/pipeline/migration-owner.json
.venv/bin/python - <<'PY'
import json
from pathlib import Path
value = json.loads(Path('.cache/pipeline/migration-owner.json').read_text())
Path('.cache/pipeline/writable-directories.txt').write_text(
    '\n'.join(value['writable_directories']) + '\n')
PY

restore_pipeline_permissions() {
  while IFS= read -r directory; do
    chmod a-w "$PIPELINE_DATA${directory:+/$directory}"
  done < .cache/pipeline/writable-directories.txt
}
trap restore_pipeline_permissions EXIT
while IFS= read -r directory; do
  chmod u+w "$PIPELINE_DATA${directory:+/$directory}"
done < .cache/pipeline/writable-directories.txt

.venv/bin/python -m pipeline migrate --root "$PIPELINE_DATA" \
  --report .cache/pipeline/migration-owner-applied.json
.venv/bin/python -m pipeline migrate check --root "$PIPELINE_DATA"
.venv/bin/python -m pipeline plan --root "$PIPELINE_DATA" \
  --report .cache/pipeline/migration-owner-plan.json
restore_pipeline_permissions
trap - EXIT
```

The matching commands are `chmod u+w "$PIPELINE_DATA/<directory>"` before apply
and `chmod a-w "$PIPELINE_DATA/<directory>"` afterwards, for each directory in the
fresh report. An empty relative directory denotes the root itself. Apply and
recover also preflight permissions and print exact commands if any are missing.
Do not use recursive chmod on the workspace.

If interrupted, retain the report and directory list. Re-enable exactly those
directories and re-run the same `python -m pipeline migrate --root "$PIPELINE_DATA"`
apply; it recovers first. Then repeat check/plan and restore protection.
Do not delete the saved `work/ledger.pre-migration.sqlite3` or recovery journals.
A simulation checks mapping and recorded hashes only; application must be followed
by the ordinary on-disk plan with zero stale/new units. If native versions differ,
investigate the identity change; do not use handover to conceal it.

Only after those checks pass, remove the obsolete checkout-name symlink if one
still exists. Confirm first that it is a symbolic link whose target is the current
checkout, and remove only the link, never its target. Then repeat `migrate check`
and `plan` against the workspace.

These are owner application instructions, not actions taken by this agent.

## Prepare the build machine

The release build runs on a Linux machine with about 32 GB of memory and a 300 GB
persistent disk, provisioned by the owner. Provisioning creates billable
resources. The machine's service account needs read access to the raw-mirror
bucket and permission to create objects in it for accepted pins; grant those at
the bucket level, because the VM's access scope alone does not provide them.

Install base tools and uv, give the intended login user ownership of the
workspace and data directories, and install the reviewed merged checkout there.
Install the Rust toolchain that `core/Cargo.toml` requires (the inspected branch
declares Rust 1.99), for example `rustup toolchain install 1.99.0 --profile
minimal` and a checkout-local `rustup override set 1.99.0`. Enable systemd
lingering for the login user (`loginctl enable-linger`) and run long jobs in
tmux, so that a closed ssh session does not stop the user manager and kill them.
Then run `uv sync --all-extras --locked` from the checkout to build the client
extension. The checkout pins Python 3.12.8. Record SQLite, GEOS and other native
versions before comparing identities with another machine.

Before rebuilding plate evidence, check `pdftotext -v` against the pinned
`25.11.0` in `config/sources/plates.yaml`. The distribution package may differ;
provide the reviewed extractor instead of relabelling its version.

Transfer the **migrated** workspace to the data disk while writers are stopped.
Use an owner-controlled copy that preserves relative symlinks and file bytes;
never use a destructive `--delete` against the source workspace. Keep the source
copy until the new machine's read-only `migrate check` and `plan` verify the
copied data. Missing caches intentionally stay absent. The raw mirror supplies
raw payloads, not a substitute for the retained normalized and geographic outputs
and ledger. This transfer is an owner action.

The VM profile starts with the measured conservative one-worker, 1 GB DuckDB,
2 GB process budgets. Increase them only after measuring the VM; 32 GB installed
RAM is not a measured per-stage requirement. Keep at least 5 GB free. Derive a
workspace allowance from the copied workspace and currently available disk:

```sh
export PIPELINE_DATA=/path/to/data-disk
export TMPDIR="$PIPELINE_DATA/work/tmp"
export UV_CACHE_DIR="$PIPELINE_DATA/work/uv-cache"
mkdir -p "$TMPDIR" "$UV_CACHE_DIR"
PIPELINE_WORKSPACE_LIMIT=$(.venv/bin/python - <<'PY'
import os
import shutil
from pathlib import Path
from pipeline.runtime.resources import workspace_bytes
root = Path(os.environ['PIPELINE_DATA'])
print(workspace_bytes(root) + shutil.disk_usage(root).free - 5_000_000_000)
PY
)
export PIPELINE_WORKSPACE_LIMIT
```

The runtime still checks actual free space and pauses under pressure. The scalar
allowance does not reserve the entire disk or override the 5 GB floor.

## Monthly procedure

Keep the previous release locally for `CHANGES.md` and its verification. Choose a
new `YYYY.MM` version, or a positive `.patch` suffix for a corrected release; never
reuse a published version. Commit reviewed pin/policy changes before starting.
Run from the merged checkout on the prepared build machine, not the protected original copy.

```sh
set -eu
export PIPELINE_VERSION=2026.11
export PIPELINE_PREVIOUS=2026.10
export PIPELINE_STAGING=s3://OWNER-STAGING-BUCKET/thereabouts

# Propose first (payloads are kept in the workspace raw store and the mirror),
# then review the file-level diff and accept those exact bytes.
.venv/bin/python -m pipeline pins update --root "$PIPELINE_DATA" --profile vm
.venv/bin/python -m pipeline pins update \
  --from-file .cache/pipeline/pins-proposal.yaml --accept

plan_status=0
.venv/bin/python -m pipeline plan --root "$PIPELINE_DATA" --profile vm \
  release.enabled=true "release.version='$PIPELINE_VERSION'" \
  "release.previous_version='$PIPELINE_PREVIOUS'" \
  "resources.max_workspace=$PIPELINE_WORKSPACE_LIMIT" \
  "storage.s3_release=$PIPELINE_STAGING" --report .cache/pipeline/monthly-plan.json \
  || plan_status=$?
[ "$plan_status" -le 1 ] || exit "$plan_status"
# Exit 1 means the plan contains expected work; inspect its explanations.

.venv/bin/python -m pipeline run --root "$PIPELINE_DATA" --profile vm \
  --through publish release.enabled=true "release.version='$PIPELINE_VERSION'" \
  "release.previous_version='$PIPELINE_PREVIOUS'" \
  "resources.max_workspace=$PIPELINE_WORKSPACE_LIMIT" \
  "storage.s3_release=$PIPELINE_STAGING"
.venv/bin/python -m pipeline release registry --root "$PIPELINE_DATA" \
  --version "$PIPELINE_VERSION" storage.s3_release=s3://OWNER-PUBLIC-BUCKET \
  --report docs/pipeline/release-registry.yaml
```

For the first release, omit `release.previous_version` and leave it empty in the
configuration. Confirm country/block selection is empty for a full world release.
The dataset stage will stop if its cap is too small; choose the cap from measured
input/output size and available disk. The laptop profile caps dataset output at
3 GB; the VM profile derives its cap from `resources.max_workspace`. Actual free
space and the workspace allowance remain enforced throughout the write.
Resource pressure pauses the run;
a failed spatial/evaluation gate requires investigation and a reviewed policy-bound
approval, not an unconditional retry or a fabricated review file.

Interrupted units resume through the ledger. Check `work/runs/<timestamp>/` for
logs and completion summaries, and retain the release's manifest, logical digest,
licences, card and changelog. No stage should silently recreate a published version.

### A dangling place reference stops the dataset stage

The error lists each missing key by table and column, such as
`phone_metadata.territory: country:AC`. Confirm it in the lookups inputs and find
its source before changing configuration. If the target was dropped upstream,
fix that stage instead. Otherwise decide each key in `release.dataset.closure` of
`config/release.yaml`:

1. When a real country or place covers the code, as `SH` covers the ISO 3166
   exceptional reservations `AC` and `TA`, add it to `place_aliases`
   (`country: {AC: SH}`). The alias target must exist.
2. When nothing sensible covers it, list it in `excluded_places`; the rows that
   name it are dropped. Cells, `place_to_city`, `places`, `canonical_cities` and
   `countries` never lose rows, so a missing key there must be fixed upstream.
3. Leave `unknown_places: fail`, so that the next unknown code stops the release
   again instead of passing silently.

This is a configuration change: it re-identifies only the `dataset`, `packs` and
`publish` units. Check the counts in the manifest's `closure` object and the
README's Place references section before publishing.

### A repeated key stops the dataset stage

Assembly refuses a release that repeats a key declared in `config/dataset.yaml`.
The error names the table, its key columns and up to five repeated values; the
staging directory is discarded, so confirm the duplicates in the lookups inputs.
Fix the source or its normalization when you can. If the release cannot wait,
withdraw that table's key. This is a configuration change, not a code change, and
there is deliberately no skip switch: a release must not declare a key it breaks.

1. In `config/dataset.yaml`, set the table's `primary_key: []`, and reword its
   `grain` if it promises one row per key.
2. Delete every relationship whose `references.table` is that table; the schema
   loader refuses a relationship that does not target a declared key. For
   `countries`, these are the `country_code` references of `plate_codes`,
   `plate_formats` and `plate_priors`.
3. Run `python -m pipeline dictionary` and commit the regenerated files;
   `dictionary --check` fails until you do. Also remove the table from
   `ENFORCED_KEYS` in `tests/pipeline/release/test_dataset_metadata.py`, and
   re-render the committed `docs/dataset/README.md` as `test_readme.py` does.
4. Rerun the release. The published schema, dictionary and README change, so the
   dataset stage and the packs rebuild; no upstream unit re-identifies.

Note the withdrawn key in `CHANGELOG.md`, and restore it once the duplicates are
fixed upstream.

## Validate staging, then publish the same files

`run --through publish` above targets staging. While `DATA_LICENSES.md` still
carries an `OWNER DECISION` paragraph (CC BY-SA plate content), staging needs
`release.publish.private=true`; a public destination refuses it. Require the
`dataset/<version>/_SUCCESS` and `packs/<version>/_SUCCESS` receipts and recheck
their listed object hashes; read `packs/<version>/acceptance/*.json` (every pack
was opened at `ulimit -n 256` and checked against seeded dataset samples before
it was archived); inspect per-table row counts, `CHANGES.md`, coverage and the
generated README. Run the end-to-end test over the staged copy. It is `tests/e2e/world_e2e.py` (marker
`world`, deselected by default). Set `THEREABOUTS_E2E_RELEASE` to the staging root
that holds `dataset/` and `packs/`, and `THEREABOUTS_E2E_REPORT` to the report
path, then run `uv run pytest -m world tests/e2e/world_e2e.py`. It serves `packs/`
on loopback and installs from it with each client.

Run the three README examples on local files and on the owner's S3 setup.

Use a dry run first for any destination:

```sh
.venv/bin/python -m pipeline release upload --root "$PIPELINE_DATA" \
  --version "$PIPELINE_VERSION" "storage.s3_release=$PIPELINE_STAGING" --dry-run \
  --report .cache/pipeline/staging-upload-plan.json
```

After the owner accepts the staged release, upload **the same local immutable
files** to the public destination (do not rebuild between staging and publication):

```sh
.venv/bin/python -m pipeline release upload --root "$PIPELINE_DATA" \
  --version "$PIPELINE_VERSION" storage.s3_release=s3://OWNER-PUBLIC-BUCKET \
  --dry-run --report .cache/pipeline/public-upload-plan.json
# Owner executes after reviewing that exact inventory:
.venv/bin/python -m pipeline release upload --root "$PIPELINE_DATA" \
  --version "$PIPELINE_VERSION" storage.s3_release=s3://OWNER-PUBLIC-BUCKET \
  --report .cache/pipeline/public-upload.json
```

Existing correct objects are skipped. A checksum conflict stops publication;
resolve the discrepancy explicitly, without replacing a released version. The
success receipts are last and identify exactly which dataset/pack files
completed. `release upload` refuses to start unless the workspace ledger records
the dataset, every archive, acceptance report and the index with exactly these
bytes.
This task's local demonstration used `release.packs.families=[]` because no real
writer was available; do not carry that override into a full release accidentally.

## Publish to GitHub Releases

The owner's chosen host is GitHub Releases of `brightertiger/thereabouts`
(`release.publish.target=github`; settings under `release.publish.github` in
`config/release.yaml`). Clients default to
https://github.com/brightertiger/thereabouts/releases/latest/download/. A release
`v<version>` holds flat assets; each archive carries its own directory
structure, and installation rebuilds the local tree:

| Asset | Content |
|---|---|
| `<family>.tar.zst` | Pack archives |
| `acceptance-<family>.json` | Acceptance reports |
| `manifest.json`, `README.md`, `DATA_LICENSES.md`, `DATASET_CARD.md`, `CHANGES.md`, `DATA_DICTIONARY.md`, `data_dictionary.json`, `content.json` | The dataset's top-level documents |
| `dataset-<table>.zip`, or `-001`, `-002`… past 2 GiB | Each dataset table as stored zips of `<table>/…` |
| `dataset-manifest.json` | Every zip with its members, and every document, for `data install dataset` |
| `index.json` | Format 3 with absolute URLs, `asset_id` and `api_url`, listing every published version |

The publisher reads its token only from `GITHUB_TOKEN`: a fine-grained personal
access token limited to this repository with **Contents: Read and write**, the
only permission release uploads need. Never put it in configuration or reports.

```sh
.venv/bin/python -m pipeline release upload --root "$PIPELINE_DATA" \
  --version "$PIPELINE_VERSION" release.publish.target=github --dry-run \
  --report .cache/pipeline/github-upload-plan.json
# Owner executes after reviewing that plan, with GITHUB_TOKEN exported:
.venv/bin/python -m pipeline release upload --root "$PIPELINE_DATA" \
  --version "$PIPELINE_VERSION" release.publish.target=github \
  --report .cache/pipeline/github-upload.json
```

The dry run is offline. It needs no token and lists every asset with its size
(zip digests appear once the zips are built). `release upload` still requires
the ledger proof first. The upload then:

1. writes the table zips under `work/releases/<version>/zips/`. They are
   deterministic, so a rerun gives the same bytes, and each is read back by the
   clients' Rust reader;
2. finds the release for the tag, or creates a **draft**. GitHub creates the tag
   `v<version>` at publication from the default branch unless it already exists,
   so create it on the release commit first if that matters;
3. deletes incomplete uploads in the draft, refuses unexpected or conflicting
   assets, uploads only missing ones and verifies each by size and the SHA-256
   digest GitHub reports (downloading and hashing it when GitHub reports none);
4. uploads `dataset-manifest.json`, then `index.json`, the union of every
   published release's index plus this version;
5. publishes the draft last, marked latest only when no published release has a
   newer version, then re-reads it to confirm every asset.

Rerun the same command to resume an interrupted upload. A published release is
never altered, except to add a missing asset that no published
`dataset-manifest.json` or `index.json` names by asset id; otherwise publish a
patch version (`YYYY.MM.N`). While `DATA_LICENSES.md` carries the CC BY-SA
`OWNER DECISION` paragraph, a public publish refuses. `release.publish.private=true`
uploads and verifies the draft and stops there, unpublished. Resolving the
decision changes the release documents, so the next run refuses that draft
because it holds different files; nothing is released yet, so delete the draft
on GitHub and rerun. A draft's `index.json` is rebuilt on every run, so it
always lists every version published before it. GitHub limits a
release to 1,000 assets, each under 2 GiB; the plan enforces both. The same
target runs as the `publish` stage (`run --through publish` with
`release.publish.target=github`), whose unit destination is `github:<repository>`.

GitHub keeps one latest release per repository, and the clients' default URL
reads `index.json` from it. Publish any other release in this repository (such as
client code) with "Set as the latest release" unchecked, or the default URL
stops finding `index.json` until the next dataset release.

Clients read the `releases/latest/download/` and `releases/download/<tag>/`
redirect routes, not the REST `releases/latest` endpoint, which allows 60
unauthenticated requests an hour per address. While the repository is private,
those routes return 404, so clients need `THEREABOUTS_RELEASE_TOKEN` (or
`GITHUB_TOKEN`) with **Contents: Read**. They then read the index and assets
through the API and send the token only to `api.github.com`.

**The later public switch.** Make the repository public in its settings. Nothing
is republished: the same assets become reachable through the public download
routes, and clients stop needing a token. Afterwards, check
`thereabouts data list --remote` without a token.

**Optional Hugging Face mirror.** For analysts, the dataset tree
(`dataset/<version>/`, as `thereabouts data install dataset` restores it) can be
mirrored to a Hugging Face dataset repository, tagged per version with the same
files. That mirror is not automated here and is not a client source.

Finally fill and validate [release-registry.yaml](release-registry.yaml) against
the current upstream registry schema, confirm public anonymous reads and licence
notices, and use [the registry PR draft](release-registry-pr.md) for the owner's
submission to `awslabs/open-data-registry`. No registry PR was opened here. Retain
measurement logs and shut down or delete the build machine separately.
