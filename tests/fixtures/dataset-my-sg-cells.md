# Captured MY/SG cells inventory

`dataset-my-sg-cells.json` is the exact cells inventory extracted from the
MY/SG dataset manifest produced by the package-5 `release prepare` command.
The original scratch output was deleted; the final pass reproduced preparation
from read-only golden inputs and verified that the full manifest SHA-256 is
identical to `docs/measurements/CLIENT_RELEASE_MEASUREMENTS.json` before extracting it.

The test keeps these block IDs, paths, row counts and row-group numbers and
constructs synthetic rows with the same shape. It replaces only file sizes and
checksums. It also creates an empty group with the pipeline's exact
`ParquetWriter`-closed-without-writes representation: `blocks: []`, `rows: 0`,
zero physical row groups. The real three-block MY/SG subset itself has no empty
group. Neither pytest nor the writer's synthetic test needs the real workspace.
