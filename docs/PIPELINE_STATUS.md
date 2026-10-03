# Pipeline redesign status

Package 1 is complete: it supplies the portable runtime and verified adoption of
the retained workspace. Work is on `feat/pipeline`; commits are local only. Packages 2–5 are
deferred at this reviewable package boundary. The real workspace has only been
read, and its migration has not been applied.

## Review fixes 1–3

Fixes H1, H2 and M4 are implemented together: verified one-time identity handover,
permission preflight before lock/backup/journal creation (including recovery), and
original-backup verification across separate paths/adopt operations. The source
ledger remains `d71802b95e36aeed8b95b53b3613e3499a4cfc7eb051dbac8880856fa5d73a37`.
Checks: 685 tests passed, 8 skipped; Ruff/format passed (468 files); strict mypy
passed (452 source files). Read-only plan and handover dry-run both reproduce the
stage table below: 85,577 current, zero stale/new.

`migrate handover --dry-run` on an adopted ledger compares independently discovered
ported-stage keys with the saved keys, verifies outputs, and proposes only new
identity, parameters and input hash. Outputs, completion times, custody and absent
markers stay intact. It refuses changed dependencies and a second identity change
after handover. The handover audit lives separately in SQLite. No stage is ported
yet, so the real-workspace dry run has zero eligible ported stages at this commit;
the transition is exercised on synthetic applied ledgers.

The protected workspace still has its legacy ledger. A handover dry run there
first simulates adoption using `config/adoption.yaml`, then checks any ported
stages' independent discovery. Plan prints explicitly that zero stale under this
simulation is by construction: it checks mapping and hashes, not engine
semantics. Packages 2 and 3 must additionally pass handover on an applied copied
ledger and the independent source/engine tests. Ordinary plan against an applied
ledger remains strict and does not silently hand over changed identities.

For reviewer application, generate a fresh dry-run report first. It lists exactly
the existing directories needing temporary write permission in
`writable_directories` (302 at this checkpoint). Apply and recover also print each
exact `chmod u+w` command and its matching `chmod a-w` command if permission is
missing. Neither command runs chmod itself. Run these commands **only as the
reviewer applying the approved migration**, from this worktree:

```sh
PIPELINE_DATA=/Users/ujjwal/Downloads/solo/thereabouts/data
.venv/bin/python -m pipeline migrate --dry-run --root "$PIPELINE_DATA" --report .cache/pipeline/migration.json
.venv/bin/python -c 'import json; print("\n".join(json.load(open(".cache/pipeline/migration.json"))["writable_directories"]))' > .cache/pipeline/writable-directories.txt
while IFS= read -r directory; do
  [ -z "$directory" ] || chmod u+w "$PIPELINE_DATA/$directory"
done < .cache/pipeline/writable-directories.txt
.venv/bin/python -m pipeline migrate --root "$PIPELINE_DATA" --report .cache/pipeline/migration-applied.json
.venv/bin/python -m pipeline migrate check --root "$PIPELINE_DATA"
while IFS= read -r directory; do
  [ -z "$directory" ] || chmod a-w "$PIPELINE_DATA/$directory"
done < .cache/pipeline/writable-directories.txt
```

Keep the directory list until application/recovery has completed and protections
are restored. It is generated before chmod and is not replaced by the application
report. No chmod command above was executed against the real workspace.
Review fixes 4–9, then packages 2 and 3, are the next work.

## What is built

The runtime includes OmegaConf schemas/profiles and overrides, a relative-path
ledger, stage and unit dependency validation, the single fingerprint rule,
bounded worker scheduling, resource admission, atomic publication, run logs,
invalidation and recoverable migration. Low disk or resident-memory headroom
pauses admission. These checks do not impose an operating-system memory limit
on arbitrary stage code. SQLite writer waiting is configurable too.

Source and engine declarations inspect retained outputs. Their rebuild methods
fail explicitly until packages 2 and 3 port the implementations. Synthetic stages
prove dependencies within a stage, lazy discovery, unchanged-byte propagation,
absent-input restoration and retry after interrupted manifest publication.

The legacy `build_data` package is unchanged. The only client source change is
`CELL_FORMAT_VERSION`; encoding behavior is unchanged. [DATA_PIPELINE.md](DATA_PIPELINE.md)
is the usage guide; superseded build guides remain under [history](history/).
[DATASET_README.md](DATASET_README.md) is the early release-layout draft, not a
generated release reference.

From this worktree, inspect the protected workspace with:

```sh
.venv/bin/python -m pipeline plan --root /Users/ujjwal/Downloads/solo/thereabouts/data
.venv/bin/python -m pipeline status --root /Users/ujjwal/Downloads/solo/thereabouts/data
.venv/bin/python -m pipeline migrate --dry-run \
  --root /Users/ujjwal/Downloads/solo/thereabouts/data \
  --report .cache/pipeline/migration.json
```

Read-only SQLite uses `mode=ro&immutable=1` and refuses a nonempty WAL. For the
unmigrated ledger, `plan` labels its result **SIMULATED ADOPTION**. It verifies
hashes in memory without blessing new identities on disk. An adopted ledger is
checked against its saved identities normally. The world test additionally
applies migration to a copied ledger and JSON inside this worktree, then checks
saved identities against original payloads read-only with copied JSON overlaid.
It copies no Parquet or other data tree.

## Real-workspace plan

The final read-only CLI `plan` and migration dry run both exited successfully.
They report the same counts as the copied-ledger application proof:

| Stage | Current | Stale | New | Units with absent outputs |
| --- | ---: | ---: | ---: | ---: |
| download | 13 | 0 | 0 | 4 |
| normalize | 13 | 0 | 0 | 0 |
| reconcile | 1,111 | 0 | 0 | 1,111 |
| cells | 41,442 | 0 | 0 | 0 |
| cities | 555 | 0 | 0 | 0 |
| evaluate | 1 | 0 | 0 | 0 |
| normalize_cells | 41,716 | 0 | 0 | 0 |
| lookups | 726 | 0 | 0 | 0 |
| **Total** | **85,577** | **0** | **0** | **1,115** |

## Migration changes and evidence

The mapping processes 134,312 old ledger rows, retires 42,339 superseded/cache
rows, and produces 85,577 adopted units. Source-unit aggregation explains the
remaining difference in row counts. It rewrites 588 existing JSON files and
imports six verified JSON evidence files. There are 2,574 intentionally absent
output records across 1,115 units.

- The active `golden` symlink points to normalized output. Former base records
  are matched to `base_cells/current.json` by table, block/country and recorded
  hash. The selected base's entire table inventory is verified too.
- Exact-manifest offload receipts authorize absent raw outputs for
  `geoboundaries`, `geonames`, `osm_land` and `overture`. Remote objects are
  **not verified**; their recorded custody is retained explicitly.
- Reconciliation's deleted outputs retain their recorded hashes and
  `outputs_absent`. Restoration is needed only when an actual consumer executes
  or reconciliation is explicitly selected for materialization.
- Six plate-source auxiliary records refer to repository JSON files. Migration
  verifies their bytes and proposes content-addressed copies under
  `raw/plates/configuration/`; their source files are unchanged.
- Overture JSON pointers such as `/properties/names/...` remain JSON pointers.
  Historical review hashes are never rebound to different evidence to make
  them pass. Unknown stages and corrupt retained payloads stop adoption.

The detailed dry-run report is `.cache/pipeline/migration.json`. It records the
original ledger hash, per-row dispositions, relocations, new identities and unit
input hashes, and before/after JSON sizes and hashes. Application saves the exact
old ledger, journals JSON originals, and publishes the prepared ledger last.
Synthetic tests exercise rollback/retry, separate `paths`/`adopt` steps, a move
to a new root, and idempotence.

**Reviewer command, not run against the real workspace in this task:**

```sh
.venv/bin/python -m pipeline migrate \
  --root /Users/ujjwal/Downloads/solo/thereabouts/data \
  --report .cache/pipeline/migration-applied.json
```

Stop old builders before application; they must not run against the adopted
ledger. Follow with `migrate check` and `plan` using the same `--root`. Production
rebuilding still requires packages 2 and 3. The old checkout-name symlink is
left for the reviewer because removing it would write outside this worktree.

## Measurements and validation

Machine: Apple M2, 8,589,934,592 bytes RAM (8 GiB), macOS. The ordinary suite
passed **676 tests, 8 skipped**. Ruff check and formatting passed (461 files);
strict mypy passed (445 source files). The skipped tests require explicit world
fixtures. The explicit migration world proof passed in 352.018 seconds with
1,082,605,568 bytes peak RSS. It preserved the original ledger hash/mtime and
every JSON original, applied the migration to copies, and verified idempotence.
The original ledger copy was 112,971,776 bytes; the adopted copy was 151,146,496
bytes; rewritten/imported JSON totaled 29,404,126 bytes. The final dry-run
verified 17,677,115,785 payload bytes. These are full retained-workspace adoption
measurements, not a production rebuild benchmark. The committed results are in
[PIPELINE_MEASUREMENTS.json](PIPELINE_MEASUREMENTS.json).

The full existing golden content digest was recomputed once: **14 tables,
98,077,250 rows**, matching
`0e543e65bc26987a2714b89f2b23395e11c9e48d482d9ee2315d3a890a0e9614`.
It took 1,261.885 seconds with 541,097,984 bytes peak RSS. The unchanged legacy
digest implementation used a measured merge fan-in of 265 for this verification
process, avoiding a second on-disk copy of its row-hash runs. Row encoding,
sorting and digest framing were unchanged; the scratch bound was
2,119,253,760 bytes and the scratch files were removed by the digest reader.
The helper and detailed digest report remain in `data/pipeline-work/`.
At final review, worktree files totaled 1,111,395,098 bytes and free disk was
50,709,729,280 bytes. Scratch allocation was bounded before starting and copies
were admitted only after checking the 3 GB worktree allowance and 5 GB disk floor.

Dataset and pack sizes: **not generated**. Package 4's subset build, complete
generated README with column references and executed examples, and local publish
are not part of this runtime package. No real stage was run on the protected
workspace and no cloud data operation was performed.

## Next packages and owner follow-ups

1. Package 2: source adapters, fourteen source configs including `plate_country`,
   actual pins, mirror/storage operations and source discovery. Replace retained
   declarations and extend adoption without rebuilding preserved outputs.
2. Package 3: engine moves, policy JSON-to-YAML equivalence, fingerprint-bound
   reviews, evaluation and plate-country stages, fixture/pilot digest comparisons;
   then delete `build_data` and its temporary repository-evidence reader in migration.
3. Package 4: measured release subset, coalesced cells, complete generated README,
   manifests/licences/card/changes, packs, local publish and registry output.
4. Package 5: VM and monthly release procedure documentation/scripts, unexecuted.

No geographic-policy decision was made. The owner still needs to review metadata
migration, verify remote custody needed for a future rebuild, and choose release
contact/citation and publication settings in later packages. Nothing was pushed
or published. All task outputs, temporary files, environment and reports are in
this worktree; a local Git commit uses Git's existing shared worktree metadata.
The real `data/` workspace was not modified.
