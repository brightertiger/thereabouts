# Client release engineering

Version 0.1.0 is a draft. No registry release or remote workflow was executed.
The owner publishes 0.1.0 to supersede the old 0.0.1 placeholders; an existing
immutable registry version is not overwritten.

## Artifacts

Python uses maturin, the mixed src/ project and abi3-py311. The wheel contains
the Python API and native Rust extension, including the pipeline writer.
Only NumPy is a mandatory Python runtime dependency; pipeline/dev groups are
retained in uv.lock. The package's PyPI readme is clients/python/thereabouts/README.md.

The Python workflow runs lint, types, pytest and Rust gates, then builds
Linux x86_64/aarch64 manylinux2014, macOS x86_64/arm64 and Windows x86_64 wheels,
plus an sdist. Every wheel is installed in its native runner for a no-data
import/version smoke check. Platform matrix jobs are defined, not locally
emulated or claimed as executed.

The Node workflow builds WASM with the locked Rust workspace and
wasm-bindgen-cli 0.2.129, runs node --test and TypeScript checks on Node 22/24,
and creates an npm tarball. Its whitelist includes the ESM runtime, bin,
declarations, README and generated pkg/ WASM. WASM is not checked in; prepack
builds it reproducibly. Consumers need no compiler. The separate pipeline
workflow runs lint, types and synthetic tests without real data.

## Local reproduction

~~~sh
uv sync --locked --all-extras
uv run maturin build --locked --release --out .tmp/artifacts
uv run maturin sdist --out .tmp/artifacts
python -m pip install /path/to/thereabouts-0.1.0-wheel.whl
python tests/wheel_smoke.py
cd clients/node
npm ci --ignore-scripts
npm pack --pack-destination ../../.tmp/artifacts
~~~

Fresh pip install . is also supported and is tested without installed data.
The release engineering pass checks local native wheel/sdist builds and packed
npm import/version behavior. Artifact sizes and hashes are generated into
CLIENT_PACKAGE_MEASUREMENTS.json by tests/benchmarks/package_artifacts.py.

## Owner publication controls

Publish jobs require all of:

1. An explicit workflow_dispatch with publish enabled.
2. A checked-out tag matching the package version.
3. The pypi-release or npm-release environment, configured by the owner with
   required reviewers and protected tag restrictions.
4. Registry trusted-publisher configuration for that repository, workflow and
   environment.

The workflows use OIDC permissions rather than stored tokens. No token or
credential was added. Environment protection and registry configuration are
external prerequisites, not settings a workflow file can enforce by itself.
Nothing is published on a normal push, pull request or unapproved tag.

The code licence is MIT; review the data redistribution requirements described
in docs/licenses.md before approving artifacts.
Configure the release endpoint and publish verified data separately. Its local
index and archive layout is specified in cli.md; dataset and pack manifests
remain separate inventories. The MY/SG proof includes core plus five forward
packs because the real plate tables are unavailable.

No world build, upstream download or data publication is part of qualification.


## Editable build cache

uv cache keys cover each local crate linked by thereabouts-py, recursive Rust
sources and cli-core resources including grammar.json. The offline regression
check is `uv run pytest tests/pipeline/test_build_cache.py`; it walks the local dependency
graph and requires every source/resource file and crate manifest to be covered.
Rust-only edits therefore invalidate the editable extension on the next uv run.

The MY/SG proof script supports both `python tests/benchmarks/release_path.py` and
`python -m tests.benchmarks.release_path`. With --from and a new worktree-local --output,
it writes measurements.json inside that output. Updating the tracked
CLIENT_RELEASE_MEASUREMENTS.json additionally requires --write. Ordinary
measurement runs leave historical tracked figures unchanged.

## Offline coordinate-client development

Use a dedicated worktree and its own environment. These commands require the
existing offline cache, Rust 1.99, wasm32-unknown-unknown and wasm-bindgen
0.2.129; they never provision a missing tool over the network. First integrate
the core-owned coords module and `tests/fixtures/coordinates/vectors.json`.
A contract stub compile is not a correctness gate. Never replace missing core
code or vectors with a production fallback.

```sh
export CARGO_TARGET_DIR=/Users/ujjwal/Downloads/solo/thereabouts-work/target
export CARGO_NET_OFFLINE=true CARGO_BUILD_JOBS=1
export UV_OFFLINE=1 PIP_NO_INDEX=1 PROJ_NETWORK=OFF
export UV_PROJECT_ENVIRONMENT="$PWD/.cache/coords-venv"
/opt/homebrew/anaconda3/bin/uv sync --offline --locked --all-extras --no-install-project
export VIRTUAL_ENV="$UV_PROJECT_ENVIRONMENT"
export PATH="$VIRTUAL_ENV/bin:/opt/homebrew/anaconda3/bin:$PATH"
# An inherited Conda environment conflicts with the selected worktree venv.
env -u CONDA_PREFIX maturin develop --offline --locked --uv
python -c 'import thereabouts, thereabouts._core; print(thereabouts.__file__); print(thereabouts._core.__file__)'
/opt/homebrew/anaconda3/bin/uv run --offline --no-sync pytest tests/client/core tests/client/mcp
```

Both import paths must resolve to the current worktree's editable build. Never
use another checkout's prebuilt extension as validation evidence. If provisioning
fails, retain the exact offline error and leave the gate blocked. The example's
uv sync installs already locked dev extras but does not run the pipeline.
Only the explicit core/MCP test directories above are authorized here;
`tests/client/forward/test_plates.py` imports pipeline and is excluded. Never run
bare pytest or the pipeline/build-cache tests from this restricted recipe.

Run Cargo checks from `core/`, one process at a time, with the same preset target:

```sh
cargo fmt --check
cargo clippy --offline --locked -p thereabouts-py -p thereabouts-wasm --all-targets --all-features -- -D warnings
cargo test --offline --locked -p thereabouts-wasm
cargo test --offline --locked -p thereabouts-py
cargo check --offline --locked -p thereabouts-core -p thereabouts-cli-core -p thereabouts-wasm --target wasm32-unknown-unknown
```

The Python crate disables its Rust test/doctest harnesses. Its cargo-test exit
status does not validate the extension; the fresh editable build and pytest do.
Check free disk before starting each build and keep it strictly above 5 GiB.
Coordinate with sibling packages, use one Cargo job and never clean the shared
target. Cached declarations and stubs cannot establish conversion correctness.

For Node, use an already installed Node 22 or 24. From `clients/node/`:

```sh
npm ci --offline --ignore-scripts --no-audit --no-fund
CARGO_NET_OFFLINE=true CARGO_BUILD_JOBS=1 npm run build
npm test
npm run check
npm run format
```

`build-wasm.mjs` resolves a supplied `CARGO_TARGET_DIR` from the workspace root,
uses it in Cargo's environment and reads the wasm-bindgen input from it. The
fallback without the environment variable is `core/target`; the preset above
is mandatory for the coordinate packages. Missing npm cache entries are blocked
gates, not permission to fetch them. Using an installed matching TypeScript or
Prettier binary can check source, but does not establish npm-ci success.

The full Node suite includes loopback HTTP and native-Python comparisons. When
network use is prohibited or the native extension is unavailable, run explicit
non-network files only, for example:

```sh
node --import ./test/offline.js --test test/coordinates.test.js test/library.test.js
```

Coordinate parity tests require `THEREABOUTS_PYTHON` to select this worktree's
fresh native installation. Report subsets, facade-only tests, snapshot builds
and unsupported Node 23 runs separately; none qualifies the Node 22/24 matrix.
No package archive, publication, pipeline run or remote CI is required here.
