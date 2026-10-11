# Documentation index

## Users

- [Python client](clients/python.md) — open a geocoder, lookups, results, batches and errors.
- [Node client](clients/node.md) — the same API for Node 22 and 24.
- [Command line](clients/cli.md) — command grammar, output formats, batch input and exit codes.
- [Installing data](clients/data-install.md) — packs, sources, the store layout and the offline guarantee.
- [MCP server](clients/mcp.md) — setup for Claude Desktop, Claude Code and other clients, tools and resources.
- [Agent skill](../skills/thereabouts/SKILL.md) — teaches an agent to use the MCP tools and the dataset.
- [Examples](../examples/README.md) — runnable usage examples.
- [Licences](licenses.md) — code licence and separate data obligations.

## Dataset

- [Dataset guide](dataset/README.md) — Parquet layout, columns, counts and query examples.
- [Data dictionary](dataset/DATA_DICTIONARY.md) — tables, joins, enumerations, MCP tools and result fields; machine form in [`data_dictionary.json`](dataset/data_dictionary.json).
- [Code packs](dataset/code-packs.md) — postal and airport packs and their lookups.
- [Pack format](dataset/pack-format.md) — normative serving format 2.2 for every family.

## Maintainers

- [Contributing](../CONTRIBUTING.md) — toolchain, tests and what needs no pipeline data.
- [Client status](clients/status.md) — generated state, conformance and measurements.
- [Client release](clients/release.md) — building and releasing the Python and Node packages.
- [Recorded measurements](../tests/benchmarks/measurements/) — evidence read by benchmarks, tests and these guides.
- [Pipeline guide](pipeline/README.md) — stages, configuration and commands.
- [City policy](pipeline/city-policy.md) — city granularity and footprint conventions.
- [`examples/ground-truth/`](../examples/ground-truth/) — evaluation ground truth read by the evaluate stage and the examples.
- [Release procedure](pipeline/release-procedure.md) — building, staging and publishing a monthly release.
- [Registry submission](pipeline/release-registry-pr.md) and [registry metadata](pipeline/release-registry.yaml) — draft release registration.
