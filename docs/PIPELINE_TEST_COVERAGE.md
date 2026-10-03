# Pipeline test coverage after the engine move

The tests exercise synthetic inputs without network access. The previous
`build_data` controllers and their six fingerprint/ledger implementations are
removed. Controller-specific tests have been replaced with tests of the single
runtime, rather than retaining aliases for deleted APIs.

| Retired controller area | Current decision coverage |
| --- | --- |
| Source CLI, ledger, status and locks | `tests/pipeline/test_runner.py`, `test_ledger.py`, `test_resources.py`, `test_config.py` |
| Download, offload/restore and source manifests | `tests/pipeline/sources/test_download.py`, `test_source_stages.py`, `test_pins.py`; local/memory mirror integrity, interrupted file retry, absent custody, publication failure, corruption and portability |
| Old schema/source configuration hashes | `tests/pipeline/test_fingerprints.py`, `tests/pipeline/sources/test_source_stages.py`; declared code/config/pins/native dependencies and changed byte behavior |
| Reconcile/golden rebuild, snapshot and activation controllers | `tests/pipeline/test_geographic_runtime.py`, `test_discovery_refresh.py`, `test_runner.py`; actual engines through final verification, all dependencies, resumption, corruption repair and inventory rediscovery |
| Six old portability guards | `tests/pipeline/test_ledger.py`, `test_fingerprints.py`, `test_handover.py`, `test_migration.py`; root moves, changed code, strict identity handover, preserved outputs and rollback |
| Watch loop/disk pause | `tests/pipeline/test_resources.py`, `test_runner.py`; pause/retry, bounded scans and propagation of ordinary failures |
| Old v0 acquisition/settlement ingestion | Removed production behavior. Frozen fixture builders and scalar reference remain only under `tests/support`; client equivalence fixtures are unchanged. |

The source decision tests under `tests/acquire` retain name/alias classification,
lossless geometry splitting, holes, repairs, SHX and publisher counts, ZIP CRC,
plate parsing, syntax and ambiguity. The shared downloader intentionally resumes
at verified file boundaries; old HTTP Range/ETag append tests describe a removed
implementation, not a promise of the new adapter.

The engine tests retain scalar/certificate/compaction equivalence, date-seam
handling, state votes, administrative crosswalks, code/phone ambiguity, partial
spatial joins, preserved cardinality, city footprints, neighbouring settlements,
policy projections and holdout isolation. Policy conversion tests compare the
canonical fingerprint for every country. Dataset release generation, publish
idempotency and release pack stages belong to package 4.

Two opt-in `world` tests read the retained workspace. One applies migration and
handover only to copied JSON and a copied ledger, then verifies unchanged source
bytes and idempotence. The other reconstructs a bounded Malaysia pilot and
compares logical rows and complete Parquet SHA256 for radius OFF and ON. They
require `THEREABOUTS_PIPELINE_DATA` and an explicit worktree `--basetemp`.
