# Building and measuring the Python client

> Historical: this document describes the retired Python/Cython client. Its
> commands and API are no longer supported. See [CLIENT_RELEASE.md](CLIENT_RELEASE.md)
> for current builds and [CLIENT_STATUS.md](CLIENT_STATUS.md) for current measurements.

The Python client can use an optional Cython kernel to reconstruct the H3 identity
of a stored cell. `Geocoder(..., backend="python")` selects the reference path;
the default `backend="auto"` selects the extension when present. `info()` reports
`python` or `cython`. Both paths use the same NumPy searches, labels, catalogue
validation, geographic data and public results. Only a missing extension permits
fallback; a broken dependency import or runtime failure propagates.

The fallback requires no Thereabouts extension or Cython runtime. NumPy and H3
remain runtime dependencies, including their own compiled components. Queries
never compile code or install dependencies.

The read-path redesign and current populated-sample measurements are in
[CLIENT_PERFORMANCE.md](CLIENT_PERFORMANCE.md). Both backends now meet the
requested warm targets there. Numeric columns reconstruct parents in NumPy;
the Cython kernel is used by scalar/object results. The measurements below
describe the phase 4 baseline, before that redesign.

## Why this kernel (phase 4 baseline)

A preliminary profile of 10,040 synthetic numeric-column queries attributed
0.056 of 0.196 seconds (29%, including child calls) to reconstructing stored H3
cells. That function extracts base-7 digits, fills H3 fields and validates the
result with H3. The 47-line Cython implementation preserves those checks and
implements no geographic policy. Tests exhaust all local keys in ordinary,
pentagon and polar blocks, including invalid digit slots; compare scalar, batch
and column results; and test fallback and failure propagation.

[CLIENT_ACCELERATION_MEASUREMENTS.json](CLIENT_ACCELERATION_MEASUREMENTS.json)
records the comparison on **Apple M2, 8 GiB RAM, macOS 27 arm64, Python 3.12.8**,
H3 4.5.0 and Cython 3.3.0. The sample is the same **208,592-byte synthetic pack**
with 67,230 stored rows, seven blocks and five retained places. Queries are
clustered in four dense blocks; no cache eviction or real catalogue pressure
was measured. Seven alternating warm numeric-column runs gave:

| Measurement | Python | Cython |
| --- | ---: | ---: |
| Median numeric-column points/s | 108,381 | 150,991 |
| Reconstruction kernel mean | 2.612 µs | 0.216 µs |
| Public scalar median / p99 | 198.667 / 251.708 µs | 195.000 / 283.292 µs |
| Public-result batch points/s | 5,116 | 5,079 |

Numeric-column throughput improved **39%**. There is no demonstrated improvement
in public-result throughput. Catalogue record decoding consumes roughly **85%**
of the public batch profile; this motivated the now-implemented bounded decoded-place cache. At this
baseline the scalar and public batch targets were unmet.
The two public measurements ran sequentially in one process, so their reported
peak RSS values are cumulative high-water marks, not isolated backend footprints
(the combined peak was 114,180,096 bytes).

Reproduce after building the extension in this worktree:

```sh
TMPDIR="$PWD/.cache/tmp" OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  .venv/bin/python -m benchmarks.acceleration \
  .cache/serving-measurement-reviewed/pack --output .cache/acceleration.json
```

## Native and fallback distributions

The setuptools backend builds the checked-in generated C by default and fails
if the compiler fails. It does not silently produce a wheel lacking the extension.
Set `THEREABOUTS_PURE_PYTHON=1` to build a separate `py3-none-any` wheel. Data and
build-stage dependencies are excluded from both wheels. The sdist includes the
Cython source, generated C and tiny fixture for validation; Cython is needed to
regenerate C, not to build the sdist's extension.

From the worktree, with temporary/cache directories already created:

```sh
TMPDIR="$PWD/.cache/tmp" UV_CACHE_DIR="$PWD/.cache/uv" uv sync --frozen
.venv/bin/cython src/thereabouts/reading/_reader_cy.pyx
TMPDIR="$PWD/.cache/tmp" CLANG_MODULE_CACHE_PATH="$PWD/.cache/clang" \
  .venv/bin/python setup.py build_ext --inplace
TMPDIR="$PWD/.cache/tmp" UV_CACHE_DIR="$PWD/.cache/uv" \
  uv build --sdist --wheel --out-dir .cache/wheels/native
THEREABOUTS_PURE_PYTHON=1 TMPDIR="$PWD/.cache/tmp" UV_CACHE_DIR="$PWD/.cache/uv" \
  uv build --wheel --out-dir .cache/wheels/python
```

Generation is pinned to **Cython 3.3.0** in the dev dependency group and lockfile.
Regenerating the C file was byte-identical. The generated file intentionally
exceeds the handwritten module size guideline; review the `.pyx` and exhaustive
parity tests. Its Git attributes mark it as generated and exempt only that file
from whitespace checks, preserving exact compiler output. This uses Cython's documented [C generation and distribution
model](https://cython.readthedocs.io/en/stable/src/userguide/source_files_and_compilation.html).

`pyproject.toml` supplies [cibuildwheel options](https://cibuildwheel.pypa.io/en/stable/options/)
for normal-GIL CPython 3.11–3.14, native Linux/macOS host architecture and Windows
AMD64, excluding musllinux. Run on both x86_64 and arm64 Linux/macOS hosts for
the proposed 20-wheel matrix. The configured wheel smoke test asserts that the
extension is present, uses an installed wheel outside the source import path,
and compares a verified fixture result against the Python backend. No CI workflow
was triggered, and other hosts/CPython versions remain unqualified.

Only local CPython 3.12/macOS arm64 builds were executed:

| Local artifact | Bytes |
| --- | ---: |
| Native wheel (`cp312-cp312-macosx_11_0_arm64`) | 72,937 |
| Fallback wheel (`py3-none-any`) | 49,628 |
| Source distribution | 124,458 |

Both wheels were installed in separate fresh worktree-local environments containing
only their runtime dependencies, and passed `python -I tests/wheel_smoke.py PACK
BACKEND`. The fallback wheel contained no shared library or C/Cython source;
the sdist contained both sources and no compiled binary. With both wheels offered
via local `--find-links`, pip selected the fallback for simulated Linux s390x
wheel tags. This tests wheel selection, not runtime or NumPy/H3 availability on
s390x. No package was uploaded or published.

## Final client qualification after phase 7

The rebuilt macOS arm64/CPython 3.12 native wheel is **93,496 bytes**, fallback
wheel **70,188 bytes**, and sdist **139,866 bytes**. Both installed wheels pass
reverse lookup, fallback parity, postal multiplicity and airport ambiguity
smoke tests with source imports excluded. The native wheel with the explicit
`mcp` extra also passes an actual stdio round trip in an isolated host/server;
the base fallback wheel reports a clear optional-extra error for `mcp` while
normal lookup imports neither MCP nor Pydantic. No package is published.

Wheels exclude build stages, fixtures, world data and C/Cython sources. The sdist
contains the generated C and Cython input and no shared library. Other platform
wheels and remote CI remain unverified. See [MCP_SERVER.md](MCP_SERVER.md) for the
transport bounds, measured resource correction and tested host configuration.
