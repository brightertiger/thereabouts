# Golden dataset card — completed v1

This is the completed 2026-10-02 world publication, schema `golden-1`, for offline
city/state/country lookup and source-preserving lookup-table joins. Counts and
answers below come from [quality.json](quality.json) and the published
[manifest.json](manifest.json), not the interim scalar evaluation. The controller,
golden manifest and golden run marker all report completion.

Coordinates retain WGS84 source values but place assignments use their H3
resolution-8 centres and logical stored-cell ancestors. Eligibility is OSM land
or the 1 km offshore band. Offshore area labels use the projected land point;
city fallback uses the original centre, same country, within 50 km inclusive.
Ineligible ocean, unlocated source rows and unresolved eligible land are distinct.
IP coordinates are database estimates. Timezone membership remains independent
of land coverage and may retain source overlaps.

Sources retain their release, licence and provenance fields. Consult
[DATA_LICENSES.md](DATA_LICENSES.md) and the retained original notices before
release; the licence summary is still a draft. Full columns and reader semantics
are in [GOLDEN_DATASET.md](../../docs/GOLDEN_DATASET.md), city/state policy in
[RECONCILIATION.md](../../docs/RECONCILIATION.md), and the failure audit and rebuild
evidence in [GOLDEN_V1.md](../../docs/GOLDEN_V1.md).

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
