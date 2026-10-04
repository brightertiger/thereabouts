# Documentation index

## Dataset

- [DATASET_README.md](DATASET_README.md) — the released Parquet dataset: layout, every column, counts and query examples.
- [PACK_FORMAT.md](PACK_FORMAT.md) — normative specification of serving pack format 2.2 for every family.
- [CODE_PACKS.md](CODE_PACKS.md) — postal and airport packs and their lookups.

## Clients

- [CLI.md](CLI.md) — normative command grammar, data store and transport contract for the Rust CLI and Node.
- [CLIENT_STATUS.md](CLIENT_STATUS.md) — generated client state, conformance and measurements.
- [CLIENT_RELEASE.md](CLIENT_RELEASE.md) — building and releasing the Python wheel and npm package.

## Pipeline

- [DATA_PIPELINE.md](DATA_PIPELINE.md) — pipeline stages, configuration and commands.
- [PIPELINE_STATUS.md](PIPELINE_STATUS.md) — pipeline redesign state and measured validation.
- [PIPELINE_TEST_COVERAGE.md](PIPELINE_TEST_COVERAGE.md) — where retired controller behaviour is now tested.
- [RELEASE_PROCEDURE.md](RELEASE_PROCEDURE.md) — owner procedure for building, staging and publishing a monthly release.
- [migration-repairs.md](migration-repairs.md) — workspace metadata repairs for the migration.
- [release-registry-pr.md](release-registry-pr.md) and [release-registry.yaml](release-registry.yaml) — draft registry submission.

## Design specs

- [superpowers/specs/](superpowers/specs/) — approved client, pipeline and reconcile redesign specs.
- [explorations/](explorations/) — exploratory memos.

## History and measurements

- [history/](history/) — superseded plans, evaluations and docs for the retired v1 runtime, `build_data` and format 1.
- [measurements/](measurements/) — recorded measurement, review and comparison JSON written by `benchmarks/` and reviews.
- Redirect stubs kept for stable links from config, fixtures and code:
  [DESIGN.md](DESIGN.md), [GOLDEN_DATASET.md](GOLDEN_DATASET.md), [GOLDEN_V2.md](GOLDEN_V2.md),
  [CITY_NORMALIZATION_PLAN.md](CITY_NORMALIZATION_PLAN.md), [PLATES.md](PLATES.md),
  [RECONCILIATION.md](RECONCILIATION.md), [SERVING_FORMAT.md](SERVING_FORMAT.md).
