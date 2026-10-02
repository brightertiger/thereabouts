# City normalization plan

V1 does not distinguish a settlement that names the countryside from a city that absorbs its neighbourhoods. All **6.69 million settlement entities have role `city`**. Small anchors therefore win inside large cities, while the benchmark sometimes asks for a suburb instead of its parent city. Parent roll-ups alone barely change this.

Build **one city/town table, one place-to-city map, a small country-policy file, and a spatial cell rule**. Cities and towns own their footprints; smaller places cannot win inside them. Outside those footprints, keep standalone villages and other settlements. Start with the existing polygons and recover missing city footprints from retained wards; use GHSL to constrain inferred urban footprints.

The missing prototype is now measured. The boundary-respecting combination tested—population/seat candidates, population-weighted urban allocation with protected centres and known city limits, plus modest footprints for small towns—raises the **same frozen check score from 85.84% to 91.95%**, a net **2,087** additional agreements. It also produces **130 new mismatches**, which must be sorted before a world release. These are source-agreement results, not independent accuracy. The largest visible gains do not require new data: Mumbai's retained wards reconstruct a footprint whose Mumbai answers rise from **2 of 707 cells to all 707**.

**Read the check score with care.** The candidate list that scores best (GeoNames places of at least 15,000 people, plus administrative seats) is nearly the same set of places as the check itself, and the 1 km anchor guard and the town radius both protect the area around each candidate's own point. Those steps therefore pass the check largely by construction: the 1,073 checks gained by the town radius show that the rule does what it says at the anchor, not that the town's extent is right. The measures that are not circular are the footprint results (distinct answers and city share inside the large cities), the neighbour probes, and the hand-checked set proposed below. Judge each phase on those first.

The owner has decided:

- Rural land may report its village; towns report the town. Wards, neighbourhoods, districts and absorbed villages inside a city/town report that city/town.
- Independent neighbours keep their names: Howrah, Noida, Thane, Navi Mumbai, Yokohama and Petaling Jaya.
- New Delhi reports Delhi; Westminster reports London; Shinjuku reports Tokyo; Brooklyn reports New York.

Two choices remain:

- **Keep the rural nearest-settlement limit at 50 km, with a “distant nearest” flag above 25 km? Recommend yes.** A hard 25 km limit would remove about 17.61 million currently filled cells; distance alone does not establish that their villages are wrong.
- **Allow inferred footprints where a town has no boundary? Recommend a limited first release with the method recorded.** A population-scaled radius fixes many missing-town cases, but it also changes Kāmthi to Yerkhera. Review those new failures before enabling the rule everywhere.

The next implementation should deliver the visible city repairs first, then the global rule and small-town extension.

## What to build

A **city footprint** is the area in which one city or town owns the output name. A **canonical city** is its chosen identity. A **roll-up** maps a smaller place to that identity. A metropolitan urban cluster can contain several canonical cities. Villages outside city/town footprints keep their own existing identities.

Use the population/seat set below as the starting *candidate list*, with Overture classes, links and country policy deciding which candidates may absorb other settlements. It performs best in the prototype, but 37,819 candidates have some village/hamlet evidence: a low-level administrative seat is not automatically a town. Do not promote all of them to city status. Weak village-seat candidates need an established town/city footprint or a country rule before they acquire absorption authority. The scores below include this mechanical list as tested; the effect of that further eligibility filter has not yet been measured.

| Artifact | Minimum contents | How it is built |
| --- | --- | --- |
| `canonical_cities` | `city_id`, preferred source/place ID, country, city/town kind, display names, anchor, population, source IDs, footprint references and allocation rule | Reuse existing IDs where possible. Choose names from the city identity, not a linked ward/village. Footprint references point to retained area IDs, GHSL polygons or an explicitly inferred radius. Computed country output; it contains absorbing cities/towns, not a duplicate copy of every village. |
| `place_to_city` | `place_id`, output `city_id`, `method`; an optional evidence/source reference | Canonical city → itself; ward/absorbed settlement → city; standalone village → itself; non-settlement or unresolved identity → explicit null/status. Use accepted identity/part relationships, then the same spatial rule at the place anchor. This map also serves postal/airport/IP lookups that join to a place. A new canonical identity must have a corresponding published place row. |
| Country policy file | Source IDs for city parts, independent neighbours, accepted footprint groups, excluded broad areas, naming/eligibility exceptions | Small reviewed data file, initially the named cases. Pin Mumbai's 24 wards, Tokyo's 23 wards, London's 33 members and New York's five boroughs. Protect the linked city-class/GeoNames-section conflicts, including Navi Mumbai and Taketa. |

Keep geometry in the existing country databases and the GHSL input; compile spatial indexes per country. An area that spans several cities is split by the spatial rule, not assigned one unconditional city through the place map. A country/state container does not become a city because its administrative seat shares an identifier.

The cell rule is:

1. Apply an approved city/town polygon or a policy union of parts. Within it, report the canonical identity. Give independent-city boundaries priority at shared edges.
2. In an urban centre without a resolved city boundary, divide the remaining area among its same-country canonical anchors. The measured provisional rule protects a 1 km core around the nearest eligible anchor, then minimizes distance divided by the square root of population, with a 15,000 population floor. A city with an accepted limit cannot expand beyond it. Remove its part-anchors from competing independently.
3. For a small town outside GHSL with no usable polygon, test a radius of `sqrt(max(population, 5000)/(π × 3000))` km, clamped to 0.5–3 km and limited to towns of at most 50,000 people. The tested range is about 0.73–2.30 km. An overlap goes to the nearer eligible town. This is a fallback footprint, not a municipal boundary.
4. Elsewhere preserve the existing settlement answer. Retain rural village polygons and the nearest valid settlement within 50 km. Record nearest assignment, and flag distances above 25 km. Do not drop zero-population records merely because their population is missing.

One quality repair is still required outside the prototype's overlays: if the old answer came from an invalid broad city promotion, recompute the remaining rural polygon/nearest alternatives instead of retaining that old city. Chongqing is the clearest case. The overlay experiment deliberately leaves other existing answers in place; it has not simulated this full rural repair.

Record methods such as policy polygon, city polygon, urban allocation, town radius and rural nearest in `city_method`. Exact distance need not become a stored per-cell column; that would interfere with cell compaction. The place map's method should distinguish self, identity alias, policy part and spatial absorption.

### Fit to the existing pipeline

Insert normalization between `build_data.reconcile` and `build_data.golden`. The retained SQLite files already hold the points, divisions and rejected ward polygons needed here. A first implementation can read them without repeating the roughly one-hour world reconciliation. Reconcile must run again only when its source/link/classification output changes.

Checkpoint normalization by country, keyed by reconciliation digest, policy hash, GHSL hash and normalization version. Write a temporary output, validate it, then publish that country checkpoint atomically. A plain manifest supplies idempotence and resume; no review database is needed. Limit work to one country at a time and keep large joins bounded on the 8 GB M2.

Golden must recompute city labels and methods, regenerate affected canonical/place rows, rerun quality checks, and compact the resulting cells again. A compact parent cell may straddle a new footprint: simply replacing its `city_id` is insufficient. Reuse the existing country/state/land inputs, split affected parents to resolution 8 when needed, then recompact. Full golden rebuild time and extra disk use have not been measured; do not assume the reconciliation time also describes golden. Pilot one country, then use the existing resumable world build.

Later, if needed: cache a small Wikidata type/parent subset for disputed identities; add identity history when actual ID migrations occur; replace the policy file with a review interface only if it becomes unwieldy.

## Build in three measured steps

Each implementation phase ends in a pilot rebuild, the frozen anchor check, the fixed footprint census and the neighbour tests; a world rebuild follows only after its new independent-town errors are resolved. The table gives **simulation results**, not claims that a new dataset has been built. Country footprint repairs are applied before general inference.

| Phase | Change | Frozen check result | Cell effect |
| --- | --- | --- | --- |
| 1. Repair the known city footprints | Reconstruct Mumbai; clip Istanbul and the four Chinese municipalities to their urban cores; enforce Delhi, Kolkata, KL, NYC and existing London/Tokyo policy. | 29,286/34,171 (85.70%); 1 gained / 48 lost vs v1 | 9,399 additional city-labelled cells in the ten tested policy footprints (16,811 memberships). |
| 2. Add canonical urban allocation | Build the candidate table/map; screen polygons; allocate GHSL areas with core and boundary protection. Resolve weak village-seat eligibility and the observed new failures before release. | 30,358/34,171 (88.84%); 1,144 gained / 119 lost vs v1 | 1,031 sample cells change versus v1: about 1.03M worldwide affected cells. |
| 3. Add missing-town footprints | Enable the small-town radius only after inspecting its new failures. | 31,420/34,171 (91.95%); 2,217 gained / 130 lost vs v1 | 56 additional sample cells change: about 56,000 worldwide. This step fixes 1,073 checks and breaks 11 relative to phase 2. |

The first phase's anchor score falls even though its city footprints become coherent: 48 previously exact/credited observations are rolled up, including source-labelled Istanbul and Chinese city parts. One old mismatch becomes exact. Keep these as visible grading conflicts rather than changing expected labels to match the new output. This is why both anchor and footprint measures are necessary.

For the first world release, reproduce **at least 31,420/34,171 (91.95%) on the frozen diagnostic**, resolve the independent-town regressions, and preserve all six named neighbour anchors and every cell in their available polygons. On accepted single-city footprints, require at least **99% of eligible resolution-8 cells to return that city**; the policy prototypes reach 100%. London must retain its existing 100%, not expand into neighbouring towns to improve a metropolitan-cluster score. For Dhaka, the measured proxy share reaches 70.22%; its real municipal/built-up boundary still needs verification before setting a comparable city-interior target.

The sample expansions count changed labels, not independently confirmed fixes. They use the original sampling probability of 0.001: the final 1,087 changed sample cells imply about **1.09M affected resolution-8 cells**, with an approximate 95% sampling margin of ±65,000. There are 2,087 net check gains, 130 new mismatches and 62 previously exact 15,000–100,000-population observations that lose their own name. These pools overlap; do not add them.

Keep the 50 km rural cutoff in these first three phases. A subsequent quality-only rebuild can add the distant-nearest flag, resolve confirmed duplicate settlements and remove invalid region-wide city fallback. Publish its rural label changes and coverage separately; a cell-fix forecast for that rural rebuild is not available.

## What the prototype measured

All four candidate sets were counted worldwide. The assignment experiment covers all **34,171 checks**, the existing **200,267-cell probability sample**, and every available own/GHSL footprint in the top-500 cohort: **2,558,247 unique eligible resolution-8 cells** in the combined query set. It is not a relabelling of all 199.61M eligible cells. Country, state and land eligibility stay fixed.

“Top 500” means the largest on-disk GeoNames populations excluding section/historical/abandoned codes. This is the same reproducible cohort as the earlier diagnosis, including its suspect populations and identities. Stored coarse cells were resolved to their represented resolution-8 cells; footprint counts are complete censuses.

The original corrected expectations are frozen: credit the 1,905 supported sub-city checks, 212 city-state cases and 21 KL parts. This leaves the baseline **29,333/34,171 = 85.84%**. For exact comparability, all main tables keep those expected IDs. Applying the owner's newly explicit New Delhi→Delhi and Brooklyn→New York expectations changes two rows, leaves the baseline count unchanged, and raises the final result from **31,420 (91.95%) to 31,422 (91.96%)**. No duplicate pool is credited wholesale, and no expected answer is inferred from the simulated winner.

### Four mechanical candidate definitions

Counts below are distinct identities after the existing city-state, London/Tokyo policies and the explicit New Delhi/Brooklyn roll-ups. GeoNames links consolidate source divisions; unlinked Overture identities remain separate. All sets protect the six existing linked city-class/section-code conflicts; Navi Mumbai and Taketa survive every definition.

| Set | Mechanical definition | World identities |
| --- | --- | --- |
| A: typed | Overture locality class city or town; active linked populated place or unlinked Overture identity. | 115,920 |
| B: population/seats | Active GeoNames populated places with population ≥15,000, or administrative-seat codes PPLC/PPLA through PPLA5; exclude PPLX sections except protected conflicts. | 103,240 |
| C: union | A or B. | 169,555 |
| D: strict union | C, then population ≥5,000 or explicit city class or national/first-order capital; exclude sub-city type/name signals except protected conflicts. | 59,243 |

| Country | A: typed | B: population/seats | C: union | D: strict |
| --- | --- | --- | --- | --- |
| CN | 33,776 | 15,442 | 37,478 | 5,432 |
| IN | 4,720 | 3,784 | 6,273 | 4,604 |
| US | 7,815 | 5,384 | 8,905 | 5,642 |
| JP | 1,539 | 1,289 | 1,828 | 1,622 |
| GB | 1,648 | 1,808 | 2,691 | 1,346 |
| BD | 519 | 137 | 554 | 175 |
| TR | 1,019 | 1,637 | 1,734 | 763 |
| MY | 491 | 358 | 654 | 433 |
| BR | 3,388 | 2,674 | 3,791 | 3,361 |
| ID | 2,087 | 9,260 | 10,459 | 573 |
| RU | 2,586 | 2,182 | 2,874 | 2,191 |
| DE | 2,297 | 8,085 | 9,190 | 2,521 |
| FR | 1,173 | 802 | 1,279 | 1,162 |
| CA | 1,540 | 322 | 1,621 | 557 |

A drops the GeoNames identities for Lagos, Brasília, Sharjah and Depok from the absorbing list. B misses typed smaller towns and some explicit city/section conflicts such as Subang Jaya; it also omits unlinked Overture duplicates such as “Bogotá ciudad” while retaining the linked GeoNames Bogotá. C avoids those source omissions but admits both identities and many districts. D wrongly drops Belfast and Port-au-Prince because conflicting linked records trigger its broad sub-city screen. Removing candidates does not remove their raw records or automatically change rural answers.

The hard district cases are measurable. Before policy, **507** typed candidates have the GeoNames section code PPLX, including **52** explicitly typed cities. After policy, A/B/C/D retain respectively **575/58/588/6** explicit sub-city signals. Their source records also contain the word “district” for **2,358/2,410/2,757/1,613** identities; C has **15,850** administrative twins. These evidence sets overlap. They include genuine city-counties, so a district-word blacklist would also remove Munich, Bangkok and other cities.

Kadıköy (744906) has town and district evidence, zero recorded population and an administrative twin: A/C keep it, B/D omit it. Esenyurt (747323) is a district/town with 983,571 people and passes all four. Setagaya (11790342) has 940,071 people, PPLX and city class; A would keep it before the existing Tokyo policy removes it. Overture's retained ancestry, administrative twin, local type and policy membership separate these better than the published `parent_id`. Country policy is still needed to say that an Istanbul district is a city part while Navi Mumbai is independent.

B contains **71,685 candidates below 15,000 population**, **30,617 with zero population**, and **37,819 with some village/hamlet evidence**. This is the main unresolved eligibility risk in the otherwise strongest candidate list. Keep those raw settlements; require stronger evidence before giving a weak village-seat candidate a city/town footprint.

### Assignment results

All variants start with the same polygon screen: eligible identity; locality/localadmin/county source rather than an unapproved region; compatible settlement class; and anchor inside the grouped polygon. Existing explicit policy areas pass. This admits 52,231 identities from 52,534 area parts. It rejects the tiny village polygon incorrectly linked to Dhaka and rejects 73 region parts. It is a mechanical screen, not a municipal-boundary audit; some remaining administrative containers account for new failures.

Within GHSL, nearest and weighted variants use only anchors in the same urban centre and country. The weighted variant minimizes distance / √max(population, 15,000). Outside the new footprints, v1 stands. “+ town radius” adds the missing-footprint experiment described in the design. The baseline for every row is **29,333 / 85.84%**.

| Set | Candidates | Nearest urban | Weighted urban | Weighted + town radius | Checks gained / lost |
| --- | --- | --- | --- | --- | --- |
| A | 115,920 | 28,332 / 82.91% | 28,423 / 83.18% | 28,629 / 83.78% | 1,006 / 1,710 |
| B | 103,240 | 30,323 / 88.74% | 30,376 / 88.89% | 31,438 / 92.00% | 2,226 / 121 |
| C | 169,555 | 30,034 / 87.89% | 30,133 / 88.18% | 30,777 / 90.07% | 1,598 / 154 |
| D | 59,243 | 30,121 / 88.15% | 30,168 / 88.29% | 31,000 / 90.72% | 1,798 / 131 |

The selected prototype starts with B, then adds a 1 km anchor guard, the explicit footprint repairs and known city limits. In cities with accepted limits, remove their parts as competing anchors and prevent the city from claiming the urban cluster beyond its boundary. Elsewhere retain weighted inference. It scores **31,420**, slightly below B's unbounded weighted/radius score of **31,438**, while respecting the named boundaries.

| Original failure pool | Pool size | B nearest | B weighted | Selected, before town radii | Selected, with town radii |
| --- | --- | --- | --- | --- | --- |
| Sub-city answer | 246 | 148 | 149 | 145 | 188 |
| Nearest answer changes after cell snapping | 1,131 | 522 | 530 | 522 | 984 |
| Duplicate/name variant | 196 | 49 | 48 | 48 | 139 |

These pools begin with zero credited cases. The final corrections are **188/246**, **984/1,131** and **139/196**, respectively. Duplicate/name agreement can improve without having solved the underlying identity link.

The town-radius extension changes 1,089 check answers: **1,073 become correct and 11 become wrong**, net +1,062. Its losses include Huocheng→Shuiding, Nyingchi→Bayi, Taliwang→Motong, Kāmthi→Yerkhera, Simpang Renggam→Kampung Simpang Renggam and Takeo→Phumĭ Véal Srê. Large recorded populations or displaced anchors can sit inside a smaller town's inferred radius. Resolve these conflicts using source identity and town boundaries; do not override them simply to make the benchmark exact.

The 1 km urban anchor guard alone fixes 44 checks and loses 18 relative to unguarded B, net +26. Several losses are duplicate centres or parts of KL/Bangkok; the explicit KL footprint restores its accepted roll-ups. This guard protects a centre, not an entire independent city's territory.

### The large cities

Two fixed denominators are reported. The GHSL table below covers the **whole connected urban cluster containing each anchor**, including independent neighbouring cities. Its expected-city share is a fragmentation diagnostic, not a city-accuracy percentage to maximize. The own-footprint table in the appendix retains the original administrative extents, including overlarge ones. Footprint memberships overlap across cohort cities, so aggregate counts are sums of memberships.

Each result is **share returning the named city; number of distinct answers**. The final column includes known boundary limits; it does not merge entire metropolitan areas.

| City | Eligible cells | V1 | Nearest B | Weighted B | Selected bounded rule |
| --- | --- | --- | --- | --- | --- |
| Dhaka | 8,150 | 0.06%; 3,404 | 0.72%; 20 | 70.40%; 18 | 70.22%; 20 |
| Istanbul | 1,556 | 0.51%; 114 | 1.03%; 30 | 63.82%; 27 | 81.62%; 4 |
| Mumbai | 1,090 | 0.18%; 69 | 30.64%; 11 | 56.06%; 9 | 52.84%; 8 |
| Delhi | 2,789 | 44.71%; 321 | 46.76%; 29 | 60.81%; 21 | 46.76%; 15 |
| Kolkata | 3,067 | 7.92%; 381 | 8.51%; 40 | 69.58%; 40 | 7.92%; 40 |
| Tianjin | 1,320 | 28.11%; 69 | 0.15%; 78 | 57.50%; 30 | 100.00%; 1 |
| Shanghai | 5,542 | 24.27%; 91 | 0.32%; 74 | 46.32%; 67 | 95.78%; 6 |
| Tokyo | 7,621 | 12.85%; 178 | 12.60%; 123 | 14.74%; 124 | 12.60%; 124 |
| London | 2,488 | 84.57%; 105 | 84.57%; 36 | 93.29%; 20 | 84.57%; 17 |
| New York | 4,082 | 28.12%; 222 | 28.10%; 108 | 44.22%; 112 | 28.10%; 111 |

The unbounded weighted result wrongly encourages London, New York and Kolkata to expand beyond their known city limits. The selected rule keeps the lower, appropriate shares in those shared clusters. Conversely, Shanghai and Tianjin's approved urban portions lose their district fragments.

| Fixed top-500 footprint set | Before → selected: city share | Before → selected: summed distinct answers | Before → selected: footprints with multiple answers |
| --- | --- | --- | --- |
| 279 original own footprints | 71.46% → 82.54% | 6,603 → 3,232 | 157 → 111 |
| 491 GHSL urban footprints | 21.17% → 39.82% | 63,702 → 5,890 | 460 → 354 |

Macro-averaging, giving each available city footprint equal weight, changes own-footprint share from **84.89% to 90.19%** and GHSL share from **36.14% to 72.46%**. The pooled shares above weight each cell membership equally, so broad Chinese administrative areas dominate the own-footprint total.

Useful single-city footprints can already be recovered:

| City / footprint | Eligible cells | V1 city answers | After policy | Distinct answers before → after |
| --- | --- | --- | --- | --- |
| Mumbai | 707 | 2 (0.28%) | 707 (100%) | 48 → 1 |
| Istanbul | 1,270 | 6 (0.47%) | 1,270 (100%) | 103 → 1 |
| New York | 1,379 | 1,375 (99.71%) | 1,379 (100%) | 5 → 1 |
| Shanghai | 5,308 | 1,345 (25.34%) | 5,308 (100%) | 86 → 1 |
| Tianjin | 1,320 | 371 (28.11%) | 1,320 (100%) | 69 → 1 |
| Tokyo (23 wards) | 1,009 | 1,008 (99.90%) | 1,009 (100%) | 2 → 1 |
| London (33 members) | 2,388 | 2,388 (100.00%) | 2,388 (100%) | 1 → 1 |

Mumbai's 24 administrative wards are retained as district polygons. Their union supplies the missing footprint without a download; [BMC's ward map](https://portal.mcgm.gov.in/irj/portal/anonymous/BMC-on-Map-Wards-Offices?guest_user=english) confirms the 24-ward organization. Istanbul uses its connected GHSL extent intersected with the retained province boundary; [the municipality's jurisdiction description](https://ibb.istanbul/ibb/belediye-hakkinda/yetki-alani/) supports the district/province relationship. NYC's [five boroughs](https://portal.311.nyc.gov/article/?kanumber=KA-02877) roll up to its existing municipal identity. These establish policy membership; the retained geometry still needs the boundary spot checks below.

Dhaka remains the important missing-boundary case. Its linked village polygon is one cell, and no usable city-wide boundary was found. GHSL provides a broad 6,611 km² cluster, not a Dhaka municipality. The selected rule changes 3,404 names to 20 and gives Dhaka 70.22% of that cluster; independent places and the urban edge remain unresolved. Delhi's original own footprint improves from 1,811/1,820 to 1,820/1,820; Kolkata from 248/250 to 250/250. Tokyo's original 4,336-cell extent partly includes the prefecture and must not be used as a single-city target: the relevant 23-ward scope has 1,009 eligible cells.

### What it breaks or leaves uncertain

| Independent city | Own anchor, all variants | Available own polygon: v1 → selected | ~2 km anchor patch: v1 → selected |
| --- | --- | --- | --- |
| Noida | retained | 274/274 → 274/274 | 48/61 → 48/61 |
| Howrah | retained | — | 13/61 → 49/61 |
| Thane | retained | 212/212 → 212/212 | 43/61 → 42/61 |
| Navi Mumbai | retained | 155/155 → 155/155 | 55/56 → 54/56 |
| Yokohama | retained | 724/724 → 724/724 | 61/61 → 61/61 |
| Petaling Jaya | retained | 114/114 → 114/114 | 50/61 → 50/61 |

All six anchors survive, and all **1,479 cells** in the five available neighbour polygons retain the independent city. Howrah has no usable own polygon in this evidence. Within its 61-cell anchor patch, nearest B gives it 39 cells, unguarded weighting 28, and the protected-centre/bounded version 49. The remaining patch is not an adjudicated Howrah boundary. The selected rule also gives Thane and Navi Mumbai one fewer patch cell than v1 outside their retained own polygons. Those edge locations require review; anchor survival alone is insufficient.

The final 130 newly mismatching checks include **62 previously exact observations with populations 15,000–100,000**. Some are appropriate parts being absorbed, such as Istanbul neighbourhoods; others are unresolved independent-town losses. Examples needing investigation include **Porto Belo→Camboriú, Safranbolu→Karabük, Hoffman Estates→Schaumburg, Buffalo Grove→Wheeling, Loves Park→Rockford and Morton Grove→Niles**. An accepted administrative polygon can still be a township/container rather than the town. Exclude such polygons or protect the municipality using country/source evidence before release. The full loss list and the eleven radius-induced losses are saved in `rework/details.json`.

No single filter is ready to be declared a worldwide definition of a city. The measured gain supports building the small layer and reviewing its specific regressions; it does not justify shipping the mechanical candidate list unchanged.

### Rural quality: keep villages, improve evidence

After removing the selected city/town overlays, the sample contains **118,972 unchanged rural nearest answers**. Of these, **107,103 (90.02%)** have zero/missing population and 53,496 have village/hamlet class. Median anchor distance is **6.43 km**, the 90th percentile **30.81 km**, and the 99th **47.48 km**.

| Hard cutoff | Sample answers removed | Estimated cells removed | Overall sample coverage |
| --- | --- | --- | --- |
| 50 km | 0 | 0.000M | 80.25% |
| 35 km | 8,578 | 8.578M | 75.97% |
| 25 km | 17,608 | 17.608M | 71.46% |
| 10 km | 45,160 | 45.160M | 57.70% |

The selected overlay preserves overall sample coverage at **80.25%**. Use the **50 km hard cutoff already in v1**, and flag the 17,608 sample answers beyond 25 km as distant nearest. Their 14.80% share of remaining rural nearest answers measures distance, not how many are wrong. Do not substitute a district or empty field merely to improve a distance statistic.

A separate positive-population-only sensitivity test covers the ten countries with the most rural-nearest sample observations: RU, US, CA, CN, AR, AU, IN, KZ, CD and ID. Among **55,315 zero-population answers**, removing those anchors leaves **20,459 with no positive-population settlement within 50 km**; for 46,971 the closest positive anchor is over 5 km farther away. Its median distance is 34.82 km. This strongly argues against banning zero-population villages.

The same ten-country audit finds **142/62,278 sampled answers (0.23%)** associated with different entity IDs having the same normalized name within 1 km. These are duplicate candidates, not confirmed aliases. Resolve shared-source/QID duplicates where settlement type and location agree; otherwise retain the village and flag the conflict. Deduplication may reduce arbitrary name changes, but the measured pool does not explain the widespread long rural distances.

## A small, independent evaluation

Build **120 hand-checked points in one working day**: six points in each of the ten named large cities (60), four in each of the six independent neighbours (24), 18 small-town/edge points and 18 rural controls. Include interiors, ward centres and both sides of city boundaries. Reserve 80 before tuning; use 40 for development. An owner or agent can assemble the set from official municipal maps and address context, recording coordinates, expected settlement, source URL/date and a short reason. The owner need only settle ambiguous cases. Do not show predictions until the expected labels are recorded.

Report canonical settlement agreement, sub-city leakage inside cities, independent-city absorption, and rural distance/coverage separately. An initial acceptance goal is **at least 95% agreement on the 80 held-out points**, with no known independent-city identity failures, alongside the mechanical gates in the phase table. Publish ambiguous points rather than silently scoring them either way.

GeoNames cannot independently grade a layer whose anchors and population thresholds come from GeoNames. Wikidata also shares identifiers with these inputs, and GHSL becomes an input to the new rule. Keep the 34,171-point score as a reproducible diagnostic and the footprint counts as spatial consistency measures. The hand-checked points supply the separate judgment about actual city membership. No public-geocoder requests were made; use one only if its terms permit the particular sample and retention. The public [Nominatim policy](https://operations.osmfoundation.org/policies/nominatim/) is unsuitable for systematic reverse-geocoding grids.

Check ID references, same-country assignment, complete/self village mappings, acyclic policy roll-ups, valid geometry and deterministic rebuild/resume. Compare country totals and inspect the new-regression list after every rebuild. This is a small regression file and a country-policy file, not a review service.

## Supporting diagnosis

### Why the original numbers were misleading

Raw exact identity is **27,195/34,171 = 79.59%**. The old “exact or any containing area” score is **32,382/34,171 = 94.76%**; it credits overbroad areas as well as correct city membership. The provisional owner-rule baseline is **29,333 = 85.84%**, after the supported roll-ups described above. The 94.76% figure cannot be treated as owner-rule accuracy.

All 6,976 non-exact answers were classified using source codes/classes, links, hierarchy, winning areas and original-versus-cell-centre nearest lookup. The categories partition the observations; examples are in the appendix.

| Failure class | Count | Largest country counts |
| --- | --- | --- |
| Answer looks like a sub-city unit | 246 | ID 64; CN 52; VN 26 |
| Sub-city check correctly gets a larger city | 1,905 | US 255; CA 207; AU 191 |
| Sub-city check; roll-up unresolved | 412 | AE 34; AU 33; DE 31 |
| Existing city-state convention | 212 | HK 141; SG 64; MO 6 |
| Country/coverage disagreement | 67 | PS 47; CN 5; EH 4 |
| Duplicate or name variant | 196 | BR 59; US 36; JP 15 |
| Historical/abandoned check | 28 | RU 6; UA 5; IN 4 |
| Larger containing unit; identity unresolved | 2,239 | CN 664; US 216; JP 200 |
| Nearest changes after resolution-8 snapping | 1,131 | IN 288; ID 131; CN 107 |
| Other nearest mismatch | 49 | IN 4; TZ 4; ET 3 |
| No answer: ineligible check cell | 2 | GB 1; MG 1 |
| Other area/link mismatch | 489 | JP 42; CN 37; BR 36 |

There are **6,875,329 places**, of which **6,693,928 have role city**, and **4,312,887 distinct city IDs** used by cells. Explicit sub-city codes/types flag 22,718 places but only 130 used city IDs; adding name screens gives 38,583 places, 1,839 used IDs and 85,021 represented cells. These screens miss many urban fragments. Conversely, 3,237,866 places and 1,948,083 used IDs are village/hamlet class, appearing in **64,532,179 cells**. Under the owner's decisions those are valid in the countryside, not a global error count.

The published hierarchy has **zero city-valued parents**: 4,980,607 parents are states, 1,894,448 countries and 274 null. Raw Overture ancestry is richer, but strict hierarchy roll-ups changed only 21 failing answers into matches; the GHSL-constrained relaxed prototype moved 79. That contradicts the expectation that `parent_id` alone could deliver the improvement.

Away from benchmark anchors, 307 of 352 nearest answers sampled inside GHSL were zero-population or village/hamlet anchors. Only three were more than 10 km away, none more than 25 km. The urban problem is usually the **wrong nearby anchor**, not a distant one. There were no eligible empty cells in the sampled GHSL centres or the top-500 GHSL footprint census. Delhi, Dhaka, Istanbul and Mumbai all pass at their exact GeoNames anchors despite failing between those anchors.

### China, Malaysia and coverage

China's 121 regressions comprise **116 region promotions and five locality winners**. Of the region promotions, 115 return Chongqing and one Tianjin. The Chongqing answers are 40.2–384.5 km from their anchor; 114 exceed the 50 km nearest cutoff because an area assignment bypasses it. None lies in the Chongqing GHSL core. The selected prototype fixes **117/121**, versus **15/121 without the small-town radius**. Rural cells still inheriting the broad promotion outside these repaired footprints remain a separate quality problem.

Malaysia's 21 regressions are parts of Kuala Lumpur, supported by the city's [structure-plan zones](https://ppkl.dbkl.gov.my/en/pskl2020/) and retained city evidence. The unguarded global allocation preserves only two of those accepted KL roll-ups. Keeping the KL footprint explicitly restores **all 21**, while Petaling Jaya's own polygon remains separate.

Area-based assignment fell from 72,311,908 to 41,152,487 represented resolution-8 cells; nearest rose from 93,143,091 to 119,221,420; any-city coverage fell by **5,081,092**, to 160,373,907 of 199,608,564 eligible cells. V1 removed weak locality polygons, demoted administrative containers and tightened shared-identity requirements. Cells exposed by those removals fall back to nearest; beyond 50 km they become empty.

The retained rejected-polygon sample estimates that 25.50M ±2.76M current nearest cells and 5.27M ±0.82M current empty cells lie in rejected localities. Superseded v0 cells/databases are unavailable, so a cause-by-cause transition count for the exact 5.08M loss cannot be reconstructed. Under the new rural policy, preserving sensible village coverage matters; maximizing coverage by retaining an oversized city region is still wrong.

| Country | Checks | Old corrected agreements | Selected agreements | Gained / lost |
| --- | --- | --- | --- | --- |
| IN | 3,779 | 3,312 | 3,602 | 300 / 10 |
| US | 3,410 | 3,048 | 3,182 | 142 / 8 |
| BR | 2,377 | 2,246 | 2,304 | 59 / 1 |
| CN | 2,122 | 1,249 | 1,515 | 299 / 33 |
| JP | 1,301 | 1,033 | 1,072 | 39 / 0 |
| DE | 1,140 | 1,065 | 1,093 | 29 / 1 |
| RU | 1,109 | 1,055 | 1,069 | 14 / 0 |
| GB | 868 | 729 | 748 | 20 / 1 |
| ES | 736 | 691 | 701 | 11 / 1 |
| FR | 692 | 615 | 621 | 7 / 1 |
| IT | 662 | 610 | 618 | 9 / 1 |
| MX | 644 | 575 | 614 | 40 / 1 |
| PH | 530 | 422 | 445 | 23 / 0 |
| CA | 513 | 449 | 453 | 6 / 2 |
| ID | 450 | 233 | 425 | 193 / 1 |
| MY | 358 | 237 | 313 | 79 / 3 |
| TR | 432 | 407 | 390 | 6 / 23 |
| BD | 137 | 118 | 130 | 13 / 1 |

### Sources worth using

| Source | Evidence and acquisition decision |
| --- | --- |
| GeoNames | Already on disk; global codes/population/anchors, daily exports, CC BY 4.0. Use as identity and settlement evidence, not an independent grade. [Export](https://www.geonames.org/export/), [codes](https://www.geonames.org/export/codes.html). |
| Overture divisions | Existing 23 September 2026 release; global GeoParquet/retained SQLite, ODbL. Classes, local types, raw ancestry and ward polygons are useful. The published parent hierarchy is flattened. [Producer guide](https://docs.overturemaps.org/guides/divisions/). No replacement download needed. |
| **GHSL UCDB general characteristics** | **Adopt the already tested 6,902,089-byte ZIP**, containing a 9,457,664-byte GeoPackage plus CSV and 11,422 worldwide urban-centre polygons. R2024A V1.2, 2025 extent, updated package May/June 2026; CC BY 4.0; 1 km source grid, Mollweide coordinates. [Exact package](https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_UCDB_GLOBE_R2024A/GHS_UCDB_THEME_GLOBE_R2024A/GHS_UCDB_THEME_GENERAL_CHARACTERISTICS_GLOBE_R2024A/V1-2/), [overview](https://human-settlement.emergency.copernicus.eu/ucdb2024Overview.php), [attribution](https://human-settlement.emergency.copernicus.eu/GHSLhowToCite.php). No full indicators download is needed. It misses smaller towns and merges metropolitan neighbours, hence the radius/boundary tests. |
| Wikidata | Existing links cover about 14.9% of places. CC0, JSON/RDF, live API/weekly dumps. The retained 15-item sample helps distinguish boroughs/wards from independent cities. Later acquire only disputed candidate types/parents, initially capped at 100 MB; actual required size is unmeasured. [Official access guidance](https://www.wikidata.org/wiki/Help:Data_access). |
| Natural Earth urban areas | The tested 13,097,698-byte Shapefile ZIP is public domain, but its 2002–03 MODIS origin and cartographic 1:10m geometry are too coarse/old for production boundaries. GHSL covers 491 top-500 anchors versus 472 here. [Producer page](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-urban-area/). Do not adopt it. |
| Official municipal boundaries | Priority gaps are Dhaka, Howrah and the failed independent-town cases. First reuse retained boundaries; then acquire only the missing local layers after checking their specific format, licence and date. No particular new municipal download's size/licence has been verified. |

### What remains unverified

The mechanical city/town status of weak administrative seats; real boundaries for Dhaka, Howrah and small towns; the 130 new diagnostic mismatches; radius and weighted-allocation precision away from the sampled points; the exact v0→v1 coverage transition; rural repair after removing broad city promotions; and full production rebuild cost. The normalizer and new dataset have **not** been implemented. All protected inputs were opened read-only; this work changes only this document and scratch analysis files, with no git operations.

## Appendix A: original footprints and experiment details

The next table keeps the original on-disk own footprint exactly, even when it is too broad or too small to be the intended city. Each result is city share; distinct answers.

| City | Eligible cells | V1 | Selected |
| --- | --- | --- | --- |
| Dhaka | 1 | 100.00%; 1 | 100.00%; 1 |
| Istanbul | missing | — | — |
| Mumbai | missing | — | — |
| Delhi | 1,820 | 99.51%; 5 | 100.00%; 1 |
| Kolkata | 250 | 99.20%; 2 | 100.00%; 1 |
| Tianjin | 23,498 | 78.33%; 95 | 78.46%; 61 |
| Shanghai | 14,330 | 32.16%; 124 | 59.27%; 80 |
| Tokyo | 4,336 | 24.65%; 40 | 24.24%; 41 |
| London | 2,388 | 100.00%; 1 | 100.00%; 1 |
| New York | 1,379 | 99.71%; 5 | 100.00%; 1 |

The raw candidate counts before common policy are A 115,976; B 103,434; C 169,775; D 59,424. The four population/seat exceptions with lower populations alongside Navi Mumbai and Taketa are Gosford, Bongaree, Sakaide and Manzanillo; all six are already linked city-class/section-code conflicts in the current city catalogue. Raw Japanese wards remain inspectable even though existing policy removes them from the absorbing list.

The sample uses seed 20261002 and independent selection probability 0.001 for each represented resolution-8 cell, including pentagons. Method/country stratum counts and expansions remain in the scratch outputs. Country boundaries/eligibility are inherited from golden; the two ineligible anchor cells remain failures. The selected prototype's 1 km guard and radius formula are experiment parameters, not established city definitions.

### Full comparison across definitions

Pool entries below are corrected observations out of the original 246 sub-city answers, 1,131 snapping mismatches and 196 duplicate/name cases. Baseline credit in these pools is zero.

| Set / allocation | Sub-city answer | Snapping mismatch | Duplicate/name variant |
| --- | --- | --- | --- |
| A / nearest | 99 | 334 | 3 |
| A / weighted | 102 | 345 | 3 |
| A / weighted + town radius | 129 | 564 | 4 |
| B / nearest | 148 | 522 | 49 |
| B / weighted | 149 | 530 | 48 |
| B / weighted + town radius | 192 | 992 | 139 |
| C / nearest | 108 | 448 | 8 |
| C / weighted | 113 | 492 | 9 |
| C / weighted + town radius | 145 | 867 | 23 |
| D / nearest | 133 | 489 | 17 |
| D / weighted | 133 | 503 | 17 |
| D / weighted + town radius | 176 | 930 | 53 |

### A large-city GHSL results

| City | Nearest: city share; distinct | Weighted: city share; distinct |
| --- | --- | --- |
| Dhaka | 1.72%; 49 | 66.72%; 48 |
| Istanbul | 0.96%; 38 | 64.52%; 31 |
| Mumbai | 43.94%; 7 | 58.53%; 7 |
| Delhi | 46.79%; 14 | 61.13%; 14 |
| Kolkata | 7.96%; 38 | 68.37%; 37 |
| Tianjin | 1.67%; 26 | 47.65%; 20 |
| Shanghai | 0.49%; 93 | 20.41%; 92 |
| Tokyo | 12.60%; 126 | 12.92%; 126 |
| London | 84.65%; 29 | 92.48%; 24 |
| New York | 28.10%; 154 | 33.56%; 154 |

### B large-city GHSL results

| City | Nearest: city share; distinct | Weighted: city share; distinct |
| --- | --- | --- |
| Dhaka | 0.72%; 20 | 70.40%; 18 |
| Istanbul | 1.03%; 30 | 63.82%; 27 |
| Mumbai | 30.64%; 11 | 56.06%; 9 |
| Delhi | 46.76%; 29 | 60.81%; 21 |
| Kolkata | 8.51%; 40 | 69.58%; 40 |
| Tianjin | 0.15%; 78 | 57.50%; 30 |
| Shanghai | 0.32%; 74 | 46.32%; 67 |
| Tokyo | 12.60%; 123 | 14.74%; 124 |
| London | 84.57%; 36 | 93.29%; 20 |
| New York | 28.10%; 108 | 44.22%; 112 |

### C large-city GHSL results

| City | Nearest: city share; distinct | Weighted: city share; distinct |
| --- | --- | --- |
| Dhaka | 0.37%; 56 | 62.94%; 53 |
| Istanbul | 0.96%; 46 | 61.76%; 38 |
| Mumbai | 30.64%; 12 | 54.86%; 10 |
| Delhi | 46.76%; 31 | 60.81%; 22 |
| Kolkata | 7.96%; 51 | 66.87%; 50 |
| Tianjin | 0.15%; 81 | 46.59%; 33 |
| Shanghai | 0.32%; 107 | 17.45%; 99 |
| Tokyo | 12.60%; 128 | 12.77%; 128 |
| London | 84.57%; 42 | 91.52%; 28 |
| New York | 28.10%; 161 | 32.46%; 163 |

### D large-city GHSL results

| City | Nearest: city share; distinct | Weighted: city share; distinct |
| --- | --- | --- |
| Dhaka | 0.72%; 26 | 70.06%; 24 |
| Istanbul | 1.03%; 25 | 63.17%; 24 |
| Mumbai | 30.64%; 12 | 54.86%; 10 |
| Delhi | 46.76%; 29 | 60.81%; 21 |
| Kolkata | 7.96%; 44 | 67.59%; 43 |
| Tianjin | 1.67%; 16 | 84.62%; 9 |
| Shanghai | 0.49%; 35 | 65.34%; 33 |
| Tokyo | 12.60%; 124 | 13.40%; 124 |
| London | 84.57%; 38 | 92.36%; 25 |
| New York | 28.10%; 151 | 34.27%; 152 |

### Aggregate comparison across definitions

| Set / allocation | Own share; summed distinct | GHSL share; summed distinct |
| --- | --- | --- |
| A / N | 72.72%; 3,940 | 26.57%; 7,683 |
| A / W | 73.20%; 3,849 | 37.70%; 7,461 |
| B / N | 81.76%; 3,124 | 27.17%; 6,951 |
| B / W | 82.43%; 2,973 | 39.86%; 6,534 |
| C / N | 72.54%; 4,254 | 24.38%; 9,238 |
| C / W | 73.10%; 4,071 | 36.95%; 8,629 |
| D / N | 92.13%; 1,991 | 28.34%; 5,904 |
| D / W | 92.86%; 1,889 | 40.82%; 5,630 |

### Original failures by country

| Country | Sub-city answer | Sub-city check / larger city | Unresolved sub-city check | City-state | Country disagreement | Duplicate |
| --- | --- | --- | --- | --- | --- | --- |
| IN | 3 | 21 | 19 | 0 | 0 | 2 |
| US | 1 | 255 | 27 | 0 | 0 | 36 |
| BR | 0 | 99 | 0 | 0 | 1 | 59 |
| CN | 52 | 12 | 3 | 0 | 5 | 4 |
| JP | 2 | 70 | 8 | 0 | 0 | 15 |
| DE | 7 | 146 | 31 | 0 | 0 | 0 |
| RU | 0 | 120 | 1 | 0 | 0 | 12 |
| GB | 1 | 41 | 22 | 0 | 0 | 0 |
| ES | 0 | 189 | 0 | 0 | 0 | 1 |
| FR | 1 | 35 | 0 | 0 | 0 | 0 |
| IT | 0 | 63 | 1 | 0 | 0 | 0 |
| MX | 7 | 9 | 10 | 0 | 0 | 0 |
| PH | 0 | 10 | 0 | 0 | 0 | 7 |
| CA | 0 | 207 | 2 | 0 | 0 | 4 |
| ID | 64 | 0 | 1 | 0 | 0 | 0 |
| MY | 4 | 2 | 3 | 0 | 0 | 1 |
| TR | 1 | 0 | 14 | 0 | 0 | 0 |
| BD | 0 | 0 | 4 | 0 | 0 | 1 |

| Country | Historical | Larger unit | Snapping | Other nearest | No answer | Other area |
| --- | --- | --- | --- | --- | --- | --- |
| IN | 4 | 133 | 288 | 4 | 0 | 14 |
| US | 0 | 216 | 45 | 3 | 0 | 34 |
| BR | 0 | 35 | 0 | 0 | 0 | 36 |
| CN | 0 | 664 | 107 | 1 | 0 | 37 |
| JP | 1 | 200 | 0 | 0 | 0 | 42 |
| DE | 0 | 18 | 4 | 0 | 0 | 15 |
| RU | 6 | 27 | 1 | 0 | 0 | 7 |
| GB | 0 | 94 | 3 | 1 | 1 | 17 |
| ES | 1 | 35 | 0 | 0 | 0 | 8 |
| FR | 0 | 64 | 0 | 0 | 0 | 12 |
| IT | 0 | 47 | 1 | 0 | 0 | 3 |
| MX | 0 | 21 | 31 | 0 | 0 | 0 |
| PH | 1 | 61 | 22 | 1 | 0 | 16 |
| CA | 0 | 47 | 1 | 0 | 0 | 10 |
| ID | 0 | 7 | 131 | 1 | 0 | 13 |
| MY | 0 | 72 | 48 | 3 | 0 | 11 |
| TR | 0 | 6 | 4 | 0 | 0 | 0 |
| BD | 0 | 2 | 12 | 0 | 0 | 0 |

## Appendix B: twenty examples per failure class

These are the retained v1 observations, selected before the new simulations. The only class with fewer than twenty members is the two ineligible/no-answer cases; both are shown. Full evidence, all classified rows and country-by-class counts are in `classified-failures.json` and `country-categories.csv`.

### Answer looks like a sub-city unit (246)


| Country | GeoNames ID | Check place → v1 answer |
| --- | --- | --- |
| CN | 1792947 | Tianjin → 鼓楼街道 |
| CN | 1793511 | Taiyuan → Liuxiang Subdistrict |
| ID | 1625822 | Surabaya → Kapasari |
| EC | 3652462 | Quito → Dos Puentes |
| CN | 1795855 | Shaoxing → 府山街道 |
| CN | 1797945 | Qingyuan → Zhouxin Subdistrict |
| ID | 1627896 | Semarang → Mugassari |
| UG | 232422 | Kampala → Nile |
| CN | 1793505 | Taizhou → 城中街道 |
| ID | 8581443 | South Tangerang → Sawah Baru |
| CN | 1784990 | Zhanjiang → Haitou |
| CN | 1801180 | Maoming → Guandu Subdistrict |
| CN | 1797798 | Qingpu → 夏阳街道 |
| ID | 1631761 | Pekanbaru → Simpang Empat |
| CN | 13608002 | Fengxiang → Zhelin |
| CN | 1787957 | Xuhui → 枫林路街道 |
| CN | 1805540 | Jingzhou → 东城街道 |
| CN | 1789176 | Feicheng → Laocheng |
| ID | 1633419 | Padang → Olo |
| CN | 1790254 | Xiaogan → Guangchang Subdistrict |

### Sub-city check gets a larger city (1,905)


| Country | GeoNames ID | Check place → v1 answer |
| --- | --- | --- |
| CN | 11072148 | Puxi → Shanghai |
| CN | 1912214 | Nanhai → Foshan |
| CN | 13405906 | Luohu District → Shenzhen |
| CN | 1791351 | Wuchang → Wuhan |
| HU | 3046446 | Pest → Budapest |
| CO | 7033318 | Kennedy → Bogota |
| JP | 11790342 | Setagaya → Tokyo |
| CN | 1805701 | Jing’an → Shanghai |
| IN | 12069922 | Rohini → Delhi |
| CN | 1785412 | Zhabei → Shanghai |
| CN | 2050970 | Hondlon → Baotou |
| MX | 3514663 | Álvaro Obregón → Mexico City |
| CN | 2050971 | Qingshan → Baotou |
| JP | 11071717 | Edogawe → Tokyo |
| JP | 10987897 | Adachi → Tokyo |
| EG | 353225 | Madīnat an Naşr → Cairo |
| JP | 1861321 | Itabashi → Tokyo |
| US | 4951305 | South Boston → Boston |
| VN | 1585330 | Chợ Lớn → Ho Chi Minh City |
| VN | 1904564 | Bình Thạnh → Ho Chi Minh City |

### Sub-city check; nearest answer unresolved (412)


| Country | GeoNames ID | Check place → v1 answer |
| --- | --- | --- |
| IQ | 99071 | Al Mawşil al Jadīdah → Mosul |
| LB | 268743 | Ra’s Bayrūt → Hamra |
| IN | 1254745 | Teni → Allinagaram |
| IN | 6943660 | Shivaji Nagar → Pune |
| CN | 1809061 | Jiaojiang → Waidongcun |
| MY | 8504423 | Subang Jaya → Kampung Kenangan |
| IN | 1272866 | Dhārāvi → Kherwadi |
| IN | 10581114 | Jājmau → Purwa Bhikhāri |
| JP | 1863905 | Honchō → Minamihonchō |
| BD | 7696679 | Pallabi → Sekerkalsi |
| JM | 3489297 | New Kingston → Half Way Tree |
| BD | 11395976 | Mirpur Model Thana → Senpāra Parbata |
| PK | 11785389 | Wah Cantt → Losar Shafu |
| AE | 292261 | Dayrah → Bur Dubai |
| IL | 7498240 | West Jerusalem → Jerusalem |
| ZA | 8764562 | Diepsloot → Doornrandjies |
| IE | 6697759 | South Dublin → Firhouse |
| TR | 442301 | Batikent → Çakırlar Çiftliği |
| IN | 1277082 | Baranagar → Belgharia |
| CL | 3878431 | Ñuñoa → Providencia |

### Existing city-state convention (212)


| Country | GeoNames ID | Check place → v1 answer |
| --- | --- | --- |
| HK | 1819729 | Hong Kong → Hong Kong |
| SG | 1880252 | Singapore → Singapore |
| HK | 12747063 | New Territories → Hong Kong |
| HK | 1819609 | Kowloon → Hong Kong |
| HK | 12747064 | Hong Kong Island → Hong Kong |
| HK | 1931681 | Victoria → Hong Kong |
| MO | 1821274 | Macau → Macau |
| HK | 1818446 | Tuen Mun → Hong Kong |
| HK | 1818920 | Sha Tin → Hong Kong |
| HK | 1818953 | Sham Shui Po → Hong Kong |
| HK | 1818304 | Wong Tai Sin → Hong Kong |
| HK | 1819607 | Kowloon City → Hong Kong |
| HK | 1818506 | Tseung Kwan O → Hong Kong |
| HK | 1819595 | Kwai Chung → Hong Kong |
| HK | 1818209 | Tsuen Wan → Hong Kong |
| HK | 1818558 | Tin Shui Wai → Hong Kong |
| SG | 1880159 | Ulu Bedok → Singapore |
| SG | 1884382 | Bedok New Town → Singapore |
| HK | 1818673 | Tai Po → Hong Kong |
| SG | 7289760 | Sengkang New Town → Singapore |

### Country/coverage disagreement (67)


| Country | GeoNames ID | Check place → v1 answer |
| --- | --- | --- |
| PS | 7303419 | East Jerusalem → Jerusalem |
| PS | 281133 | Gaza → Gaza |
| EH | 2462881 | Laayoune → Laayoune |
| PS | 281124 | Khān Yūnis → Al-Mawasi |
| PS | 281129 | Jabālyā → Jabalia |
| PS | 285066 | Hebron → Hebron |
| PS | 282615 | Nablus → Nablus |
| CN | 13527315 | Santo António → Macau |
| PS | 281102 | Rafaḩ → Al-Mawasi |
| CN | 13527308 | Nossa Senhora de Fátima → Macau |
| EH | 2463447 | Dakhla → Lasarka |
| IL | 8199378 | Modiin Ilit → Modi'in Illit |
| PS | 281141 | Dayr al Balaḩ → Deir el-Balah |
| PS | 281145 | Bayt Lāhyā → Jabalia |
| PS | 284375 | Battir → Beitar Ilit |
| CN | 13527318 | São Lourenço → Macau |
| KE | 186180 | Moyale → Moyale |
| CN | 1808588 | Hekou → Bản Phiet |
| PS | 281577 | Ţūlkarm → Tulkarm |
| BR | 3665016 | Benjamin Constant → Islandia |

### Duplicate/name variant candidate (196)


| Country | GeoNames ID | Check place → v1 answer |
| --- | --- | --- |
| CN | 1792892 | Tianshui → Qinzhou |
| JP | 11611609 | Sagamihara → Sagamihara |
| TJ | 1221874 | Dushanbe → Dushanbe |
| BR | 6317344 | Jaboatão dos Guararapes → Jaboatão dos Guararapes |
| NP | 1282898 | Pokhara → Pokhara |
| JP | 11837657 | Ichikawa → Ichikawa |
| PH | 13118244 | Mandaluyong → Mandaluyong |
| CN | 12159964 | Chongzuo → Chongzuo |
| US | 4297983 | Lexington → Lexington |
| US | 4683416 | Corpus Christi → Corpus Christi |
| IR | 6861211 | Kāshān → Kashan |
| JP | 2130203 | Hachinohe → Hachinohe |
| BR | 3404545 | Cabo de Santo Agostinho → Cabo de Santo Agostinho |
| IR | 13405749 | Nasimshahr → Nasimshahr |
| IR | 6672634 | Nasīm Shahr → Nasimshahr |
| PE | 3934876 | Miraflores → Miraflores District |
| SA | 101732 | Unaizah → Unaizah |
| IR | 6657205 | Fardīs → Fardis |
| BR | 3406429 | Barcarena → Barcarena |
| BR | 3448031 | Sapucaia do Sul → Sapucaia do Sul |

### Historical/abandoned check observation (28)


| Country | GeoNames ID | Check place → v1 answer |
| --- | --- | --- |
| ES | 6544105 | Sant Martí → Barcelona |
| UA | 11778464 | Borshchahivka → Kyiv |
| JP | 1864031 | Fukayachō → Takabatake |
| RU | 481453 | Troparëvo → Moscow |
| UA | 13535745 | Pechersk → Kyiv |
| RU | 1485724 | Yurga → Staraya Yurga |
| AF | 1121381 | Bāzār-e Yakāwlang → Ākhundān |
| AU | 6949382 | Pittwater → Mona Vale |
| RU | 476368 | Vatutino → Moscow |
| RU | 518740 | Novokhovrino → Moscow |
| UA | 13580099 | Stare Misto → Kyiv |
| UA | 691743 | Telychka → Kyiv |
| PK | 1174301 | Khalabat → Jhamra |
| CI | 2292324 | Balakouya → Balokouya |
| SB | 2104533 | Panatina → Tambakokomu |
| SG | 1882402 | Kangkar → Singapore |
| RU | 521416 | Nikulino → Moscow |
| RU | 819552 | Annino → Moscow |
| PH | 1716858 | Cordova → Day-as |
| UA | 11776362 | Demiyivka → Kyiv |

### Larger containing unit; status unresolved (2,239)


| Country | GeoNames ID | Check place → v1 answer |
| --- | --- | --- |
| CN | 1790842 | Wuzhong → Jinxing |
| CN | 1798524 | Pudong → Shanghai |
| PK | 1168197 | Peshawar → Peshawar City Tehsil |
| CN | 13308620 | Bao'an → Shenzhen |
| PK | 1179400 | Faisalabad → Faisalabad City Tehsil |
| CN | 1798425 | Puyang → Jinhua |
| US | 5110302 | Brooklyn → New York |
| CN | 1800480 | Minhang → Xinzhuang |
| PK | 1177662 | Gujranwala → Gujranwala City Tehsil |
| CO | 3687925 | Cali → Cali ciudad |
| US | 5133273 | Queens → New York |
| CN | 1816917 | Baoshan → Shanghai |
| CN | 1794035 | Songjiang → Shanghai |
| MX | 3526683 | Iztapalapa → Mexico City |
| CN | 1793036 | Chengtangcun → Zaozhuang |
| CN | 7283386 | Changshu → Suzhou |
| PK | 1167528 | Quetta → Quetta City Tehsil |
| CN | 12358576 | Wanzhou → Chongqing |
| US | 5125771 | Manhattan → New York |
| CN | 1814870 | Yiwu → Jinhua |

### Nearest changes after H3 snapping (1,131)


| Country | GeoNames ID | Check place → v1 answer |
| --- | --- | --- |
| BD | 1200109 | Gazipur → Gazipur City Corporation |
| IN | 1273865 | Coimbatore → Kattūr |
| CN | 12359313 | Qingyang → Wulipu |
| SD | 379252 | Khartoum → Sheikh Habibullah |
| CN | 1797121 | Jieyang → 港墘村 |
| IN | 1258393 | Rasapūdipalem → Sītammapeta |
| CN | 8400694 | Taizhou → Xiayang |
| ID | 1622786 | Makassar → Parang |
| CN | 1797353 | Quanzhou → Heping Shequ |
| CN | 1804879 | Kaifeng → Lijing Shequ |
| KR | 1841811 | Gwangju → Ch’ungjang-dong |
| CN | 1804120 | Lianjiang → Dunzai |
| MG | 1070940 | Antananarivo → Manakambahiny |
| CN | 1801934 | Luohe → Xinhuajie Shequ |
| ID | 1642548 | Jepara → Donorejo |
| IN | 1263214 | Meerut → Tahsīl |
| CN | 1785294 | Anyang → Caihonglu Shequ |
| SN | 2244322 | Touba → Darou Khoudoss |
| NO | 3143244 | Oslo → Basarhallene |
| CN | 1788572 | Xinxiang → Wangtuncun |

### Other nearest-place mismatch (49)


| Country | GeoNames ID | Check place → v1 answer |
| --- | --- | --- |
| IN | 1278314 | Āsansol → Jaykaynagar |
| KE | 193627 | Karuri → Githuri |
| EG | 361179 | Al Ḩawāmidīyah → Munā al Amīr |
| MY | 1744246 | Seri Kembangan → Serdang |
| VN | 1591440 | Bắc Quang → Làng Quang |
| LK | 1229989 | Point Pedro → Puloli East |
| CN | 1808977 | Hanchuan → Huancheng |
| EG | 362865 | Abū an Numrus → Nazlat al Ashţar |
| RO | 665850 | Suceava → Trei Movile |
| VN | 1594402 | An Khê → Tân An |
| MG | 1070661 | Antanifotsy → Ilempona |
| IN | 13665129 | Nani Daman → Daman |
| GB | 2655198 | Bootle → Seaforth |
| SB | 2108502 | Honiara → Tamatangga |
| US | 4175117 | The Hammocks → Hammocks |
| BW | 933471 | Mahalapye → Thomadithotse |
| BW | 933685 | Kanye → Galosabanyana |
| DO | 3511336 | Boca Chica → Ensanche Bella Vista |
| GW | 2373235 | Contumo → Ponta Vasconcelos |
| ZM | 912072 | Katete → Matonje |

### No answer; ineligible H3 centre (2)


| Country | GeoNames ID | Check place → v1 answer |
| --- | --- | --- |
| GB | 2648827 | Garston → ∅ |
| MG | 1056487 | Soalala → ∅ |

### Other area/link mismatch; unresolved (489)


| Country | GeoNames ID | Check place → v1 answer |
| --- | --- | --- |
| TW | 12908892 | New Taipei City → Xinzhuang District |
| KR | 1838524 | Busan → Nampo-dong |
| BR | 3469058 | Brasília → Cruzeiro |
| GN | 2422465 | Conakry → Matam |
| IQ | 99532 | Basrah → حي الخليج العربي - الرابعة |
| PH | 1723510 | Budta → Northern Kabuntalan |
| IN | 1268295 | Kalyān → Kalyan-Dombivli |
| IN | 1253133 | Virār → Vasai-Virar |
| YE | 415189 | Aden → Aden City |
| AE | 292913 | Al Ain City → Industrial Area |
| CN | 13608000 | Jinshan → Lüxiang |
| IN | 1276014 | Bhayandar → Mira-Bhayander |
| OM | 287286 | Muscat → al Ghubrah al Shamaliyah |
| US | 4645421 | New South Memphis → Memphis |
| CN | 13608003 | Chongming → Gangyan |
| EG | 360829 | Al Maḩallah al Kubrá → Hussein Sayed Ahmed Ali |
| JP | 11836117 | Suginami → Ishioka |
| CN | 2036581 | Jiamusi → Changqing |
| CN | 12446699 | Daxing’anling → 塔河镇 |
| EG | 361320 | Al Fayyum → Forth District |

## Appendix C: files and reproduction

All paths below are under `data/work/city-analysis/`. The protected input manifest/quality hashes are recorded in `input-snapshot.json`; `rework/verification.json` checks their preservation and the reported counts.

| Evidence | Files |
| --- | --- |
| Four global candidate sets | `rework/candidates.py`, `rework/candidates.parquet`, `rework/candidate-summary.json`, `rework/policy-map.json` |
| Fixed query cells and footprints | `rework/common.py`, `rework/queries.py`, `rework/queries.parquet`, `rework/checks.json`, `rework/footprints/`, `rework/footprint-meta.json` |
| Main 20 simulations | `rework/simulate.py`, `rework/simulation/`, `rework/polygon-summary.json` |
| Core/policy/boundary variants | `rework/refine.py`, `rework/bounded.py`, `rework/refined/`, `rework/bounded/`, `rework/policy-repairs.json`, `rework/policy-footprints.json`, `rework/bounded-summary.json` |
| Before/after measurements | `rework/report.py`, `rework/check-scores.json`, `rework/check-results.json`, `rework/footprint-results.json`, `rework/footprint-aggregate.json`, `rework/sample-results.json`, `rework/details.py`, `rework/details.json` |
| Rural quality | `rework/rural_probe.py`, `rework/rural-positive-probe.parquet`, `rework/rural-positive-summary.json`, `rework/rural-duplicate-countries.json` |
| Retained diagnosis | `check-places.json`, `classified-failures.json`, `classification-summary.json`, `country-categories.csv`, `place-tags.parquet`, `city-cell-counts.parquet`, `ghsl-sample.parquet`, `coverage-audit.json`, `top500*.json` |
| Small sources and document generator | `sources/ghsl/`, `sources/ghsl-manifest.json`, `sources/wikidata-sample.json`, `rework/write_document.py` |

Reproduction order: `candidates.py`, `queries.py`, `simulate.py`, `refine.py`, `bounded.py`, `report.py`, `rural_probe.py`, `details.py`, `write_document.py`, `verify_rework.py`. Run with the project virtual environment and `PYTHONDONTWRITEBYTECODE=1`. Existing candidate/simulation checkpoints are reused; delete only the corresponding scratch checkpoint when changing a tested rule. The scripts never invoke git or write to normalized, reconciled or golden data. Total scratch use remains below 2 GB.
