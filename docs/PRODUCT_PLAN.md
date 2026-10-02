# Thereabouts product implementation plan

**Recommendation, 2026-10-02:** build an offline place-context library with a
Python + Cython core, Python/CLI/npm clients and selected integrations. Begin with
coordinates and H3 cells: the [market check](MARKET_CHECK.md) found demand for
reverse geocoding, while demand for the wider bundle remains unproven.

## The first page: what to build and decide

**First release: a Thereabouts preview in 4–6 engineer-days.** Ship the renamed
Python package and CLI for coordinates, r8 H3 cells and bounded batches. Explicitly
download `reverse-preview`: the existing **21.35 MB archive / 53.06 MB installed**
world table. Include offline installation, dataset identity, attribution and
method/null semantics. Label its old nearest-settlement policy
`legacy-nearest-50km`; freeze that snapshot rather than maintain a second pipeline.
These are [measured old-table sizes](EVALUATION.md), not golden-data forecasts.

Then ship a **golden-data Python/Cython reader in 15–25 days**, using a new exporter
after validated v2. A *pack* is an independently installable, immutable set of
data files plus a manifest listing checksums, versions and notices. Readers use
compact binary indexes. Add **one requested lookup family in 5–8 days**, a
**Node-only npm reader in 8–12 days**, and **one integration in 2–5 days**. Each step
ends in a usable release and a demand gate. The parallel v2, plate and rename work
are dependencies, excluded from these estimates.

The owner needs to decide:

| Question | Recommendation | Main consequence of the alternative |
| --- | --- | --- |
| **Preview now or wait for normalized cities?** | Release now; test three real workflows with disclosed limitations. | Waiting delays learning until the golden reader and v2 quality work finish. |
| **How should npm use the core?** | A JS reader of the same format, with shared conformance fixtures. | Shared C reduces duplicated algorithms but adds native builds; a Python worker adds a second installed runtime. |
| **Must npm run in browsers?** | Node only initially. | Browsers add storage quotas, eviction, workers and different cold reads; Wasm alone does not solve these. |
| **Download automatically on first lookup?** | Explicit `data install`; queries never use the network. | Automatic downloads ease demos but complicate latency, disk use and offline guarantees. |
| **Which code licence, and accept ODbL data?** | MIT code before preview; ODbL detailed data with source obligations reviewed before upload. | Apache-2.0 adds an explicit patent grant/notice duties. Permissive-only data requires replacing ODbL inputs and rebuilding. |
| **What earns additional inputs?** | Two users demonstrate the same multi-input join problem; postal first if requested. | Building every family adds update/support tracks before proving value. |

**Success:** three independent real workloads, two planned repeat integrations,
and acceptance of actual data size, licence and answer quality. Package download
counts and pipeline completion do not establish that demand.

## 1. What exists, and what the product adds

The current `src/pyofflinegeocoder/` reads `h3-table-v1`, using H3 and NumPy. It
does not read golden Parquet. Its measured warm median of 13.54 µs and batch rate
of 436,159 points/s describe one M2 workload. The [design](DESIGN.md) already
provides useful ancestor addressing, memory-mapped files, lazy string decoding,
bounded batches and verification. *Memory mapping* lets the operating system load
file pages as needed; installed size is not the same as resident RAM.

The golden pipeline has done the expensive geographic reconciliation and joins.
The client still needs a serving exporter, reader, installer, public result model,
pack lifecycle and release tests. Reusing `build_data.golden.reader.Cells` as the
public runtime would bring build-time concerns into the package and would not
provide the intended small dependency and latency contract.

**Observed baseline:** read-only inspection of the completed `golden-1` manifest
and representative Parquet footers on 2026-10-02 found **2,537,060,501 payload
bytes**, across 42,164 listed tables. This excludes the manifest and reports; it
refines the task’s approximate 2.7 GB description. The manifest is dated
`2026-10-02T01:59:25.377028+00:00`, SHA256
`0834561dac0efaa67c493613fc303b5ee7627360d1f96b34270de0daed6a10f8`.
The observed file was under the permitted main-checkout `data/golden/` directory;
no build, scan of all cell values or re-verification of its payload hashes was run.

| Golden table family | Rows | Measured Parquet MB, decimal |
| --- | ---: | ---: |
| Cells | 62,355,684 | 604.43 |
| Places | 6,875,329 | 1,424.45 |
| Postal | 5,036,067 | 127.67 |
| IP ranges | 7,786,864 | 289.80 |
| Airports | 86,154 | 9.46 |
| Trade locations | 116,213 | 8.11 |
| Timezone memberships + IANA tables | 4,567,490 + 821 | 61.12 |
| Phone prefixes + numbering metadata | 427,963 + 254 | 11.14 |
| Countries + subdivisions | 252 + 8,911 | 0.88 |

These are build-output sizes, not serving-pack sizes. Much of the place schema is
source IDs and JSON evidence; it is not appropriate to materialize 6.9 million
Python objects on open. Lookup rows preserve observations and duplicates, rather
than constituting unique geographic entities. Schema details are in
[GOLDEN_DATASET](GOLDEN_DATASET.md) and [GOLDEN_V1](GOLDEN_V1.md).

The worktree’s [GOLDEN_V2](GOLDEN_V2.md) records a passed pilot and a world build
in progress. It adds canonical cities, place-to-city mappings, settlement kinds
and explicit assignment methods. The town-radius rule is **off**, as already
decided by the owner. Do not reopen that choice in the runtime. The final v2
snapshot, its holdout result and plate schema are not available here. The serving
exporter must consume their eventual verified manifests, not assume that these
v1 counts or pilot results describe the final world.

The product boundary is place context: settlement, administration, associated
entities, candidates and evidence. Addresses, navigation, authoritative municipal
containment at the original coordinate, device/person tracking, fuzzy global
search and current currency policy are outside the initial product.

## 2. Architecture and the npm decision

```text
Acquisition → reconciliation → base H3 cells → city normalization → golden v2
                                                        (Parquet + evidence)
                                                                  │
                                              new serving exporter + verifier
                                                                  │
                                                immutable packs on Hugging Face
                                                      /                   \
                                   Python reference + Cython         Node JS reader
                                          │                          same file format
                                Python API and CLI                   same test vectors
                                          │
                                optional analytics / MCP adapters
```

**Recommendation:** put geographic policy in the pipeline and portable data.
Readers implement addressing, exact-key searches, interval searches, validation
and decoding. They do not independently infer cities or redo spatial joins.
Python owns the first implementation and public API. Cython accelerates a few
numeric operations; CLI and Python integrations call that API. The Node client
shares the format and observable contract, not Python binaries.

A normal Cython extension is a CPython extension. Node cannot load it as a Node
add-on. Cython-generated C is not automatically an independent C library: it
usually depends on Python objects and the Python runtime. There are four realistic
choices; effort below is planning judgement beyond the Python reader.

| npm implementation | Initial effort | Cost over several years | Recommendation |
| --- | --- | --- | --- |
| JS reader + `h3-js` | 8–12 days for reverse lookup, pack management and parity | Two small decoders/search implementations; every format change needs both. No native Thereabouts add-on builds. | Start here, after the format settles. |
| Small hand-written C kernel, called by Cython and a Node-API binding | 15–25 days for extraction, bindings, memory ownership and packaging | One hot algorithm, but Python wheels plus Node OS/CPU/libc artifacts, sanitizers and native debugging. Public wrappers and installers still differ. | Reconsider if real Node workloads miss their agreed performance budget. |
| C kernel compiled to WebAssembly | 20–35 days including a first storage adapter; browsers add more below | Portable compute artifact, but asynchronous file access, memory copies, workers and JS/Wasm interface maintenance. | Appropriate only with a demonstrated browser requirement. |
| npm launches a persistent Python worker / local server | 3–5 days | Two installed runtimes, environment discovery, protocol versions, lifecycle and IPC overhead. Per-query process launches are unusable for this purpose. | An opt-in deployment bridge, not the npm product. |

Node-API provides ABI stability—binary compatibility across supported Node
versions—for add-ons using that API. It does not remove platform builds or make
external libraries ABI-stable. The official docs describe `node-addon-api` and
prebuilt-binary tooling such as `prebuildify`. These make the C option feasible,
not free. [Node-API documentation](https://nodejs.org/api/n-api.html)

Use the maintained [h3-js binding](https://github.com/uber/h3-js) for coordinate
conversion; it already transpiles the H3 C core. Match supported H3 versions
across clients and test coordinate-to-cell agreement at edges. Expose H3 keys as
lowercase hexadecimal strings in JSON; a JavaScript `Number` cannot exactly
represent arbitrary uint64 values. Use `BigInt` or two uint32 halves internally.

**Node storage is a real difference.** Start with asynchronous file reads and a
bounded cache of blocks/pages, with a proposed 64 MB configurable cache. Read the
small directory once; group batches by block, then restore input order. Do not
load the whole world into a Buffer or imply that JS has Python’s mmap behavior.
Use `await Geocoder.open(...)`, `await reverse(...)` and an async batch iterator;
measure event-loop delay as well as throughput. Support Node 22 and 24 LTS at
launch if still maintained then; the live release table currently lists those
as LTS and 26 as Current. [Node release table](https://nodejs.org/en/about/previous-releases)

Browser support would need regional packs, persistent browser storage, explicit
quota/eviction recovery, asynchronous opening and a worker to keep the UI
responsive. Budget a separate **15–25 days after the Node reader**, before mobile
browser qualification. Emscripten’s default filesystem is in-memory; alternative
backends must be enabled. A Wasm build does not make a gigabyte dataset behave
like a local mmap. [Emscripten filesystems](https://emscripten.org/docs/api_reference/Filesystem-API.html)

Keep one repository and one release checklist. Do not create a general plugin
framework or promise a shared C ABI before a second consumer needs it.

## 3. Serving files and the export stage

### 3.1 Format recommendation

Keep Parquet as the canonical build/audit output and an optional analytics
download. It is columnar and compressed: random lookups can require decoding
pages and constructing larger runtime objects. A new **`thereabouts-pack-1`**
format should use immutable binary arrays and UTF-8 string blobs. It is a new
serving format, distinct from both `golden-2` and the old `h3-table-v1`.

SQLite is a credible alternative for catalogues and exact-key tables: it saves
custom indexing code and has mature integrity tools. It would still leave the
H3 index to solve, add another access model across clients, and need measured
query/decode overhead. Recommend a small number of fixed array layouts first;
switch the nonspatial tables to SQLite only if the prototype shows the custom
export/reader effort is out of proportion. Do not promise 13 µs through SQL.

Specify bytes in a format document and tiny binary fixtures before optimizing:

| Component | Proposed representation and contract |
| --- | --- |
| Header/directory | Magic bytes, format major/minor, required-feature flags, section types, uint64 byte offsets/lengths and row counts. Little-endian integers; explicit padding and 8-byte section alignment. No native structs, pickles or executable content. |
| Coordinate/H3 index | Reuse resolution-3 logical blocks and finest-to-coarsest ancestor keys from the existing format. Local uint16 keys, sparse sorted lists or ranked bitmaps. Present-but-unassigned land has an explicit row; ocean is absence. |
| Labels | Block-local dictionaries of 16-byte tuples: three uint32 local place references plus uint32 encoded method/land flags. Reference zero means null; no row is separate. Dictionary selectors are uint8/uint16. Use flat tuples when dictionary encoding would be larger. |
| Place records | A compact fixed record containing source-qualified canonical ID, names, role/kind, country, parent, sovereign, normalized-city and provenance references. Pack-local uint32 IDs are implementation details; the public ID remains a string. Nullable fields have explicit validity bits. |
| Text and lists | UTF-8 bytes with uint64 offsets and a terminal offset; length-delimited candidate/reference lists. Decode lazily into a bounded cache. Retain preferred, English and local names where supplied; do not infer translations. |
| Exact-key families | Sorted normalized key bytes plus offsets and postings. A *posting* is the list of source observations/candidates for one key. Include source variant, link method/status and original-versus-spatial evidence. |
| IP | Separate IPv4 and IPv6 tables; sorted inclusive start/end endpoints and payload references. IPv4 uses uint32 keys; IPv6 uses 16-byte big-endian comparison keys. Validate non-overlap or compile disjoint segments with candidate lists; a naive predecessor search is wrong on arbitrary overlapping ranges. |
| Phone | Sorted digit prefixes partitioned by length and language; test longest applicable prefix first. Retain candidate territories and the pinned numbering rules. Full phone validation is a separate adapter concern. |
| Timezone | Its own H3 membership index, permitting multiple zones and ancestors at resolutions 0–8, plus IANA metadata. It covers oceans independently of the reverse pack. Do not force its coarse cells into the reverse index’s r3-only layout. |

Offsets and spans are checked before mapping/reading; unknown required features,
invalid enums, overflow, invalid UTF-8 or dangling references reject the pack.
Readers should not require mapping a single multi-gigabyte allocation. Partition
large payloads at section/block boundaries, targeting **64–256 MB transport
shards**, and record every shard independently. The exact shard cut is an export
parameter, not a new geographic boundary.

**Avoid a mandatory full-place catalogue.** Each functional pack contains the
minimal catalogue closure it uses: referenced places plus their needed parents,
sovereigns and normalization targets. Thus airport users download an airport
pack, not all world cells and 6.9 million places. Packs may duplicate small place
records but keep the same public identities. A future `places-full` pack can
support arbitrary ID lookup without making it every user’s dependency.

Every pack includes source/release/licence tables and enough evidence to explain
the returned method and link. Full raw JSON provenance remains in the published
golden Parquet and can be mirrored for offline audits. `explain()` returns local
evidence and a golden manifest/table/source-row reference; it never fetches more
data. This distinction must be visible when detailed evidence is not installed.

### 3.2 Exporter contract

Add a build-only serving stage after final normalized cells, joins and quality
verification. The proposed interface is `python -m build_data.serve export`;
this is future work, not an existing command. It should:

1. Accept an explicit completed golden manifest and verify its hashes and schema.
   Use only listed tables. Reject pending blocks/joins and mixed generations.
2. Stream one H3 block or bounded lookup partition at a time. Assign deterministic
   local IDs from sorted public IDs, preserve v2 methods and normalized city
   identities, and form each pack’s reference closure. Reuse build-only
   DuckDB/PyArrow; neither enters the runtime wheel.
3. Encode spatial lookup payloads from their final joined IDs, preserving source
   answers and disagreement flags. Recover cell assignment methods by joining
   the source H3 key to cells: current spatial lookup schemas do not copy all
   those method columns. Do not relabel source points against different policy.
4. Write temporary files with relative paths, canonical manifest serialization,
   fixed compression settings and no timestamp-dependent payloads. Record input
   manifest, exporter revision, policy, H3 and build-tool versions.
5. Verify all references, sorted keys, interval rules, bitmap ranks, candidate
   accounting, method/null semantics and source-to-serving equivalence. Exhaust
   small fixtures; stream all stored world records to check the transformation.
6. Publish only after validation, by atomic rename to an immutable versioned
   directory. A separate publisher uploads to Hugging Face and verifies a clean
   download before advancing the release index.

Budget export memory at **≤1 GB** and use bounded external sorts for the large
catalogue. Measure export wall time, temporary disk, archive size, installed size
and peak RSS in the first prototype. No spatial rebuild is needed just to change
the serving layout. Coordinate answers still come from the **r8 centre** and
logical ancestors of that cell, never from recomputing a coarse cell directly
from the original latitude/longitude.

### 3.3 Pack sizes: measured inputs, estimated outputs

The following are **capacity-planning ranges**, not measurements or promises.
Installed estimates include each functional pack’s minimal catalogue and notices;
the two reverse components are shown separately to explain the total. Download
estimates assume gzip/deflate transport and repeated strings/labels; benchmark
them before quoting any user-facing download size. MB means 1,000,000 bytes.

| Pack / component | Estimated installed MB | Estimated download MB | Scope |
| --- | ---: | ---: | --- |
| Frozen preview | **53.06 measured** | **21.35 measured** | Existing table; archive is the measured ZIP. |
| Detailed reverse: cell index only | 250–800 | 80–350 | V1 row count is the planning baseline; v2 may compact differently. |
| Detailed reverse: referenced catalogue | 350–850 | 100–350 | Millions of settlements, compact names/IDs/hierarchy; excludes raw JSON evidence. |
| **`reverse-world`, combined** | **600–1,650** | **180–700** | Cells plus that catalogue; one logical installation. |
| `postal` | 200–550 | 60–200 | All retained editions/candidates; country selection is a later optimization. |
| `ip-dbip` | 280–650 | 90–250 | IPv4/IPv6 endpoints and deduplicated source/spatial payloads. |
| `airports` | 10–30 | 3–12 | Multiple code indexes and minimal place closure. |
| `trade` | 15–40 | 4–15 | UN/LOCODE, including unlocated observations. |
| `timezones` | 40–100 | 15–45 | Multi-zone membership index and IANA reference tables. |
| `phone` | 15–45 | 5–20 | Prefixes, languages, territory candidates and numbering metadata. |
| `codes` | 1–4 | 0.3–2 | Country and subdivision systems and their candidate links. |
| `plates` | Unmeasured | Unmeasured | Provisional admission budget ≤20 MB installed; not a forecast of the other agent’s output. |
| `places-full`, only if demanded | 600–1,200 | 180–500 | Full compact identity catalogue and normalization map; no duplicate cells. |

The estimates have a byte-level basis, rather than a ratio to Parquet. At the
observed 62.36 million cell rows, a simple uint16 key + 16-byte label costs
**1,122.4 MB**, before about 2 MB of block directory. Choosing the smaller of
flat and dictionary layouts bounds that cell representation at roughly this
baseline; the 250–800 MB range assumes dictionary reuse, still to be measured.
The old 64-bit label cannot carry all new identity and method information.
For all 6.875 million places, a 48-byte fixed portion alone costs **330.0 MB**;
strings and lists are additional. Reverse needs at least the identities actually
used by cells—v1 used 4.31 million distinct city IDs—not merely the ~100,000
absorbing city candidates discussed in the normalization prototype.

IP endpoints plus one uint32 payload pointer cost about **43.4 MB for IPv4** and
**150.0 MB for IPv6** at the observed family counts; names, coordinates, evidence
and indexes explain the larger pack estimate. Postal storage likewise includes
five million observations and candidate links, not just unique postal strings.
If the prototype exceeds these ranges, revise the installation proposition before
release; do not sacrifice ambiguity or method fields to hit an invented number.

Regional reverse packs are a later adoption experiment, not the first exporter’s
prerequisite. Retain the world’s assignments and all referenced hierarchy records;
declare coverage and return `outside_coverage` instead of ocean. An H3 block
crossing a country border cannot simply be dropped or relabelled as belonging to
one country. Country partitioning is easier for postal lookup than spatial cells.

## 4. Distribution, compatibility and offline operation

### 4.1 Installation and updates

**Recommendation:** small wheels/npm tarballs contain code, the format contract
and release metadata. Data lives in a public Hugging Face dataset repository.
The runtime dependencies remain H3 and NumPy for Python; use the standard library
for the initial CLI, HTTPS download, hashes and gzip/ZIP extraction. Publisher
tooling may use `huggingface_hub`; it need not become a lookup dependency.

Proposed commands, with versions below illustrative:

```text
pip install thereabouts
thereabouts data list --remote
thereabouts data install reverse-world --version 2026.10.0
thereabouts data info
thereabouts reverse 52.37 4.9 --json
thereabouts data verify --full
thereabouts data update --check
```

`data list` is local unless `--remote` is supplied. `install` shows exact archive
and installed bytes, required disk, source dates, coverage and licence before
transfer; support `--yes` for automation. Missing data raises an actionable error
with the installation command. Imports, opening, lookups and normal CLI/MCP
queries perform **zero network access**. An explicit `data update` resolves a new
version; installing new code never updates data implicitly.

Resolution order is explicit `data_dir`, `THEREABOUTS_DATA`, then the default
per-user store. Use persistent application-data locations, since deleting a cache
must not be assumed harmless for offline users: `$XDG_DATA_HOME/thereabouts`
(default `~/.local/share/thereabouts`) on Linux,
`~/Library/Application Support/Thereabouts` on macOS, and
`%LOCALAPPDATA%\Thereabouts` on Windows. Python and Node implement the same rules.
Temporary downloads may use the OS cache directory; installed packs live under
`packs/<family>/<version>/<manifest-digest>/`. Containers and shared read-only
volumes should use an explicit path.

Download to a temporary sibling directory, resume only against the pinned
revision/validator, verify SHA256 and byte counts, bound extraction size and reject
path traversal/symlinks. Use per-pack installation locks and atomic activation
through a small `current.json`, avoiding a requirement for Windows symlinks.
Retain the previous installation until an explicit prune; active readers keep
their original version open. Windows file locking must be tested: do not overwrite
or delete mapped files during an update. Opening validates headers, sizes and
compatibility without rehashing a gigabyte; install and `verify --full` do the
full hash/structural check. A read-only immutable store is the normal contract.

A checksum obtained beside a file detects corruption, not a compromised publisher.
For the preview, ship the exact trusted manifest digest in the code release and
pin the Hugging Face commit. Before independent data updates, use signed release
indexes/manifests with a verifier key distributed in the client and an explicit
key-rotation procedure; a small optional verification dependency is preferable
to writing cryptography. Until that exists, require a trusted digest supplied by
the operator for data newer than the client’s embedded release list. This is a
deliberate limitation of the two-dependency initial installer.

Air-gapped users need both data **and code dependencies**. Provide documented
connected-machine steps to download exact wheels for the target platform and a
pack bundle containing manifests, hashes and notices, then transfer them. Support
`pip install --no-index --find-links ...` and
`thereabouts data install --from /media/pack-bundle --offline`; Node installations
also need a prepared dependency cache or transferred application installation.
Accept an unpacked verified data directory directly. An offline smoke test must
block DNS/network and cover install-from-file, opening and all installed queries.

### 4.2 Four independent versions

| Version | Meaning and drift behavior |
| --- | --- |
| Code version | Semantic version of Python/npm API. Preview APIs may change with release notes; stabilize the result envelope before adding families. |
| Serving format | Major/minor and required features. Reject unsupported majors or required features before decoding. Additive optional metadata may be ignored. |
| Data release | Dated immutable release such as `2026.10.0`, plus source snapshot dates. A source or geographic-policy change produces a new release even if bytes have the same layout. |
| Catalogue identity epoch | Version of canonical identity/normalization relationships. Pack-local integers never join across packs; public IDs join only with compatible epochs and documented migrations. |

Each manifest records its own digest, input golden digest, H3 reference version,
policy digest, catalogue epoch, format features, pack dependencies, minimum reader
versions, source versions, coverage, build revision and every payload’s hash/size.
The release index pins an immutable Hugging Face commit, not `main`. Publish a
tested compatibility matrix for Python and npm; one client lagging behind must
not force silently degraded reads.

**Code newer than data:** read old supported formats, preserve their semantics,
and show age in `info()`. **Data newer than code:** reject incompatible formats
with a required-version message; compatible newer data can be explicitly
installed. **Two packs with different catalogue epochs:** individual lookups may
remain useful, but reject a combined identity join until compatible packs or an
explicit crosswalk are selected. A future source ID disappearing is not proof
that the place ceased to exist; retain redirects/tombstones when independently
established, and otherwise report unresolved migration.

For the first detailed releases, publish lookup families against the same golden
snapshot/epoch. A monthly IP refresh may reuse that catalogue, but its spatial
join must record which cell snapshot supplied the canonical answer. It must not
silently join with whichever reverse pack happens to be installed.

### 4.3 Hosting and registry constraints, checked live

| Service | Verified fact on 2026-10-02 | Consequence |
| --- | --- | --- |
| PyPI | Defaults are **100 MB per uploaded file** and **10 GB per project**, with an increase-request process. [Official limits](https://docs.pypi.org/project-management/storage-limits/) | Keep data out of every platform wheel; dozens of duplicated data-bearing wheels waste the project allowance. |
| Public npm registry | The [publish documentation](https://docs.npmjs.com/cli/v11/commands/npm-publish/) does not state a universal numeric tarball ceiling. An [npm CLI issue](https://github.com/npm/cli/issues/4794) records a 229.9 MB tarball rejected in 2022; that is historical evidence, not today’s limit. | **Current numeric limit unverified.** Use `npm pack --dry-run` and a project budget below 5 MB for Thereabouts’ own JS tarball; do not make distribution depend on discovering the maximum. |
| Hugging Face storage | Current policy gives free public storage on a **best-effort** basis, 100 GB free private storage, no fixed per-repository dataset/model size limit within account capacity, and recommends fewer than 100,000 files, fewer than 10,000 per folder and files below 200 GB. [Storage policy](https://huggingface.co/docs/hub/storage-limits) | Our expected packs fit these structural recommendations. Consolidate the 41,162 cell partitions into shards; confirm account capacity and retention rather than treating public hosting as an unlimited SLA. |
| Hugging Face dataset hosting | Large dataset guidance requires a dataset card, community reuse and suitable formats. [Policy](https://huggingface.co/docs/hub/storage-limits) | Publish useful golden Parquet for inspection alongside serving archives; document the custom format and intended offline/analytics use. Acceptance of this exact repository has not been confirmed. |
| Hugging Face terms | Uploaders need rights to the content; notices of customary licences continue to govern reuse. [Terms](https://huggingface.co/terms-of-service) | Hosting does not clear source rights or replace the licence review in §7. |
| Hugging Face downloads | Resolver requests have separate quotas in five-minute windows, with 429 responses and rate-limit headers; anonymous/free quotas can change. [Rate-limit documentation](https://huggingface.co/docs/hub/rate-limits) | Fetch a few archives, cache them locally, retry with backoff/reset headers, and support offline/mirror import. No query-time dependency on hosting. |

The Hub’s separate [upload guide](https://huggingface.co/docs/hub/en/datasets-upload-guide-llm)
contains different quota summaries; use the dedicated storage policy and the
actual account settings before upload. Keep an owner-controlled copy of released
archives and manifests. Start with current and previous public releases and
preserve referenced reproducibility snapshots where source terms permit; review
storage after each release. A public revision URL is not a retention guarantee.

## 5. Python API and input semantics

### 5.1 One result envelope, explicit resolvers

Proposed detailed-release API; the preview implements only reverse/H3/batch:

```python
from thereabouts import Geocoder

with Geocoder(data_dir="/srv/thereabouts", packs=["reverse-world"]) as geo:
    answer = geo.reverse(52.37, 4.9)
    answer = geo.from_h3("8860145b49fffff")  # Bengaluru reference cell
    for answer in geo.reverse_many(coordinates, errors="collect"):
        consume(answer)

# Later, with corresponding packs installed:
# geo.postal("10001", country="US")
# geo.airport("JFK", scheme="iata")
# geo.ip("8.8.8.8")
# geo.phone("+442079460000")
# geo.plate("KA", country="IN", scheme="registration-prefix")
```

Use named methods or `resolve(kind=..., value=..., context=...)`; never guess that
`IN`, `CA`, `TR` or a digit string identifies one input type. Return a frozen
`Resolution` with a JSON-compatible serialization:

| Field | Meaning |
| --- | --- |
| `status` | `matched`, `ambiguous`, `not_found`, `unassigned`, `ineligible`, `outside_coverage`, or `invalid_input` for collected batch errors. |
| `selected` | One `Candidate`, or null when no justified single answer exists. A candidate may have country/state but no city. |
| `candidates` | Stable ordered list of distinct candidate identities, with their source observations and relationship evidence; do not discard duplicates’ provenance. |
| `query` | Typed normalized input and context. Scalar results may echo it; adapters avoid logging sensitive input values. |
| `reference` | Query/source H3 key, reference resolution, stored ancestor resolution and quantization policy where applicable; null for nonspatial evidence. |
| `data` | Pack versions, catalogue epoch, manifest digests and policy identity needed to reproduce the answer. |
| `warnings` | Structured flags such as `distant_nearest`, `source_country_disagrees`, `stale_source` or `inferred_extent`. |

A candidate contains a `place`/source entity where available and nullable
`city`, `state`, `country`, `sovereign` records, each with ID, display name, role
and known code/system. Preserve `settlement_kind`: the city slot can legitimately
contain a rural village. Include `relationship` (for example spatial context,
numbering allocation or registration jurisdiction), `methods` per field, source
IDs/releases, qualitative evidence, and nullable accuracy/distance metadata.
An airport remains an airport observation associated with a place; it is not
turned into the airport municipality’s identity. The preview's city/state labels
have no canonical place IDs in the old table: return null IDs and identify that
capability in `info()`. Do not manufacture identities from names or imply that
preview results can join to the golden catalogue.

Use `confidence = {basis, calibrated_probability: null}` initially. Basis values
describe evidence such as `source_boundary`, `policy_boundary`, `inferred_urban`,
`nearest_settlement`, `source_association`, `exact_code_link` and `unknown`.
Do not invent percentages or globally label every exact code match “high
geographic accuracy.” Calibration would require independent per-method data.

Preserve the dataset’s `city_polygon`, `policy_polygon`, `urban_allocation`,
`rural_polygon`, `rural_nearest`, `rural_nearest_distant` and null methods;
reserve support for `town_radius` without enabling that policy. A source polygon
is evidence at the represented centre, not a guarantee about the original point.
V2 records **the >25 km category, not exact per-cell distance**. Report that band
and the 50 km cutoff; leave exact distance null unless an appropriate anchor and
distance calculation are explicitly available. The preview cannot recover these
new categories from its old table and must expose its coarser method honestly.

### 5.2 What each input can claim

| Resolver | Required context / algorithm | Ambiguity and limits |
| --- | --- | --- |
| Coordinates | Finite numeric latitude/longitude in bounds; r8 H3 conversion then logical ancestors. Reject booleans/strings; normalize +180 consistently. | Distinguish ocean from eligible unassigned land. Retain country, state and sovereign separately under the published boundary perspective. |
| H3 | Initially accept valid resolution-8 cell strings only. | Reject other resolutions with an explanation. A later explicit `mode="centre"` for coarse cells is a point interpretation, never a claim of uniform labels across the coarse cell; finer cells can explicitly map to their r8 parent. |
| Postal | Country required; preserve leading zeros. Version country-specific space/case normalization and source-edition precedence. Exact key → all observations → candidate places. | Several cities can share a code. Retain source labels and cell-derived answers separately, including `IN/560001`’s known source-coordinate discrepancy from [DATA_PIPELINE](DATA_PIPELINE.md). Never choose the first row as truth. |
| IP | Parse literal IPv4/IPv6, normalize IPv4-mapped addresses under a documented rule, then inclusive range lookup; no DNS. | Private/reserved/unknown inputs do not get a guessed city. DB-IP source answer and spatial context remain distinguishable. Missing accuracy radius stays null. IP location is an estimate, not device location. |
| Airport | Explicit `iata`, `icao`, `ident`, `gps` or country-scoped local scheme. Exact code postings; optional type/status filter. | Codes can be absent/reused and the source contains heliports/closed sites. Default returns candidates with status; “serves city” and “lies near city” remain different fields. |
| Trade location | Normalize country + UN/LOCODE location component; preserve facility-function/status evidence. | A trade location is not necessarily a seaport. Retain the 23,339 v1 source rows without usable coordinates as found source entities with unresolved spatial context. |
| Phone | Prefer E.164; national input requires default region. Validate via an optional maintained numbering library, then longest applicable prefix/language and candidate territory rules. | Current golden links are largely to countries; descriptions are not verified city identities. No current-location or residence claim. Missing/overlapping numbering evidence remains ambiguous. |
| Plate | Country and scheme/version preferred; exact jurisdiction code lookup first. | Unknown country yields candidates or `ContextRequiredError`, never a guessed jurisdiction. Registration prefixes, international distinguishing signs and full registration strings need separate schemas. No OCR, owner lookup or present vehicle location. Historical validity matters. |
| Country/subdivision code | Explicit code system, e.g. ISO alpha-2/alpha-3/numeric, ISO-3166-2 or GeoNames admin1. | Areas need not have a city. Preserve ambiguous/unmatched and historical codes; source-assigned XK is not silently reclassified as official ISO. |
| Timezone at coordinates | Independent H3 membership pack, all matching zones. | Ocean answers and overlapping zones are valid; no arbitrary first-zone winner. |
| Timezone identifier | IANA reference metadata and country associations. | A timezone does not determine a city. Return region metadata/candidates, not its reference point reverse-geocoded into an invented unique city. Time rules remain the job of `zoneinfo`/tzdata. |

Phone adapters must record the validation-library and numbering-metadata versions
alongside the prefix-pack version. Define their compatible pairing so a new
validator cannot silently narrow candidates using different allocation evidence.
The upstream [libphonenumber FAQ](https://github.com/google/libphonenumber/blob/master/FAQ.md)
explains both parsing ambiguity and why numbering validity does not establish
residence or reachability.

For ambiguous results, `selected` is null; a caller can explicitly filter by
country or other evidence, or call `require_one()` and receive an
`AmbiguousResultError`. Pagination/limits must report truncation and preserve a
continuation mechanism; a truncated candidate list must never become a false
unique match. Sorting is deterministic, not a hidden confidence ranking.

### 5.3 Batches, errors and lifecycle

Keep bounded iterators with a default 4,096-row chunk and stable input order.
`reverse_many` returns the same logical result as scalar calls. Add typed column
arrays for analytics to avoid one Python object per field, with ID/name decoding
on request. Heterogeneous `resolve_many` dispatches by explicit kind and restores
order. Missing packs, corruption and unsupported formats fail the operation;
`errors="collect"` handles individual invalid rows, while `errors="raise"` is
the Python default. Chunked iteration may yield earlier results before an error;
document that it is not transactional.

Use typed exceptions: `InvalidInputError`, `ContextRequiredError`,
`DataNotInstalledError`, `UnsupportedPackError`, `CorruptPackError`,
`IncompatibleDataError`, `AmbiguousResultError`, `ClosedGeocoderError` and
installer-only network/disk errors. Ordinary no-match is a result, not an
exception. Missing fields are null, not empty strings or fabricated zeroes.

Open once per process and reuse the reader. Close is idempotent; subsequent
calls and buffered iterators fail. Results own their decoded strings and remain
usable after close. Keep immutable handles safe for concurrent reads, synchronize
close against active chunks, and document that a new process opens its own
handle. Thread safety and GIL release do not by themselves promise parallel speed.

## 6. Cython, clients and plugins

### 6.1 What to compile and ship

Profile the new reader before claiming speedups. Good Cython targets are H3 bit
address extraction, sparse binary search, bitmap rank/popcount, label gathers,
IPv4/IPv6 comparisons and batches of those operations. H3 already has a compiled
implementation; compiling a Python wrapper around a single H3 call is not the
main opportunity. Keep downloads, schema validation, policy, text normalization
and result construction in Python until a profile says otherwise.

Maintain a straightforward Python/NumPy implementation as the reference and
fallback. “Pure-Python fallback” means no **Thereabouts** extension; H3 and NumPy
remain dependencies. Ship `_reader_py` and an optional `_reader_cy`, select the
accelerator when importable, and expose `backend="python"` for diagnosis and
conformance. Do not silently fall back after corruption or a runtime exception.
Separate small kernels are preferable to requiring the Cython runtime in the
fallback: [Cython pure-Python syntax](https://cython.readthedocs.io/en/latest/src/tutorial/pure.html)
is available, but its decorators/type helpers need deliberate interpreted-mode
packaging.

**Build recommendation:** one packaging backend with explicit extension support
(setuptools is a reasonable replacement for the current simple Hatchling setup),
PEP 517 isolated builds, pinned Cython generation, generated C in the source
distribution, and `cibuildwheel` on GitHub Actions for binary wheels. Publish a
separately built `py3-none-any` wheel of the same version containing the fallback,
and test that pip selects it on an unsupported platform. Native builds must fail
CI if the extension is accidentally omitted. An opt-out source-build flag is
useful for distributors; end users should not need a compiler for supported
wheels. Current registry observations are **Cython 3.3.0** and **cibuildwheel
4.2.1**, not permanent pins. [Cython metadata](https://pypi.org/pypi/Cython/json),
[cibuildwheel metadata](https://pypi.org/pypi/cibuildwheel/json),
[build platforms/options](https://cibuildwheel.pypa.io/en/stable/options/),
[Cython compilation and distribution](https://cython.readthedocs.io/en/stable/src/userguide/source_files_and_compilation.html)

Initial wheel matrix: CPython **3.11–3.14**, normal GIL builds, for Linux
manylinux x86_64/aarch64, macOS x86_64/arm64 and Windows x86_64: **20 wheels plus
one fallback wheel and an sdist**. Test native ARM runners where available.
Linux wheel repair uses auditwheel, macOS delocate and Windows repair tooling as
needed through the build workflow. Do not claim abi3 compatibility without
proving the chosen Cython/NumPy interface supports it. Test imports and a real
fixture lookup inside each wheel’s clean environment, outside the source tree.
Qualify H3/NumPy wheel availability too. Alpine/musl, Windows ARM, PyPy,
free-threaded CPython and the next Python version are later support decisions,
with fallback only where dependencies themselves install and pass tests.

**Performance contract:** promise offline, bounded-memory operation and published
measurements, not universal microseconds. Initial engineering targets on the
documented M2-class reference machine are warm scalar median **≤50 µs**, p99
**≤500 µs**, and end-to-end batch **≥100,000 coordinates/s** for the detailed
Python reader. These are unverified targets including H3 and normal results;
ID-only throughput is reported separately. Measure cold open, first touch,
uniform-world versus clustered access, page faults, RSS, cache size and full
verification cost. Node gets its own budget with its first adopting user; do not
copy Python’s benchmark into npm documentation. If Cython does not improve a
measured bottleneck, simplify the kernel rather than increase maintenance for a
headline claim.

### 6.2 CLI and integrations

The CLI belongs in the Python package using a small standard-library command
parser initially. It is a shell/batch interface, not a separate geocoder.
Support `reverse`, `h3`, typed `resolve`, `batch`, `info`, `explain` and the data
commands. Read CSV or JSON Lines from stdin, stream results, allow explicit input
columns and write progress to stderr. JSON Lines preserves candidate arrays;
CSV requires an explicit flatten/explode policy. Stable exit codes: 0 for a
completed operation (including ordinary no-matches), 2 for usage/invalid input,
3 for data/compatibility errors, 4 for installation/I/O errors, 5 for collected
row errors after output completes. Handle broken pipes without a traceback.

The two meanings of “plugins” get separate product names:

| Meaning | Interface and priority |
| --- | --- |
| **Data packs** | Declarative files conforming to supported schemas. `data install postal` adds postal records; it does not execute downloaded code. New resolver kinds require a client release, while new data versions do not if compatible. |
| **Integrations** | Optional Python extras or small adapter packages calling the same API. No independent datasets, normalization policies or hidden updates. Add discovery/registration only when external implementers actually need it. |

Prioritize integrations according to the first repeat workflow:

| Integration | Smallest useful interface | Effort and boundary |
| --- | --- | --- |
| pandas | Batch columns/arrays into a DataFrame preserving index, nulls and status; avoid row-wise `apply`. | 2–3 days; optional dependency. No special accessor required first. |
| Polars | `map_batches` or an explicit batch-to-Struct adapter with declared output schema and null behavior. | 2–4 days; Python adapter first, not a Rust expression plugin. [Supported UDF model](https://docs.pola.rs/user-guide/expressions/user-defined-python-functions/) |
| DuckDB | Register an Arrow batch UDF from Python, e.g. `thereabouts_reverse(lat, lon)` returning selected fields/status. | 3–5 days; PyArrow/DuckDB extra. This is not an extension loadable into standalone DuckDB CLI. [Function API](https://duckdb.org/docs/lts/clients/python/function) |
| MCP server | `thereabouts mcp` over stdio, wrapping `reverse`, bounded `reverse_many`, typed `resolve`, `info` and `explain`. | 3–5 days; optional SDK dependency and a tested host example. |
| Agent-specific plugin | Configuration, descriptions, examples and attribution pointing at the same MCP server. | 1–2 days per verified host; no parallel agent-only geocoder or host marketplace maintenance before demand. |

MCP is the Model Context Protocol, a tool interface used by agent hosts. Use the
official Python SDK, whose current stable line is **v2** (observed PyPI version
**2.2.0**); the official TypeScript SDK also now has a stable v2 line. Pin and test
the selected release rather than copying old FastMCP examples unexamined.
[Python SDK](https://py.sdk.modelcontextprotocol.io/),
[Python package metadata](https://pypi.org/pypi/mcp/json),
[TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)

Serve read-only tools with typed schemas and structured results, a bounded request
size (initially 1,000 points), explicit candidate truncation and stderr logging.
Do not expose installation or arbitrary filesystem paths as model-callable tools.
Launch the already installed executable so an agent host does not download
packages each time it starts. Stdio keeps the first deployment local; a hosted
HTTP service adds authentication, deployment and abuse controls and is a separate
product decision. This adapter’s dependency tree stays outside the two-dependency
lookup installation.

Do not implement a native DuckDB extension, Rust Polars plugin, mobile SDK,
browser pack manager or hosted API in the first sequence. They can be valuable,
but each creates another release/platform contract.

## 7. Licensing is a release dependency

**Code decision deadline: before a functional public preview.** Recommend MIT for
low-friction use; Apache-2.0 is a sound alternative when the explicit contributor
patent grant is preferred. Copyleft code is also possible, with additional
downstream conditions and a different adoption tradeoff. Confirm rights to
contributors’ code before assigning a licence. Add a real licence file and
package metadata in implementation work; this document does not choose it on the
owner’s behalf. [MIT text](https://opensource.org/license/mit),
[Apache-2.0 text](https://www.apache.org/licenses/LICENSE-2.0)

**Data decision deadline: before any public Hugging Face upload, including an
experimental golden pack.** The small preview needs its Natural Earth and
GeoNames notices reviewed too. For the detailed database, recommend the existing
pipeline’s derivative-database treatment under ODbL, retaining the separate
rights and attribution of its contents. Overture divisions and OSM land are
ODbL inputs. ODbL permits commercial use, excludes the operating software from
its scope, and imposes share-alike/access conditions for public use of derivative
databases. Whether a downstream enrichment is a derivative database, collective
database or produced work depends on the actual use. Do not promise that all
downstream datasets are unrestricted or that every application must open its
code. [Overture attribution](https://docs.overturemaps.org/attribution/),
[ODbL §§2.3, 3.1, 4.3–4.6](https://opendatacommons.org/licenses/odbl/1-0/)

The acquired sources are more varied than “ODbL + CC BY + CC0.” Before release,
produce a per-pack bill of materials identifying **which rows/fields were
actually admitted**, source version, licence text, attribution, modifications,
redistribution conditions and unresolved questions. The reconciliation policy
currently allows selected geoBoundaries licence labels; acquisition retained
other labels too, so auditing the admitted output matters. Explicitly review:

- GeoNames and DB-IP CC BY attribution, links, licence and change notices;
  public-domain/CC0 material; GHSL attribution in v2.
- Overture’s upstream attribution and timezone-boundary-builder’s ODbL data.
- GeoNames GB postal’s Royal Mail notice, iso-codes/pycountry’s LGPL-labelled
  source, DataHub/UNECE edition and standards-rights caveats.
- Apache-2.0 telephone metadata and the forthcoming plate sources’ actual terms.

[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) and
[DB-IP’s own download/licensing page](https://db-ip.com/db/download/ip-to-city-lite)
support reuse subject to their requirements, but this research has not established
legal compatibility of every combined field or each customer’s downstream use.
Resolve uncertainty by reviewing the specific source, obtaining permission or
excluding the affected pack—not by declaring the whole database CC0. Ship
`LICENSES/`, `ATTRIBUTION.md`, a machine-readable source table, dataset card and
an attribution example for CLI/export/MCP consumers. Required notices remain in
every minimal pack even when raw evidence is optional.

Separating files does not undo an ODbL-derived spatial join. A truly permissive
source-only airport/code pack is an option, but must omit derived fields that
create those obligations and have its own documented contract. A permissive
replacement world pack would need different boundaries and land data, quality
evaluation and an ongoing update pipeline; do not promise it for free. Obtain
focused legal review if commercial redistribution or a customer’s use makes
these classifications material.

## 8. Quality, conformance and sustainable releases

### 8.1 Three different kinds of evidence

**Construction correctness:** prove that serving files reproduce their golden
input and that all readers agree. Check all reference IDs, method/null bits,
candidate multiplicities and interval endpoints. Exhaust the small spatial
fixture, including pentagons, date seam, poles, coarse ancestors and coverage
edges. Preserve the distinction between the H3 construction contract and actual
geographic quality.

**Source diagnostics:** keep the 34,171 GeoNames observations, frozen supported
roll-ups, accepted-footprint censuses, neighbour boundaries and transition counts
from the city work. They locate regressions; they do not independently establish
accuracy because the builder uses those sources and policies. Do not advertise
the old “identity or containing city” number as world city accuracy.

**Independent user-facing evaluation:** use the existing
[120-point hand-checked set](../eval/city_points/README.md): 40 development and
80 held-out points, one explicitly ambiguous holdout case. The set covers 20
countries, is deliberately selected and correlated within cities/towns, and uses
OSM cross-checks related to an input source. Report counts by group and evidence
strength, the ambiguous case separately, point-set/pack hashes and every error.
It tests city answers; it does not certify state accuracy, worldwide population
accuracy or boundary clearance. Preserve the proposed **≥76/80** holdout target
and no unexamined independent-neighbour loss as release gates, not “95% global
accuracy.” If the frozen v2 run has already scored holdout, use that result; do
not rerun tuning on it. Once inspected it becomes a regression set, and new
claims need a newly collected blinded sample.

For added inputs, separately measure key coverage, unique/ambiguous/unmatched
rates, source-country disagreement, link precision and correct semantic
granularity on independently adjudicated samples. Compare source-only answers
with canonical joins; the shared catalogue must demonstrate improvement in a
real workflow. Start with at least 50 independently reviewed examples per new
family, stratified for ambiguities and missing context, and publish the small
sample limitation. A count of successful joins is not a count of correct cities.

### 8.2 Cross-client conformance and CI

Commit a small versioned conformance bundle: binary pack fixtures, normalized
inputs, expected JSON results/errors and malformed-pack cases. The Python
reference, Cython, Node, CLI serialization and MCP serialization must agree on
IDs, statuses, methods, candidate ordering, Unicode, leading zeros, signed/unsigned
endpoints and missing values. Compare coordinates/distance fields with declared
tolerances only where floating point is involved. Test both oldest-supported
and newest-supported pack features; unknown required features must fail equally.

Per-PR CI should run fast fixture tests, lint/type checks, forced fallback and
accelerated modes, a deterministic fixture export, malformed-header bounds tests
and network-blocked runtime tests. Add tests for interrupted installs, checksum
failure, disk exhaustion, simultaneous installers, close-during-batch and update
while mapped. Native parsers deserve fuzzing and sanitizers on scheduled/release
runs. Keep world rebuilds out of every PR.

Release CI builds and installs the **actual** wheel/sdist/npm artifacts in clean
environments, verifies that build-only dependencies and world data are absent,
and exercises a real pack installation plus offline query. Run full serving
verification and world regression reports once per data candidate. Benchmark
on a stable reference machine with a fixed pack/workload; noisy shared CI timing
is advisory unless a broad regression is reproducible. Publish unsuccessful or
skipped checks as such. Use review branches and PR CI; merge and registry/data
publication remain explicit release actions. Trusted publishing is available for
PyPI; configure the project/workflow identity before the release job.
[PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/)

### 8.3 Cadence and comparable distribution models

Recommend code patches as needed and a monthly release window during preview,
then fewer intentional API releases. Start geographic data **quarterly**, with
urgent corrections only after the same gates; a source publishing more often
does not require rebuilding everything that often. If IP is adopted, maintain a
separate monthly DB-IP pack, which matches its published update schedule.
Telephone and timezone metadata can have their own dated snapshots, but no
freshness SLA should precede an automated refresh and review process. Report
source age in metadata; offline reads keep working with old licensed packs.

Existing projects illustrate workable parts of this model, not proven performance
for Thereabouts:

| Project, checked live | Distribution/implementation observation | Lesson for Thereabouts |
| --- | --- | --- |
| [timezonefinder](https://github.com/jannikmi/timezonefinder) | Engine and `timezonefinder-data` are separate packages, with a declared compatible data range; data installs as a dependency. The current [data wheel](https://pypi.org/pypi/timezonefinder-data/json) is **32,653,639 bytes**, version `3.2026.4`; the [engine metadata](https://pypi.org/pypi/timezonefinder/json) is `9.0.0`. | Independent code/data versions work. Our much larger data merits explicit external installation instead of copying its automatic data dependency. |
| [MaxMind DB Python reader](https://github.com/maxmind/MaxMind-DB-Reader-python) | Reads a separately supplied MMDB with C-extension/mmap and pure-Python mmap/file modes. The reader package does not supply a GeoIP database. | Strong precedent for a small reader, optional compiled path and independently licensed data. Do not substitute MaxMind data terms for the actual DB-IP source. |
| [pgeocode](https://github.com/symerio/pgeocode) | Country-oriented postal lookup downloads and caches data under a configurable directory, default `~/.cache/pgeocode`. | Country scoping is useful; Thereabouts deliberately makes the first data transfer explicit. |
| [reverse-geocoder](https://github.com/thampiman/reverse-geocoder) | Builds nearest-neighbour lookup from a bundled GeoNames city CSV; [PyPI](https://pypi.org/pypi/reverse-geocoder/json) lists a **2,246,559-byte** source archive for `1.5.1`. | Small specialist data can be bundled; this is not evidence that 2.54 GB of golden tables should be packaged the same way. |

Budget **1–2 maintainer-days/month** after the narrow release for issues,
dependency/wheel upkeep and triage, plus **2–4 days per quarterly data release**
for review and publication once refreshes are automated. Several input families
could raise this to **3–5 days/month plus refresh work**. These are planning
allowances, not observations of maintainer labour. Track actual support hours,
successful repeat installations and error reports; stop adding families if
support consumes the available implementation time. Keep a small policy file and
public error catalogue rather than building a correction-management service.

## 9. Phases, effort and exit criteria

Effort means focused engineer-days for one maintainer, including implementation,
fixtures, documentation and release checks. It excludes the parallel rename/v2/
plate work, elapsed build/download time, legal review turnaround and waiting for
testers. No new geographic acquisition or browser support is assumed. Reserve
**25–40% calendar slack** for integration and support. Phases 3–5 can be reordered
to serve a real user; all follow the stable detailed format/result contract.

| Phase | Work and installable outcome | Effort | Exit criterion / decision gate |
| --- | --- | ---: | --- |
| **1. Narrow preview** | Integrate the rename when ready; licence code; publish existing frozen world pack on HF; explicit installer, basic result envelope, r8 H3 input, Python + CLI, release CI. Usable `thereabouts` preview. | **4–6 days**, with a week of user trials alongside | Clean install and offline batch work on supported systems; exact old behavior retained/documented; notices complete. Three external real workloads, two intended repeat integrations before substantial expansion. If these fail, retain a bounded preview and pause expansion. |
| **2. Detailed Python/Cython** | Two-day format/size prototype; serving exporter, compact catalogues, v2 method-rich API, Python fallback and Cython kernels, wheel matrix, verified detailed reverse pack and compatible installer. | **15–25 days** | Final v2 completion/quality evidence accepted; all source-to-serving checks pass; holdout and neighbour gates addressed; actual sizes/cold and warm benchmarks published; detailed-data licensing cleared; installed artifact works offline. If v2 is late or fails quality, keep the preview usable rather than rebrand pilot results. |
| **3. One additional input** | Build the generic exact-key/postings pack once and ship the family selected by two real users. Default candidate: country-scoped postal lookup; codes may be a small companion. | **5–8 days** | Users demonstrate a useful shared-identity join; ambiguous/duplicate/unlocated fixtures pass; independent sample and licences reviewed; installation works without the reverse-world pack. Otherwise defer further families. |
| **4. npm for Node** | JS/TypeScript reader, `h3-js`, asynchronous bounded I/O, pack install/import, typed results, shared conformance and Node LTS CI; release coordinate/H3 support first. | **8–12 days** | npm install requires neither Python nor a compiler; same fixture results and pack digests as Python; measured cold/warm throughput, bounded memory and event-loop behavior fit the adopting workload. List supported families explicitly. |
| **5. One integration** | Ship the first requested pandas/Polars/DuckDB adapter or the stdio MCP server; use the same core and data store. | **2–5 days each** | One documented end-to-end user job/host test, explicit nulls/candidates, no query network and no second policy implementation. A second integration needs a second use case. |
| **6. Earned expansion** | Additional small exact-key families (airports/trade/codes), then IP, phone and plate packs with their own semantics and refreshes. Release one at a time. | **2–4 days per small family; IP 5–8; phone 5–8; plates 3–6 after source/schema review** | Every family has an adopting workflow, rights review, independent quality examples, update owner/cadence and portable conformance vectors. Node parity typically adds **1–3 days per new family**, more if a new index is needed. |

The first five phases with **one** integration total **34–56 engineer-days**,
roughly 7–12 focused weeks before slack and external waits. The owner can learn
after the first 4–6 days. The whole expanded scope is not a two-week packaging
exercise: every new index, source and integration creates a maintenance track.
If the owner declines the legacy preview, start phase 2 first and carry its
installation/CLI/licence work forward; do not add phases 1 and 2 mechanically
when estimating that alternative.

Phase 2’s first prototype is a stop/revise point: measure cells plus the actual
minimal catalogue before freezing the format, compare flat and dictionary
layouts, and check whether users accept the result. If a world pack is too large,
test one regional pack or a narrower output set with them. Do not pre-emptively
design dozens of country editions.

## 10. Risks and remaining unknowns

| Risk | Response / decision that limits it |
| --- | --- |
| Universal-input scope outruns demand | Keep installable phase gates and ask for real multi-input examples; optional packs do not by themselves validate the bundle. |
| City quality is mistaken for format correctness | Preserve methods and source disagreement; publish independent errors and neighbour losses separately from exact reproduction checks. |
| Larger catalogues erase the old startup/RAM advantage | Lazy compact records, per-pack reference closure, bounded caches and cold-cache measurements before performance claims. |
| JS/Cython implementations diverge | Freeze byte/semantic contracts, share malformed and valid fixtures, require parity per supported family and stage new formats until both clients are ready. |
| Native packaging becomes a second project | Limit Cython kernels and platforms, keep a tested fallback, defer shared C/Node add-ons and browsers. |
| Data rights or source age block distribution | Source-level release gate, dated notices, independently installable families and exclusion of uncleared material. |
| Hosting or a mutable upstream breaks reproducibility | Immutable revision/digest pins, operator-held archive copies, offline import and explicit compatibility checks. |
| Monthly packs overwhelm a solo maintainer | Start quarterly geography and one lookup family; track maintenance time before promising additional refresh schedules. |

**Not verified in this task:** final v2 world counts/quality/holdout or plate
contents; serving-pack sizes/compression, export resources and Python/Cython/Node
performance; the planned wheel matrix, browser feasibility and any client
conformance run; current numeric npm tarball ceiling; the HF account’s available
quota, acceptance of this exact dataset and long-term retention; legal
compatibility of every admitted source or a customer’s derivative use; user
adoption, willingness to pay and actual ongoing support effort. Each is a phase
gate or explicitly labelled estimate above, not a completed result.

All linked external facts in this plan were checked live on **2026-10-02** using
the primary documentation/repositories or registry responses cited beside them.
The DuckDB stable URL redirected, so the linked LTS function documentation was
used. The MCP “what’s new” page failed to load in this research; the official SDK
homepages and live registry supplied the version/transport evidence instead.
No comparable-package benchmark, data pipeline, wheel build, accuracy evaluation
or package publication was performed for this writing task. Only this plan is
the requested repository change.
