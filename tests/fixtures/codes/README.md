# Synthetic code-pack fixtures

These three compatible packs were exported from `tests.codes.fixtures.snapshot`.
They contain synthetic countries AA/BB, invented places and postal/airport
observations, not real geographic evidence. Postal inputs include a deliberately
conflicting source label; airports include repeated observations, code reuse,
closed sites, missing coordinates and an unindexed observation.

Regenerate under the worktree with `benchmarks.code_packs`, then use the same
input manifest/release to export reverse with a 2,048-byte shard target. Each
pack includes checksums, synthetic public-domain notices and the exporter/input
identity. Small indivisible records can exceed the target. All three share the
same golden digest/epoch. The original reverse fixture at `../serving` remains
available for older reverse-only format and method/ancestor conformance.
