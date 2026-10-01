# Golden v1 rebuild, 2026-10-02

## Baseline analysis (before implementation changes)

The exhaustive v0 audit reads the committed Parquet cells at every GeoNames P
record with population at least 15,000, then inspects the corresponding SQLite
identity links, source classifications, hierarchy and winning polygon evidence.
All 34,171 observations were included: 25,522 identical cities and **8,649
non-identical answers**. The pre-change baseline is archived under
`data/work/v1/`: `reconciled-v0.json`, `golden-v0.json`, `quality-v0.json`,
`city-audit-v0.json` (one evidence record per non-identity result). The original
country reports were also consulted; they evaluate original coordinates, whereas
the golden audit evaluates resolution-8 centres.

These are mutually exclusive, ordered **evidence classes**, not independent
ground-truth adjudication. In particular, source PPLX classifications can be
wrong, and an untyped locality can be a legitimate municipality. Uncertainty is
retained rather than labelling every containing city a correct suburb.

| Class | Count | Largest concentrations (counts) |
| --- | ---: | --- |
| Untyped locality: ward or administrative area | 2,011 | PK 326, CN 292, VN 251, TH 123, IR 88, TN 88 |
| Source-labelled suburb within a larger linked city | 1,657 | US 255, CA 210, AU 191, ES 189, RU 118, BR 99 |
| Other linked containing city; identity unresolved | 1,170 | US 218, JP 193, IN 120, PH 71, CN 44, BR 43 |
| Nearest neighbour changed by r8 centre displacement | 1,043 | IN 287, ID 153, CN 75, MY 53, US 46, UG 43 |
| County/localadmin polygon standing for city | 838 | CN 619, GB 86, PL 35, FR 26, MM 22, CA 13 |
| Unlinked locality with explicit settlement class | 610 | EG 66, VN 60, CN 53, IR 51, MY 34, IN 28 |
| Subcity observation without a containing city polygon | 539 | DE 93, UA 51, AE 34, AU 33, CZ 29, US 27 |
| Linked city wins over the observation's own polygon | 240 | BR 34, US 33, ES 23, BE 21, JP 19, FR 15 |
| Deliberate city-state convention | 213 | HK 141, SG 65, MO 6, MC 1 |
| Unlinked polygon has the same normalized name | 133 | BR 46, US 21, RU 10, IR 9, RW 8, JP 7 |
| Country perspective/coverage disagreement | 69 | PS 47, CN 5, EH 4, IL 3 |
| Suspected ambiguous/name link to another identity | 52 | BR 25, JP 11, US 5, PH 2, RU 2, CA 1 |
| Other nearest neighbour; missing/displaced source anchor | 47 | IN 4, TZ 4, ET 3, GW 3, MY 3, US 3 |
| Historical/abandoned source observation | 27 | RU 6, UA 5, IN 4, AO 2, PK 2, AF 1 |

The nearest-displacement class specifically verifies that the *original* point
returns its own identity but the stored r8 centre returns another. Missing city
polygons underlie many other classes and are recorded independently as
`own_city_area_parts`; they are not added again to these exclusive totals.
The 52 suspected link collisions are not 52 proven bad links. Same-name distinct
GeoNames records and stale/contradictory Wikidata evidence require adjudication.

Mumbai is one example of the widespread untyped-locality issue: its linked city
point is a *child* of L Ward in Overture's containment hierarchy, and has no city
polygon. Blindly rolling every child into its parent would preserve the error.
Pakistan's tehsils and Vietnam's wards show the same pattern. Cameroon combines
unlinked numbered city subdivisions with genuinely distinct linked towns;
Zimbabwe includes unlinked municipality names, excluded PPLX observations and
two nearby GeoNames Ruwa records with different populations.

Baseline golden counts: answers 34,169/34,171; country 34,102/34,171;
state 33,259/33,907; identity-or-containing 32,457/34,171; exact identity
25,522/34,171. All 13 existing named fixtures pass. Repository baseline:
225 tests passed, 7 skipped.

## Join and integrity diagnosis

The 1,775 unmatched subdivisions comprise **1,530 ISO-3166-2** and **245
GeoNames-admin1** observations; the 8,911 denominator combines both systems.
49 additional GeoNames admin1 observations have multiple candidate places.
The v0 linker only indexes canonical states, omitting retained districts such as
French departments and British local authorities.

Unmatched countries are EH, AN and CS. EH has a GeoNames TERR record but no
accepted default-perspective country polygon; 49 retained cities consequently
reference a missing country. AN and CS are historical countries.

Phone ambiguity is initially 95,723 rows: calling code 61 accounts for 60,578;
1 for 32,498; 7 for 1,160; 44 for 814; 39 for 353; 47 for 166;
358 for 144; 599 for 10. The source contains territory-specific fixed-line
patterns, so shared calling codes alone overstate ambiguity. Non-geographic
001 service metadata has no geographic country; AC and TA are calling-plan
territories without separate country entities.

## Implementation and rebuild

Results and operational handoff are appended after the sample and validation.
