# Source-data replacement plan

Research date: **2026-10-01**. This is a plan, not a new pipeline or a completed
accuracy evaluation. The runtime contract in [DESIGN.md](DESIGN.md) remains one
combined table: query → H3 resolution-8 cell → ancestor lookup → city, state,
country and country code. Every answer is determined at build time from that
cell's centre, including the coastal rule below.

## Recommendation for the owner

| Role | Recommended source and precedence |
| --- | --- |
| Physical land and coastline | **OSM land polygons, split WGS84 edition from osmdata.openstreetmap.de.** Replace Natural Earth's eligibility outline. Add a bounded coastal band to handle centres just offshore. |
| Country / territory | **Overture divisions**, with a versioned territory-code and disputed-boundary policy. Use territorial areas for assignment, not for unlimited ocean coverage. |
| State | **Overture divisions selected by a per-country administrative policy**; use **geoBoundaries gbOpen selectively** to replace a missing, stale or semantically wrong layer. Start with its verified UK constituent-country layer. |
| City / locality polygons | **Overture division_area + division hierarchy**, selecting municipalities/settlements rather than neighbourhoods. Explicit city-state and metropolitan conventions cover Singapore, Monaco and Tokyo. |
| Settlement points | **GeoNames allCountries**, filtered to current populated places without a population floor; supplement with Overture `division` locality points. |
| Names | English names from the selected entity's Overture names or matched GeoNames `alternateNamesV2`, then a local Unicode name. Preserve source IDs and aliases in build artifacts. |

**Run locally.** The useful inputs fit this machine; resumable bulk downloads are
more reliable for a world build than repeatedly scanning remote Parquet by
country. Use remote column/range reads for small pilots. GCS is optional backup,
not a required processing dependency. Estimated first-build download is **7–9 GB
including retry allowance**, peak working disk **28–35 GB**, with a **45 GB hard
workspace cap** and at least **20 GB free-space reserve**. Limit total builder RSS
to **5 GB**, with one geometry worker. Estimated automated build time is **12–36
hours including transfer at an effective 5–20 Mbit/s**; prolonged outages add time.
Allow **10–18 engineer-days** to implement, calibrate and review this plan, not
just run it. These estimates require the early regional measurement gate below.

**The shipped table should be released as an ODbL 1.0 derivative database.** OSM
land and Overture divisions introduce share-alike even if only labels/H3 cells
are shipped. Keep CC BY and other required source notices too. The software's
licence can remain separate. Dropping direct OSM land would not remove ODbL while
Overture divisions remain. Budget for **250–800 MB installed / 90–350 MB compressed
(estimated)**, and plan packaging by H3 base cell if the actual wheel exceeds
the PyPI limit. First deliver the coastline-only change with the current city
catalogue, then improve administrative and city semantics.

## Evidence, units and limits of this investigation

Every size, timing and count below is identified as **M** (measured in this
workspace or in a live response), **L** (looked up, linked), **E** (estimated),
**T** (proposed target/limit), or **B** (owner-supplied baseline). Sizes use decimal
MB/GB unless explicitly written MiB/GiB. Durations are estimates on the specified
M2/8 GB machine, not benchmark results for the proposed pipeline.

**B:** 2,797 of 161,540 original settlements have no row (1.73%); 9 of 560
million-plus settlements fail. The supplied list names eight of those nine:
Lagos, Hong Kong, Xiamen, Shantou, Guayaquil, Monrovia, Belém and Mombasa. Recover
the ninth from the frozen audit rather than guessing. Monaco is an additional
required regression. Proximity to an existing cell is evidence of a coastal
failure, not proof of which outline/rasterization mechanism caused it.

**M, existing benchmark:** [build.json](../benchmarks/build.json) records
20,808,748 stored rows; 50,951,071 table bytes; 53,056,366 complete pack bytes;
21,347,383 ZIP bytes; 687.93 seconds for table build plus verification; and
246,595,584 bytes peak labelling RSS. It enumerated 691,776,122 centres and
labelled 40,319,034. Its timing excludes source preparation and compression.
These are the old-source baseline, not predictions for detailed polygons.

All probe files are outside the repository at:

```text
/private/tmp/claude-501/-Users-ujjwal-Downloads-solo-PyOfflineGeocoder/2573e848-a978-4d6d-bd6b-d080d49ba647/scratchpad/dataplan-work/
```

Evidence there includes `heads.json`, `zip-metadata.json`, `*-objects.json`,
`parquet-metadata.json`, `parquet-probe-result.json`, `gb-ADM*.json`,
`gb-probes.json`, and the probe scripts. The tables below embed the significant
results so this document does not depend on temporary files surviving.
**M:** the Parquet experiment transferred 21,147,285 response-body bytes; the
small geoBoundaries geometries transferred 1,827,504 bytes; the two gbOpen
inventories transferred 760,878 bytes. ZIP-directory probes transferred 1,813
bytes. Including other small listings/pages, **E: less than 30 MB** was fetched
by the scripted probes, well below the requested approximately 500 MB limit.
No full global source archive was downloaded.

## Source assessment

### GeoNames: complete gazetteer, not a polygon source

Use `allCountries.zip`, `alternateNamesV2.zip`, `countryInfo.txt`,
`admin1CodesASCII.txt`, `admin2Codes.txt` and the feature-code dictionary.
`allCountries` supplies UTF-8 point records with ID, name/asciiname, coordinates,
feature class/code, country and administrative codes, population and modification
date. Alternate-name records add language, preference, historic/colloquial flags
and validity dates. The comma-separated aliases in `allCountries` do not retain
the language metadata needed for reliable English selection. GeoNames
administrative codes are not uniformly ISO codes; join through its code tables,
not by assuming they equal Overture region codes. **L:** schema and **CC BY 4.0**
in the [dump specification](https://download.geonames.org/export/dump/readme.txt).

**L:** global coverage, daily exports, over 12 million features and approximately
4.8 million populated places are advertised on the
[GeoNames overview](https://www.geonames.org/about.html). Those rounded counts are
not a count of our eventual eligible records. Expect uneven completeness,
misclassified neighbourhoods and missing population values. Changing from
`cities1000` alone cannot solve those semantic problems.

| Archive | Compressed bytes, M: HEAD | Expanded bytes, M: remote ZIP central directory |
| --- | ---: | ---: |
| [allCountries.zip](https://download.geonames.org/export/dump/allCountries.zip) | 422,003,018 | 1,788,639,329 |
| [alternateNamesV2.zip](https://download.geonames.org/export/dump/alternateNamesV2.zip) | 204,804,536 | 785,712,764, including language-code file |
| [cities1000.zip](https://download.geonames.org/export/dump/cities1000.zip), comparison only | 11,052,765 | 31,948,451 |

All three responses advertised byte ranges and answered the small range probes
with HTTP 206. `allCountries` had Last-Modified `2026-10-01 02:08:51 GMT`, ETag
`"1927414a-65cbde5a07139"`; alternate names had `2026-10-01 02:13:54 GMT`, ETag
`"c3511b8-65cbdf7adc880"` (**M**). These URLs change daily: neither a date in our
manifest nor an ETag is a publisher SHA256. Pin the bytes when acquired; reject
a changed remote object during resume. **E:** filtered points, retained aliases
and disk indexes occupy 1–2 GB; measure actual eligible count before H3 sizing.

### Overture: administrative hierarchy and locality geometry

Pin release **`2026-09-23.1`**, the current release in the checked documentation
and successfully listed objects (**M/L**). It is distributed as GeoParquet on
AWS S3 in `us-west-2` and Azure in `westus2`; releases are monthly.
Country/region coverage is global, while locality and finer polygons are patchy.
The guide describes OSM and geoBoundaries inputs; the current attribution page
also lists Esri Community Maps and LINZ. Retain the release-specific attribution
and row provenance, rather than assuming the guide exhausts the contributor
list. **L:** [divisions guide](https://docs.overturemaps.org/guides/divisions/),
[catalog access](https://docs.overturemaps.org/getting-data/cloud-sources/) and
[licensing](https://docs.overturemaps.org/attribution/).

**L/M, schema:** `division` is a point entity carrying `id`, `names`, `country`,
`region`, `subtype`, `class`, `admin_level`, `parent_division_id`, `hierarchies`,
`perspectives`, optional `wikidata`/`population`, and `sources`. Read hierarchy
and perspective explicitly. Overture `admin_level` is its normalized hierarchy
position, not a raw OSM admin-level number or necessarily geoBoundaries ADM n.
[Division specification](https://docs.overturemaps.org/schema/reference/divisions/division/).

`division_area` joins through **`division_id`**, not its own area ID. Its
polygon/multipolygon, repeated labels/codes and `is_land` / `is_territorial`
distinguish land-clipped and territorial extents. A landlocked area can have both
flags true; a coastal area may have separate land and territorial rows. Do not
require both flags globally, or union both versions as independent countries.
**M:** Monaco had both country variants in the probe.
[DivisionArea specification](https://docs.overturemaps.org/schema/reference/divisions/division_area/).
For each accepted country/state/locality entity, prefer its territorial variant
for containment, falling back to its land variant only if no territorial area
exists. Apply the independent land/coastal eligibility rule in either case.

Names contain a primary string, language-keyed `common` names, and variant rules;
English is optional, not implied by `primary`. **L:**
[names schema](https://docs.overturemaps.org/schema/reference/common/names/).
The live file has WKB binary geometry, a struct bbox, nested names/sources and
the two extent booleans (**M**). Current documentation labels the schema v2.0.0;
record the actual Parquet schema fingerprint as well as the release.

**M: S3 ListObjectsV2 byte totals** under
[`release/2026-09-23.1/`](https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/?list-type=2&prefix=release%2F2026-09-23.1%2Ftheme%3Ddivisions%2F):

| Type | Objects | Bytes | Decision |
| --- | ---: | ---: | --- |
| `divisions/division` | 1 | 581,868,458 | Include; M: 4,688,229 point entities, not all cities |
| `divisions/division_area` | 8 | 4,531,207,040 | Include selected administrative/locality rows; M: 1,080,667 areas |
| `divisions/division_boundary` | 1 | 512,261,151 | Exclude: derive needed edges from selected polygons |
| `base/land` | 128 | 30,149,166,659 | Exclude from default acquisition |

**M:** land total came from the corresponding
[base/land listing](https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/?list-type=2&prefix=release%2F2026-09-23.1%2Ftheme%3Dbase%2Ftype%3Dland%2F).
Overture land does include a coastline-derived global land surface, alongside
other natural features. It is not simply land cover, nor is every row an
eligibility polygon. OSM is its upstream source; it is monthly and ODbL.
**L:** [base guide](https://docs.overturemaps.org/guides/base/) and
[land schema](https://docs.overturemaps.org/schema/reference/base/land/).
Direct split OSM land is much smaller and avoids having to prove the correct
subtype/geometry filter across this mixed theme. Do not fetch the entire base
theme, buildings, transportation or addresses.

Exclude **Overture Places**: it describes destinations/POIs, not municipal areas
or a settlement gazetteer. Its current theme licences are CDLA Permissive 2.0 and
Apache 2.0, with contributor-specific notices; they do not replace the ODbL
licence of divisions. **L:** [Places guide](https://docs.overturemaps.org/guides/places/).

#### What remote filtering actually saved

**M:** reading all nine division/area footers used 4,316,885 bytes. The Monaco
bbox `[7.40, 43.72, 7.44, 43.76]` intersected six area row groups. Projected
attribute reads, followed by geometry for the group containing Monaco records,
brought total transfer to **21,147,285 bytes in 37 HTTP range requests, 20.72 s**.
The selected **23 rows** contain **46,939 WKB bytes**. Geometry alone required
15,919,692 transferred bytes because Parquet fetches compressed column chunks,
not just the matching features. This was a measured PyArrow range reader,
**not a DuckDB benchmark**, and not a measurement of the home link's sustained
throughput. Record output bytes and network bytes separately in later pilots.

The geometry chunk was in
`type=division_area/part-00002-f7766c1a-fff7-57b4-a3ae-5905c3ea9b9e-c000.zstd.parquet`,
row group 37. The probe used ETag preconditions and checked `Content-Range` and
returned byte count. This is reproducible from the snapshot listing and footer.

**M:** all area geometry chunks total **4,414,924,314 bytes**, **97.43%** of area
object bytes. Point columns needed for geometry, hierarchy, names and provenance
sum to **573,394,509 compressed bytes**, almost the whole point object. Therefore
do not promise order-of-magnitude world-download savings from `SELECT` columns
or `WHERE country = ...`. Geometry rows of different subtypes share row groups.
The source objects are partitioned by theme/type and spatially arranged within
files, **not by country**.

For pilots use explicit overlapping bbox predicates (`xmin <= east`,
`xmax >= west`, `ymin <= north`, `ymax >= south`) and only needed columns with
[DuckDB/httpfs](https://docs.overturemaps.org/getting-data/duckdb/) or equivalent
range reads. Do not use a fully-contained bbox test, which loses encompassing
country polygons. Resolve parent IDs separately; an entity's point may lie
outside the pilot even when its polygon contains it. Split antimeridian bboxes.

For the world build prefer one resumable acquisition of the **5.113 GB** of
division/area objects, then local bounded queries. If a pilot shows whole row
groups can be skipped, use the checkpointed range cache described below; count
all distinct transferred chunks before choosing. Do not run a separate world
remote scan for every country, and do not confuse DuckDB's in-process HTTP cache
with a durable resumable download.

### geoBoundaries: selective administrative fallback

Use **gbOpen**, per country and chosen level, with commit-pinned download URLs.
It supplies administrative polygons, not inhabited-land masks or universally
defined cities. **L:** the [API](https://www.geoboundaries.org/api.html) exposes
ADM0–ADM5, source/represented years, boundary IDs, licences and full/simplified
download links. The project describes yearly archives and ongoing GitHub
updates, not a guaranteed monthly refresh. Preserve `boundaryYearRepresented`,
`sourceDataUpdateDate` and `buildDate` independently.

**M:** the current inventories had **230 ADM0 layers / 199 ADM1 layers**; this is
not every territory at every level. ADM0 lacked separate HKG and SJM entries.
ADM1 lacked those and the five named French overseas departments. The sampled
GeoJSON properties were `shapeName`, `shapeISO`, `shapeID`, `shapeGroup`,
`shapeType`; ISO values can be empty and names have no uniform language-tagged
translation structure. Preserve them as source names, not guaranteed English.
The [ADM0 inventory](https://www.geoboundaries.org/api/current/gbOpen/ALL/ADM0/)
and [ADM1 inventory](https://www.geoboundaries.org/api/current/gbOpen/ALL/ADM1/)
were fetched directly with Python; the web reader could not render a single-
country API URL, but the direct inventories and linked files were reachable.

| Full GeoJSON, M: HEAD / small GET | Bytes | Measured finding |
| --- | ---: | --- |
| [GBR ADM1](https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/GBR/ADM1/geoBoundaries-GBR-ADM1.geojson) | 198,798 | Four constituent countries; England is `GB-ENG`; represented year 2021 |
| [MCO ADM0](https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/MCO/ADM0/geoBoundaries-MCO-ADM0.geojson) | 22,866 | One polygon, represented year 2017, OSM/ODbL |
| [SGP ADM0](https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/SGP/ADM0/geoBoundaries-SGP-ADM0.geojson) | 313,973 | One polygon, OSM/ODbL |
| [SGP ADM1](https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/SGP/ADM1/geoBoundaries-SGP-ADM1.geojson) | 1,081,841 | Five planning regions; not useful as this product's state field |
| [NOR ADM0](https://github.com/wmgeolab/geoBoundaries/raw/41af8f1/releaseData/gbOpen/NOR/ADM0/geoBoundaries-NOR-ADM0.geojson) | 56,165,425 | HEAD only; represented year 2017 |
| [NOR ADM1](https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/NOR/ADM1/geoBoundaries-NOR-ADM1.geojson) | 68,203,205 | HEAD only |
| [PHL ADM1](https://github.com/wmgeolab/geoBoundaries/raw/41af8f1/releaseData/gbOpen/PHL/ADM1/geoBoundaries-PHL-ADM1.geojson) | 440,897,026 | HEAD only; 17 regions, represented year 2020 |

The inventory describes Indonesian ADM1 as **34 units, year 2017 (M)**. Do not
prefer this over newer Overture simply because gbOpen offers an ADM1 file.
Country-specific freshness and level selection matter. **E:** allow **0.05–1 GB**
for selected fallback files; obtain HEAD sizes for the actual allowlist before
building. A global total for all gbOpen geometries was **not measured** and is
not included in the download budget; do not clone its repository or fetch CGAZ.
**M:** a conditional 32-byte range read of the commit-pinned GBR ADM1 GitHub media
URL returned HTTP 206 and `Content-Range: bytes 0-31/198798`; resumability was
demonstrated for that chosen fallback, not assumed from HEAD alone.

**Licence qualification:** gbOpen is described as CC BY 4.0 compliant, but its
actual per-layer metadata contains other original licences. **M:** each of the
ADM0 and ADM1 inventories included **84 ODbL-labelled layers**; Kosovo ADM0
listed CC BY-SA 2.0 despite identifying OSM as its source. Other entries had
ambiguous licences. Use only an explicit compatible-license allowlist with the
original notices retained; exclude unresolved/contradictory entries rather than
silently relabel them CC BY. The independently acquired UK layer is CC BY 4.0.
Overture already uses geoBoundaries, so gbOpen is not an independent accuracy
reference and wholesale duplication is not worth including.

### OSM land: the additional source worth including

Use the [split WGS84 land polygons](https://osmdata.openstreetmap.de/data/land-polygons.html),
assembled from `natural=coastline`, with slightly overlapping pieces. They cover
continents/islands, carry no usable country/city names, and do not subtract inland
lakes. This is appropriate for the existing inland-water eligibility convention.
Do not download the unsplit or Web Mercator versions as well. The website says
updates are usually daily; unrepaired coastline errors can delay publication.
**L:** [download cadence](https://osmdata.openstreetmap.de/info/downloading.html).

**M:** [land-polygons-split-4326.zip](https://osmdata.openstreetmap.de/download/land-polygons-split-4326.zip)
was **927,857,432 bytes**, with **1,343,282,294 expanded bytes** from ZIP metadata.
The SHP member alone is **1,319,701,724 bytes**. Last-Modified was
`2026-10-01 03:37:19 GMT`, ETag `"374dfb18-65cbf220083e3"`; byte-range requests
succeeded. The unused complete archive was **922,675,025 bytes / 1,326,824,206
expanded (M)**. These are measured metadata sizes, not downloaded archives.

Use the unsimplified split geometries; stream features using the SHX index and
maintain source-edge identity so artificial split edges cannot become coastlines.
Do not build a world union in memory. Preserve islands, holes, poles and dateline
wrap. **E:** tiled land, edge indexes and the coastal band occupy 2–4 GB. Verify
Antarctic coverage explicitly; do not silently retain Natural Earth globally to
hide an ice/coastline gap. Any necessary polar fallback must be separately pinned,
licence-reviewed and recorded as a coverage exception before release.

The download is **ODbL**, copyright OpenStreetMap contributors. Linking the
osmdata service itself is appreciated, but is not the OSM licence requirement.
**L:** [licence statement](https://osmdata.openstreetmap.de/info/license.html).

## Labelling policy

### Land, offshore centres and the cause of current misses

Use a detailed terrestrial footprint `L` from OSM coastlines, including inland
water inside that footprint. Country territorial polygons determine jurisdiction;
their extension over the sea does **not** make that sea eligible.

For each resolution-8 centre `c`, use this proposed, versioned rule:

1. If `c` is in `L`, keep it eligible. Label country/state/locality by containment
   at `c` and the precedence below.
2. Otherwise, if geodesic distance from `c` to `L` is at most **1,000 m (T)**,
   keep it eligible as a coastal cell. Let `q` be its nearest point on true land.
   Derive jurisdiction from the land containing `q`, resolving competing land
   pieces by distance, then the declared territorial perspective, then stable
   source ID. Use `q` for polygon membership of this offshore answer and `c` for
   nearest-settlement distances. Never snap inland centres across a border.
3. Otherwise omit the row. Land without a resolved jurisdiction remains a present
   row with unknown fields and an audit entry; it is not classified as ocean.

`q` is a deterministic build-time function of the **cell centre**, not of each
query point. Every coordinate mapping to the same H3 cell still gets one answer.
This deliberately assigns some genuinely offshore points a nearby terrestrial
label, only within this band. It is not an ocean navigation/jurisdiction product.
Near narrow straits it may choose the opposite shore; quantify this in tests.
Do not extend the band to 5 km to conceal simplified source boundaries.

**L:** H3 reports a resolution-8 average area of about **0.737 km²** and average
edge length about **0.531 km** in its
[cell statistics](https://h3geo.org/docs/core-library/restable/). An average is
not a maximum-radius proof. During the pilot compute a conservative global
bound on centre-to-cell-edge distance, including pentagons and face seams, and
verify the 1 km guard covers it. This addresses rasterization only; it cannot
repair an island missing from the underlying land source. Use spherical distance
or locally bounded projections, never a fixed-degree buffer. Include buffer,
nearest-shore ownership and polygon boundaries in refinement; if no safe coarse
certificate exists, evaluate all fine centres of the affected block.

Before choosing the production band, run this **2×2 ablation** with exactly the
same frozen settlement coordinates and city/country labelling:

| Mask | Strict centre eligibility | Centre eligibility plus the same 1 km band |
| --- | --- | --- |
| Current Natural Earth land OR country mask | A: reproduce current misses | B: quantify rule change on the old outline |
| OSM land mask | C: quantify outline replacement alone | D: proposed combined fix |

For every original miss retain its point `p`, H3 centre `c`, displacement,
`p/c` containment in each mask, true-shore distance and A/B/C/D results. Classify
old-mask `p inside, c outside` as centre-rule loss; `p outside old, p inside new`
as outline loss; retain both/interactions and suspected bad-coordinate cases.
Report `B−A`, `C−A`, `D−C`, `D−B`, overlap of rescued IDs, remaining IDs and
counts by country/population. Repeat against Natural Earth land alone to expose
the current country-union effect. Check all misses, not just the 600-point sample.
Use test bands **0, 0.5, 1, 1.5 and 5 km (T experimental values)** to show the
coverage/false-ocean tradeoff; 5 km is diagnostic, not the recommended release.

### Country and territory precedence

Define `country` as an **ISO-coded country or separately coded territory**, not
necessarily a sovereign state. Preserve sovereign-parent information only in
build provenance. Prefer the most specific accepted coded territory over its
sovereign parent: GF/RE/GP/MQ/YT, HK, and SJ must not collapse to FR/CN/NO.
Display SJ as **Svalbard and Jan Mayen**, not as a claim that Svalbard is sovereign.
Recommend **XK / Kosovo**, explicitly marked as a user-assigned code, not an
official ISO assignment. Never invent an ISO code from a name or reuse a missing
code marker.

Maintain `territory-policy` records keyed by canonical country code, source IDs,
source-code aliases, sovereign parent, accepted geometry IDs, precedence and
perspective. Resolve any Overture FR/CN/NO-labelled subordinate polygons to their
separately coded territories through that mapping. GeoNames codes help identity
matching, not polygon boundary reconstruction. If an Overture country/dependency
geometry is missing, a reviewed gbOpen ADM0 is the next candidate. Its outline is
still not the land mask. SJM/HKG are absent from the probed gbOpen ADM0 inventory,
so their Overture coverage is a mandatory preflight gate, not an assumed fallback.

Select one documented Overture default hierarchy/perspective, with reviewed
territory/dispute overrides. Reject incompatible overlapping claims before cell
labelling; do not choose the lexically first political claimant. Once the policy
has selected equivalent geometries, closed-boundary numerical ties use stable ID.
An unresolved named territory blocks release of that country's coverage rather
than inheriting the sovereign silently. The full HK/SJ/French-territory geometry
inventory was not probed in this planning task.

### State means a chosen administrative concept per country

Create a reviewed `admin-policy` table with country, semantic level, selected
Overture IDs/subtypes/levels, fallback gbOpen level, effective date and rationale.
The default is the top meaningful subdivision below the chosen country/territory;
the map is completed and audited for every supported country. Do not simply
choose the smallest containing polygon or `admin_level = 1` everywhere.

| Country/category | Proposed state output | Selection / fallback policy |
| --- | --- | --- |
| US, CA, AU, BR, IN | State/province/territory, including federal districts | Overture semantic region, matched to subdivision IDs; reviewed gbOpen ADM1 fallback |
| GB | England, Scotland, Wales or Northern Ireland | Use the measured gbOpen GBR ADM1 constituent-country layer until Overture is verified equivalent; Westminster is not a state |
| JP | Prefecture, including Tokyo | Overture region with prefecture identity; no promotion of a city ward to state |
| FR metropolitan | Région | Overture region; reviewed gbOpen ADM1 where needed |
| GF, RE, GP, MQ, YT | `None` if no distinct principal subdivision under this policy | Do not repeat the territory name as its state or inherit a metropolitan French region |
| CN excluding separately coded territories | Province, autonomous region or provincial-level municipality | Explicit region crosswalk; HK/MO handled as territories |
| ID | Province | Prefer current Overture; do not overwrite with the measured 2017 gbOpen layer |
| PH | Province; independent city where it is province-equivalent | Map the actual province level in Overture; gbOpen ADM2 candidate after inspection, not its measured ADM1 regions; NCR and independent cities need explicit policy entries |
| SG, MC, HK, MO | `None` | Do not expose planning regions/wards/districts as states; use the city-state or city-territory convention |
| XK | District, if supported by the selected current hierarchy | Do not assume the gbOpen ADM1 municipalities have the intended state meaning |

The mapping changes selection, not official administrative reality. Version
exceptions and verify source membership/coverage. A fallback is a **whole selected
administrative layer per country**, or a specifically bounded missing area with
its own provenance, not arbitrary per-cell mixing of old/new state borders.
Missing state is allowed where no meaningful layer exists, never a reason to
remove a land row. Resolve names via entity IDs and code crosswalks, not fuzzy
name joins alone.

### City means containing settlement, then a nearby settlement

Recommended semantics are the named municipal/settlement locality containing the
centre (or the coastal projection), with explicit conventions for familiar cities.
A metropolitan commuting area is not automatically a city. Overture locality
polygons outrank nearer GeoNames points *inside that same containing locality*;
this is what prevents an ordinary `PPL` neighbourhood from stealing its name.

Select `division_area` locality candidates joined to `division` hierarchy and
class. Exclude neighbourhood, macrohood, microhood and borough answers; roll a
sub-city entity up to a verified city ancestor. Subtype alone is insufficient:
counties, enormous rural municipalities and nested villages require the country
locality policy. For nested real settlements prefer the most specific settlement
with its own identity, except entities explicitly classified as sub-city areas.
Unrelated overlapping localities go to a review ledger; equivalent ties use
containment, policy rank, then stable ID. Do not sort only by area or population.

For Singapore and Monaco, define the country land footprint as the city's
footprint and emit Singapore/Monaco, with no state. Apply the analogous explicit
city-territory convention to Hong Kong and Macao, using their own coded territory
footprints rather than districts as the returned city. For Tokyo, emit **Tokyo** over
the union of its special wards, while retaining separate municipalities elsewhere
in Tokyo Prefecture. Obtain the ward geometries/IDs from the selected Overture
snapshot; do not label all of Tokyo Prefecture or a radius around a point Tokyo.
The distinction is supported by Tokyo's official
[municipality description](https://www.english.metro.tokyo.lg.jp/municipalities-within-tokyo).
Similarly roll NYC boroughs to New York City, and London boroughs to London where
the hierarchy supports that urban identity. These are explicit area/entity rules,
not exceptions keyed to the regression coordinates or returned string.

When no accepted locality contains the centre:

- Use GeoNames feature class P with the existing current-settlement allowlist in
  [DESIGN.md](DESIGN.md), without a population threshold; retain unknown/zero
  population. Continue excluding `PPLX`, historical, abandoned and destroyed
  places. Add Overture locality points only after excluding sub-city classes.
- Match duplicates by shared source identifier/Wikidata where present, followed
  by compatible country/admin, names and distance. Keep ambiguous matches separate
  and audited; never merge solely by normalized name or proximity. A matched
  Overture sub-city identity can suppress a mislabeled GeoNames `PPL` candidate.
- Choose the nearest eligible point **within the selected country/territory**
  and within the existing **50 km** inclusive cutoff. This deliberately replaces
  the old cross-border nearest rule. Do not hard-filter state, which can incorrectly
  remove the nearest real town at a state border. Stable canonical ID breaks exact
  distance ties; population does not let a distant large city swallow a village.
- If neither polygon nor eligible nearby point exists, return `city=None` while
  retaining country/state and row presence. Do not manufacture a city from a
  county, hotel, POI or an unbounded nearest search. Country-unknown land gets no
  unconstrained cross-border point fallback.

### Names and conflicts

Store one display language in the shipped table: **English where explicitly
available, local Unicode otherwise**. Within an entity prefer a current common
English Overture name; then a confidently matched GeoNames preferred English
alternate; then another current non-colloquial English name. An official English
variant is a fallback, not a reason to replace a familiar short common name with
“Municipality of …”. If no English name exists use Overture primary, GeoNames
Unicode name, or gbOpen shapeName for the selected entity. Use GeoNames asciiname
only if the usable Unicode name is missing; transliteration is not translation.

Discard historic/time-expired and link/airport-code aliases from display-name
selection. Normalize Unicode NFC and whitespace, preserve accents and script,
and use a stable ID tie-break for remaining equivalent alternates. Country display
names and approved familiar city names live in the versioned identity policy,
with links to source entities. Keep language choice and source per field in build
provenance; aliases need not all ship. Report English-name coverage rather than
claiming all names are English. No runtime language selector is proposed.

Precedence is **role-specific**: OSM decides physical coverage; accepted country
policy decides jurisdiction; the country admin map chooses the entire state
layer; locality containment decides city before points; matched name provenance
decides spelling. A detailed coastline never overrules a country code, and a
GeoNames point never shifts a political boundary. Retain every conflict and
override with source IDs, reason, reviewer and policy hash.

## Ordered, resumable pipeline

### Common checkpoint and resource contract

This is new builder work: the current immutable-output build does **not** already
provide these per-unit checkpoints. Use a local SQLite ledger in WAL mode and
content-addressed files. Each completed unit records:

```text
stage, unit_id, input_sha256s, source_release/ETag, policy_hash,
builder_version, schema_hash, output_paths, output_sizes, output_sha256s,
row/feature counts, extent, verification_status, completion_time
```

Write each output to a sibling `.part`, flush/fsync, validate, atomically rename,
then transactionally mark the unit complete. On restart verify completed outputs
before skipping them. Adopt a fully verified orphan output or remove only its
temporary unit; never append duplicate results. A changed source/policy creates a
new build ID and invalidates dependent units, leaving the old published table
usable. Limit retries with exponential backoff/jitter and persist the pending
unit when offline; do not mark network failures as empty results.

**T:** one geometry worker; at most two download streams; DuckDB memory limit
2 GB and at most two threads; spill directory capped at 6 GB; process-tree RSS
soft stop at 5 GB. Arrow batches are bounded by bytes as well as row count, with
an initial 32 MB batch target. A huge individual geometry is split/streamed in
an isolated unit; if it cannot fit, stop that unit and reassess, not swap the
machine indefinitely. Count macOS/NumPy/GEOS memory outside DuckDB's memory limit.
No global GeoDataFrame, geometry union, fine-cell label array or world STRtree.

| Stage, inputs → outputs | E: incremental disk / peak total workspace | E: process-tree RSS; duration | Unit, checkpoint and exact resume behavior | Verification before completion |
| --- | --- | --- | --- | --- |
| 0. Freeze baseline and source inventory → release manifest, policies, download worklist | <0.1 GB / <1 GB | <0.5 GB; 10–30 min machine time, policy review separately | One listing page/API country-level record; save URL, redirect, size, ETag, date and raw response hash. Resume missing pages/records; atomically freeze the worklist. | Expected object counts, required territories, schema fingerprints, licence allowlist; preserve original settlement IDs/coordinates and table hash. |
| 1. Acquire chosen archives and Parquet → immutable raw cache | 6.7–7.7 GB / 8–9 GB | <0.5 GB; 1–5 h at effective 5–20 Mbit/s, 2–8 h allowing interruptions | One 8 MiB HTTP range; ledger stores object identity, byte interval, chunk hash and completed bitmap. Resume missing ranges only, then verify whole object. | HTTP 206, exact Content-Range/length, unchanged ETag; total size and SHA256; ZIP CRC; Parquet footer/row count. |
| 2. Extract/parse GeoNames → filtered points, alternate-name index, code maps | ≤4.5 GB including 2.575 GB raw TSV / 12–14 GB | 0.5–1.5 GB; 0.5–2 h | Extraction unit is one ZIP member; incomplete deflate member is re-inflated from the verified local ZIP, not fetched again. Parsing unit is 64 MiB of TSV ending at a complete line; record start/end byte offsets, rows and output hash. Resume via raw TSV seek. | CRC for each extracted member; UTF-8/schema checks; unique IDs; valid coordinates; included/excluded feature-code counts; alias foreign keys and retained-name counts. |
| 3. Normalize Overture and selected gbOpen → role-filtered polygon/point partitions plus entity graph | 3–6 GB outputs; ≤3 GB temporary / 18–24 GB | 1–3 GB; 1–4 h | Overture unit: object + row group, subdivided into byte-bounded batches when necessary. gbOpen unit: country/level file and feature batch. Record input row/feature range and output tile parts. Resume only unfinished batches using local cached input. | Area→division joins including off-region parents; flag combinations; country codes/perspectives; per-subtype counts; invalid/empty geometry ledger; source licences. Do not discard rejected geometry silently. |
| 4. Prepare land and coastal distance data → indexed land tiles/true shore segments | 1.343 GB expanded SHP plus 2–4 GB tiled data; ≤2 GB temporary / 23–30 GB | 1–3 GB; 1–4 h | ZIP member, then bounded SHP record range (initially ≤1,000 features, also byte-capped). Checkpoint SHX record index, tile parts and hashes. Resume SHP directly; completed tiles need not be regenerated. | WGS84 bounds, valid rings, pole/seam/island samples, overlapping split-edge cancellation, inland water convention; no artificial tile/split boundary counted as coast. |
| 5. Reconcile entities, policies and local indexes → canonical tiled reference pack | 1–3 GB net outputs, temporary work within 6 GB spill cap / 28–35 GB | 2–4 GB; 1–4 h | One country policy audit, then one spatial tile + halo + policy version. Record canonical entity IDs, match/conflict counts and source tile hashes. Resume unfinished tile; policy changes invalidate affected tiles and dependent H3 blocks. | Parent graph cycle/orphan checks; territory coverage ledger; state-level membership; ambiguous match ledger; label oracle agrees on overlapping tile interiors. |
| 6. Label and compress H3 → completed block files | 0.3–1 GB expected output, ≤2 GB including temporary blocks / ≤35 GB | 2–5 GB; 3–10 h | One resolution-3 subtree, at most 16,807 res-8 descendants as in current design. Record root ID, reference tile hashes, row/dictionary counts and block checksum. Retry only unfinished root. No world flat table. | Scalar/vector oracle equality on pilot; disjoint ancestors; collapse only equal complete child labels; certify against new polygon/coastal/nearest-country policy, otherwise refine. |
| 7. Assemble, verify and package → immutable combined table or packaging shards | ≤2 GB including old/new output and archives / ≤35 GB | 0.5–2 GB; 0.5–2 h | One H3 base cell for assembly, one fixture/test partition for validation, one package for compression. Record sorted block list, offsets, checksum and test results. Resume missing units; final manifest/publish rename only after all pass. | All acceptance gates below, full checksums/format verifier, actual built wheel size, all 122 base-cell coverage entries, reproducibility and forced-interruption tests. |

The ranges are budgets, not additive peak allocations. **E, simultaneous peak
ledger:** raw inputs 8 GB + extracted TSV/SHP 4 GB + normalized/indexed references
10 GB + spill/active conversion 6 GB + block/final/package artifacts 3 GB + prior
table/logs/tools 1 GB = **32 GB**. Allow 3 GB variation to reach 35 GB. **T:** refuse
new work before workspace usage exceeds 45 GB or system free space falls below
20 GB, whichever is earlier. This leaves ample room within the stipulated 70 GB.
Delete expendable temporary conversions only after their verified successors
exist; retain pinned raw sources and the old published table. Do not accumulate
multiple world builds or full duplicated geometry stores.

Use spatial tiles chosen to stay inside those limits, initially a regular grid
with finer splits for complex coasts. Index nearest-place candidates with a
**50 km halo plus the full descendant envelope**; index the coastal rule with
its **1 km band plus that envelope**. Include all containing admin/locality
polygons even if their representative points are outside. Restrict ownership to
tile interiors to avoid duplicate outputs; keep full source edges for distance
tests. Split polar/seam tiles explicitly. Identical IDs and labels must survive
different tile sizes and processing order.

#### Download recovery details

An HTTP `Accept-Ranges` header alone is not enough: first test a small range.
Use `If-Match`/`If-Range` with the pinned validator; reject a 200 response to a
nonzero range and never append it to a partial object. If the validator changed,
keep the previous snapshot intact and either obtain its archived bytes or start
a new source snapshot. Mutable daily GeoNames/OSM URLs make this an actual risk
on a slow connection. Publisher checksums, when supplied, take precedence;
otherwise exact remote size plus ZIP CRC/Parquet integrity and our final SHA256
provide transport/cache verification, not publisher authentication. S3 multipart
ETags are **not MD5 checksums**; the listing's composite checksum declarations
are not automatically full-object SHA256 values either.

For a regional Parquet range-cache unit record object URL/ETag, footer hash, row
group, selected column paths, every byte interval and its hash, then the exported
Parquet hash/count. Persist successful intervals before executing the next read;
on interruption re-read only missing intervals. A sparse local backing file must
never expose an unfetched hole as valid data. Use PyArrow's row-group reader or a
complete verified local extract as DuckDB input. A bare remote `COPY (SELECT …)`
can restart its current query; it is not a durable row-group checkpoint by itself.

gbOpen URLs must resolve to a full commit SHA; HEAD followed by a tiny 206 test
must confirm range behavior for each artifact route. If range is unavailable,
use a range-capable GitHub media endpoint or an immutable archived mirror. **No
dataset artifact may enter the build worklist without a demonstrated resumable
route.** Small metadata responses resume at the last completed listing page or
API record. Source inventories, not a floating `current` URL, determine the
resumed run's files.

## Storage and cloud alternatives

**Choose all-local acquisition and processing for the first build.** It has no
cloud charges, keeps the build usable offline after acquisition, and its measured
inputs fit comfortably. Buying GCS does not shorten the incoming download or make
repeated remote queries reliable; uploading every intermediate would add traffic
over the same shaky connection.

**M, read-only environment check:** `gcloud` is installed at
`/opt/homebrew/bin/gcloud`, an active account is configured, and a default project
is set. Authentication listing does not verify token validity, storage/VM IAM,
quota, billing or ability to create resources. No bucket/VM was created and no
cloud write or billable job was performed.

| Alternative | Recommendation and rough cost |
| --- | --- |
| Local compute + GCS durable snapshots | Optional after the local pilot if the owner wants machine-loss recovery. Upload immutable sources, policy manifest, completed base-cell bundles and final artifacts; do not mirror spill files. **E:** 10–20 GiB stored costs about **$0.20–$0.40/month**, plus well under $1 of operations at this scale if bundling. A complete 20 GiB restore to India is about **$2.40** egress before allowances. Use resumable uploads with persisted session URI/offset, CRC32C/SHA256, generation preconditions and a final completion marker. |
| VM adjacent to Overture | Conditional fallback if sustained local delivery is below **2 Mbit/s (T)**, or memory/geometry/time gates fail. Prefer an AWS VM in **us-west-2** or Azure VM in **westus2**, where Overture resides. **E:** Linux 4 vCPU/16 GiB, 60 GB scratch, 12–36 h at a budgeting rate **$0.15–$0.25/h**, plus disk/egress: approximately **$3–$12 per build**, allow **$20** for retries. This is a budget estimate, not a quoted instance SKU. Only the estimated 90–350 MB final archive plus reports crosses the home link. GCS can hold durable artifacts if desired. |
| GCE VM + GCS | Viable if existing GCP access matters more than source proximity, but GCS/GCE is **not next to the public Overture bucket** in the same provider. Budget **E: $5–$20/run**, including inter-cloud transfer contingency, and verify current regional pricing before provision. Same staged local-disk processing inside the VM; GCS is object storage, not a mmap/spill filesystem. |

**L, cost basis:** GCS Standard regional storage is about $0.020/GiB-month from
the published hourly rate; ingress is free and initial internet egress to Asia
excluding China is $0.12/GiB. See
[GCS pricing](https://cloud.google.com/storage/pricing). AWS documents free direct
S3↔EC2 transfer in the same region in its
[data-transfer pricing](https://aws.amazon.com/ec2/pricing/on-demand-backup/);
[EBS guidance](https://docs.aws.amazon.com/prescriptive-guidance/latest/optimize-costs-microsoft-workloads/ebs-migrate-gp2-gp3.html)
uses $0.08/GiB-month for baseline gp3. VM hourly amounts above are estimates;
[GCE pricing](https://cloud.google.com/products/compute/pricing) is region/type
dependent. Costs exclude tax and assume immediate VM/disk teardown, no NAT
gateway, and explicit artifact retention/lifecycle. No spot/preemptible capacity
is assumed. A cloud run must use the same checkpoints, budget cap and stop policy.

## Licence and distribution commitment

Treat this combined H3 lookup database as a **Derivative Database under ODbL
1.0**, not as a licence-free collection of names or a rendered map. Publicly ship
the table under ODbL, preserve notices, and offer recipients the machine-readable
database with the required licence/access rights. Retain reproducible source and
transformation manifests; review whether offering the full derived table or the
alterations is the appropriate fulfilment for the release. Share-alike applies
to the adapted database, not automatically the independent Python library.
**L:** [ODbL text, particularly sections 4.2–4.6](https://opendatacommons.org/licenses/odbl/1-0/)
and [summary](https://opendatacommons.org/licenses/odbl/summary/).

Ship `DATA_LICENSES.txt`, machine-readable per-source licence/provenance, snapshot
dates, transformation descriptions and links alongside **every** data pack:

- © OpenStreetMap contributors; ODbL link; identify Overture Maps Foundation and
  the coastline service.
- GeoNames, CC BY 4.0; identify filtering, naming changes and source date.
- geoBoundaries plus the original layer provider/licence; preserve any required
  contributor notices from the pinned Overture release, including applicable
  Esri/LINZ notices.
- During the coastline-only milestone, retain Natural Earth's public-domain
  attribution while its administrative labels remain; remove it only when no
  derived labels from that source remain.

The recommendation is a release-licensing commitment, not an assertion that
every gbOpen entry is compatible. Unresolved CC BY-SA/ambiguous entries are
excluded pending resolution. If the owner requires an entirely permissive table,
the OSM/Overture recommendation must change; even a gbOpen-only alternative needs
its own per-layer OSM/ODbL audit. Attribution does not substitute for share-alike.

## Size forecast and early measurement gate

More detailed coast/state/locality edges force refinement; millions of small
settlements create many more nearest-place regions. Containing city polygons can
also *reduce* fragmentation inside cities. Neither coastline vertex count nor
gazetteer count scales the final compressed table linearly.

**E:** use **80–200 million stored rows**, approximately **250–800 MB installed**
including dictionaries/names, and **90–350 MB ZIP/wheel** as the initial planning
range. This is a scenario estimate, not a measured world result. The existing
format uses 1/2-byte local values, sparse/bitmap keys, shared label dictionaries
and interned city strings; dense blocks and repeated municipal labels compress
differently. **E:** names alone may grow to **30–100 MB** after excluding aliases
from shipment. Do not promise the old 21 MB archive size or a sub-100 MB release.

Before the world build, build **the Philippines as the first sizing region**
(many coastlines and islands, one of the observed worst countries). Start with a
Metro Manila/coastal subset for rapid feedback, then the full country with all
required parents and distance halos. **E:** 1–3 h machine time after local inputs;
full calibration/analysis takes part of a milestone day. Compare old sources,
coastline-only, new admin/locality polygons, and allCountries point fallback using
identical roots. Measure HTTP bytes, raw/normalized/spill disk, peak process-tree
RSS, labelled centres, stored rows per depth, local dictionary widths, names,
installed bytes and the actual archive/wheel bytes.

Add smaller strata from Norway (coasts), Java (dense villages), Tokyo/NYC (urban
containment), and an inland sparsely settled region. Extrapolate separately by
coastal blocks, admin/locality boundaries and candidate-settlement density, using
counts available from normalized references; weight by world block counts and
reserve **2× uncertainty (T)** on unrepresented strata. Philippines alone is not
a defensible world average. Stop before the world job if the disk/RSS caps fail,
or change packaging before the forecast's upper bound crosses **80 MB per wheel
(T safety margin)**.

**L:** PyPI's current default is **100 MB per uploaded file**, not per internal
table member ([PyPI limits](https://docs.pypi.org/project-management/storage-limits/)).
Splitting files *inside one oversized wheel* does not solve this.

Fallback: package the combined-table blocks by **H3 base cell (122 base cells)**,
grouping small base cells into data-only distributions below the safety margin.
Use separate downloadable archives or separate data distributions; never upload
multiple invalid variants of the same wheel filename. If one base cell exceeds
the limit, subdivide its packaging by resolution-1/3 roots. Pin every shard's
snapshot, hash, block range and name-pool version in one global manifest.

Keep the logical single table and lookup unchanged: an explicit offline data
installation/assembly step concatenates verified blocks in order, rebases the
directory offsets, and installs one mmap pack atomically. Shared dictionaries
and the name pool are shipped once (or split into verified byte-range artifacts
and assembled); do not duplicate a huge global name pool in each shard. There is
no runtime network lookup. Test monolithic versus assembled-shard byte/answer
equivalence and reject mixed snapshots or missing base cells. A PyPI size-limit
increase can be requested, but the release must not depend on its approval.
Also check existing uint32 offsets, 16-bit admin indices and name-byte offsets
before assembly; fail explicitly if any format limit is exceeded.

## Acceptance gates

All figures here are **T: release targets**, not claimed results. Keep a frozen
baseline test set separate from the new allCountries catalogue; new source
additions/removals must not alter the denominator of the original audit.

| Check | Target and interpretation |
| --- | --- |
| Original settlement self-lookup | Final no-row rate **≤0.05%: at most 80 / 161,540**; at least **99.95%** have country code after the chosen territory policy. List every remaining miss and every changed country code; no blanket exception exclusions. |
| Large cities | **560/560** million-plus settlements have row, nonempty city and expected country/territory code. Recover and include the ninth original miss. |
| Coastline first milestone | Reduce original no-row rate to **≤0.1%: at most 161** and remove no-row failures for all named coastal points. Report country/name defects separately while old administrative sources remain. |
| Worst-country coverage | PH, ID, NO, GR, IT each **≤0.1%** no-row on the frozen catalogue, with raw counts, population strata and coast-distance strata. No country-wide regression hidden by the world percentage. |
| Expanded gazetteer | At least **99.9% row presence** for valid current settlement records, including the zero/unknown population stratum; report unknown country/state/city separately. Newly identified sub-city records may legitimately return a parent city, not their own name. |
| City identity | For a reviewed stratified sample of **1,000** settlement/locality points, **≥98%** accepted municipal/settlement identity; no neighbourhood answers in the named major-city regressions. Same spelling is not a sufficient identity test. |
| False land/ocean behavior | Deep-ocean controls beyond the band always return no row. Test centres just inside/outside the 1 km threshold, narrow straits and borders; do not count intended coastal-band answers as false positives. Every newly eligible cell outside physical land must satisfy the rule. |
| Correctness of compression | Exhaustive fine-centre equality to the scalar source oracle in the regional fixture, plus complete adversarial coastal/pentagon/seam blocks; no sampling-only proof that collapsing is sound. Random world checks are supplementary. |
| Recovery and reproducibility | Kill/resume at range download, TSV parse, geometry tile, H3 block and final assembly; corrupt a completed unit; detect changed ETag/policy; resume to identical payload hashes without rereading completed remote units. Different worker/order/tile schedules give identical labels. |
| Resources and artifacts | RSS ≤5 GB, normal disk ≤35 GB and hard caps respected; per-upload artifact <80 MB or selected external distribution; full format verifier and checksums pass. |

Required regression coordinates below are **proposed fixtures**, not measurements
of the new table. Also use each named settlement's *exact frozen GeoNames point*,
which can differ from these representative coordinates. Pin IDs and expected
canonical entities so a spelling update is not mistaken for a boundary failure.

| Location, latitude / longitude | Required final answer |
| --- | --- |
| Lagos, 6.4551 / 3.3841 | Lagos; Lagos state; Nigeria / NG; present row |
| Hong Kong, 22.3193 / 114.1694 | Hong Kong city and territory / HK; state absent under city-territory policy |
| Monaco, 43.7384 / 7.4246 | Monaco city; state absent; Monaco / MC |
| Singapore, 1.3521 / 103.8198 and 1.2903 / 103.8519 | Singapore city; state absent; SG; neither Ang Mo Kio New Town nor a planning region as city/state |
| Tokyo, 35.6895 / 139.6917 and 35.6762 / 139.6503 | Tokyo city; Tokyo prefecture; Japan / JP; not Asagaya-minami |
| Lower Manhattan, 40.7128 / -74.0060 | New York City; New York; United States / US; not a borough/neighbourhood |
| Central London, 51.5074 / -0.1278 | London; England; United Kingdom / GB; state is not Westminster |
| Pristina, 42.6629 / 21.1655 | Pristina; Kosovo / XK; explicit user-assigned code metadata |
| Cayenne, 4.9333 / -52.3333 | Cayenne; French Guiana / GF |
| Saint-Denis, -20.8823 / 55.4504 | Saint-Denis; Réunion / RE |
| Basse-Terre, 15.9985 / -61.7255 | Basse-Terre; Guadeloupe / GP |
| Fort-de-France, 14.6161 / -61.0588 | Fort-de-France; Martinique / MQ |
| Mamoudzou, -12.7806 / 45.2278 | Mamoudzou; Mayotte / YT |
| Longyearbyen, 78.2232 / 15.6469 | Longyearbyen; Svalbard and Jan Mayen / SJ |
| Xiamen, Shantou, Guayaquil, Monrovia, Belém, Mombasa | At their frozen catalogue points: present, correct city, respectively CN/CN/EC/LR/BR/KE |

For each coastal fixture test the point, its cell centre and nearby land/offshore
centres. State absence for the French territories follows the chosen admin
policy. For any coordinate too close to a real boundary to share the expected
centre answer, report the geometric conflict and retain a nearby interior
fixture; do not conceal the original result or special-case its coordinate.

**Independent-source check:** reserve the US Census **2025 National Places
Gazetteer** exclusively for validation, never as a builder input or naming
crosswalk. **L:** the official listing reports approximately **1.2 MB** for its
[place archive](https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/),
with [product documentation](https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.2025.html).
Acquire it using the same range/size/checksum contract. Compare its internal
points, state codes and names for all incorporated places, stratifying coastal,
small/rural and urban locations. **T:** ≥99.9% row/country/state agreement and
≥98% city-identity agreement on the reviewed unambiguous incorporated subset.
Report Census-designated places separately because their statistical boundaries
may differ from this municipal-city definition. Publish all disagreements.

This is an external-source validation, not proof of statistical independence:
OSM or GeoNames may share government lineage. Supplement it with **100 (T)**
manually reviewed non-US coastal/island/admin points from official local sources,
keeping them out of development tuning. Record URLs, dates, coordinates and
adjudication. Do not claim a world accuracy percentage from a US-only holdout or
use geoBoundaries/OSM/Overture to “independently” validate themselves.

## Milestones and risks

Engineer effort below is **E**, sequential and includes ordinary fixes/review.
Automated run durations are in the stage table; elapsed outage time is additional.

| Milestone | Deliverable and exit condition | Effort |
| --- | --- | --- |
| 1. Close coastal no-row gaps | Freeze baseline; acquire only split OSM land; implement its bounded tiling/checkpoint path, the centre coastal rule and A/B/C/D audit. Keep existing GeoNames city and Natural Earth administrative policies for this milestone. Produce an actual candidate table and meet the coastline target; expose remaining administrative errors rather than expanding the offshore radius. | 2–3 days; E: 2–6 h first automated run |
| 2. Resolve countries and states | Pin Overture; audit named territories, perspective and country/state mappings; use gbOpen UK layer and other individually justified fallbacks. Emit territory codes and review every default-country map entry. | 2–4 days |
| 3. Resolve cities and names | Import allCountries/alternateNames; locality containment, hierarchy roll-ups, city-state/Tokyo conventions, deduplication and country-constrained fallback. Measure naming coverage and unresolved identities. | 3–5 days |
| 4. Measure before world scale | Full Philippines pilot and smaller strata, format/transfer/RSS measurements, choose shard packaging if needed. Finish interruption/reproducibility tests and confirm world budget. | 1–2 days |
| 5. World candidate and release review | Resumable world build, frozen settlement audit, independent holdout, regression table, licence bundle and actual distribution artifacts. Release only after gates and owner decisions below. | 2–4 days; E: 12–36 h first complete automated run |

Milestone 1 changes coverage only; it does not claim correct Monaco/HK/overseas
country labels or municipal city names until later milestones. If its coverage
target fails, use the ablation to identify missing land/bad coordinates/algorithm
errors, not coordinate exceptions. Its first OSM-derived table already carries
the ODbL consequence.

The risks most likely to exceed **E: 10–18 engineer-days** are:

- **Administrative semantics and stale/missing locality polygons:** a global
  per-country audit is human work; sparse locality coverage may leave “nearest
  settlement” answers. Budget another **E: 3–7 days** if many countries need
  individually sourced boundaries or metropolitan conventions.
- **Complex polygons / fragmentation:** a few coastal geometries can dominate
  memory, tiling duplication and fine-centre work. Early gates may force smaller
  tiles, another **E: 1–3 days** of optimization, or the cloud fallback. Do not
  infer world timing from the old 11.5-minute table build.
- **Daily snapshot replacement during interrupted downloads:** ETags prevent
  mixed files but cannot resurrect old bytes. Acquire one large mutable archive
  at a time, preserve verified snapshots, and optionally back them up to GCS.
- **Source disagreement/licence metadata:** contradictory gbOpen licensing or
  disputed-country coverage can block individual fallbacks. Prefer vetted
  Overture coverage where available; unresolved required territories block release.
- **Size and format limits:** allCountries may exceed the forecast or create too
  many distinct labels in a block. Measure dictionaries/offsets early and retain
  the base-cell packaging route; do not respond by dropping small settlements.

## Decisions for the owner

Recommended defaults are explicit so implementation can start once adopted:

1. **Accept ODbL for the shipped data**, with independent software licensing and
   an accessible machine-readable derivative database. Otherwise re-plan sources.
2. **Adopt territory-style country output** (GF/RE/GP/MQ/YT/HK/SJ) and **XK for
   Kosovo**, with a documented default political perspective and dispute overrides.
3. **Adopt English-first Unicode names and the proposed city/state semantics**:
   England for London state; prefectures for Japan; province-equivalent state for
   PH; Singapore/Monaco city-state behavior; Tokyo over its special wards; bounded
   same-country nearest fallback and honest `None` where unsupported.
4. **Accept the 1 km centre-based coastal tolerance**, subject to the radius and
   false-ocean tests, including terrestrial answers for some genuinely offshore
   coordinates in those cells.
5. **Use local processing initially**; decide whether to pay for optional GCS
   backups and adopt the suggested **$20/run cloud fallback budget** only if the
   local pilot fails its gates. This plan does not authorize provisioning.
6. **Accept multiple data artifacts if necessary** and an explicit offline
   assembly/install step, or choose external full-pack distribution. Do not require
   all expanded data in one sub-100 MB wheel without a measurement.
7. **Adopt the acceptance targets and update policy**: recommend quarterly shipped
   snapshots initially, using monthly Overture and a pinned contemporary daily
   GeoNames/OSM snapshot, with urgent reviewed correction releases. “Complete”
   means measured coverage and documented residuals, not a guarantee that every
   real-world settlement has an authoritative city polygon.

Not verified here: a new world table's accuracy, full filtered GeoNames counts,
global normalized geometry size, full-country pilot timing, all named territory
geometries, complete state crosswalks, global locality coverage, end-to-end
DuckDB transfer/resume behavior, or cloud billing/IAM. Those are explicit milestone
gates. Successful small probes do not constitute a completed pipeline or passing
acceptance suite.
