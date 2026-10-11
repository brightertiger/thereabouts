# Client release engineering

Version 0.1.0 is the first published client release; it supersedes the old
0.0.1 registry placeholders. An existing immutable registry version is never
overwritten.

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
Data is published separately, to GitHub Releases by default (see
docs/pipeline/release-procedure.md). Its local
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
