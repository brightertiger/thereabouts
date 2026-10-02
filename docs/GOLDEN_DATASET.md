# Golden dataset (schema `golden-1`)

The v1 world publication is complete. All measurements below are from the final
stored-cell [quality report](../data/golden/quality.json). The v0 failure audit
and rule-change evidence are in [GOLDEN_V1.md](GOLDEN_V1.md).

The golden stage consumes committed reconciliation country checkpoints and acquired
lookup manifests. It writes only beneath the supplied data directory. The H3
reference key is **resolution 8**. A row's original coordinates are retained, but
its place assignment is the answer at its H3 cell's centre. These can differ near
boundaries. Countries and cities inherit the reconciliation policy, without new
name, boundary, or nearest-city overrides.

## Run and resume

```sh
GOLDEN_DATA=/Users/ujjwal/Downloads/solo/PyOfflineGeocoder/data
uv run --no-sync python -m build_data.golden static --data-dir "$GOLDEN_DATA"
uv run --no-sync python -m build_data.golden pilot --countries BE NL LU CA --workers 2 --data-dir "$GOLDEN_DATA"
uv run --no-sync python -m build_data.golden run --workers 2 --watch --data-dir "$GOLDEN_DATA"
uv run --no-sync python -m build_data.golden status --data-dir "$GOLDEN_DATA"
```

`pilot` defaults to blocks whose conservative dependencies include BE, NL, LU or
AU. The example command selects Benelux and Canada. It exhaustively compares all resolution-8 centres with
direct vector labelling,
checks every ancestor lookup, and compares 16 evenly spaced centres in each block
with the independent scalar reconciliation oracle. The synthetic test region
additionally compares **every** fine centre against that independent scalar oracle.
`--verify-blocks` enables the same exhaustive checks for another run.

`plan` caches the actual finest-centre envelope of every resolution-3 root.
`--countries CC ...` selects country-dependent blocks; `--limit-blocks N` bounds a
run. `lookups` refreshes joins and checks from existing committed cells without
building more cells. `--watch` refreshes country availability after each complete
pass, sleeping 300 seconds by default. A single golden lock prevents overlapping
controllers. One or two worker processes own different blocks; two blocks at most
are in flight. Reconciliation's lock, code and working files are untouched.

The completed marker is `work/golden/run.json` with `completed: true`, together
with a committed `golden/manifest.json` also having `completed: true`. Individual
country and cell checkpoints are useful before then. `status` does not build or
hash tables. The same command safely resumes verified units, rebuilds corrupt
outputs, and fills pending lookup joins when more cells exist. An interrupted
Parquet write cannot complete its ledger unit. Do not infer completion from a
process exiting, a log line, or the existence of a Parquet file.

The golden stage has an 8 GB logical disk cap for `golden/` plus `work/golden/`.
It preserves 13 GB free. For this run, acquisition/reconciliation was externally
configured with a 12 GB reserve; golden does not modify that setting. Temporary joins have a 512 MB memory limit and a 512 MB spill cap.
A resource guard stops new units; `--watch` reports `waiting for disk` and retries
after the polling interval. Other I/O failures remain visible failures. The stage
never deletes another stage's data. Source
raw custody is described in [DATA_PIPELINE.md](DATA_PIPELINE.md#raw-offload-and-restore).

## Layout and manifest

```text
golden/
  manifest.json                  # sole published table inventory and input hashes
  quality.json                   # counts, coverage, disagreements and checks
  DATA_LICENSES.md                # source attribution and licence summary draft
  DATASET_CARD.md                 # final v1 counts, limitations and intended use
  places/<CC>.parquet
  cells/<resolution-3-root>.parquet
  lookups/<spatial-kind>/joined.parquet
  lookups/<static-kind>/<source-partition>.parquet
work/golden/
  countries.json                 # expected countries and source component envelopes
  blocks.sqlite                  # reusable finest-centre envelopes; hashed dependencies
  run.json, pilot.json            # progress and pilot evidence
work/ledger.sqlite3               # shared golden.* checkpoints
```

The manifest records schema version, reference/block resolution, source policy,
reconciliation and golden builders, country/land hashes and each table's absolute path, kind,
row count, bytes and SHA256. Cell records also name their resolution-3 block.
The manifest and its companion reports are committed as `golden.manifest/current`.
Only use its listed files, never glob for a supposedly complete snapshot. Running
updates replace files atomically; readers needing a stable verified snapshot
should wait for the controller to finish and verify manifest checksums.

Empty ocean blocks have a zero-row Parquet and a checkpoint. This distinguishes
known ineligibility from a block awaiting reconciliation. Empty files contribute
to the 41,162 real H3 resolution-3 blocks, including pentagons. No logical pentagon
padding addresses are treated as real cells.

## Places

Canonical `place_id` is the reconciliation identity, never a name-derived ID.
Country identities are `country:<CC>`; other identities retain role and source.
District entities are retained as well as countries, states and cities, preserving
the reconciled catalogue. JSON fields are serialized UTF-8 JSON, not pickles.
Unknown values are null. A population of zero remains distinct from null.

| Column | Type | Meaning |
| --- | --- | --- |
| `place_id` | string | Stable canonical identity, unique in the complete catalogue |
| `role` | string | `country`, `state`, `city`, or retained `district` |
| `name` | string | Reconciliation's preferred display name |
| `name_en` | string? | Preferred name only when its naming provenance explicitly identifies English |
| `local_name` | string? | Source's local/default name; not an inferred translation |
| `country_code` | string | ISO alpha-2, plus source/user-assigned codes such as XK |
| `code` | string? | Country or subdivision code actually known to reconciliation |
| `code_status` | string? | Source/code status, including `user-assigned` for XK |
| `parent_id` | string? | Canonical parent, null for countries |
| `parent_method` | string? | Evidence for a parent assignment when recorded |
| `sovereign_id` | string | `country:<sovereign_code>`; can await that country in a partial snapshot |
| `sovereign_code`, `sovereign_name` | string? | Recorded sovereign, otherwise the country itself; unknown name remains null |
| `population` | int64? | Reconciled population |
| `geonames_id` | string? | Linked GeoNames source identity |
| `geonames_admin1` | string? | GeoNames source admin1 code, not an ISO subdivision inference |
| `feature_code` | string? | Retained GeoNames/source classification |
| `source_subtype`, `settlement_class`, `city_exclusion` | string? | Source role/class and recorded reason for retaining an administrative unit outside city selection |
| `overture_ids` | list<string> | Overture identities on the canonical entity |
| `wikidata_ids` | list<string> | Known Wikidata IDs from source evidence and retained GeoNames links |
| `source_ids` | JSON string | Full source/identity list |
| `provenance` | JSON string | Naming/source evidence, release, licences and upstream attributes |
| `name_provenance` | JSON string | Chosen naming source and explicit language evidence |
| `link` | JSON string | Reconciliation's identity-link method/evidence or JSON null |

No aliases are erased from source provenance. This table does not manufacture ISO
codes, coordinates or translations for canonical entities lacking them.

## Cells

| Column | Type | Meaning |
| --- | --- | --- |
| `h3` | string | Canonical lowercase H3 hexadecimal key |
| `h3_uint64` | uint64 | Same H3 key as an unsigned integer |
| `h3_resolution` | uint8 | Stored resolution, between 3 and 8 inclusive |
| `country_id`, `state_id`, `city_id` | string? | Foreign keys to `places.place_id` |
| `country_method`, `state_method` | string? | `area` when assigned; null when absent |
| `city_method` | string? | `area`, `nearest`, or null |
| `land_method` | string | `land` or `offshore` |

Each eligible r8 centre has exactly one stored ancestor; ineligible ocean has
none. Eligible but unresolved land has a row with null place IDs. Fields and
methods must all be equal to collapse a subtree. Compaction stays within r3
checkpoint roots; this trades a few extra rows for independent resumption.

The builder reuses the original hierarchy traversal and conservative-certificate
approach. It enumerates every actual r8 descendant (including pentagon children),
then tests enclosing rectangles against unsimplified polygon boundaries, including
holes, overlaps and artificial source splits. A rectangle with no boundary crossing
has constant containing identities. Nearest-city certificates additionally require
the nearest/runner-up gap and inclusive 50 km cutoff to remain separated by a
spherical route-distance bound over the entire rectangle. Sea and offshore
uncertainty refines to r8. Equal labels are collapsed again after refinement.

Eligibility follows OSM land or the reconciliation's 1 km spherical offshore
projection. Land predicates use prepared polygons. For offshore candidates, each
short great-circle segment is enclosed by a spherical cap at its midpoint with
radius half its arc length. Length-bucketed cKDTrees query those caps enlarged by
the cutoff, so no segment within the cutoff can be missed. Candidate segments
still obey the scalar oracle's outward-rounded SQLite polygon bounds and seam
windows. Exact endpoint/segment projection follows the original equations.
Numerical ties, cutoff uncertainty, and projections extremely close to an
administrative edge use the scalar oracle. Land/country/state/city priorities and
same-country fallback are unchanged. No empirical H3 radius assumption is used.

A dependency envelope is expanded for every possible offshore projection and
checked against **all acquired country polygon component envelopes**, including
countries not yet reconciled. Any pending country makes the entire block wait.
The extra 1e-4 degree margin covers SQLite float32 R-tree rounding. At the date seam, actual descendant centres are split into disconnected western
and eastern envelopes; expanded windows wrap at ±180°. Certificates that cross
the seam or approach a pole refine to the finest centres.

`build_data.golden.reader.Cells` performs ancestor lookup. Never calculate a fresh
coarse cell from a coordinate: logical ancestry from the original r8 key is the
contract. Batched source joins use nonoverlapping integer descendant intervals,
which include harmless invalid-digit gaps but exactly the valid H3 descendants.
Distinct source keys join within r1 subtrees, bounding each interval sort to at
most 49 r3 blocks. An ASOF lower-endpoint match plus an upper-endpoint check
rejects gaps, then a key join restores every original source row, including duplicates.

## Shared lookup fields

All lookup kinds preserve acquisition's columns, types, rows and source order
semantics (physical output row order is not promised). Repeated source observations
remain repeated observations. The shared original fields are:

| Columns | Type | Meaning |
| --- | --- | --- |
| `source`, `source_id` | string | Adapter and source-scoped identity |
| `source_release`, `license`, `provenance` | string | Pinned release, exact licence label and JSON source evidence |
| `latitude`, `longitude` | float64? | Original WGS84 coordinates, where the kind has point fields |
| `h3`, `h3_uint64`, `h3_resolution` | string?, uint64?, uint8? | Original reference cell; located points are r8; timezone memberships can be coarser |

Postal codes, airports, trade locations and IP ranges add:

| Column | Type | Meaning |
| --- | --- | --- |
| `country_id`, `state_id`, `city_id` | string? | Assignment obtained from the compact `cells` table |
| `cell_country_code` | string? | Country derived from `country_id`; original `country_code` remains intact |
| `cell_status` | string | `matched`, `unassigned` eligible land, `ineligible` ocean, `pending` block, or `unlocated` source row |
| `country_disagrees` | bool? | Comparison of non-null source and spatial country codes; null when either side is unavailable |

The quality report counts true disagreements and the compared denominator.
Missing or pending assignments do not silently count as agreement. Reruns replace
pending joins once their cells are committed. Earlier pilot files may remain on
disk; the manifest lists only the current `joined.parquet` for each spatial kind. Source coordinates and source city
names are never silently corrected from spatial answers.

## Lookup tables and their other columns

Every name below is a directory beneath `lookups/`. All fields below are strings
unless another type is specified. Shared original fields above are present in
every table; point fields are present only where explicitly noted.

| Table | Other original columns and meanings |
| --- | --- |
| `postal_codes` | `country_code`, `postal_code`, `place_name`; `admin1_name`, `admin1_code`, `admin2_name`, `admin2_code`, `admin3_name`, `admin3_code` retain source administrative labels/codes; `accuracy` retains the source accuracy value; `variant` distinguishes base versus full postal editions. Includes point fields and spatial join fields. |
| `airports` | `ident`, `iata_code`, `icao_code`, `gps_code`, `local_code` are source identifiers; `type`, `name`, `municipality`, `country_code`, `region_code` preserve source classification, labels and codes. Includes closed sites/heliports, point fields and spatial join fields. |
| `trade_locations` | `locode`, `country_code`, `location`, `name`, `name_ascii`, `subdivision_code`; `function`, `status`, `iata_code`, `date`, `change`, `remarks`, `coordinates_raw` preserve UN/LOCODE evidence. Includes nullable point fields and spatial join fields. |
| `ip_ranges` | `ip_start`, `ip_end` are inclusive textual endpoints; `ip_version` is uint8 (4 or 6); `ip_start_packed`, `ip_end_packed` are 16-byte big-endian comparison keys (IPv4 left-padded with zero bytes); `country_code`, `region`, `city` retain DB-IP's own answer. Includes point fields and spatial join fields. |
| `timezone_cells` | `tzid` plus non-null H3 key fields: compact cell membership at the acquisition stage's r8 centre semantics, including oceans. Preserved byte-for-byte as hardlinks to verified immutable normalized files. This is an independent membership table and retains any source overlaps; it is not clipped to eligible land. |
| `zone_tables` | `table` identifies the IANA reference table; `tzid`, `country_codes`, `comments`, `coordinates_raw` preserve its values. Includes nullable point fields for the IANA reference coordinate. These are reference metadata, not spatial place assignments. |
| `countries` | `country_code`, `alpha3`, `numeric`, `name`, `calling_code`, `currency`, `languages`, `tld`, `continent`, `m49`, `region_code`, `region_name`, `subregion_code`, `subregion_name`, `intermediate_region_code`, `intermediate_region_name`: source country/code hierarchy and reference metadata. |
| `subdivisions` | `code`, `code_system`, `country_code`, `name`, `type`, `parent_code`, `geoname_id`, `name_ascii`: ISO or GeoNames subdivision metadata. GeoNames admin codes are never treated as ISO codes. |
| `phone_metadata` | `territory`, `calling_code`, `leading_digits`, `national_prefix`, `international_prefix`, `metadata_xml`: original libphonenumber territory/service metadata; non-geographic service territory 001 is retained. |
| `phone_prefixes` | `prefix`, `calling_code`, `language`, `description`, `country_codes` (list<string>): multilingual geographic descriptions and candidate country codes. Shared calling codes can refer to several countries. |

The four code/phone tables add `country_id` (string?, direct country-code match),
`place_id` (string?, unique target only), `place_ids` (list<string>, all code-derived
candidates), and `link_status` (`matched`, `ambiguous`, `unmatched`, `pending`).
Subdivisions first use explicit ISO codes or the reconciled GeoNames state
crosswalk, then administrative GeoNames identity or exact country-scoped aliases
of retained states/districts. If no exact alias exists, the ISO row's stated type
may qualify its name (for example, `Bagerhat District`), and explicitly coded
same-country alternate names may match. Multiple matches remain ambiguous.
`link_method` records the evidence. Names never manufacture ISO codes on canonical
places.
Phone prefixes narrow their supplied country codes with the pinned libphonenumber
fixed-line patterns and leading digits. A candidate survives if some full number
can extend the prefix; short shared prefixes remain ambiguous. Missing or
contradictory pattern evidence retains the original candidates. The original
`country_codes` column is unchanged; descriptions are not fuzzy-matched to cities. An ambiguous multi-country prefix has all candidate
IDs and a null singular ID. Missing reconciled countries remain pending.

## Quality report semantics

`quality.json` lists per-table rows and bytes, lookup status/disagreement counts,
blocks built/waiting/remaining, stored cells per resolution and represented finest
centres. The final results below evaluate both named fixtures and large settlements
through `cells`. Pending blocks would remain in the denominator; this publication
has none. The integrity gate requires unique canonical IDs and no dangling cell,
parent or sovereign references. A catalogue country can exist without a selected
spatial border, as EH does under this boundary perspective.

The [dataset card](../data/golden/DATASET_CARD.md) records the final snapshot.
The licence summary remains a draft; original source licences and evidence remain
attached and must be consulted when preparing a release.

## Final table rows and cell resolutions

These are the completed publication's rows, counted in `quality.json`. Lookup
rows preserve source observations, including duplicates; they are not unique
place counts.

| Table | Rows |
| --- | --- |
| `places` | 6,875,329 |
| `cells` | 62,355,684 |
| `postal_codes` | 5,036,067 |
| `ip_ranges` | 7,786,864 |
| `airports` | 86,154 |
| `trade_locations` | 116,213 |
| `timezone_cells` | 4,567,490 |
| `zone_tables` | 821 |
| `phone_prefixes` | 427,963 |
| `phone_metadata` | 254 |
| `countries` | 252 |
| `subdivisions` | 8,911 |

| Stored H3 resolution | Cells |
| --- | --- |
| 3 | 1,141 |
| 4 | 5,145 |
| 5 | 72,657 |
| 6 | 790,253 |
| 7 | 7,158,066 |
| 8 | 54,328,422 |

The **62,355,684 stored cells** represent **199,608,564
resolution-8 eligible centres** across all **41,162 resolution-3 blocks**.
Eligibility includes OSM land and the 1 km offshore band; **1,811,604**
represented centres use offshore projection. These are counts of centres, not a
spherical land-area estimate. All **277 country checkpoints** are ready, with
zero remaining or waiting blocks and no pending lookup rows.

## Final world settlement check through stored cells

The before/after comparison uses the archived v0 cells and the final v1 cells,
not the interim scalar oracle. All **34,171** GeoNames class P observations with
population at least 15,000 were evaluated at their resolution-8 cell centres,
including PPLX and historical observations. No observations remain pending.

| Measure | v0 stored cells | v1 stored cells |
| --- | --- | --- |
| Answer | 34,169/34,171 (99.99%) | 34,169/34,171 (99.99%) |
| Country agreement | 34,102/34,171 (99.80%) | 34,102/34,171 (99.80%) |
| State agreement | 33,259/33,907 (98.09%) | 33,259/33,907 (98.09%) |
| Exact city identity | 25,522/34,171 (74.69%) | 27,195/34,171 (79.59%) |
| Different containing city | 6,935/34,171 (20.29%) | 5,187/34,171 (15.18%) |
| Identity or containing city | 32,457/34,171 (94.98%) | 32,382/34,171 (94.76%) |

A city is present for **34,169/34,171** observations. State comparison excludes
intentionally absent states and empty source admin1 codes; **244** applicable
states remain unmapped and count as disagreements. Containment is geometric
membership at the cell centre, not an independently adjudicated municipal
identity. Agreement with these source records is not holdout accuracy.

The final stored-cell comparison recovers **1,854** v0 non-identities and
introduces **181** new identity mismatches, a net gain of **1,673**. Exact city
identity rises **4.90 percentage points**; identity-or-containing falls by **75**
observations. The full change evidence is `data/work/v1/world-change-classes.json`.

## Final named fixtures and city probes

Every answer below comes from the completed `cells` table at the input's r8
centre. All **13 named fixtures pass**. All **16 additional probes** have a
matched cell; that does not make every city answer correct. Delhi, Dhaka and
Istanbul are known wrong answers, discussed under “Known limitations of v1”.
A dash means an intentionally absent state. Coordinates and cell keys are in
`quality.json` under `checks.named` and `checks.probes`.

### Named fixtures

| Probe | City | State | Country | City method |
| --- | --- | --- | --- | --- |
| lower Manhattan | New York | New York | United States | area |
| Tokyo | Tokyo | Tokyo | Japan | area |
| Singapore | Singapore | — | Singapore | area |
| Monaco | Monaco | — | Monaco | area |
| Hong Kong Central | Hong Kong | — | Hong Kong | area |
| Lagos | Lagos | Lagos State | Nigeria | nearest |
| London | London | England | United Kingdom | area |
| Cayenne | Cayenne | — | French Guiana | nearest |
| Pristina | Pristina | District of Prishtina | Kosovo | area |
| Bengaluru | Bengaluru | Karnataka | India | area |
| Paris | Paris | Ile-de-France | France | area |
| Cagayan de Oro | Cagayan de Oro | Cagayan de Oro | Philippines | area |
| Eindhoven | Eindhoven | North Brabant | Netherlands | area |

### Additional city probes

| Probe | City | State | Country | City method |
| --- | --- | --- | --- | --- |
| Mumbai | Mumbai | Maharashtra | India | nearest |
| Delhi | New Delhi | Delhi | India | area |
| Kolkata | Kolkata | West Bengal | India | area |
| Chennai | Chennai | Tamil Nadu | India | area |
| Karachi | Karachi | Sindh | Pakistan | area |
| Dhaka | Joār Sāhāra | Dhaka Division | Bangladesh | nearest |
| Jakarta | Jakarta | Special Capital Region of Jakarta | Indonesia | area |
| Manila | Manila | Manila | Philippines | area |
| São Paulo | São Paulo | São Paulo | Brazil | area |
| Mexico City | Mexico City | Mexico City | Mexico | area |
| Cairo | Cairo | Cairo | Egypt | area |
| Istanbul | Mercan Mahallesi | Istanbul | Turkey | nearest |
| Moscow | Moscow | Moscow | Russia | area |
| Seoul | Seoul | Seoul | South Korea | area |
| Shanghai | Shanghai | Shanghai | China | area |
| Sydney | Sydney | New South Wales | Australia | area |

Monaco uses offshore projection within the eligibility band; its city method is `area`.

## Final lookup joins

Static links use source codes and administrative/numbering evidence; spatial
links use the final stored cells. All source rows are accounted for, with zero
pending or unassigned spatial rows.

| Static table | Matched | Ambiguous | Unmatched |
| --- | --- | --- | --- |
| `countries` | 250 | 0 | 2 |
| `subdivisions` | 8,247 | 96 | 568 |
| `phone_metadata` | 243 | 0 | 11 |
| `phone_prefixes` | 427,912 | 44 | 7 |

| Spatial table | Matched | Ineligible | Unlocated | Country disagreements / compared |
| --- | --- | --- | --- | --- |
| `postal_codes` | 5,030,928 | 5,139 | 0 | 12,038 / 5,030,928 |
| `ip_ranges` | 7,786,137 | 727 | 0 | 2,500 / 7,786,137 |
| `airports` | 85,822 | 332 | 0 | 188 / 85,822 |
| `trade_locations` | 91,873 | 1,001 | 23,339 | 613 / 91,873 |

Country disagreements compare retained source country codes with cell assignments;
they are reported without adjudication. Ineligible rows are outside the land/
offshore coverage, while unlocated trade rows lack coordinates. Timezone cells
and zone tables retain their source membership/reference semantics rather than
receiving these place joins.

The **8,911** subdivision rows combine **5,046 ISO-3166-2** and **3,865
GeoNames-admin1** records. ISO has **4,617 matched / 44 ambiguous / 385 unmatched**;
GeoNames has **3,630 / 52 / 183**. Compared with v0, unique subdivision matches
increase from **7,087 to 8,247**, while unmatched rows fall from **1,775 to 568**.
Additional administrative aliases also expose ambiguity (**49 to 96**), which
remains explicit. Remaining gaps need validated identity, name/type or version
crosswalks; a same-name settlement does not establish an administrative unit.

Countries match **250/252**, up from **249/252** after adding the missing EH
catalogue identity. AN and CS remain historical with no current single-country
target. Phone metadata leaves AC, TA and nine non-geographic `001` services
unmatched. Phone-prefix ambiguity falls from **95,723 to 44**: **43** have
overlapping numbering languages (37 under +61, four under +212, two under +39),
and one +134597 prefix lacks supporting fixed-line patterns. Stronger allocation
evidence may resolve more. The **seven** unmatched prefixes are five AC rows
and two translated TA `2908` rows; TA now narrows correctly instead of selecting
SH merely because it has a represented country. Original candidates are retained.

## Final integrity results

| Check | Count |
| --- | --- |
| Duplicate place IDs | 0 |
| Missing cell place IDs | 0 |
| Missing parent references | 0 |
| Missing sovereign references | 0 |

All **6,875,329 places** and the final cell foreign keys pass these
checks. `country:EH` occurs once and resolves the **49** former parent and **49**
sovereign references without inventing a Western Sahara boundary or changing
the selected territorial perspective.

Of **199,608,564** represented r8 centres, **199,608,025** have a
country and **180,083,434** have a state. A null assignment is distinct
from a dangling reference: **539** eligible centres have no country, and
**39,234,657** have no city. City coverage and its tradeoff are below.

## Known limitations of v1

**City identity improved at settlement anchors, but polygon-backed city coverage
fell.** Compared with v0, the share of resolution-8 land centres whose city comes
from a containing area fell from **72,311,908 to 41,152,487**, nearest-point
assignments rose from **93,143,091 to 119,221,420**, and centres with any city
fell from **165,454,999 to 160,373,907**. The common denominator below is all
199,608,564 eligible centres, including the 1 km offshore band.

| City assignment | v0 centres / eligible centres | v1 centres / eligible centres |
| --- | --- | --- |
| Containing area | 72,311,908/199,608,564 (36.23%) | 41,152,487/199,608,564 (20.62%) |
| Nearest point | 93,143,091/199,608,564 (46.66%) | 119,221,420/199,608,564 (59.73%) |
| Any city | 165,454,999/199,608,564 (82.89%) | 160,373,907/199,608,564 (80.34%) |

V1 stopped treating untyped, unlinked locality polygons as cities, including many
wards, boroughs, subdistricts and tehsils. It also excludes administrative
containers of much larger linked city/town points unless the container has its
own classified, linked settlement identity. County/localadmin polygons cannot
stand in for cities without shared Wikidata settlement identity, and a region
needs the exact shared identity of a uniquely linked, explicitly classified city;
a similar name or a capital/seat relationship is insufficient. These rejected
areas remain retained administrative entities, but no longer supply city labels.
The rule does not reject every ward or county merely by its name.

Removing a weak city polygon does not create the missing municipal boundary.
Where no accepted city polygon covers a centre, same-country nearest-point
fallback applies within 50 km; beyond that cutoff the city is absent. Area
assignments decrease by **31,159,421**, nearest assignments increase by
**26,078,329**, and any-city coverage loses **5,081,092** centres (**2.55 percentage
points**). These are net aggregate changes, not a measured one-to-one transition
of individual centres between methods.

The accuracy cost near city edges is loss of boundary-based discrimination:
nearest-point regions can cross municipal boundaries, assign an outside neighbour
inside a city, or extend a city beyond its actual edge. Small or misclassified
settlement anchors can win. Snapping inputs to r8 centres adds displacement near
those boundaries. The settlement-anchor identity improvement does not establish
better accuracy at arbitrary edge locations; the size of that edge error has not
been independently measured.

| Limitation | Next work |
| --- | --- |
| Reduced area coverage and greater nearest-point dependence | Audit rejected polygons by subtype and settlement evidence; recover validated municipal boundaries and administrative-to-city identity links. Test interior points and transects across city edges, measuring identity, boundary errors and missing-city coverage together. Preserve separate suburb municipalities; do not recreate broad city areas from population radii. |
| **Delhi → New Delhi** (area), a known wrong answer for the requested Delhi city | Review the linked Delhi/New Delhi polygons and hierarchy, then document and validate the intended city versus municipality scope. Use source identity and explicit policy data where needed, preserving distinct municipalities rather than patching this probe. |
| **Dhaka → Joār Sāhāra** (nearest) | The linked Dhaka polygon does not cover the probe, so a zero-population GeoNames PPL anchor wins. Obtain or validate the missing city footprint and review the subunit classification before changing fallback eligibility. |
| **Istanbul → Mercan Mahallesi** (nearest) | The pinned reconciliation has no linked Istanbul city polygon; a zero-population GeoNames PPL anchor wins. Link a valid city footprint and audit neighbourhood classifications and hierarchy. |
| **181 new identity mismatches** (CN 121, MY 21, DE 6, BE 5; every other country at most three) | Adjudicate the retained regression records, starting with China and Malaysia. Broad shared-identity administrative footprints can absorb point-only settlements lacking their own polygon; constrain those footprints with municipal evidence and recover independent settlement boundaries. Keep genuine suburbs distinct from independent municipalities, and rerun both identity and coverage checks. |

All 21 Malaysian regressions return Kuala Lumpur and satisfy geometric
containment; examples include Setapak, Wangsa Maju, Bukit Bintang and Bangsar.
They remain in the mismatch count: source PPL classification and geometric
containment alone cannot decide municipal identity. The three probe errors are
not asserted to be disjoint from the settlement regression set. Detailed evidence
is retained in `remaining-probe-evidence.json`, `malaysia-regression-evidence.json`
and `world-change-classes.json` under `data/work/v1/`.

Separately represented suburb municipalities are intended city answers. Broad
metropolitan membership does not override a classified, linked municipality's
own polygon. Rejected finer units remain in `places` with source classification
and exclusion evidence; a per-cell ward/borough column is still deferred.

## Incremental v1 rebuild

`blocks.sqlite` caches the expensive actual H3 descendant envelopes independently
of the reconciliation builder. Changed country envelopes or offshore policy
recompute dependency intersections; unchanged normal roots reuse their stored
bounds. A legacy `blocks-<hash>.sqlite` supplies bounds after a SQLite integrity
check, with every dependency rechecked and seam roots enumerated again. The
cell implementation fingerprint includes the cell Arrow schema separately from
the place schema. Changing static links, reports or place-only columns does not
invalidate cells. Cell fingerprints still include each required country's verified
partition, land, runtime policy and spatial implementation. Unchanged source
rows and timezone hardlinks remain reusable.

Before replacing golden files, the controller publishes `completed: false`.
Completion requires both `work/golden/run.json` and `golden/manifest.json` to say
`completed: true`, with the integrity checks above passing. Both markers are true for the final v1 publication;
[GOLDEN_V1.md](GOLDEN_V1.md#completed-rebuild-and-evidence) records completion and
audit evidence.
