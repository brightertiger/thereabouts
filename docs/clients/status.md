# Client state — integrated coordinate frames

Qualified locally on 2026-10-05 in `thereabouts-coords-stitch`, branch
`wp/coords-stitch` (base `27f4343`). Core, PyO3/Python, WASM/Node, MCP and both
CLI hosts use the integrated Rust coordinate implementation and all **380
shared vectors**. Changes are uncommitted; nothing was pushed or published.

The implemented inputs are geodetic and its aliases, ECEF, ENU/NED, UTM,
UTM/UPS MGRS, geohash, pluscode, H3, S2, DMS, NMEA, GeoJSON Point and WKT Point.
The new APIs and explicit CLI frame mode add `query` provenance; legacy reverse
and H3 defaults keep their original result shape. Converted position, H3 cell
centre, catalogue anchor, source height, decoded footprint and measurement
uncertainty retain their distinct meanings. See [coordinate inputs](coordinates.md)
and [CLI/MCP](cli.md).

## Final gates on this tree

| Gate | Final result |
| --- | --- |
| `cargo fmt --check` | Passed |
| Workspace `cargo clippy --offline --locked --all-targets --all-features -- -D warnings` | Passed |
| `cargo test --offline --locked --workspace -- --skip http::tests:: --test-threads=1` | **142 passed**, 0 failed/ignored; 82 core, 49 CLI/CLI-core, 11 writer; 2 HTTP tests excluded |
| wasm32 `cargo check --offline --locked` for core, CLI-core and WASM | Passed |
| Offline locked uv provisioning and editable `maturin develop --offline --locked --uv` | Passed; final extension freshly rebuilt |
| `pytest tests/client` with the two explicit exclusions below | **238 passed**, 0 failed/skipped |
| Repository-wide `ruff check` / `ruff format --check` | Passed; **483 files** checked |
| Repository-wide strict `mypy` | Passed; **471 source files** |
| Real offline release WASM build and wasm-bindgen | Passed |
| Ten permitted Node test files, `node --test --test-concurrency=1` | **445 passed**, 0 failed/skipped; all 380 vectors and three exact geohash cases in four formats |
| `npm run check` / `npm run format` | Passed |
| Clean offline `npm ci` | Blocked: uncached `undici-7.30.0.tgz`; existing pinned dependencies used |

Python uses CPython 3.12.8 and a fresh editable maturin build under
`.cache/coords-venv`; package and `_core.abi3.so` imports resolve inside this
worktree. Rust/cargo is 1.99.0; wasm-bindgen is 0.2.129. All Cargo commands were
offline/locked with the prescribed shared target, one job and one gate at a time.
Rust/Node test-runner concurrency was one. Logs, commands and diagnostics are
retained under `.cache/stitch/`.

Python collection explicitly excludes `tests/client/cli/test_http.py` (six HTTP
tests) and `tests/client/forward/test_plates.py` (three tests; imports pipeline).
Rust excludes two `http::tests` using loopback HTTP. Node runs all ten other test
files and excludes `install.test.js` and `stall.test.js`, which use HTTP.
Neither the pipeline, VM scripts nor full workflow tests were executed. Static
Ruff/mypy checks may read pipeline source; they do not execute it.

Node results are **provisional for the supported runtime matrix**: only
23.10.0 was installed; Node 22/24 and remote CI were not run. A clean
`npm ci --offline --ignore-scripts --no-audit --no-fund` in an isolated directory
with the existing cache failed `ENOTCACHED` for `undici-7.30.0.tgz`. Validation
used copies of existing undici 7.30.0, TypeScript 5.9.3 and Prettier 3.6.2.
This is not a passing clean-install gate.

## Closed integration failures and parity rules

The original **107 Node failures** were reproduced: 105 footprint cases, their
parent and one lease test. WASM scalar rendering reparsed JSON with a lossy
decimal-to-f64 reader; the shared table spool had a second such roundtrip.
Rendering now restores coordinate query numbers with the host's correctly
rounded JSON parser, and the table spool retains coordinate display text.
Conversion maths remain in Rust. The three exact geohash precision regressions
are covered in native and WASM through JSON, NDJSON, CSV and table selection.
The lease test now honors `VIRTUAL_ENV`. Python's stdio MCP inventory now includes
`reverse_point`; its strict schema and annotations are documented in the guides.

Every query field and its schema are compared between direct WASM and CLI with
zero numeric tolerance (`-0` and `0` are numerically equal). Native/WASM full-query
parity permits only `1e-12°` on computed boundary vertices and `1e-7 m` on radius;
measured maxima were `5.69e-14°` and `3.67e-9 m`. These target arithmetic
allowances do not change fixture tolerances: normalized points still use the
core-owned tolerances, and exact half-spans/grid sizes, schemas, status/cells,
error codes, conversion lists and other metadata remain exact. No vector was
removed, skipped or edited. All 380 also run through Python and MCP; MCP returns matching public JSON for
372 schema-admitted vectors and expected transport errors for the remaining eight.

No Rust coordinate contract, public API, dependency, lockfile or workflow changed.
Legacy byte compatibility was rerun against a **fresh local build of pre-coordinate
`4efb85d`**: **340 API results and 1,408 CLI outputs per runtime**, independently
in native Rust and Node/WASM, are byte-identical including stderr and exit codes.
The corpus spans both core fixture packs, evidence on/off, all four output formats,
and CSV/NDJSON batches. Exact captures and artifact identities are retained locally.

## Artifact measurements

| Bytes | Before coordinates | Final tree | Delta |
| --- | ---: | ---: | ---: |
| Generated WASM | 2,535,600 | 2,753,757 | +218,157 |
| WASM gzip | 877,775 | 957,458 | +79,683 |
| Node source payload | 65,593 | 73,949 | +8,356 |
| Node payload including pkg | 2,640,902 | 2,869,686 | +228,784 |

Both endpoints were freshly built with Rust 1.99.0 and wasm-bindgen 0.2.129.
Before is pre-coordinate `4efb85d`; after is this final integrated tree.
Gzip uses level 9 and mtime zero. Payload sums runtime/bin/pkg, declarations,
README, package.json and the root licence; it excludes node_modules and tar
headers. No npm pack or publication ran. Resource logs show processes below
1.5 GB and free disk above 5 GB; the shared target was reused without cleanup.

## Still unverified

- Publication/upstream authentication, independent MGRS lettering/OLC references
  and a surveyed WGS84 station with realization/epoch remain open in the
  [fixture evidence record](../../tests/fixtures/coordinates/README.md).
  Client parity does not authenticate reference material.
- Node 22/24, remote CI, cross-platform packaging and release matrices were not run.
- Clean npm-ci remains blocked by the missing undici tarball cache entry.
- HTTP, pipeline and full workflow suites remain unrun under the task restrictions.
