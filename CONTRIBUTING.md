# Contributing

Client work needs no pipeline data. The tests build their own small synthetic
packs, and nothing in the default test run touches the network.

## Toolchain

- Rust 1.99 with the `wasm32-unknown-unknown` target (the workspace is in `core/`).
- Python 3.11 or newer, and [uv](https://docs.astral.sh/uv/). CI uses Python 3.12.
- Node 22 or 24, and `wasm-bindgen-cli` 0.2.129 for the Node package.

## Where things live

| Path | Contents |
| --- | --- |
| `core/` | Rust workspace: core, CLI, Python bindings, WebAssembly, pack writer |
| `clients/python/thereabouts/` | Python package, console and MCP server |
| `clients/node/` | Node package, with its tests in `clients/node/test/` |
| `pipeline/`, `config/` | the data build; see [the pipeline guide](docs/pipeline/README.md) |
| `skills/thereabouts/` | the agent skill |
| `tests/` | Python tests: `client/`, `pipeline/`, `skill/`, `e2e/`, `benchmarks/` |
| `docs/` | documentation, indexed in [docs/README.md](docs/README.md) |

## Run the checks

Python, from the repository root. This builds the Rust extension the first time.

~~~sh
uv sync --locked --all-extras
uv run ruff check && uv run ruff format --check && uv run mypy
uv run python -m pipeline dictionary --check
uv run pytest
~~~

Rust:

~~~sh
cd core
cargo fmt --check
cargo clippy --locked --all-targets --all-features -- -D warnings
cargo test --locked
~~~

Node:

~~~sh
cd clients/node
npm ci --ignore-scripts
npm run build      # compiles the WebAssembly into pkg/
npm test
npm run check      # TypeScript declarations
npm run format
~~~

`pytest` skips tests marked `world`, which need a full world release. The
generated data dictionary and dataset README are committed. After changing
`config/dataset.yaml` or `config/api.yaml`, run `uv run python -m pipeline
dictionary` and commit the result.

## Pull requests

Keep a change focused, add a behaviour-level test for new functionality, and run
the checks for the parts you touched. The CI workflows in `.github/workflows/`
run the same commands. By contributing you agree your work is released under
the [MIT licence](LICENSE).

Changes to hashed pipeline modules, policies or source settings re-identify
every build unit and force a full rebuild. Say so in the pull request, and
discuss such changes first.
