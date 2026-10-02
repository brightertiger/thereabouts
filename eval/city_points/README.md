# City-answer reference points

`points.csv` contains 120 deliberately selected, individually desk-reviewed points for checking the **city field** of the offline reverse geocoder. Sources were checked on **2026-10-02**. This is an externally researched reference set, not a comparison against the project's GeoNames input. It contains no project predictions and has not been graded.

The required outputs are `points.csv` and this document. `evidence.csv` separates membership, coordinate and map evidence; `sources/` preserves short source extracts, identifier records, search notes and cached map responses. `coordinate_overrides.tsv` records corrected coordinates and the reasons for using them. Earlier candidate caches remain for audit and are not additional reference rows. The final row and `evidence.csv` determine which source and map cache apply.

## Meaning of the expected city

1. Inside a city or town, return that city or town, never a ward, neighbourhood, district or village absorbed into its built-up area.
2. Independent neighbouring cities retain their own names: Howrah, Noida, Thane, Navi Mumbai, Yokohama and Petaling Jaya must not become Kolkata, Delhi, Mumbai, Tokyo or Kuala Lumpur.
3. The owner's containing-city convention takes precedence over local administrative terminology: New Delhi → Delhi; City of Westminster → London; Shinjuku → Tokyo; Brooklyn → New York.
4. A standalone town expects its own name. A rural location in or beside a village expects the village, not the enclosing district or a distant city.

Aliases normally mean the same settlement. Consequently **New Delhi, Westminster, Shinjuku and Brooklyn are not accepted aliases** of their containing cities. The one explicit alternative-settlement exception is the ambiguous Bario row, described below. Do not expand accepted names from model results.

## Sampling and split

| group | total | dev | holdout |
| --- | ---: | ---: | ---: |
| large-city | 60 | 20 | 40 |
| neighbour | 24 | 8 | 16 |
| town | 18 | 9 | 9 |
| rural | 18 | 3 | 15 |
| **total** | **120** | **40** | **80** |

The ten large cities are Dhaka, Istanbul, Mumbai, Delhi, Kolkata, Tianjin, Shanghai, Tokyo, London and New York. Each has one centre, three interiors in different named subunits, and two outer-city points. The interiors include New Delhi, Westminster, Shinjuku, Brooklyn and Asian-side Kadikoy. Each of the six independent neighbours has a centre, two interiors and a point on the side facing its larger neighbour.

The 18 town points cover **nine towns, with two points each**, so every town is represented in both splits: Oak Park, Evanston and Wilmette (United States); St Andrews (United Kingdom); Bayeux (France); Paraty (Brazil); Swakopmund (Namibia); Takayama (Japan); Oamaru (New Zealand). Public settlement descriptions put these roughly in the requested 10,000–150,000 range, using varying census dates and urban/municipal definitions. The Chicago-area municipalities deliberately test separate adjoining towns; the sampling does not require every town to be geographically isolated.

The 18 rural points cover Castle Combe, Clovelly, Plockton, Reine, Vik, Monsanto, Ogimachi, Khinalug, Bario, Mawlynnong, Hogsback, Nieu-Bethesda, New Norcia, Nundle, Terlingua, Ocracoke, Purmamarca and Cachora. Town and rural groups each span six inhabited continents. Overall there are **20 countries and 43 named expected places**.

Splits were assigned without seeing any project answer. Large-city IDs `03` and `06` are dev. Neighbour IDs `01`, plus `howrah-04` and `yokohama-04`, are dev. Each town's `01` is dev. Rural dev IDs are `castle-combe-01`, `mawlynnong-01` and `nieu-bethesda-01`. All remaining IDs are holdout. This gives exactly one third dev overall; individual groups have different ratios to keep every city and town in both splits. Singleton rural villages occur in only one split; the rural group occurs in both.

Use **dev for tuning and holdout for one final score after choices are frozen**. Report denominators and group scores, with a separate result for the ambiguous row. If excluding that row in a strict supplementary score, its holdout denominator is 79 instead of 80. Record the `points.csv` SHA-256 from `validation.json` with results. Do not move points between splits, repair labels or add aliases in response to holdout errors. Independently established factual corrections need a new version and an explicit note that an already inspected holdout is no longer fresh. Both splits are present in the file; confidentiality must be enforced by the evaluator's workflow.

## Selection and verification

Landmarks and localities were chosen by geography before any grading: public buildings, museums, railway stations, parks, temples and documented village centres. Membership was read from municipal or national sources, institutional addresses, tourism authorities and settlement descriptions. Wikipedia supplied many landmark coordinates and some descriptions. Coordinates were then compared against a second public map source, with mismatches reviewed individually. Descriptions say “approach”, “grounds” or “environs” where the coordinate is beside the building rather than on its footprint. Chinese coordinates are recorded as WGS84; GCJ-02 map positions were not copied as WGS84.

All 120 final coordinates have a cached OSM Nominatim reverse cross-check in the stated country and within 400 metres of its returned nearby feature. The largest distance is approximately 398 metres on Tianjin airport grounds; all others are below 150 metres. **A nearby-feature distance is not a boundary-clearance measurement or proof that a reverse-geocoder label is correct.** Membership uses the accompanying documentary evidence and the owner's rules. The country's map result and local feature were reviewed together; labels such as borough, county or district were not copied into `expected_name`.

There are **90 high-confidence and 30 medium-confidence rows**. High means the place membership and location agree in the reviewed evidence. Medium flags weaker documentary coverage, a corrected or approximate landmark coordinate, an outer-city interpretation, or settlement-granularity uncertainty. It is a qualitative assessment, not a probability.

There are **21 rows with only one non-OSM source family**, plus the OSM map cross-check; 99 have two non-OSM families. No row rests on OSM alone, and no row has only a single source overall. The 21 are:

`istanbul-06`, `kolkata-05`, `kolkata-06`, `tianjin-01`, `tianjin-02`, `tianjin-04`, `tianjin-05`, `howrah-01`, `howrah-03`, `howrah-04`, `st-andrews-01`, `bayeux-02`, `paraty-02`, `swakopmund-02`, `oamaru-01`, `ogimachi-01`, `mawlynnong-01`, `nieu-bethesda-01`, `new-norcia-01`, `purmamarca-01`, `cachora-01`.

For six of these, Wikipedia is the only non-OSM source: `kolkata-06`, `tianjin-01`, `tianjin-05`, `howrah-03`, `howrah-04`, `swakopmund-02`. These are medium confidence. The remaining single-family rows usually have an official or specialist description plus a map-derived coordinate. “Family” counts source hosts, grouping Wikipedia language editions and excluding identifier sites and OSM-derived Mapcarta. Distinct hosts do not guarantee independent underlying evidence; Wikipedia may cite the same institution. OSM itself is related to a pipeline input, so this limitation matters.

The one-off Nominatim job made **148 requests**, including searches and rejected/replaced coordinates. It used one process and thread, a descriptive `CityPointsReference/1.0` User-Agent, cached every response, waited at least 1.1 seconds after each request, and imposed a 149-request cap. Do not rerun collection as a recurring evaluator. See the [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/).

Expected names were not derived from GeoNames or Overture dumps. Public Wikipedia/Wikidata pages supplied matching identifiers only after expected settlements were selected; public GeoNames pages resolved several major-city identifiers. Wikidata IDs are populated on **116 rows**, GeoNames IDs on **105 rows**. Blank values are intentional where the item was unresolved, retrieval failed, or an administrative and a settlement item could not safely be distinguished. An identifier is supporting metadata, not a competing city definition.

No project lookup, data table or point prediction was consulted. An initial required repository search unexpectedly returned generic pipeline code snippets despite an exclusion request; those snippets supplied no point predictions and were not used to select points or answers. Subsequent research and all file writes stayed under this directory. No git operation or dependency change was performed.

## Columns

The CSV is UTF-8 with a header, standard CSV quoting and one point per record. Empty optional fields are empty strings.

| Column | Meaning |
| --- | --- |
| `id` | Stable point identifier; retain it when correcting evidence. |
| `group` | `large-city`, `neighbour`, `town`, or `rural`. |
| `role` | `centre`, `interior`, `edge`, or `facing-side`; geographic sampling role. |
| `latitude`, `longitude` | WGS84 decimal degrees, latitude first; six printed decimal places do not imply survey precision. |
| `expected_name` | Common English name under the owner's settlement rules. |
| `accepted_names` | Other accepted names separated by `|`, excluding `expected_name`; local script, spelling and historical variants where applicable. Bario contains a documented alternative settlement interpretation. |
| `expected_kind` | `city`, `town`, or `village` at the intended settlement scale; not a uniform legal classification. Oak Park and Wilmette are statutory villages but town-scale here; tiny New Norcia is village-scale despite “monastic town” wording. |
| `country_code` | ISO 3166-1 alpha-2 code; `GB` for the United Kingdom. |
| `expected_wikidata` | Public Wikidata Q-ID for the expected place, when securely identified. |
| `expected_geonames_id` | Public GeoNames identifier for matching only, when securely identified. |
| `what_is_here` | Landmark, address or locality and the smaller unit containing it. |
| `source_url` | `|`-separated evidence URLs: membership first, coordinate source next if different, then the final OSM cross-check feature; occasionally an additional supporting source. |
| `source_checked` | ISO date of desk review, not the publication date or a promise of current HTTP availability. |
| `reason` | One sentence connecting the point to its expected settlement. |
| `confidence` | `high` or `medium` under the definitions above. |
| `ambiguous` | `yes` only for a knowingly accepted alternative settlement interpretation. |
| `split` | Frozen `dev` or `holdout` assignment. |

Matching should accept the expected name or a listed alias, with Unicode normalization, case folding and whitespace normalization. Do not strip arbitrary place suffixes or match the name of an enclosing administrative area. Use IDs only when they denote the expected place; state/country identifiers must not substitute for it. This set does not provide an expected state field.

## Hard cases and limits

- **Bario (`bario-01`, holdout) is the sole ambiguous row.** The tourism source describes a dispersed cluster of villages. The airfield-side map identifies Pa' Ramapuh Atas. `Bario`, `Pa' Ramapuh Atas` and `Pa Ramapuh Atas` count as acceptable answers here, but the latter two are not synonyms for the whole cluster. The Q-ID remains the broad Bario item.
- **Published centroids can be wrong for a landmark.** New Norcia was moved to the community's own directions-map coordinates; Terlingua to the Starlight Theatre in the historic village; Purmamarca to Plaza 9 de Julio, away from the separate railway locality. Ogimachi uses Wada House rather than the centroid of the multi-village UNESCO site. Tianjin Museum, Sabarna Sangrahashala, Mawlynnong, Bayeux's tapestry museum and several other landmarks also required reconciliation. Bayeux refers to the established Rue de Nesmond museum site, independent of opening or relocation schedules.
- **Municipal and built-up-city edges differ.** Tianjin, Shanghai and Istanbul have extensive administrative territories. Their edge samples represent outer urban areas or forest/airport margins inside the containing city, not points close to every municipality's distant legal border. The Tianjin South station candidate was dropped because its separate-town setting did not meet the intended rule. Tokyo uses the 23-ward urban-city interpretation here.
- **Boundary clearance remains qualitative.** Border-hugging candidates were replaced, including Garia, northern Noida and waterside New York locations. No polygon-distance calculation certifies a minimum few-hundred-metre buffer for every row. Small coastal villages and compact municipalities make that especially difficult. Before treating this as a certified kilometre-hex boundary benchmark, obtain independent municipal boundaries and review those clearances; do not infer safety merely from a landmark address. The current set supports documented settlement answers but does not certify hexagon-boundary immunity.
- Some official sites block automated fetches, fail TLS negotiation, return an app shell, or have moved pages. Browser-visible or indexed evidence and supporting sources were reviewed where possible; cache errors are retained honestly. `source_checked` does not claim every URL returned a usable HTTP 200 page. The six Wikipedia-only non-OSM cases above remain the weakest documentary cases.
- **120 selected points cannot certify accuracy per country.** The sample overrepresents documented landmarks and the named metropolitan problems, is not random or population weighted, and contains correlated points in the same settlement. Nine town pairs provide fewer independent town examples than eighteen distinct towns. Sparse rural controls cannot establish general agricultural-land coverage. Population bands, municipal status and naming conventions are not internationally uniform.

## Reproducible local check

Run from the repository root:

```sh
python3 eval/city_points/validate.py
```

This reads only this directory, uses no network or project code, and writes `validation.json` here. It checks the schema, parsing, required fields, aliases, IDs, coordinate bounds, duplicates, frozen group/split counts, per-city roles, required named subunits, README totals, matching cached query coordinates, all 120 country codes, and proximity to the returned map features. It records unresolved boundary verification explicitly. It is an integrity audit, not a substitute for the desk review or an accuracy score. `assemble_coordinates.py` and `assemble.py` can reconstruct the CSVs from the frozen selection files without network access; the other research scripts are collection provenance, not required to use the set.

Map evidence is © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), available under ODbL. Wikipedia text extracts retain their source URLs and are subject to [Wikimedia's reuse terms](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use). Other sites retain their rights; cached extracts are short review evidence, not full-page mirrors. No blanket licence over third-party evidence is asserted.
