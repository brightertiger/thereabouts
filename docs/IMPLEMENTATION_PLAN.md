> **Owner decision — 2026-10-01 (phase 2):** Use a single H3 resolution-8
> cell-centre table for city, state and country, accepting quantization error.
> Polygons and nearest-settlement searches are build/test tools only; runtime
> uses H3 and NumPy. This supersedes the runtime architecture and public contract
> below. See [the implemented table design](DESIGN.md) and the dated
> measurements in [EVALUATION.md](EVALUATION.md). The original plan follows unchanged.

# Implementation plan: offline administrative containment and settlement context

Build a Python package whose default answer describes the **original coordinate**: containing country/admin1, plus a separate nearest settlement and its distance. Use a coarse H3 index to accelerate administrative containment only if it beats a direct polygon spatial index on the target workload. Boundary cells must retain original-point polygon checks. Do not materialize a global fine-resolution cell-to-city table.

This is a plan, not an implemented library. The experiments and evidence are in [EVALUATION.md](EVALUATION.md). All sizes and performance numbers below are **estimates [E] or proposed acceptance targets**, unless identified as **measured [M]** or **looked up [L]**. Numeric type widths, API defaults and milestone identifiers are design specifications, not measured findings.

The recommended initial data product is a **cartographic global pack** from Natural Earth administration/land and GeoNames settlements. Its answers are exact only relative to that snapshot's geometry and policies. Higher-detail regional gbOpen packs come after validation. Packaging, data provenance and explicit semantics are the product; H3 is replaceable.

## First milestone: attempt to disprove the accuracy claim

Before a public API, native extension or global table build, reproduce the existing snapping experiment and add one demanding regional pilot: **Belgium/Netherlands country/admin1 borders, enclaves and coastline [proposed pilot]**, using reviewed higher-detail gbOpen data. This is a proposed region, not a dataset already downloaded in this task.

The smallest useful deliverable is a standalone experiment and a short decision report, not a package. It should:

1. Freeze source URLs, metadata, hashes and answer definitions. Define “city” as nearest eligible GeoNames settlement; do not evaluate it against municipality names.
2. Reproduce the existing Natural Earth/GeoNames benchmark and verify the reported resolution range **3–8 [measured experiment configuration]**. The current result already rejects coarse H3 as an accurate nearest-settlement substitute under the tested workload.
3. For the pilot, generate **10,000 random land points and 10,000 border/coastal points [targets]**. Construct the latter by sampling boundary segments by geodesic length, then offsets on both sides. Include island/enclave and dateline/polar synthetic fixtures separately. Report each population independently.
4. Compare direct point-in-polygon at the query, polygon label at the H3 centre, nearest settlement at the query, and nearest settlement at the centre. Separate wrong labels, nulls, ambiguity and source-data gaps. Compare Natural Earth with the more detailed pilot source rather than treating agreement with either as independent real-world truth.
5. Add a small manually adjudicated set against authoritative local evidence. A proposed **100 cases [target]** is enough to expose semantic/source mistakes, not to estimate a global accuracy rate.
6. Measure a direct polygon-index baseline and an exact spherical nearest-neighbour baseline. Estimate whether H3 would reduce actual work; no fine global fill is needed.

**Decision gate:** the owner should adopt explicit error and footprint budgets before reading the pilot outcome. Provisional requirements are **at most 0.1% country/admin1 mismatch and 1% nearest-settlement disagreement [targets]** on a representative deployment workload, with abstentions reported separately. These are product choices, not industry standards. The already-measured settlement-nearby resolution-8 results exceed those error targets. A flat table fails the gate if improving resolution cannot meet both accuracy and distribution constraints. Proceed with polygon containment if source quality is sufficient; otherwise narrow geographic scope or stop. Stop the new product if an existing engine already meets users' requirements and no maintained packaging/data advantage remains.

Estimated effort: **1–3 working days [E]**, assuming accessible pilot data. Preserve and improve the existing external scratch benchmark rather than pretending it is a released, reproducible benchmark suite.

## Public contract

Use a working import name `pyofflinegeocoder`; verify naming availability before release. Support **Python 3.11+ [proposed minimum]** initially, with the exact supported versions determined by tested wheels. All input coordinates are WGS84 latitude, longitude in decimal degrees, in that order.

Proposed public types and signatures:

```python
from dataclasses import dataclass
from os import PathLike
from typing import Iterable, Iterator, Literal

AdminStatus = Literal["matched", "ambiguous", "not_applicable", "no_coverage"]
AdminMethod = Literal["uniform_cell", "polygon", "none"]
PlaceStatus = Literal[
    "matched", "beyond_distance", "outside_land", "no_coverage", "disabled"
]
LandStatus = Literal["inside_mask", "outside_mask", "unknown"]

@dataclass(frozen=True)
class Admin:
    id: str                  # namespaced stable source ID, not a display name
    name: str
    code: str | None         # ISO where actually available
    source: str

@dataclass(frozen=True)
class AdminMatch:
    status: AdminStatus
    value: Admin | None
    candidates: tuple[Admin, ...]
    method: AdminMethod

@dataclass(frozen=True)
class Place:
    geoname_id: int
    name: str
    feature_code: str
    latitude: float
    longitude: float
    distance_km: float       # spherical great-circle distance from the query
    source_country_code: str | None
    source_admin1_code: str | None

@dataclass(frozen=True)
class ReverseResult:
    latitude: float
    longitude: float
    country: AdminMatch
    admin1: AdminMatch
    nearest_place: Place | None
    place_status: PlaceStatus
    land_status: LandStatus
    snapshot_id: str
    policy_id: str

@dataclass(frozen=True)
class DatasetInfo:
    snapshot_id: str
    schema_version: str
    source_dates: tuple[tuple[str, str], ...]
    policy_id: str
    coverage_description: str
    attribution: tuple[str, ...]

class Geocoder:
    def __init__(self, data_path: str | PathLike[str] | None = None) -> None: ...

    def reverse(
        self, lat: float, lon: float, *,
        include_place: bool = True,
        max_place_distance_km: float | None = 50.0,
    ) -> ReverseResult: ...

    def reverse_many(
        self, coordinates: Iterable[tuple[float, float]], *,
        include_place: bool = True,
        max_place_distance_km: float | None = 50.0,
    ) -> Iterator[ReverseResult]: ...

    def info(self) -> DatasetInfo: ...
    def verify(self) -> None: ...  # full local checksum/structure verification
    def close(self) -> None: ...
    def __enter__(self) -> "Geocoder": ...
    def __exit__(self, exc_type, exc, tb) -> None: ...

def reverse(
    lat: float, lon: float, *, include_place: bool = True,
    max_place_distance_km: float | None = 50.0,
) -> ReverseResult: ...  # lazy process-local default Geocoder
```

Behavior to specify before implementation:

- Reject non-finite, boolean and out-of-range coordinates with `ValueError`; latitude range is **[-90, 90]**, longitude range **[-180, 180] [API specification]**. Normalize the accepted longitude endpoint consistently. Do not guess swapped axes or silently wrap arbitrary input.
- `Geocoder()` locates the installed global data distribution; a supplied path selects a local immutable pack. Missing data raises `DataNotInstalledError` with installation instructions. Unsupported schema and damaged files raise distinct errors. No import, constructor, query or error handler downloads anything.
- `reverse_many` preserves input order, streams in bounded batches, and raises on the first invalid pair when iteration reaches it. Earlier results may already have been yielded. CSV/JSONL CLI can later offer a separately documented per-row error mode.
- `country` and `admin1` refer to containing polygons at the original coordinate. `nearest_place` refers to a settlement point. Its source admin codes may disagree with polygon results; never silently “repair” one with the other.
- The **50 km default [proposed policy]** is an explicit proximity cutoff. Passing `None` requests unlimited nearest settlement on supported terrestrial points. Negative/non-finite cutoffs are invalid. Preserve the same policy in batch and scalar APIs.
- Initial settlement search is global and unconstrained by country. A nearby cross-border settlement is a legitimate nearest-place result; its country is visible. Defer a same-country mode until its tie, missing-country and candidate-completeness behavior is specified.
- Country/admin1 can have different statuses. No admin1 in a territory is `not_applicable`, absent source coverage is `no_coverage`, and multiple containing candidates is `ambiguous`. Do not collapse these to an empty string.
- For a global pack, a point outside its mapped terrestrial mask receives `not_applicable` country/admin1 and no settlement by default. Distinguish `outside_mask` from a definitive ocean claim. Normalize the initial mask to retain inland-water areas within administrative coverage; inland lakes may then keep their administration. Surface-water typing needs a separate layer. A regional pack marks points outside its coverage `unknown`/`no_coverage`, not ocean.
- On shared boundaries return all touching candidates under a documented numerical tolerance; on overlapping claims return ambiguity under the snapshot's worldview policy. Do not emit an uncalibrated numerical “confidence.”
- Omit a generic `city` alias and a municipality field from the initial release. Add `municipality` only with genuine municipal polygons and country-specific semantics. GeoNames admin codes are not uniformly ISO subdivision codes. [Schema](https://download.geonames.org/export/dump/readme.txt)
- Do not offer `reverse(h3_cell)` as if it determines an arbitrary original point's side of a border. An explicit future `reverse_cell_center` API could answer the centre question, clearly marked as such; it is outside the initial contract.

## Data build pipeline

### Inputs and provenance

| Input | Initial role | Acquisition and policy |
| --- | --- | --- |
| Natural Earth countries, admin1 and land | Small global cartographic reference and initial pack | Pin archive checksums and actual versions, starting from the [measured sources](EVALUATION.md#protocol-and-meaning-of-ground-truth). Record default worldview and territories separately from sovereign states. Public domain. |
| GeoNames cities1000, countryInfo, admin1CodesASCII, featureCodes | Settlement catalog and readable metadata | Pin daily snapshots. Preserve stable GeoNames IDs, Unicode names, feature codes and original admin codes. Retain named administrative seats according to the source selection. Explicitly record that small villages are omitted. [Download schema](https://download.geonames.org/export/dump/readme.txt) |
| geoBoundaries gbOpen ADM0/ADM1 | Higher-detail pilot, then optional regional packs | Use [API metadata](https://www.geoboundaries.org/api.html), pin returned content hashes and boundary validity years. Review per-source licenses and contested overlaps before joining country files. Do not treat `current` as a reproducible version. |
| Optional municipal/hydrography/OSM layers | Future country-specific capabilities | Keep out of the initial global pack. Require separate semantics, license manifests, sizes and accuracy reports before adding them. |

For every source, retain URL, retrieval time, upstream version/date, validity year if known, checksum, original license, attribution and transformations. Data date and code version are independent. The PDF's licensing motivation favors Natural Earth + GeoNames/gbOpen for the default path; systematically OSM-derived cell tables bring ODbL database obligations. [OSM terms](https://www.openstreetmap.org/copyright)

### Transformation stages

1. **Fetch and freeze.** Fetch only in an explicit build command. Validate checksums, archive contents and schema. Retain a build manifest and source archives outside the source repository. A failed source refresh must not silently produce a partial global release.
2. **Normalize geometry.** Convert coordinates to the documented WGS84 representation; repair invalid geometry and log each repair. Explode multipolygons while preserving source identity and ring holes. Split/wrap antimeridian parts consistently. Treat polar polygons explicitly. Preserve original geometry for the reference oracle.
3. **Normalize administration.** Remove placeholder admin1 records from the real admin1 catalog. Build source-ID mappings, optional ISO codes and parent links. Validate child-parent geometry consistency rather than copying country labels from city metadata. Preserve disputed/overlap records and apply an explicitly versioned policy. Avoid silent geometry unions that erase competing claims.
4. **Establish coverage and land semantics.** Build a coverage mask independent of valid country/admin1 assignments. Decide how the selected land mask treats inland lakes and ice. Test tiny islands and coastal slivers. An absent polygon within a regional pack is not proof of ocean. Do not drop Antarctica by accident; distinguish a territory label from a sovereign-state assertion.
5. **Build the simplest reference index.** Use a polygon bounding-box tree and direct point-in-polygon checks. Use Shapely/GEOS for build/reference validation, not as the required production runtime if the owner retains the permissive-dependency goal.
6. **Build a trial H3 accelerator.** Start at **resolution 4 [target]**. For each cell, either certify a uniform tuple of country/admin1/land/coverage status or record complete candidate polygon parts and a mixed/unproven flag. Uniform means the whole cell is covered consistently and has no competing polygon or enclosed hole/enclave. A centre or vertex test is insufficient.
7. **Make candidate completeness conservative.** Use full polygon intersection, including tiny polygons entirely inside a cell. Ordinary H3 polygon fill is centre-based. Experimental overlapping fills may help generate candidates but require verification. Densified H3 boundaries need a conservative geometric error envelope; any cell without a sound coverage certificate stays mixed. Route polar/dateline exceptions to the direct spatial index until proven. [H3 region APIs](https://h3geo.org/docs/api/regions/)
8. **Keep hierarchy out of the first accelerator.** Map the query directly to the same fixed resolution used during the build. If adaptive H3 is later justified, specify a finest leaf resolution, traverse its logical parents, and certify descendant footprints. Never substitute the parent's drawn hexagon for its descendants' actual footprint. [H3 hierarchy limits](https://h3geo.org/docs/highlights/indexing/)
9. **Build the settlement index.** Convert reference points to unit-sphere Cartesian coordinates and construct a balanced nearest-neighbour tree. Score final candidates in the declared spherical metric. Use stable GeoNames ID to break equal-distance ties. Preserve distance thresholds and a complete search; arbitrary nearest-cell rings or a fixed candidate count do not establish the true nearest settlement.
10. **Serialize and validate.** Emit the format below, deterministic metadata, licenses and benchmark summary. Check source geometry versus serialized geometry, serialized versus reference queries, coverage gaps and null rates. Avoid additional polygon simplification in the first release; source generalization is already a limitation. Any later simplification needs an explicit error budget and shared-boundary topology validation.
11. **Review changes and publish a snapshot.** Compare country/admin counts, areas, settlement additions/deletions, label changes, sizes and benchmark regressions with the prior snapshot. Reject implausible changes for investigation. Package a new immutable data version; existing installations keep their old snapshot until explicitly updated.

### Output and expected size

The canonical artifact is one immutable, memory-mappable **`.pog` data file**, accompanied in its distribution by its manifest and attribution/license notices. Code and data have distinct version numbers. The file may contain multiple internal sections, but users install and select a pack as a unit.

The initial global estimate is grounded in the measured sources, not in a claim that a hybrid has already been built:

| Component | Size basis |
| --- | --- |
| Country/admin1/land geometry | **36.90 MB [M]** combined repaired WKB in the experiment. A canonical ring representation should be of similar order [E], before indexes. |
| Complete resolution-4 cell directory | **4.61 MB [E]**, if all **288,122 cells [L]** use the specified **16-byte records [design]**. A sparse land/mixed directory could be smaller, but needs explicit ocean and coverage handling. [Cell counts](https://h3geo.org/docs/core-library/restable/) |
| Admin tuples, candidate references, bounding-box index and coverage metadata | **5–20 MB [E]**, highly sensitive to geometry splitting and duplicate candidates; measure during the pilot. |
| Settlement catalog, text pool and prebuilt nearest-neighbour tree | **10–20 MB [E]** for the measured **171,094 records [M]**, depending on node layout and selected text fields. Omit alternate-name bulk data initially. |
| Total installed global data pack | Budget **50–100 MB [E]**. The component estimates imply roughly **57–82 MB [E]** before additional alignment/metadata variation. |
| Compressed data distribution | **20–50 MB [E]**, unverified. Actual deterministic build must replace this estimate. |
| Engine and dependency downloads | Separate from data. Aim for an engine wheel **under 5 MB [target]**; measure H3 and native wheel costs on each supported platform. |

The all-land resolution-8 flat table would cost **3.13 GB raw [E]** under the evaluation's narrower row model. The hybrid's expected improvement comes from retaining geometry and settlement points, not from assuming extraordinary compression. Full-detail gbOpen global geometry has **not** been downloaded or sized; distribute regional packs first rather than extrapolating the Natural Earth footprint to it.

## On-disk format and runtime

### Portable sections

Define a versioned little-endian format; do not serialize Python pickles, Rust struct memory or a third-party tree's private binary representation. Validate all section offsets, lengths, counts and flags before access. A new incompatible layout increments the schema version.

| Section | Proposed representation |
| --- | --- |
| Header and directory | Magic bytes, schema version, endian marker, total length, snapshot/policy identifiers, section offsets/lengths and hashes. Integer offsets use explicit widths; readers reject overflow or out-of-file references. |
| H3 directory | Sorted records: `uint64 cell`, `uint32 payload_id`, `uint8 kind`, reserved padding to **16 bytes [design]**. Kind identifies uniform, mixed or unproven cells. Binary search gives logarithmic lookup, not a claimed constant-time hash lookup. |
| Assignment payloads | Deduplicated country/admin1 IDs plus land/coverage/ambiguity flags. Null and unknown are distinct sentinels. |
| Mixed-cell candidates | Offset/count pairs into flat polygon-part ID arrays. Store country, admin1 and coverage/land candidates distinctly. Preserve every overlapping candidate. |
| Polygon parts | Source/admin ID, bounding box, ring ranges and hole roles; coordinates stored as **float64 pairs [design]**. Geographic wrapping policy is part of the format contract. Retain an auxiliary packed bounding-box tree for the direct fallback. |
| Settlement records | Stable ID, source codes, feature kind, reference coordinates, unit-sphere coordinates and string offsets. Float64 calculations preserve the reference metric. |
| Settlement tree | Portable balanced node arrays with explicit child indexes, split axes and bounds. Never load a pickled SciPy tree. Store enough information for a mathematically complete branch-and-bound search. |
| Text and metadata | UTF-8 pools with offsets; compact metadata manifest and source/license references. Decode result strings on demand. |

Prefer a proven geometry predicate over writing an ad hoc ray-casting routine as a shortcut. Large source polygon parts can be expensive to test; benchmark component-level bounding boxes and bounded caching before adding clipped-cell geometry. Clipping and duplicating geometry into every H3 boundary cell may erase the expected space advantage and introduce numerical seams.

### Loading and lookup sequence

1. Import creates no geocoder and reads no dataset. The first `Geocoder` opens the pack read-only, validates its header/section structure and memory-maps it. The default helper lazily retains a process-local instance.
2. Mapping does not mean all pages are resident. Do not copy the cell directory into a Python dict or parse all names and geometry at startup. Decode only requested records. Use a bounded geometry cache; an initial **8 MiB cap [target]** is a tuning choice, not an observed requirement.
3. Validate the coordinate, determine coverage, and compute the configured H3 index through the official binding. Search the cell directory. Use a uniform assignment only when its certificate covers the complete source-policy tuple.
4. For mixed cells, check the original point against all candidate polygon parts. Return the defined ambiguity/null results. For unproven cells or index anomalies, use the global bounding-box index; never silently return the cell centre's label.
5. If requested and permitted by land/coverage policy, query the settlement tree using the original point, convert chord distance to spherical distance, enforce the cutoff and attach the settlement's own metadata.
6. Construct immutable Python results. Batch calls should keep geometry/metadata cache locality and amortize Python/native crossings; preserve input order even if internal work is grouped.
7. `close()` releases mappings and caches; subsequent calls fail predictably. New processes reopen the same immutable file. Test threads, process spawning and interpreter teardown; do not assume inherited native handles are safe after a fork.

Full-file checksum verification occurs during installation/explicit `verify()` and can be streamed. It should not scan the entire pack on every constructor call and invalidate startup goals. The file remains immutable while open; updates install a separate version and switch on a later open. Initial implementation should validate section structure on open and validate data when decoded, with optional section-hash verification; do not call mmap alone a corruption check.

Proposed performance gates, measured on a stated ordinary laptop, are:

| Metric | Target, not measured |
| --- | --- |
| Import with no data access | **under 50 ms** |
| `Geocoder` open with warm OS cache, excluding explicit full checksum | **under 50 ms** |
| Fresh process to first result with warm OS cache | **under 150 ms** |
| Warm scalar lookup | **median under 50 µs; p99 under 1 ms** |
| Mixed random batch | **at least 100,000 points/s**, returning results under the full semantics |
| Peak RSS with a warmed global pack and streaming workload | **under 150 MB**, without materializing the whole input/output batch |

Also publish genuinely cold filesystem timings, page faults, installed size and geometry-fallback fraction; there is no validated cold-disk budget yet. These targets prioritize correctness and resource use. The measured existing nearest-place engines can be faster than the provisional batch target, so do not advertise a speed win without a fair benchmark. Retain H3 only if it provides a meaningful measured advantage over the direct polygon index without changing answers.

## Package layout and dependencies

The following is a **future layout**, not files created by this research task:

```text
pyproject.toml
src/pyofflinegeocoder/
    __init__.py           # public, lazy API
    api.py                # result construction, lifecycle, batch behavior
    models.py             # typed immutable result definitions
    errors.py
    datasets.py           # local discovery and metadata; no implicit downloads
    cli.py
    py.typed
native/
    Cargo.toml
    src/lib.rs            # PyO3 interface
    src/format.rs         # validated portable-file reader
    src/admin.rs          # candidate traversal and polygon predicates
    src/places.rs         # spherical nearest-neighbour search
build_data/
    sources.py
    normalize.py
    build_index.py
    pack.py
    validate.py
benchmarks/
    accuracy.py
    runtime.py
    fixtures/             # small redistributable cases and expected results
tests/                    # unit, property, integration and install tests
docs/
data-release/            # manifests/build config only, not raw large datasets
```

Use a small Python API over a native runtime **only after the accuracy/data gate passes**. This follows the PDF's proposed permissive-runtime positioning and avoids making SciPy/GEOS a requirement for every user. The price is responsibility for native wheels; if the owner prefers a simpler all-Python-stack product with LGPL-compatible dependencies, that is a material scope decision, not an invisible implementation substitution.

Dependency choices:

- **Production Python:** standard library plus official [`h3`](https://github.com/uber/h3-py), Apache-2.0. Pin and test a supported major API range; do not hardcode private H3 bit manipulation in Python.
- **Production native:** Rust with [PyO3](https://github.com/PyO3/pyo3) bindings and [geo](https://github.com/georust/geo) polygon predicates, permissive MIT/Apache choices. Use a reviewed permissive mmap implementation. Audit the full locked dependency graph and notices. Do not enable optional GEOS/PROJ paths accidentally.
- **Nearest-neighbour runtime:** a documented portable node layout and complete traversal, either through an audited permissive library supporting that layout or a small independently tested reader/query implementation. Keep SciPy's spherical KD-tree as the reference oracle. Do not port LGPL code from an existing geocoder.
- **Build/reference tools:** Python, H3, NumPy, SciPy, Shapely/GEOS, GeoPandas/pyogrio, and a downloader. Pin versions in a reproducible builder environment. These are not runtime dependencies of the proposed distributed engine. Using LGPL build tools does not itself make generated factual data LGPL, but their own redistribution obligations still apply if the builder image is distributed.
- **Tests/build:** pytest, property-testing tooling, maturin and wheel CI; pin the native toolchain for releases. Check Linux, macOS and Windows wheels on the supported Python versions, including ARM where promised. Do not publish platform support based solely on a successful source build on the developer's machine.
- **CLI:** standard-library argument parsing and CSV/JSONL support first. A local MCP adapter should be an optional extra only after real users request it; it must delegate to the same engine and never supply an online fallback by surprise.

The native backend is a recommended production direction, **not a prerequisite for the first prototype**. A Shapely/SciPy reference implementation establishes whether the data and semantics warrant any further engineering. Avoid claiming an entirely permissive runtime if that reference stack becomes the released runtime: Shapely wheels bundle LGPL GEOS. [Shapely licensing](https://shapely.readthedocs.io/en/2.0.7/index.html), [wheel composition](https://shapely.readthedocs.io/en/2.0.7/installation.html)

## Testing and accuracy benchmarks

Keep **algorithm error**, **source error**, **coverage**, **abstention** and **semantic disagreement** separate. A response can match the source perfectly while still being geographically outdated. Report sample denominators and confidence intervals, not a single unsupported “global accuracy” score.

### Correctness and geometry

- Differential tests: direct original-source polygon oracle versus normalized geometry versus serialized runtime output. Compare status and candidate sets, not only one chosen label. Uniform-cell and polygon-fallback answers must agree under the same source policy.
- Candidate completeness: enclaves wholly inside cells, holes, islands whose centres lie offshore, thin corridors, multipart regions, overlapping claims, mixed land/water cells, adjacent subdivisions and tiny source polygons. A nearest-boundary-centroid shortlist is not a complete containment index.
- Spherical/index edge cases: both sides of the antimeridian, poles, every relevant pentagon, resolution transitions and cell edges. If compaction is later added, test logical-parent versus direct-coarse-cell disagreements explicitly.
- Administrative semantics: countries without admin1, missing codes, placeholder features, territories versus sovereign states, mismatched parent layers and source overlaps. Tests should encode the chosen worldview, not assert it is universally correct.
- Nearest place: compare to a brute-force spherical oracle on manageable fixtures and a unit-sphere SciPy tree on the full catalog. Exercise ties, co-located records, high latitude, longitude wrap, no local settlement, disabled lookup and exact cutoff behavior. Spherical distance is the contract; do not silently claim ellipsoidal geodesic accuracy.
- Input and format: NaN/infinity, booleans, endpoints, empty batches, malformed headers, unsupported schema, truncated sections, invalid offsets, bad UTF-8, close/reopen and concurrent reads. No network must be reachable during query tests.

### Sampling and release reports

Maintain frozen seeds and immutable benchmark fixtures. Include:

- The existing area-uniform and settlement-nearby populations, with Antarctic results also reported separately.
- Population-weighted points if a suitably licensed population grid is added; record its year and sampling weights. Equal settlement weighting is not population weighting.
- Real consenting customer workloads, when available, using the distribution that actually matters to the application.
- Separate international land borders, admin1 borders, coastlines, inland water, dense settlements, rural locations, wilderness, small islands and disputed/unsupported areas.
- A boundary-distance diagnostic, using proposed bands **0–100 m, 100 m–1 km, 1–5 km, and beyond 5 km [test design]**. Construct distances geodesically or in validated local projections; buffers in longitude/latitude degrees are not metre distances.
- Independent source checks and manually labeled cases. Do not tune and certify on the same pilot fixtures; retain a held-out sample and unseen regions.

For each level, publish mismatch count/rate, abstention count/rate, coverage, ambiguity, denominators and **95% intervals [reporting specification]**. For nearest settlements report identity agreement with the selected catalog, distance distribution and any additional distance incurred by approximation. Do not call catalog agreement municipal accuracy. For regional packs, report omissions at pack edges and policy transitions explicitly.

Proposed release gates:

- **Zero known candidate-omission bugs [target]** and no deterministic unambiguous mismatch against the source oracle outside explicitly declared numerical boundary handling.
- A statistical source-agreement target of **at least 99.99% [target]** for country/admin1 on the held-out unambiguous benchmark, with all failures inspected and no exclusion chosen after seeing errors. A sample with no failures is not proof of perfect global accuracy.
- Exact nearest ordering under the chosen spherical metric, with documented numerical/tie equivalence. A spatial cache must never change that answer unless an explicitly approximate API is added.
- No hidden reduction in coverage or increase in nulls to make the accuracy number look better. Report these separately and reject unexplained regressions.
- Hash-identical output for repeated builds from pinned inputs and toolchain, or a documented explanation and deterministic normalization for fields such as timestamps.

### Resource and competitor benchmarks

Run cold process, warm process, single-call, streamed batch and repeated-coordinate workloads separately. Measure time to import, time to map data, first result, warm median/p95/p99, throughput, peak RSS, page faults, installed bytes, compressed bytes and dependency footprint. Report CPU, storage, OS, Python version, dataset hashes, concurrency and cache state.

Use two comparisons: native shipped competitor datasets to describe actual installation experience, and matched input data/semantics where adapters permit it to compare algorithms. Include `reverse_geocoder`, `reverse_geocode`, permissive `rgeocoder`/rrgeo, `python-gazetteer`, and direct polygon + spherical tree. Label unmatched semantics. The earlier binary-only `rgeocoder` installation failed on the available **CPython 3.12 macOS arm64 environment [M]**; try a supported wheel environment in benchmark CI and report the installation result honestly.

Do not let result collection dominate the claimed data footprint: measure idle, warmed lookup and full batch-harness RSS separately. Include H3 conversion and Python result construction in end-to-end claims. Assess whether supporting an H3-free direct-index build would be the simpler product.

## Data packaging and distribution

Use separate distributions:

- `pyofflinegeocoder`: API/native wheels, licenses, typed interfaces and no large embedded global dataset.
- `pyofflinegeocoder-data-world`: a platform-independent wheel carrying one default cartographic `.pog` file, manifest, attribution and data licenses. This avoids duplicating the same dataset across platform wheels.
- Proposed convenience installation: `pip install pyofflinegeocoder[world]`. The extra installs a tested compatible data version at installation time; queries remain entirely offline. Also support `Geocoder('/local/path/world.pog')` for explicit air-gapped distribution.

Names are provisional. Independently version engine schema and data snapshot; state the accepted schema range and record both in every result. The data wheel should contain its compressed wheel member as normal, leaving the installed `.pog` uncompressed for mmap. Do not ship a gzip that every process must decompress on startup. A zip-imported/unextracted data file should produce a clear unsupported-layout error or require explicit extraction during installation.

Current PyPI default limits are **100 MB per file and 10 GB total per project [L]**. Release CI must measure actual artifacts, including cumulative storage. Aim below **80 MB per uploaded data artifact [target]** for headroom. A platform-independent data wheel prevents unnecessary multiplication across native builds. [PyPI storage limits](https://docs.pypi.org/project-management/storage-limits/)

If a detailed pack exceeds the practical wheel budget, provide a reviewed versioned regional artifact through release/object storage, with checksums and an explicit download/install command. Allow manual transfer into an air-gapped system. Do not depend on PyPI granting a size-limit increase. Do not split one giant unbounded dataset into arbitrary PyPI packages just to evade the limit; meaningful regional packs should have independently useful coverage.

Country packs need exact coverage boundaries and a consistent worldview. Nearest-settlement search at pack edges requires either the small global settlement catalog or a halo at least as wide as the configured cutoff. An unlimited nearest search cannot be promised from a finite halo; prefer a shared global settlement catalog, otherwise return an explicit coverage limitation. Prevent mixing incompatible snapshot/policy versions silently.

Keep raw source downloads out of Git. Release the build recipes, license manifest and source hashes; retain retrievable source snapshots where licenses permit. Include source attribution in a readable `DATA_LICENSES`/attribution file and `Geocoder.info()`. Engine code can be Apache-2.0 while GeoNames/gbOpen portions remain CC BY. An optional OSM-derived database needs its own ODbL compliance and notices.

Suggested maintenance cadence is a **quarterly reviewed data release [proposed policy]**, with urgent fixes for demonstrated material errors. Periodically check daily upstream data in build infrastructure, but do not update user installations automatically. Document support for old schemas, a deprecation policy and a reproducible archive strategy; never treat yanking a PyPI release as freeing its storage.

## Milestones after the accuracy pilot

Durations below are planning estimates for a contributor already comfortable with geospatial data and Python; native packaging and problematic source boundaries can dominate them. They are not commitments.

| Milestone | Concrete output | Exit decision | Effort [E] |
| --- | --- | --- | --- |
| M1: accuracy falsification | The minimal experiment described first, plus reviewed semantics and error/size budgets | Reject flat H3 if it fails; narrow scope or stop if available data cannot support the desired contract | 1–3 days |
| M2: frozen data and reference engine | Reproducible pilot/global source manifests, normalization logs, direct polygon + spherical tree reference, coverage and licensing policy | Source quality and null/ambiguity behavior acceptable on held-out cases; owner accepts nearest-settlement semantics | 3–5 days |
| M3: test the accelerator | Fixed-resolution candidate/uniform index compared with direct polygon indexing; first real byte counts and fallback rates | Retain H3 only with complete candidates, identical source-relative answers and a useful measured runtime/footprint benefit | 3–5 days |
| M4: runtime and format | Validated mmap format, typed Python API, permissive native reader/predicates/search, differential tests | Correctness gates pass; startup/RSS/throughput measured against targets; otherwise simplify or adjust claims | 1–2 weeks |
| M5: installable release candidate | Engine wheels, universal world-data wheel, explicit local data selection, offline install/query tests, attribution, benchmark report | Supported platforms install without a compiler; actual PyPI files fit budgets; no first-query download | 3–5 days |
| M6: usefulness and upkeep | Small user trial, data-refresh/correction procedure, CSV/JSONL CLI | Users demonstrate a need beyond an existing engine; a maintainer owns the data release process | 1 week, plus ongoing maintenance |
| Later, conditional | Detailed country packs, municipality layers, adaptive H3, optional local MCP | Each addition addresses demonstrated demand and has its own coverage, license, size and accuracy evidence | Unestimated until scoped |

Do not begin with MCP, hosted services, address matching, a worldwide municipality layer or a maximal-resolution build. These add scope before the core proposition is tested. If H3 loses the M3 comparison, the public API and data contract can remain while the internal accelerator is removed.

## Decisions the owner must make

1. **Primary user and query distribution:** batch GPS analytics, embedded Python applications or interactive place context? Is global cartographic accuracy sufficient, or is a smaller high-detail territory the actual product?
2. **Meaning of place:** accept the proposed `nearest_place` contract, or require legal municipal containment? Confirm settlement selection, the proposed distance cutoff, language handling and whether cross-border nearest settlements are acceptable.
3. **Accuracy, abstention and resource budgets:** choose measurable per-level limits, boundary behavior, pack size, startup and memory targets. These determine whether there is a product advantage worth the maintenance cost.
4. **Worldview and water:** decide how disputed territories, dependencies, Antarctica, inland lakes, offshore points and source gaps are represented. Maritime jurisdiction is excluded unless separately commissioned.
5. **License requirement:** permissive new code only, or a fully permissive shipped runtime dependency graph? The plan recommends the latter to preserve the PDF's proposed distinction, at the cost of native wheels. Confirm whether optional ODbL packs are acceptable.
6. **Distribution and maintenance commitment:** bundled default data extra versus explicit pack installation, supported Python/OS targets, data-release cadence, correction ownership and long-term reproducible snapshot storage.

The immediate next action is M1. The research already establishes that the plain centre table is a poor default; the remaining question is whether a well-packaged, source-aware hybrid solves a specific user's problem better than the available alternatives.
