# Pipeline redesign status

## Current state

Packages 1–5 and all eleven package-2/3 review fixes are implemented locally on
`feat/pipeline`. The real workspace remains unmigrated. Use
[DATA_PIPELINE.md](DATA_PIPELINE.md) for commands and configuration; the current
schema is [DATASET_README.md](DATASET_README.md).
Final-review fixes 1–3: corrected automatic recovery instructions, expanded
per-file licence notices, and profile-specific dataset budgets. Fix 4 exercises
lookups → dataset → two fake packs → memory publication through the runner,
including ledger completion, receipt contents and resume. Fixes 5–8 follow.

Package 1 supplies configuration, the single ledger/fingerprint rule, resource
admission, runner and recoverable migration. Package 2 supplies the 13 retained
sources plus disabled `plate_country`, frozen pins and verified mirrors. Package
3 moves engines into pipeline stages, preserves the policy semantics for all 676
country projections, and removes `build_data`. The only client-source change
remains `CELL_FORMAT_VERSION`.

Package 4 adds dataset assembly, generated documentation and checksums, a client
pack adapter, fsspec publication and registry drafts. Releases remain disabled
until a version is selected. `release prepare --from INPUT --root OUTPUT
--version YYYY.MM` assembles a separate read-only snapshot; full commands are in
the pipeline guide. Source pins are checked against built inventories.
The MY/SG subset has **181,548 rows / 14 tables / 23 files / 8,736,970 bytes**;
Parquet contributes **7,336,896 bytes**. Three blocks coalesce into one cell file.
Its final build took **18.40 s** at **312,164,352 bytes RSS**.
All three README examples ran and agreed. Local publish uploaded 23 objects,
then skipped all 23 on repeat; the directory with `_SUCCESS` is **8,740,271 bytes**.
[PIPELINE_RELEASE_MEASUREMENTS.json](PIPELINE_RELEASE_MEASUREMENTS.json) records
per-table sizes, identities, reader outputs, timings and source attribution.

Package 5 supplies the owner-run [release procedure](RELEASE_PROCEDURE.md),
32 GB / 300 GB GCP provisioning scripts, monthly and staging instructions,
[registry entry](release-registry.yaml) and [PR draft](release-registry-pr.md).
Scripts passed Bash syntax checks only; no provisioning/startup command ran.
The procedure includes exact migration recovery and symlink-removal steps.

Review fixes: complete code closure and per-source invalidation (1–2), slim config
and lock plus repeated acceptance (3–4), adapter-owned pin proposals tested only
on loopback HTTP (5), full Malaysia pilot proof (6), stage-owned parameters and
configured source roles (7), removal of duplicate pack writers and `pipeline
digest` command (8), configured grids, explicit limits and source/docs cleanup
(9–10), and this status restructuring (11). Measurements and old → new identities
are in [PIPELINE_REVIEW_MEASUREMENTS.json](PIPELINE_REVIEW_MEASUREMENTS.json).

Measured on Apple M2 / 8 GiB / macOS. Current interpreter: CPython 3.12.8 /
SQLite 3.47.1; the pre-fix timing used CPython 3.12.2 / SQLite 3.46.0.
config `load()` **2.646 s → 0.158 s**; pytest **187.68 s → 44.61 s**
(the independent review measured 175 s before fixes). Current suite: **670
passed, 8 skipped**; Ruff check/format and strict mypy pass. The six Malaysia
artifacts, including base cells, city index and mapping, match retained SHA256:
**20.32 s**, **435,535,872 bytes RSS**, **141,524,404 output bytes**.
The interpreter is pinned in `.python-version`; SQLite's version is fingerprinted.

## Real-workspace plan and handover

**Zero stale under simulation checks mapping and hashes only, not world engine
semantics.** Read-only SQLite uses `mode=ro&immutable=1`; reports stay here.

| Stage | Handover | Current | Stale | New | Units with absent outputs |
| --- | ---: | ---: | ---: | ---: | ---: |
| download | 13 | 13 | 0 | 0 | 4 |
| normalize | 13 | 13 | 0 | 0 | 2 |
| reconcile | 1,111 | 1,111 | 0 | 0 | 1,111 |
| cells | 41,442 | 41,442 | 0 | 0 | 0 |
| cities | 555 | 555 | 0 | 0 | 0 |
| evaluate | 1 | 1 | 0 | 0 | 0 |
| normalize_cells | 41,716 | 41,716 | 0 | 0 | 0 |
| plate_country (disabled) | 0 | 0 | 0 | 0 | 0 |
| lookups | 726 | 726 | 0 | 0 | 0 |
| dataset / packs / publish (disabled) | 0 | 0 | 0 | 0 | 0 |
| **Total** | **85,577** | **85,577** | **0** | **0** | **1,117** |

Latest final-review plan: **320.14 s**, **1,492,369,408 bytes RSS**.
Latest handover: package 4, **331.70 s / 1,473,708,032 bytes RSS**; repeated at fix 8.
Gate reports: [PIPELINE_FINAL_REVIEW_MEASUREMENTS.json](PIPELINE_FINAL_REVIEW_MEASUREMENTS.json).
Real ledger SHA256 before/after:
`d71802b95e36aeed8b95b53b3613e3499a4cfc7eb051dbac8880856fa5d73a37`.

Migration processes **134,312** legacy rows, drops **42,334** superseded rows,
adopts **85,577** units, repairs **588** existing JSON files and imports **6**
evidence files. It re-verifies **17,677,116,404** present bytes. Missing records:

| Approved absence prefix | Files |
| --- | ---: |
| `reconciled/` | 834 |
| `work/reconcile/` | 1,662 |
| `work/geonames/` | 3 |
| `work/overture/` | 1 |
| `raw/geoboundaries/` (custody) | 63 |
| `raw/geonames/` (custody) | 2 |
| `raw/osm_land/` (custody) | 4 |
| `raw/overture/` (custody) | 9 |

The four deliberately deleted auxiliary caches total **3,260,159,017 bytes**:
`allCountries.txt` 1,788,639,329; `alternateNamesV2.txt` 785,574,856;
`lookup.sqlite3` 271,413,248; `entities.sqlite3` 414,531,584. They are adopted from
recorded hashes as `outputs_absent`. Future normalization for these sources must
regenerate them first. No broader missing-output exception is permitted. Remote
custody was not verified.

## Reviewer application steps

These commands are for the owner after review; none was applied to the real
workspace. Stop old builders first. `apply` and `recover` preflight every target
directory before writes and print exact enable/restore chmod commands when blocked.
The fresh dry-run currently lists **302** existing target directories. Preserve
that list until application or recovery finishes, including after an error.

```sh
set -eu
PIPELINE_DATA=/Users/ujjwal/Downloads/solo/thereabouts/data
.venv/bin/python -m pipeline migrate --dry-run --root "$PIPELINE_DATA" \
  --report .cache/pipeline/migration.json
.venv/bin/python -c 'import json; print("\n".join(json.load(open(".cache/pipeline/migration.json"))["writable_directories"]))' \
  > .cache/pipeline/writable-directories.txt
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
  --report .cache/pipeline/migration-applied.json
.venv/bin/python -m pipeline migrate check --root "$PIPELINE_DATA"
.venv/bin/python -m pipeline plan --root "$PIPELINE_DATA"
restore_pipeline_permissions
trap - EXIT
```

If interrupted, re-run the same `pipeline migrate --root "$PIPELINE_DATA"` apply;
it recovers first; keep the same directory list for restoring protection. Migration saves
`work/ledger.pre-migration.sqlite3` and journals JSON originals. The reviewer,
not this task, removes the external `PyOfflineGeocoder` symlink after verification.

## Open owner decisions

### Metadata repairs needing owner approval

The owner approved the classes conditionally; application still needs review.
Formatting is preserved by replacing scalar tokens only, including indentation,
separators and key order. The complete **578-file** extra-spec list and class
counts are in [migration-repairs.md](migration-repairs.md): 554 city-country files,
8 raw inventories, 6 evidence imports, 4 custody receipts, 2 active-dataset files,
and 1 each of auxiliary metadata, pilot gate, pilot summary and retained base
manifest. The base manifest repoints **42,160** table paths to `base_cells/`;
metadata hashes and sizes are then cascaded. No Parquet content changes.

Owner licence decision: LGPL-2.1 iso-codes (pycountry) rows inside `subdivisions`
of an ODbL database — keep, or re-source subdivisions from geoBoundaries/GeoNames
only. Choose release contact, citation, publication locations and plate-country inputs.
Approve changed pins and policy-bound reviews before a future rebuild. Pin
proposals require explicit `--accept` to change the lock; real upstream proposal
availability has not been tested in this task.

## Deliberately not done

No stage or migration application ran with the real workspace as its output root;
no full data rebuild, cloud access, push or public publication occurred. Real pack
writing awaits `feat/rust-core` and its `thereabouts._core.write_pack` binding.
The pipeline owns no copy of the binary format. The Rust writer also needs
coalesced-cell input support: its inspected implementation expects one r3 block
per table. Real packs and their sizes are unverified. The optional `s3fs` driver
is not installed/locked; resolve it before cloud publication. Only local and
memory backends were exercised. VM setup execution is outside this task.

The final full logical digest read all **14 tables / 98,077,250 rows** and matched
`0e543e65bc26987a2714b89f2b23395e11c9e48d482d9ee2315d3a890a0e9614`
in **1,121.60 s** at **586,940,416 bytes RSS**, identical to the baseline JSON.
Preflight reserved 2,119,253,760 scratch bytes plus 50 MB for concurrent checks
(total allowance 2,952,221,227 bytes); scratch was removed. This check is distinct
from migration's per-file verification and does not rebuild any table.

## Follow-ups and safety record

Retain this short status and linked detailed evidence. Update the frozen client's
`src/thereabouts/manifest.py` missing-data command on the Rust branch; its current
`python -m build_data` message and client test were intentionally left unchanged here.

Worktree bytes: **939,706,230**; free disk: **48,784,039,936**. The initial scratch cleanup removed
**1,049,266,242 bytes**. This task keeps new outputs below 3 GB and free disk above
5 GB; all subsequent tests set workspace TMPDIR and pytest has a worktree basetemp.
One early targeted pytest invocation omitted TMPDIR and wrote small synthetic
fixtures under macOS's external temporary directory (`pytest-233`); a temp-dir
diagnostic also used OS temp. These exceptions were disclosed when found. The
real `data/` was unaffected. No claim is made that absolutely every temporary
write in this session stayed inside the worktree.
