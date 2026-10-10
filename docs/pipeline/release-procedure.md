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
[PIPELINE_RELEASE_MEASUREMENTS.json](../../tests/benchmarks/measurements/PIPELINE_RELEASE_MEASUREMENTS.json) and the
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

## Apply migration on the existing laptop workspace

Do this once, before moving the workspace to the VM. Stop and checkpoint old
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
PIPELINE_DATA=/Users/ujjwal/Downloads/solo/thereabouts/data
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

Only after those checks pass, remove the obsolete checkout-name symlink. The
read-only inspection for this task found the relative target `thereabouts`:

```sh
.venv/bin/python - <<'PY'
from pathlib import Path
link = Path('/Users/ujjwal/Downloads/solo/PyOfflineGeocoder')
expected = Path('/Users/ujjwal/Downloads/solo/thereabouts')
if not link.is_symlink() or link.resolve() != expected.resolve():
    raise SystemExit('Unexpected path or target; leave it untouched')
link.unlink()  # Removes only the symlink, never its target.
PY
.venv/bin/python -m pipeline migrate check --root "$PIPELINE_DATA"
.venv/bin/python -m pipeline plan --root "$PIPELINE_DATA"
```

These are owner application instructions, not actions taken by this agent.

## Prepare the GCP VM

The requested machine is `e2-standard-8` (32 GB memory), with a 300 GB persistent
boot disk. `scripts/setup_pipeline_vm.sh` reads the raw-mirror bucket's location
when the owner executes it and chooses a zone in that region. It refuses a
multi-region/dual-region location instead of guessing. The bucket region was not
queried during this task. Provisioning creates billable resources.

```sh
export PIPELINE_GCP_PROJECT=OWNER_PROJECT
export PIPELINE_SERVICE_ACCOUNT=OWNER_SERVICE_ACCOUNT_EMAIL
# Optional: choose a specific zone in the bucket's region.
# export PIPELINE_VM_ZONE=REGION-ZONE
scripts/setup_pipeline_vm.sh
```

The service account needs access to read the existing GCS raw mirror and create
new mirrored objects for accepted pins; assign those bucket-scoped permissions
before running the pipeline. VM OAuth scope does not grant those IAM permissions.
Inspect startup logs and `/srv/thereabouts/SETUP_PENDING.txt`. The startup script
installs base tools and uv 0.6.14 but does not clone a repository or run a stage.
Assign `/srv/thereabouts` and `/mnt/data` to the intended login user, install the
reviewed merged checkout there, and install the Rust toolchain required by its
`core/Cargo.toml` (the inspected branch declares Rust 1.99). With the owner's
reviewed rustup installation, that is `rustup toolchain install 1.99.0 --profile
minimal` and a checkout-local `rustup override set 1.99.0`. Then run
`uv sync --all-extras --locked` from the checkout to build the client extension.
Rust installer access and Linux compilation were not exercised here.
The checkout pins Python 3.12.8. Record SQLite/GEOS and other native versions before
comparing identities with the laptop.

Before rebuilding plate evidence, check `pdftotext -v` against the pinned
`25.11.0` in `config/sources/plates.yaml`. The Ubuntu package installed by startup
may differ; provide the reviewed extractor instead of relabelling its version.
No Linux dependency installation or PDF extraction was tested here.

Transfer the **migrated** workspace to `/mnt/data` while writers are stopped.
Use an owner-controlled copy that preserves relative symlinks and file bytes;
never use a destructive `--delete` against the laptop workspace. Keep the laptop
copy until the VM's read-only `migrate check` and `plan` verify the copied data.
Missing caches intentionally stay absent. The GCS raw mirror supplies raw
payloads, not a substitute for the retained normalized/geo outputs and ledger.
This transfer is an owner action and was not performed here.

The VM profile starts with the measured conservative one-worker, 1 GB DuckDB,
2 GB process budgets. Increase them only after measuring the VM; 32 GB installed
RAM is not a measured per-stage requirement. Keep at least 5 GB free. Derive a
workspace allowance from the copied workspace and currently available disk:

```sh
export PIPELINE_DATA=/mnt/data
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
Run from the merged checkout on the prepared VM, not the protected laptop copy.

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
generated README. Run the end-to-end test over the staged copy:

```sh
scripts/vm/e2e.sh /path/to/staging   # serves packs/ on loopback; report in its run dir
```

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

Finally fill and validate [release-registry.yaml](release-registry.yaml) against
the current upstream registry schema, confirm public anonymous reads and licence
notices, and use [the registry PR draft](release-registry-pr.md) for the owner's
submission to `awslabs/open-data-registry`. No registry PR was opened here. Retain
measurement logs and choose VM shutdown/deletion separately; the provisioning
script deliberately has no destructive cleanup command.
