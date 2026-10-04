# Documentation index

## Dataset users

- [Dataset guide](dataset/README.md) — Parquet layout, columns, counts and query examples.
- [Pack format](dataset/pack-format.md) — normative serving format 2.2 for every family.
- [Code packs](dataset/code-packs.md) — postal and airport packs and their lookups.
- [Licences](licenses.md) — code licence and separate data obligations.

## Client users and maintainers

- [CLI contract](clients/cli.md) — command grammar, data store and transport.
- [Client status](clients/status.md) — generated state, conformance and measurements.
- [Client release](clients/release.md) — building and releasing Python and Node packages.
- [Python client](../clients/python/thereabouts/README.md) and [Node client](../clients/node/README.md) — public APIs and usage.
- [Recorded measurements](../tests/benchmarks/measurements/) — evidence read by benchmarks, tests and these guides.

## Pipeline operators

- [Pipeline guide](pipeline/README.md) — stages, configuration and commands.
- [City policy](pipeline/city-policy.md) — city granularity and footprint conventions.
- [`eval/`](../eval/) — evaluation ground truth read by the evaluate stage.
- [Release procedure](pipeline/release-procedure.md) — building, staging and publishing a monthly release.
- [Registry submission](pipeline/release-registry-pr.md) and [registry metadata](pipeline/release-registry.yaml) — draft release registration.
