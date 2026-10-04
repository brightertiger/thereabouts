# Evaluation: offline reverse geocoding

**Verdict: worth testing only with changes.** Build a small, maintained offline package that returns the containing country/admin1 and an explicitly separate nearest settlement. Use H3 as an optional acceleration index, with polygon checks at boundaries. Do not build the proposed global cell-centre-to-city table as the primary product. Its useful audience is batch analytics, private GPS enrichment and disconnected applications that need place context, not postal addresses or legal jurisdiction determinations.

The findings driving this verdict are:

- **Resolution 3 is much too coarse.** Its average hexagon area is **12,393 km² [L]**. In the settlement-nearby experiment, snapping changed the containing country for **15.88% [M]**, admin1 for **44.67% [M]**, and nearest settlement for **95.46% [M]** of eligible points. [H3 statistics](https://h3geo.org/docs/core-library/restable/)
- **A fine flat grid is expensive and still changes city answers.** Resolution 8 changed the nearest settlement for **5.65% [M]** of settlement-nearby points. Its land-intersecting cells number approximately **195.7 million [E]**, requiring **3.13 GB [E]** for a compact raw cell table before names and indexes.
- **Offline lookup and permissive code already exist.** The measured warm scalar runtimes of `reverse_geocoder` and `reverse_geocode` were both about **12 µs [M]**. `rgeocoder` already offers permissive Rust-backed Python; `python-gazetteer` already performs offline boundary checks. The opportunity is a better combined contract, footprint, installation experience and data maintenance—not an undiscovered lookup algorithm. [rgeocoder](https://github.com/Phil-V/rgeocoder), [python-gazetteer](https://pypi.org/project/python-gazetteer/)
- **“Nearest city” does not establish containment.** Without any H3 snapping, inheriting a settlement's country disagreed with the containing Natural Earth country on **5.10% [M]** of area-uniform eligible land points outside Antarctica. A finer grid cannot remove that semantic error.

Evidence date: **2026-10-01 [L: live source access; M: experiment date]**. **[M] measured** here, including calculations from observations; **[L] looked up** in linked primary sources; **[E] estimated** from stated assumptions. Proposed design parameters and acceptance thresholds are **targets**, not measured performance. Version numbers, identifiers, source scales and dates describe the evidence or design rather than accuracy claims. MB/GB are decimal; MiB/GiB, when used, are binary. All experimental results below concern specified datasets and sampling distributions, not universal real-world correctness.

## What the background PDF gets right—and what it does not establish

I read all **six pages [M]** of `/Users/ujjwal/Downloads/offline-geocoding-gaps.pdf`, including its linked references, before doing the investigation. It is more cautious than a simple “unfilled market” argument:

| PDF proposition | Finding |
| --- | --- |
| Established Python options use LGPL | Confirmed for `reverse_geocoder`'s license text and `reverse-geocode`'s PyPI metadata. Commercial use is not prohibited. The relevant adoption concern is redistribution conditions and organizational policy. [License](https://github.com/thampiman/reverse-geocoder/blob/master/LICENSE), [metadata](https://pypi.org/project/reverse-geocode/) |
| Their latest releases are September 2016 and May 2025 [L] | Confirmed. However, `reverse-geocode` has default-branch activity in August 2026 [L]; release age alone is not proof of abandonment. [PyPI](https://pypi.org/project/reverse_geocoder/), [commit](https://github.com/richardpenman/reverse_geocode/commit/e8815d2af2cbf2d5ff6eed482a572ab2eb650aac) |
| MIT/Apache alternatives already exist | Confirmed: `rgeocoder`, Lakhua, Polars plugin and rrgeo. Consequently permissive licensing alone is insufficient differentiation. |
| Global coverage plus a small runtime, provenance and maintenance might be useful | Plausible product hypothesis. Global source presence is not complete village coverage, polygon accuracy or useful city semantics. No user-demand or willingness-to-pay research was provided or performed. |
| Polars has an approximately 2.5 GB default cache [L] | Its current README says so, and documents a no-cache option. This is an upstream claim, not a measurement here, and is not its wheel size. [README](https://github.com/MarcoGorelli/polars-reverse-geocode) |
| Local MCP would distinguish it from the named online adapters | A local engine would offer a different deployment model. Mapbox's reverse tool still calls its API; osm-mcp uses configured services, which can include a local Nominatim server. Mapbox also has offline geometry tools, so “all its tools require network” would be false. MCP is an interface feature, not evidence of a geocoding gap. [Mapbox](https://github.com/mapbox/mcp-server), [osm-mcp](https://github.com/ni-c/osm-mcp) |

The PDF omits relevant boundary-based and newer embedded competitors below. Its recommendation to benchmark before committing to a product survives scrutiny; a claim that an H3 table is inherently better does not.

## Resolution, land coverage and storage

“H3” names the grid system; the resolution is a separate choice. These are the current official statistics, not the older H3 documentation's edge-length table. Areas and edges are **average hexagon** values, not maximum error bounds; total counts include pentagons. H3's published finest edge averages are themselves extrapolations, even though they are looked-up values here. [Statistics and methodology](https://h3geo.org/docs/core-library/restable/)

For a concrete size model, assume **16 bytes per row [E/design assumption]**: unsigned H3 key, country ID, admin1 ID and settlement ID, using widths **8 + 2 + 2 + 4 bytes [E/design assumption]**. Names are deduplicated elsewhere. This describes the plain table under evaluation, not the recommended hybrid's format.

| H3 resolution | Worldwide cells [L] | Avg area km² [L] | Avg edge km [L] | Cells intersecting mapped land [M/E] | Raw world table MB [E] | Raw land table MB [E] |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 41,162 | 12,393.435 | 68.979 | 14,466 [M] | 0.659 | 0.231 |
| 4 | 288,122 | 1,770.348 | 26.072 | 90,019 [M] | 4.610 | 1.440 |
| 5 | 2,016,842 | 252.904 | 9.854 | 598,300 ± 3,300 [E] | 32.269 | 9.572 |
| 6 | 14,117,882 | 36.129 | 3.725 | 4,080,800 ± 22,900 [E] | 225.886 | 65.293 |
| 7 | 98,825,162 | 5.161 | 1.406 | 28,161,900 ± 159,600 [E] | 1,581.203 | 450.590 |
| 8 | 691,776,122 | 0.737 | 0.531 | 195,717,300 ± 1,115,000 [E] | 11,068.418 | 3,131.477 |

**What “land cells” means.** These are cells intersecting the downloaded Natural Earth land mask, including coastal cells whose centres are offshore. They are not a fixed fraction of global cells. The mask is the **1:10 million scale, version 5.1.1 [L]**, not a survey of every island or inland waterbody. Its own documentation identifies coastline limitations. [Land source](https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-land/)

For resolutions 3 and 4, I enumerated all cells and tested intersection [M]. The counts agree exactly with an independent H3 experimental overlapping polygon fill [M]. Centre-on-land counts are only **11,605 and 81,413 respectively [M]**: a centre-only fill misses coastal and small-island coverage.

For each finer resolution I sampled **300,000 cell indexes uniformly with replacement [M]**, using base-cell descendant counts and `child_pos_to_cell`, tested their land intersection, and expanded the observed fraction to the global count. The displayed uncertainty is an approximate **95% sampling interval [E]**. It excludes systematic shoreline error and geometric approximation. Intersections use Shapely polygons from H3 boundary vertices, with longitude unwrapping, translated dateline copies and polar closure; between vertices this is a planar approximation. Coarse enumeration matching H3 is a useful check, not a proof for every fine cell. Fine-resolution totals were **not exhaustively counted**. A native fill at resolution 5 was stopped after coarse counts were obtained because it was much slower than sampling; no incomplete fill was used as a count. [H3 overlap semantics](https://h3geo.org/docs/api/regions/)

The raw sizes exclude strings, file headers, indexing, dependency wheels and Python object overhead. Allow **5–15 MB extra [E]** for settlement/admin records and names. A repeated-string JSON design at **80–160 bytes per cell [E]** would make the resolution-8 land table roughly **15.7–31.3 GB [E]**, before parsing into Python objects. Binary dictionary encoding matters more than the word “hexagon.”

These are uncompressed installed sizes, **not measured wheel sizes**. Compression and compaction can reduce them substantially; no universal compression factor was assumed. PyPI's current defaults are **100 MB per uploaded file and 10 GB per project [L]**. The file limit applies to the compressed distribution, so it would be incorrect to declare every raw table above that limit unpublishable. Conversely, meeting the wheel limit does not establish acceptable RAM or startup time. [PyPI limits](https://docs.pypi.org/project-management/storage-limits/)

Resolution 3 is suitable only for very coarse context. Resolutions 5–6 can fit modest binary files but impose considerable settlement error. Resolution 8 is still a sampling approximation and has a poor size/benefit tradeoff for a complete cell-to-settlement table. **There is no recommended single resolution for the original design.** For the proposed hybrid, start by benchmarking resolution 4 as an acceleration index: its resolution affects speed and candidate-list size, while polygon containment uses the original coordinate.

## Measured accuracy

### Protocol and meaning of ground truth

Sources downloaded directly:

- [Natural Earth countries ZIP](https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_0_countries.zip): **258 features [M]**.
- [Natural Earth admin1 ZIP](https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_1_states_provinces.zip): **4,596 features [M]**. Excluded placeholder features with `+` in `adm1_code` from the state-error denominator; otherwise Antarctica and unsplit country placeholders misleadingly count as states.
- [Natural Earth land ZIP](https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip): **6,837 polygon parts [M]**.
- [GeoNames cities1000 ZIP](https://download.geonames.org/export/dump/cities1000.zip): **171,094 records [M]**. Despite the filename, the inclusion rule also admits specified administrative seats. [GeoNames schema](https://download.geonames.org/export/dump/readme.txt)

The Natural Earth archives identify version **5.1.1 [L]**. GeoNames was the daily **2026-10-01 snapshot [L: response metadata]**. One invalid country geometry and one invalid admin1 geometry were repaired with `make_valid` [M]. Polygon labels use `covers` and a deterministic feature-order tie rule for overlaps; random sampling is not an assessment of disputed sovereignty.

The reference country/admin1 answer is the containing polygon at the **original point**. The proposed table answer is the containing polygon at `cell_to_latlng(latlng_to_cell(point, resolution))`. A centre falling outside all country polygons counts as an error, not a successful abstention. This measures the snapping error of a *polygon-derived* table. It is a favorable baseline compared with inheriting administrative labels from a nearest city.

The reference settlement is the nearest GeoNames record under **spherical great-circle distance**. A SciPy KD-tree over unit-sphere Cartesian coordinates gives the same nearest ordering; compare record identities before and after snapping. This is **nearest-settlement disagreement, not municipal membership error**, address accuracy or distance to a built-up area. No globally consistent municipal-boundary ground truth was measured.

Two reproducible populations were used, all counts below [M]:

| Sample | Generation | Land points | Country denominator | Genuine admin1 denominator |
| --- | --- | ---: | ---: | ---: |
| Area-uniform land | Generate 1,000,000 sphere-uniform points, longitude uniform and sine(latitude) uniform; retain mapped land | 287,884 | 287,845 | 263,057 |
| Settlement-nearby land | Draw 100,000 settlements with replacement, equal settlement weight; jitter within a 5 km geodesic disk using radius = 5 × sqrt(U) (local-area approximation); retain mapped land | 96,335 | 96,318 | 95,992 |

Both populations use random seed **20261001 [M: recorded parameter]**. Country/admin1 denominators exclude points with no valid source label; exclusions are not silently counted correct. Settlement comparison uses all retained land points. The second population represents points near settlements, **not a population-weighted world sample, uniform urban land, or actual customer traffic**. The first includes Antarctica for country and settlement comparisons, which makes nearest-settlement stability look better over large uninhabited regions.

### Results: mismatch percentage, all values [M]

| Resolution | Area land: country | Area land: admin1 | Area land: settlement | Settlement-nearby: country | Settlement-nearby: admin1 | Settlement-nearby: settlement |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 7.227% | 20.011% | 49.529% | 15.879% | 44.669% | 95.458% |
| 4 | 3.269% | 9.071% | 27.681% | 8.194% | 22.559% | 83.509% |
| 5 | 1.474% | 3.890% | 12.861% | 3.852% | 10.000% | 59.423% |
| 6 | 0.628% | 1.586% | 5.274% | 1.665% | 4.136% | 32.852% |
| 7 | 0.243% | 0.600% | 2.048% | 0.636% | 1.622% | 14.343% |
| 8 | 0.098% | 0.232% | 0.784% | 0.264% | 0.643% | 5.652% |

For audit, resolution-8 settlement-nearby errors are **254 / 96,318 country; 617 / 95,992 admin1; 5,445 / 96,335 settlement [M]**. Corresponding **95% Wilson intervals [M, calculated]** are **0.233–0.298%, 0.594–0.695%, and 5.508–5.800%**. Sampling precision does not include outdated/misdrawn boundaries or gazetteer omissions.

Coasts are a substantial part of the country mismatch: **183 of those 254 errors [M]** put the cell centre outside the country layer. The country-error table therefore measures wrong-country **plus lost-country** assignments; it should not be presented as an international-land-border-only statistic. Merely storing every coastal cell does not repair its offshore centre's label.

Nearest-settlement inheritance has a separate error floor. With **no snapping**, its country differs from the polygon country on **13,438 / 263,278 = 5.10% [M]** of eligible non-Antarctic area-land points and **753 / 96,283 = 0.782% [M]** of settlement-nearby points. Eligibility also requires a usable Natural Earth country code. Dataset/worldview differences contribute to this comparison; it does not independently prove each GeoNames label wrong.

Nearest-place distance also needs disclosure: the area-land sample's median is **47.3 km [M]**, with a **90th percentile of 434.2 km [M]**; the settlement-nearby median is **2.56 km [M]**. “City” can otherwise sound local when the returned label is very far away.

### Why these numbers behave this way

The cell-centre method is a quantizer. Away from an administrative boundary it can be correct; across that boundary it replaces distinct labels with one label. A majority-area label minimizes uniform-area classification error within an individual cell, but still cannot represent both sides. Population weighting would choose a different optimum and can sacrifice rural correctness.

As a **reasoned scaling estimate**, boundary error is proportional to boundary length times typical snapping displacement, divided by sampled area, when cells are small relative to features. Thin regions, enclaves, small islands and dense settlement Voronoi boundaries violate the simplest approximation. A sample concentrated on a border can have a high error even when the world-average rate is low. There is no universal country/state/city error percentage without a query distribution and an answer definition.

Natural Earth's **1:10 million map scale [L]** is not metre-scale survey truth. Its admin1 page describes coverage and currency limitations. Making H3 finer cannot repair that source; the apparent precision of a cell ID should not become an accuracy promise. A later benchmark needs higher-resolution country packs, independent reference labels, border/coastal strata, and the owner's actual workload. [Admin1 limitations](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-1-states-provinces/)

## What the API should mean by “city”

Use **`nearest_place`**, whose relation is explicitly `nearest_settlement`, with source ID, name, feature type, reference coordinates and distance. Start with the documented GeoNames cities1000 selection. It includes towns and administrative seats; it is not a complete list of hamlets. A settlement's source country/admin codes belong inside that settlement record and must never overwrite the query's polygon-derived administration.

For the initial contract, use an explicit configurable **50 km maximum distance [target/product policy]**, measured from the query to the settlement point. `None` can mean no eligible settlement within that distance; it must carry that reason. This cutoff is not a city radius, a measured accuracy threshold or a universal definition of rurality. Allow unlimited nearest-place search only when explicitly requested. Start with unconstrained nearest settlement and show its own country, including when it is across a border; a same-country option would require a separate, documented search policy.

| Input situation | Recommended answer |
| --- | --- |
| Inside a city or rural municipality | Containing country/admin1 from polygons; nearest settlement separately. Municipal membership is not implied. |
| Rural point | Same administration contract; nearby village/town if present and within the chosen distance; otherwise a reasoned null. |
| Wilderness | Administration may still exist; nearest settlement may be null. Do not call the entire nearest-settlement catchment a city. |
| Open ocean | No country/admin1/settlement in the default terrestrial product; return `outside_land`. Maritime jurisdiction is a different dataset and product scope. |
| Inland lake | Preserve country/admin1 if the selected source includes the lake; disclose that surface-water classification is unavailable unless a hydrography layer is installed. Do not infer ocean merely from “no admin1.” |
| Small omitted island or missing region | `no_coverage` or `unknown` where coverage metadata can establish that distinction. A coarse global mask cannot reliably distinguish every omitted island from ocean; document that limitation. |
| Shared border or overlapping claim | Return ambiguity and candidate identifiers; do not manufacture confidence or silently choose a political policy. |
| User requires the containing municipality | A separately named `municipality` feature with appropriate country-specific polygons and eligibility rules; defer global support. A district/ADM2/ADM3 is not automatically a city. |

## Competitive landscape checked today

Unless explicitly marked [M], the following mechanisms, releases, licenses, sizes and upstream speed claims are **[L]**. Artifact sizes exclude dependencies and may use different compression. “Unknown” means not verified, not zero. No comparable accuracy percentage was established for each competitor; different datasets, metrics and semantics make a shared accuracy ranking unjustified.

| Project | Method and accuracy limits | Distribution/footprint and speed | Maintenance evidence |
| --- | --- | --- | --- |
| [`reverse_geocoder`](https://pypi.org/project/reverse_geocoder/) | GeoNames nearest-neighbour KD-tree, with settlement administration; not containment. LGPL-2.1. | Source archive **2.25 MB [L]**; installed package **7.89 MB [M]** excluding dependencies. **12.17 µs scalar; 818k points/s batch [M]** in single-process mode. | Latest PyPI **1.5.1, 2016-09-15 [L]**; [default-branch commit](https://github.com/thampiman/reverse-geocoder/commit/a81b4095bf2cb7ef84d2187fcbc8945d5d8922d0) also dated then. Old release, still installable here. |
| [`reverse_geocode`](https://pypi.org/project/reverse-geocode/) | GeoNames KD-tree; explicitly approximate point lookup. LGPL metadata. | Wheel **3.47 MB [L]**; installed package **3.48 MB [M]**, compressed source data expands in memory. **12.08 µs scalar; 716k points/s batch [M]**. | **1.6.6, 2025-05-15 [L]**; [default-branch activity](https://github.com/richardpenman/reverse_geocode/commit/e8815d2af2cbf2d5ff6eed482a572ab2eb650aac) **2026-08-01 [L]**. Cannot fairly call it abandoned. |
| [`rgeocoder`](https://pypi.org/project/rgeocoder/) | MIT, Rust/PyO3 nearest-place engine, independent of NumPy/SciPy at runtime. Same conceptual containment limitation. | Wheels **2.43–3.66 MB [L]** by platform. Speed/RAM unmeasured here: binary-only install found no matching **CPython 3.12 macOS arm64 wheel [M]**. Linux wheels for that Python version do exist [L]; this is not a universal installation failure. | **0.1.6, 2023-10-05 [L]**; [latest default-branch commit](https://github.com/Phil-V/rgeocoder/commit/167395e48519d06d475d4ac38e876bfe4926a89d) **2025-06-02 [L]**. Packaging coverage is a concrete possible improvement. |
| [`polars-reverse-geocode`](https://github.com/MarcoGorelli/polars-reverse-geocode) | MIT, Rust/rrgeo nearest-place Polars expressions. Not polygon membership. | Example arm64 wheel **6.84 MB [L]**, Polars excluded. README claims roughly **150 ms loading and 2.5 GB cached RAM [L, upstream]**; no-cache mode exists. Comparable throughput unverified. | [PyPI](https://pypi.org/project/polars-reverse-geocode/) **0.8.1, 2026-07-25 [L]**; same-day default-branch commit. Current activity. |
| [`rrgeo`](https://github.com/gx0r/rrgeo) | MIT OR Apache-2.0 Rust KD-tree, CLI and local server variants. Nearest place, not admin containment. | README core microbenchmark approximately **155 ns [L, upstream, Apple M2]**; repeated-query benchmark is not comparable to this report's random batches or Python calls. Package/RAM footprint not verified. | [Default-branch commit](https://github.com/gx0r/rrgeo/commit/308ce2b54b61de23b79cc2b7cc67b9800dac3f97) **2025-12-30 [L]**. Useful permissive baseline; not a drop-in Python package. |
| [`Lakhua`](https://github.com/aialok/lakhua) | MIT code, OSM-derived H3 lookup, resolution **5 → 4 fallback [L]**, India only; README explicitly disclaims exhaustive coverage. No independent accuracy rate. | [Python wheel](https://pypi.org/project/lakhua/) **0.250 MB [L]**. README claims approximately **1.39 MB unpacked and sub-ms lookup [L, upstream]**. Loads JSON maps. | **1.0.1, 2026-02-26 [L]**; [same-day commit](https://github.com/aialok/lakhua/commit/e34f2083ee3aba83686a27c3b4d44cb77892f676). The proposed basic mechanism already exists regionally. |
| [`geolookup`](https://github.com/kylebernhardy/geolookup) | Apache-2.0 Harper plugin, US Census TIGER places/subdivisions/counties, compacted H3 lookup. Municipality coverage explicitly partial. Quantization still matters. | Upstream importer describes approximately **40 MB source files [L]**, not a verified installed cell database size. Speed and runtime RAM unverified. | Default-branch activity **2026-05-28 [L]** ([commits](https://github.com/kylebernhardy/geolookup/commits/main/)). Existing hierarchical H3 geocoder; US and Harper scope. |
| [`python-gazetteer`](https://pypi.org/project/python-gazetteer/) | LGPL-2.1; geoBoundaries, KD-tree candidate search followed by polygon validation, SQLite WKB and metadata CSV. Claims boundary correctness, but candidate completeness and simplification were not independently validated here. ADM2/ADM3 outputs are not uniformly cities. | Wheel **66.76 MB [L]**. Comparable speed, startup and RAM unmeasured; upstream social performance claims were not treated as a benchmark. | **0.1.1, 2025-12-19 [L]**; [GitHub commit](https://github.com/SOORAJTS2001/gazetteer/commit/1f094111bf2be99cbe5f1cd1a5a19b549b72026c) **2026-01-21 [L]**. Direct competitor omitted from the PDF. |
| [`offline-geocoder`, Node](https://github.com/lucaspiller/offline-geocoder) | MIT, GeoNames/SQLite, nearest city. Not Python, not polygon containment. | Separate database roughly **12 MB; 300 lookups/s [L, upstream]**; database not bundled in npm package. Runtime footprint not independently measured. | Default-branch commit **2018-08-02 [L]** ([history](https://github.com/lucaspiller/offline-geocoder/commits/master/)); appears dormant. |
| [`offline_geocoder`, Ruby](https://rubygems.org/gems/offline_geocoder/versions/0.3) | Apache-2.0, GeoNames offline lookup. No verified polygon-containment or accuracy guarantee. | Gem **2.09 MB [L]**; comparable speed/RAM unknown. | Latest listed **0.3, 2021-07-09 [L]**. Not a Python competitor; illustrates name ambiguity. |
| [`bd-offline-geocoder`](https://pypi.org/project/bd-offline-geocoder/) | MIT code; bundled Bangladesh polygons and limited Dhaka OSM roads/houses. National administrative context; sparse addresses and simplified lower levels. | Wheel **29.95 MB [L]**, zero Python runtime dependencies claimed; parses and caches GeoJSON. Speed/RAM unmeasured. | **0.1.1, 2026-08-22 [L]**; [repository](https://github.com/TasfiqulGhani/bd-offline-geocoder). Recent regional competitor. |
| [`geo-intel-offline`](https://pypi.org/project/geo-intel-offline/) | MIT, Natural Earth country polygons; country context, not full city/admin1 coverage. Confidence scores are not independently calibrated. | Wheel **4.27 MB [L]**. Claims **under 1 ms and under 15 MB RAM [L, upstream]**; unmeasured here. | **1.5.0, 2026-02-15 [L]**; [repository](https://github.com/RRJena/geo-intel-offline). Permissive country-only boundary alternative. |
| [`GridPin`](https://github.com/gridpin/gridpin) | Apache-2.0 engine, Rust-backed Python and mmap country files; nearest indexed address, including street-centroid approximation. Regional, not global admin truth. | [Wheel](https://pypi.org/project/gridpin/) approximately **0.75–0.91 MB [L]**, data separate. Country files **32–365 MB [L, upstream]**; France reverse throughput around **1,800/s [L, upstream]**. Different task from a settlement lookup. | **0.3.0, 2026-09-28 [L]**. Newer than the PDF's sample; memory-mapped offline distribution itself is not unique. |

Exact PyPI JSON lookups for `offline-geocoder`, `offline_geocoding` and `offline-reverse-geocoding` returned **404 [M]**. PyPI normalizes hyphens and underscores; these absences do not imply that no similar project exists. The actual boundary package is named `python-gazetteer`, not `gazetteer`.

The inspected installed implementations of the two established Python packages pass latitude/longitude pairs directly to their KD-trees. That introduces a distance-metric issue near high latitudes and the dateline, in addition to settlement-vs-containment ambiguity; this report's unit-sphere experiment does not inherit that metric. [reverse_geocoder source](https://github.com/thampiman/reverse-geocoder/blob/master/reverse_geocoder/__init__.py), [reverse_geocode source](https://github.com/richardpenman/reverse_geocode/blob/master/reverse_geocode/__init__.py)

### Local geocoding servers and the PDF's MCP examples

| Project | What it provides and accuracy limits | Size/speed/maintenance evidence [L unless stated] |
| --- | --- | --- |
| [Nominatim](https://nominatim.org/release-docs/latest/api/Reverse/) | OSM-derived indexed objects and address hierarchy; normally PostgreSQL/PostGIS. Self-hosted service can operate without external query-time network. Its reverse endpoint finds a suitable nearby object, not necessarily the exact queried address. | Full-planet installation docs recommend **128 GB RAM and at least 1 TB disk [L]**; smaller extracts change the requirement. Query speed unmeasured. [Install docs](https://nominatim.org/release-docs/latest/admin/Installation/); [default-branch commit](https://github.com/osm-search/Nominatim/commit/09c864c429ca99d27b1c71980b0e39ff6aaf357d) **2026-09-30 [L]**. GPL code, ODbL OSM data. |
| [Pelias](https://github.com/pelias/pelias) | Modular Elasticsearch geocoder, with OSM, GeoNames, Who's On First and other imports. Rich address/place queries, including reverse and coarse administrative modes; source and configuration govern accuracy. [Reverse documentation](https://github.com/pelias/documentation/blob/master/reverse.md) | Local service stack, not one tiny Python dataset. Full deployment disk/RAM and query speed unverified here; optional/full address stack includes roughly **4 GB libpostal data [L]** alone. [Requirements](https://github.com/pelias/documentation/blob/master/requirements.md). MIT umbrella repository; source licenses vary. Default-branch activity **2026-07-24 [L]**. |
| [Photon](https://github.com/komoot/photon) | Apache-2.0 Java search service over OSM/Nominatim-derived data and a search index; returns indexed features, including reverse results, rather than a general municipal-membership oracle. | Current README estimates **95 GB planet disk and recommends 64 GB RAM [L]**. Query speed unmeasured. [Default-branch commit](https://github.com/komoot/photon/commit/c411a4b1b9bd09de6e60ea657e7e23d7e575415e) **2026-09-24 [L]**. OSM data obligations remain. |
| [Mapbox MCP](https://github.com/mapbox/mcp-server) / [osm-mcp](https://github.com/ni-c/osm-mcp) | Adapters, not bundled global offline reverse-geocoding databases. Reverse accuracy follows their upstream service. osm-mcp can be configured for a local backend. | Package size and service latency unmeasured; not comparable to an in-process table. Both MIT repositories show activity in **September 2026 [L]**. A local wrapper around any engine is straightforward differentiation in interface, not in accuracy. |

**Measured runtime protocol.** Apple M2, **8 GiB RAM [M]**, macOS arm64, CPython **3.12.2 [M]**; NumPy **1.26.4**, SciPy **1.13.1**, Shapely **2.1.0**, H3 **4.5.0 [M]**. Timed imports and first queries in fresh processes with potentially warm OS caches. Warm scalar is the median of **1,000 repeated calls at the same London point [M]**. Batch throughput is the median of **three runs over the same 100,000-point sphere-uniform batch [M]**, including Python result objects; `reverse_geocoder` uses `mode=1`. Final runs were sequential after the data experiments completed.

| Runtime observation [M] | reverse_geocoder | reverse_geocode |
| --- | ---: | ---: |
| Import | 0.288 s | 0.354 s |
| First query after import | 0.327 s | 0.274 s |
| Peak process RSS during entire harness | 176.5 MB | 257.1 MB |

RSS includes Python, dependencies, generated inputs and results; it is **not idle dataset RAM**. These exploratory timings are not a controlled cross-platform benchmark. H3 conversion alone took roughly **0.64–0.78 µs/point [M]** in the accuracy harness, but that excludes storage lookup, polygon fallback and result construction. The reference spherical KD-tree handled the settlement-nearby batch at roughly **a microsecond per point [M, rounded]**, so precomputing a huge city table is not an obvious performance necessity.

## Variants and recommended architecture

| Variant | Evaluation |
| --- | --- |
| Fixed-resolution centre labels | Simple and deterministic; measured errors and size above. An explicit approximate mode might be useful for an existing H3 analytics workflow, but should not define the default answer. |
| Polygon-derived labels instead of nearest-settlement administration | Essential semantic correction. Centre assignment still loses borders. Majority overlap changes which points are wrong rather than removing the problem. |
| Adaptive/hierarchical H3, refining mixed cells | Potentially much smaller because interiors can remain coarse. Refining admin boundaries is more attractive than storing settlement Voronoi cells. At the finest level, mixed cells still need polygon checks or explicit ambiguity. No compacted global size was measured here. |
| Full-resolution fill followed by H3 compaction | Reduces repeated labels but may make the initial build unnecessarily huge. Compact **within identical labels and status**, not across administrative classes. Compression retains the original leaf-grid approximation; it does not recover actual boundaries. |
| Country/state cells plus nearest-neighbour settlement | Much better than a flat city table, provided mixed administrative cells use exact original-point containment. Country/state should not come from the returned settlement. |
| Direct polygon spatial index plus nearest-neighbour settlement | Mandatory baseline. It may be simpler and already fast enough. Drop the H3 accelerator if measurements do not justify its build and format complexity. |

**Recommended product:** polygon-defined country/admin1, a separately reported nearest settlement and a dated, licensed data snapshot. Prototype direct polygon indexing first. Then benchmark a **fixed resolution-4 H3 accelerator [target]** containing either a proven uniform assignment or a complete set of candidate polygon parts. Check the original coordinate against those candidates in mixed cells. Retain a spatial-index fallback for any unproven classification, missing candidate, polar case or data gap.

This replaces storage proportional to every small land cell with storage proportional to the coarse index, polygon geometry and settlement catalog. A global cartographic pack is provisionally **50–100 MB installed and 20–50 MB compressed [E]**, excluding engine/dependency wheels. This is a budget to test, not a built artifact. The downloaded, repaired country/admin1/land geometries total **36.90 MB of WKB [M]**, which grounds the estimate. Higher-detail geoBoundaries packs can be substantially larger and have not been sized.

There is an important H3 correctness trap: **logical parentage is exact, geographic parent containment is approximate [L]**. A query mapped directly at a coarse resolution need not equal the parent of its fine-resolution cell. For a compacted leaf-grid design, query at the designated leaf resolution and then traverse logical parents; prove uniformity over the actual descendant footprint. Checking only a parent's drawn hexagon is insufficient. The initial fixed-resolution accelerator avoids that extra invariant. [H3's own explanation](https://h3geo.org/docs/highlights/indexing/)

Do not prove a cell uniform from its centre or vertices alone: an enclave, hole or small polygon can lie wholly inside it. Require full coverage and absence of competing polygons, including the land/water layer. H3's ordinary polygon fill is centre-based; overlapping/full containment modes have different meanings and are currently exposed as experimental APIs. Candidate completeness must be tested against direct geometry, especially at the dateline and poles. [Region APIs](https://h3geo.org/docs/api/regions/)

## Data, licensing and maintenance obligations

| Source/component | License facts [L] | Consequence for the shipped product |
| --- | --- | --- |
| [GeoNames daily extract](https://download.geonames.org/export/dump/readme.txt) | Current dump says **CC BY 4.0**. Older projects often refer to older snapshots under **CC BY 3.0**. | Use the license actually attached to the acquired snapshot. Credit GeoNames, link the source/license, identify filtering/indexing changes and retain required notices. Code can remain Apache-2.0; do not label the entire data file Apache-only. |
| [Natural Earth](https://www.naturalearthdata.com/about/terms-of-use/) | Public domain, including modified redistribution. | Good low-friction bootstrap and benchmark. Record provenance and snapshot anyway. Public domain says nothing about fitness for precise jurisdiction lookup. |
| [geoBoundaries gbOpen](https://www.geoboundaries.org/api.html) | CC BY 4.0-compliant collection; metadata includes underlying source/license and validity year. Other collections have different restrictions. | Use gbOpen only for the default permissive-data path; retain per-country attribution, source licenses, dates and transformations. Country files may reflect overlapping national claims, so stitching them is a policy decision. Do not silently replace gbOpen with gbHumanitarian or gbAuthoritative. |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) | ODbL; attribution and database share-alike obligations apply as specified in the [license](https://opendatacommons.org/licenses/odbl/1-0/). | A systematically derived global H3 database should be treated as an OSM-derived database, not as license-free facts merely because it uses cell IDs. Public distribution requires the applicable ODbL notices and derivative-database availability/share-alike. This need not relicense independently written package code. Keep optional OSM packs separately identified; separation alone is not a way to evade database obligations. |
| [GADM](https://gadm.org/license.html) | Restrictions include commercial use/redistribution conditions. | Do not use it as the default redistributable commercial-friendly pack without permission. “Downloadable boundary data” is not enough. |
| [H3 Python bindings](https://github.com/uber/h3-py/blob/master/LICENSE) | Apache-2.0. | Compatible with the proposed independently written Apache-2.0 code; preserve notices and audit the exact dependency versions. |
| [Shapely/GEOS](https://shapely.readthedocs.io/en/2.0.7/index.html) | Shapely is BSD; GEOS is LGPL-2.1. Wheels can bundle GEOS. | A Shapely runtime is not an entirely permissive dependency tree. Use it freely for the research/build/reference pipeline with its obligations; if avoiding runtime copyleft is a product requirement, use a permissively licensed runtime geometry implementation, e.g. [Rust geo](https://github.com/georust/geo). |

CC BY requires appropriate credit, a license link and indication of changes; it is not share-alike. Include a machine-readable manifest plus readable attribution in both the data distribution and package documentation. [CC BY terms](https://creativecommons.org/licenses/by/4.0/)

Choose Apache-2.0 for **new code**, as the PDF suggests; MIT is also reasonable. Do not port LGPL implementation code into a permissively labeled engine without satisfying its license. Audit runtime and build dependencies separately. For the initial pack, use Natural Earth plus GeoNames; offer better admin polygons through explicitly versioned gbOpen regional packs after evaluating them. Avoid building the table by bulk-calling commercial reverse APIs: redistribution/caching terms differ, and fetching open datasets is a reproducible build process.

Freshness requires an owner: snapshot dates, reproducible manifests, data-change reports, reviewed releases and correction handling. Automated daily downloads without validation do not constitute maintenance.

## Decision and limits of this investigation

Proceed if users need **containing administration plus approximate settlement context**, care about offline operation and reproducibility, and the owner will maintain data and current wheels. The strongest potential advantage is a clear result contract with measured resource use and an entirely permissive runtime dependency option. H3 is an implementation detail. If users only need the nearest city, first use or improve an existing permissive KD-tree engine. If they need precise street addresses, use regional address data or an established local service.

Do not proceed with a promise of a tiny global cell-centre table that accurately returns arbitrary cities, states and countries. The measurements contradict that proposition under the stated semantics.

Not completed or verified: exhaustive fine-resolution land counts; global municipal-boundary accuracy; higher-detail geoBoundaries accuracy; population-weighted or customer-traffic accuracy; exhaustive competitor discovery; independent accuracy and latency benchmarks for every competitor; `rgeocoder` runtime on this platform; hierarchical/hybrid artifact compression, startup or memory; user demand or commercial viability. No library or distributable dataset was implemented.

### Reproduction record

All scripts, archives, extracted PDF text, source metadata and results are outside the repo under:

`/private/tmp/claude-501/-Users-ujjwal-Downloads-solo-PyOfflineGeocoder/2573e848-a978-4d6d-bd6b-d080d49ba647/scratchpad/codex-work/`

Relevant files: `measure.py`, `accuracy.json`, `land_counts.py`, `land_counts.json`, `land_mc.py`, `land_mc.json`, `bench_competitors.py`, `bench-rg.json`, `bench-rgc.json`, `competitors.json`, `source_urls.json`, and `background.txt`. Run scripts with that directory's `venv/bin/python`; the measurement environment uses the versions recorded above. `land_counts.py` contains an unfinished expensive fine-fill experiment; use its saved coarse results or restrict it to the coarse resolutions. The Monte Carlo script supplies the reported finer estimates.

Archive SHA-256 fingerprints [M]:

| Archive | SHA-256 |
| --- | --- |
| Countries | `ce1ac7036499a0edd641fbc093cd209a98f96a49d2eca8480aaacad35138a7f6` |
| Admin1 | `efc59726337323058f9446210adc96673179cd344e053666ee3d28cb58ba2b05` |
| Land | `e547d749445eaa0964aba76738090ec88f5e63c4585122170f98c67a7ea922dc` |
| GeoNames cities1000 | `03a8fef1f34c0547183fc80b36dd552ae402531dc0656f7dd5d033e7712c9b05` |

The coarse land counts were independently checked with H3 overlap fill. The finer sampling seed is **1729 [M: recorded parameter]**. GeoNames' live URL changes daily; retain the archived snapshot and hashes to reproduce these results exactly. Scratch storage is not a long-term published benchmark archive. The repo contains only this evaluation and the requested implementation plan as task outputs; git state was not changed.
