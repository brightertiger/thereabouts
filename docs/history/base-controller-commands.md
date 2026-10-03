# Retired base-cell controller commands

These are historical commands and measurements from the pre-pipeline builder.
The implementation was removed in package 3. Use [the pipeline guide](../DATA_PIPELINE.md)
for current commands.

## Base-stage commands (historical v1 interface)

Use `build_data.rebuild_golden` above for the current dataset. These lower-level
commands require acquired/reconciled inputs in a separate base-stage workspace;
their default output is `golden/`, which must not be the active v2 symlink.

```sh
GOLDEN_DATA=/path/to/base-stage-data
uv run --no-sync python -m build_data.golden static --data-dir "$GOLDEN_DATA"
uv run --no-sync python -m build_data.golden pilot --countries BE NL LU CA --workers 2 --data-dir "$GOLDEN_DATA"
uv run --no-sync python -m build_data.golden run --workers 2 --watch --data-dir "$GOLDEN_DATA"
uv run --no-sync python -m build_data.golden status --data-dir "$GOLDEN_DATA"
```

`pilot` defaults to blocks whose conservative dependencies include BE, NL, LU or
AU. The example command selects Benelux and Canada. It exhaustively compares all resolution-8 centres with
direct vector labelling,
checks every ancestor lookup, and compares 16 evenly spaced centres in each block
with the independent scalar reconciliation oracle. The synthetic test region
additionally compares **every** fine centre against that independent scalar oracle.
`--verify-blocks` enables the same exhaustive checks for another run.

`plan` caches the actual finest-centre envelope of every resolution-3 root.
`--countries CC ...` selects country-dependent blocks; `--limit-blocks N` bounds a
run. `lookups` refreshes joins and checks from existing committed cells without
building more cells. `--watch` refreshes country availability after each complete
pass, sleeping 300 seconds by default. A single golden lock prevents overlapping
controllers. One or two worker processes own different blocks; two blocks at most
are in flight. Reconciliation's lock, code and working files are untouched.

The completed marker is `work/golden/run.json` with `completed: true`, together
with a committed `golden/manifest.json` also having `completed: true`. Individual
country and cell checkpoints are useful before then. `status` does not build or
hash tables. The same command safely resumes verified units, rebuilds corrupt
outputs, and fills pending lookup joins when more cells exist. An interrupted
Parquet write cannot complete its ledger unit. Do not infer completion from a
process exiting, a log line, or the existence of a Parquet file.

The golden stage has an 8 GB logical disk cap for `golden/` plus `work/golden/`.
It preserves 13 GB free. For this run, acquisition/reconciliation was externally
configured with a 12 GB reserve; golden does not modify that setting. Temporary joins have a 512 MB memory limit and a 512 MB spill cap.
A resource guard stops new units; `--watch` reports `waiting for disk` and retries
after the polling interval. Other I/O failures remain visible failures. The stage
never deletes another stage's data. Source
raw custody is described in [DATA_PIPELINE.md](source-and-golden-pipeline.md#raw-offload-and-restore).
