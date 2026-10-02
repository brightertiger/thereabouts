# Thereabouts integration and data neutrality

**Status: both full content comparisons passed; regenerated v2 is verified and
locally active. Superseded duplicate payloads have been removed.**
The live, resumable record is `data/work/integration-progress.md`; all comparison
receipts and original manifests are under `data/work/integration-evidence/`.
No remote operation, push, pull request or publication was performed.

## Integration

Merged `data/plates`, `rename/thereabouts`, then `docs/product-plan` into
`data/source-plan`, locally only. The two conflicts were in golden lookup export
and normalized catalogue export. The resolution retained the final world build's
memory limits and publisher/runtime guards while adopting relative artifact paths
and dataset-scoped ledger keys. SQL and row computation were unchanged. The client
worktree and branch were not changed.

Swept the plates source, final v2 documentation and product plan for the previous
name. Seven tracked occurrences remain intentionally: the real GitHub repository
URL (one), actual checkout/scratch paths (five), and the existing bucket (one).
`uv sync --locked` installed `thereabouts`; dependency versions were unchanged.

The plates schema additions exposed overly broad acquisition guard dependencies.
Geographic settings now depend only on their original areas/places/names schemas;
existing lookup settings depend only on their original lookup schemas. The four
geographic configuration functions already included unrelated lookup schemas
before this integration, while their saved manifests recorded the original
three-schema contract. Scoping the dependencies restores that contract and keeps
plate schemas from invalidating unrelated sources. No saved manifest, ledger
receipt or recorded hash was edited to make a stage current.

## Sources and unchanged stages

Reused all 404 pinned plate snapshots from the plates worktree, verifying their
sizes and SHA-256 values, then ran the ordinary acquisition adapter in this
checkout. It created local receipts and normalized outputs without downloading:
143,935 plate codes, 250 survey rows and 159 format rows in 11 partitions.
Plates remain an acquired source; they are absent from the golden tables.

All 13 normalized source manifests validate against current configuration. The
four previously offloaded geographic raw sources and GHSL's pre-existing missing
raw download receipt retain their original status. Reconciliation and all 277
city-country outputs plus their mappings were accepted under their original
guards before any guarded regeneration. The controller reused those outputs.

The post-regeneration upstream audit found 7,688 original ledger receipts exactly
unchanged, including their input keys, output records, metadata and completion
times. All 12,870 retained upstream artifacts kept their sizes and modification
times; the pipeline also verified the current source, reconciliation and city
output hashes. Nineteen original manifests and evaluation receipts retained their
bytes and modification times. Aggregate city manifests and pilot metadata may be
republished by the controller; no country or mapping computation was repeated.

The lookup verifier retains one pre-existing source-quality finding for the
GeoNames IN/560001 coordinate; its source coordinate and H3 value are unchanged.

## Comparison method

Both baseline digests finished before regeneration began. The digest reads every
manifest-listed row, preserving duplicates, nulls, scalar values, list order and
logical column types. It excludes file paths, row/partition order, compression and
Arrow/Parquet metadata. Overall and per-table SHA-256 digests are compared.

The rename branch's digest sorter was changed from SQLite random writes to
bounded sequential runs to fit this machine. Canonical encoding, hash framing,
schema descriptors and duplicate counting are unchanged. The original and
optimized implementations produced identical results on 51,615 real rows across
all 26 base/v2 table schemas; the full datasets use the same validated format.

The base controller regenerated all 41,162 blocks from zero committed current
blocks, then verified and checkpointed the result. Its 12 logical tables match
the original base exactly, including 62,355,684 compact cells representing
199,608,564 eligible resolution-8 centres. Aggregate SHA-256:
`4d4fa896bf7b8b695238273e1526edcaae8d9473d9ca3f6c1a4c88f9a84fe7f0`.

The new pilot matches all 18 OFF/ON country reports (apart from their input
identity), summary metrics, stored-block metrics and catalogue integrity. The
existing development report was retained byte-for-byte with `--reuse-development`.
The pipeline issued a fresh review receipt after that comparison. No development
or holdout points were scored or used to tune this integration.

All 277 freshly measured stored-output world country reports match the originals
exactly, as do global integrity, mapping integrity, named checks, diagnostics,
row counts and transitions. The first final gate stopped only for the same three
previously examined boundary cells: London `88194e684dfffff` and
`88195d368dfffff`, and secondary Dearborn geometry `882ab2cda1fffff`. Their source
references and destinations are identical. A new review was bound to the actual
regenerated manifest in
[`city-normalization-thereabouts-review.json`](city-normalization-thereabouts-review.json).
The original review and original manifest hashes remain unchanged.
The resumed controller accepted this review and finished world verification at
2026-10-02 19:28 UTC. All 14 output table row counts match the original v2.

## Complete content comparison

Every digest below is identical before and after regeneration. Counts are also
identical within each stage. A dash means the table is absent from that stage.
Full per-table SHA-256 values and stage guards are in
[`rename-content-comparison.json`](rename-content-comparison.json).

| Logical table | Base rows | Normalized v2 rows | Base / v2 digest comparison |
| --- | ---: | ---: | --- |
| airports | 86,154 | 86,154 | identical / identical |
| canonical_cities | — | 68,923 | — / identical |
| cells | 62,355,684 | 66,226,680 | identical / identical |
| countries | 252 | 252 | identical / identical |
| ip_ranges | 7,786,864 | 7,786,864 | identical / identical |
| phone_metadata | 254 | 254 | identical / identical |
| phone_prefixes | 427,963 | 427,963 | identical / identical |
| place_to_city | — | 6,875,329 | — / identical |
| places | 6,875,329 | 6,875,329 | identical / identical |
| postal_codes | 5,036,067 | 5,036,067 | identical / identical |
| subdivisions | 8,911 | 8,911 | identical / identical |
| timezone_cells | 4,567,490 | 4,567,490 | identical / identical |
| trade_locations | 116,213 | 116,213 | identical / identical |
| zone_tables | 821 | 821 | identical / identical |

Overall content SHA-256 (before = after):

- Base, 87,262,002 rows: `4d4fa896bf7b8b695238273e1526edcaae8d9473d9ca3f6c1a4c88f9a84fe7f0`.
- Normalized v2, 98,077,250 rows: `0e543e65bc26987a2714b89f2b23395e11c9e48d482d9ee2315d3a890a0e9614`.

No table, row, value or logical column difference was found.

## Regeneration commands

The original active symlink was retained as `data/golden-before-thereabouts` while
the base builder used its required `data/golden` construction directory. The
original immutable base and original normalized v2 remained intact beside it.

These commands record the integration sequence while `data/golden` contained the
base construction output. Current verification/resume commands for the active
normalized publication are in [GOLDEN_V2.md](GOLDEN_V2.md#pipeline-and-reproduction).

```sh
python -m build_data.rebuild_golden --data-dir data --workers 2 --through base
python -m build_data.digest_golden data/golden \
  --output data/work/integration-evidence/base-after.json \
  --compare data/work/integration-evidence/base-before.json \
  --temp-dir data/work/integration-evidence/scratch
python -m build_data.rebuild_golden --data-dir data --workers 2 \
  --through pilot --reuse-development
python -m build_data.normalize_cells review --data-dir data \
  --review docs/city-normalization-pilot-review.json \
  --gate data/work/v2-pilot/thereabouts-gate.json
python -m build_data.rebuild_golden --data-dir data --workers 2 \
  --through world --reuse-development --output data/golden-thereabouts \
  --gate data/work/v2-pilot/thereabouts-gate.json
```

Long-running commands are detached, with logs under `data/work/`. A failed content
comparison prevents activation and cleanup; both generations must be retained.

## Activation and selective cleanup

After both complete comparisons passed, the active symlink was switched to
`data/golden-thereabouts` at 2026-10-02T19:49:11.022433+00:00. The immutable base selected by
`data/base_cells/current.json` is
`768dc09805b19bc46c803fec09b193d8a470d7f6ff1261fc25dc7e072e1fd3eb`.
The base construction directory was moved to `data/golden-base-thereabouts`
before the atomic symlink replacement. No published manifest was rewritten.

The cleanup verified each duplicate against its saved file hash before removing
only the Parquet payloads listed by these three manifests:

| Superseded copy | Removed Parquet files | Apparent bytes |
| --- | ---: | ---: |
| Original immutable base | 42,164 | 2,537,060,501 |
| `data/golden-v2` | 42,718 | 2,518,961,896 |
| `data/golden-base-thereabouts` | 42,164 | 2,537,060,501 |

The redundant `data/golden-before-thereabouts` symlink was also removed. All
original manifests, reports, licences, cards, development/holdout receipts and
unlisted files remain, with a separate `RETIRED_PAYLOADS.json` notice in each
retired directory. The full deletion inventory is retained at
`data/work/integration-evidence/cleanup-inventory.json`. Apparent bytes include
hard-linked duplicates and are not a claim about physically freed disk blocks.

All 42,164 v1 table files were hash-verified before and after cleanup; its manifest
is unchanged. `data/reconciled`, every acquired/normalized source and all other
user material remain. Original score receipts stay in the retired v2 metadata
directory; they are neither copied into nor rebound to the new publication.

## Code validation

On frozen integration code `40fbfde`: 316 tests passed, seven skipped; the three
explicit city tests against `data/h3-world` passed. Ruff lint and formatting passed,
strict mypy passed for 276 source files, and H3 world verification passed. The full log is
`data/work/integration-checks-final.log`. No external CI or publication was run.

## Final status

Post-cleanup verification passed for the active normalized manifest, every active
table/verification artifact and the current immutable base. Acquisition reports
plates complete (404/404 raw snapshots; 11 normalized partitions); all 13
normalized sources remain current. Reconciliation, city countries and city
mappings reuse their original receipts. The base, pilot and normalized world are
verified complete; radius remains OFF. There is no active build or scoring job.

Disk after verification: 16.08 GiB free. Source validation still reports only the
pre-existing raw offload/GHSL receipt statuses and the unchanged postal coordinate
finding described above. No external CI was run. Full local checks passed on the
frozen code; subsequent repository changes are documentation and proof receipts.

Local integration commits: `fcd2dc8` (plates), `18acfba` (rename conflicts),
`1e3ec29` (product plan), `17ee252` (schema guards/no-rescoring controller),
`40fbfde` (bounded digest sorting). This document and the final comparison/review
receipts are committed separately after verification. All work remains on
`data/source-plan`; the client branch/worktree and all sibling data are retained.
