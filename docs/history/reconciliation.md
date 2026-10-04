# Reconciliation policy and final v1 evidence

The v1 world rebuild is complete. All outcome tables below use the final
published stored cells at resolution-8 centres, as recorded in
quality.json (`data/golden/quality.json`, untracked workspace file). They replace the earlier pilot and
interim scalar measurements. The v0 failure classification is retained in
[GOLDEN_V1.md](base-cell-results.md#baseline-analysis-before-implementation-changes), and
[GOLDEN_DATASET.md](../GOLDEN_DATASET.md) defines the schema and reader contract.
Source acquisition is unchanged.

## Final city rule and limits

Link country-scoped Overture divisions to GeoNames by unique Wikidata identity within a 100 km guard, otherwise normalized Unicode names within 10 km. Ambiguous close candidates remain separate and are recorded. Administrative roles link to GeoNames A, city roles to P. GeoNames Wikidata evidence comes from `wkdt` aliases; Overture evidence comes from retained `upstream.wikidata`.

V1 requires an eligible GeoNames settlement link or an explicit Overture city,
town, village or hamlet class before using a locality polygon as a city. Untyped
unlinked administrative localities are retained as districts, not city polygons
or nearest-city anchors. A locality containing a linked city/town at least five
times its recorded population (minimum 15,000) is also demoted if it lacks its
own classified, linked settlement identity. Hierarchies describe containment: a
city point inside a ward does not make that ward the city's parent municipality.

Explicit roll-ups and city-states retain priority. Otherwise the most specific
classified, linked municipality wins, preserving separate suburb municipalities.
Linked untyped localities retain population ordering below those municipalities.
County/localadmin promotion still requires a shared Wikidata settlement identity
and has lower priority. A region may supply a city footprint only when it shares
exactly the same Wikidata identity with a uniquely linked, explicit city-class
locality; a state's capital or a similar name is insufficient. All shared-identity administrative footprints rank below linked localities
and above unlinked settlement classifications. No city names or probe coordinates enter these decisions.

City-state footprints are SG/MC/HK/MO. The JP policy assigns precisely the 23 locality areas ending in 区 within JP-13 to the linked Q1490 city. A changed membership count fails the unit. Other Tokyo prefecture municipalities retain their own city identities. The GB policy assigns 33 pinned county identities (32 boroughs plus City of London) to Q84, using the [official borough map](https://data.london.gov.uk/download/e55pw/f1d04c59-4590-4291-b4ea-3abc624156b7/London_Borough_Boundary_Map_A4.pdf). No rule uses a fixture coordinate. Nearest fallback uses eligible GeoNames or unmatched Overture locality points, same country, ≤50 km inclusive, and is labelled `nearest`.

## Output and operation

`data/reconciled/manifest.json` lists the sole committed snapshot. Each country has a SQLite partition with indexed `entities`, `areas`/`area_bounds`, `points`/`point_bounds`, GeoNames and division evidence, identity links, and state crosswalks. Geometry is unsimplified WGS84 WKB; JSON record blobs use lossless zlib (read with `build_data.reconcile.common.unpack`). Provenance and aliases are retained. Country partitions remain disk-backed; a lookup reads only intersecting geometries. The manifest retains all source manifests and the global OSM land index reference.

Land eligibility uses OSM containment or a spherical nearest-boundary projection within 1 km. Labels use that land point; nearest-city distance uses the original query. Overlapping OSM split polygons are never counted as separate coastlines. Ocean beyond the band is ineligible; unresolved land retains empty fields.

Checkpoints use the acquisition workspace, ledger, fingerprints, hash verification and atomic output helpers. Stages: source validation, country extraction, identity links, country assignment, quality, manifest commit. A single advisory lock owns reconciliation. Interrupted units rebuild; completed units verify and skip. A new generation first archives the old manifest and commits an explicitly
incomplete manifest. Each replacement SQLite country is checked and hash-verified
before retiring that country's old partition and extract/link intermediates.
Resume skips verified countries without recreating their deleted intermediates.
An interrupted replacement keeps the previous partition; an interrupted cleanup
is retried. `load()` rejects an incomplete generation, while golden discovery
uses matching committed country checkpoints. The land index is one bounded-memory streaming checkpoint; an interruption rebuilds it.

```sh
uv run --no-sync python -m build_data.reconcile
uv run --no-sync python -m build_data.reconcile --countries JP GB US
uv run --no-sync python -m build_data.reconcile status
uv run --no-sync python -m build_data.reconcile --world
```

The default is the full pilot. A subset command publishes a subset snapshot. `--world` refuses a failed or stale pilot gate. World completion is indicated by `data/work/reconcile/run.json` having `world: true, completed: true`, with a committed manifest containing the world country list; errors leave the marker incomplete.

Reuse `Locator` as a context manager for bulk queries, or call `build_data.reconcile.locate(lat, lon)` for a verified single lookup. Returned field objects include names, local names, codes, population, parent, source IDs, naming and boundary provenance; top-level fields include sovereign and methods.

State-code crosswalks fall back to a ≥95% dominant GeoNames admin1 among at least 10 contained populated places below 15,000 people. Large evaluation places are excluded from these votes. The full code counts and confidence are retained; this is source agreement, not independent boundary validation.

A unique shared Wikidata link and explicit Overture `city` class can override a conflicting GeoNames PPLX code, recording `classification_conflict` on the canonical link. This applies to an Overture locality, never a neighborhood/macrohood/microhood area. It retains the linked GeoNames anchor for fallback. Town-class conflicts remain excluded.

The named Lagos check accepts the source-preferred English label “Lagos State” for Lagos (NG-LA); the actual returned label is reported verbatim. This is a validation name equivalence, not an output-name override.

## State and sovereign choices

GB uses geoBoundaries ADM1 for its constituent countries. PH uses Overture
counties (provinces), supplemented by independent city localities directly below
regions. Country policy chooses the meaningful state level rather than assuming
that every Overture region is a state. SG, MC, HK and the five French dependencies
intentionally omit state. French dependencies retain FR/France as sovereign;
HK retains CN/China. Each country report records its policy and reason.

State disagreements include coastal gaps, unresolved code crosswalks, changed
administrative boundaries and conflicting source codes. A plausible display name
does not silently count as agreement with an unmapped code.

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

## Completed rebuild and validation

Policy is `reconciliation-1`; the final reconciliation builder is
`e4bb8ae48002bb0d54a0ba59247fb4bb13e86ce2506849f91074856b085a5e8a`.
The sample gate passed before the world rebuild, and all 277 country replacements
completed with predecessor partitions and extract/link intermediates retired.
The world controller, golden manifest and golden run marker all report
`completed: true`. Full completion/audit evidence is in
[GOLDEN_V1.md](base-cell-results.md#completed-rebuild-and-evidence).

The final code validation recorded **237 passed, 7 existing skips** for
`uv run --no-sync pytest`, with `ruff check`, `ruff format --check` (209 files)
and strict `mypy` (206 source files) passing. Logs are
`data/work/v1/{pytest-final,ruff-final,format-final,mypy-final}.log`.
The final sample's exhaustive certificate/vector/ancestor-equivalence check
covered **487,403 r8 centres**, plus **1,856 independent scalar checks**, before
launch. These implementation checks are distinct from the final stored-cell
world quality results above; this documentation update does not rebuild data.
