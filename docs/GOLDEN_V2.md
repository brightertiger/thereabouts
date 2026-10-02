# Golden v2 city normalization

**Status: final pilot gate passed; detached world build in progress.** Golden v1 and
reconciliation remain intact. Do not interpret the city-plan prototypes, the
source-point diagnostic or a successful country checkpoint as a completed world.
The original failed pilot is archived under `data/work/v2-before-rework/`.
The regenerated pilot report is `data/work/v2-pilot/summary.json`; the process handoff
is `data/work/v2-progress.md`. Results and the gate decision are recorded below.

## Pipeline and reproduction

The normalizer is production code in `build_data/cities/`. It reads committed
reconciliation country databases and the acquired GHSL manifest. It never imports
or reads `data/work/city-analysis/`. Source membership, city-specific exceptions,
independent neighbours, exclusions, aliases and all numeric thresholds live in
`build_data/cities/policy.json`. Mumbai has 24 pinned source ward IDs, Tokyo 23,
London 33, Jakarta five mainland administrative cities, and New York five pinned borough identities. Delhi includes both the
Delhi and New Delhi municipal polygons.

The complete controller chain and clean-workspace commands are in
[DATA_PIPELINE.md](DATA_PIPELINE.md#acquired-sources-to-normalized-golden-data).
`build_data.golden` produces the base cells; `build_data.normalize_cells` expands
those cells at resolution 8 and normalizes city assignments. The base dependency
is verified and checkpointed under `data/base_cells/`, independently of the active
`data/golden` publication. No raw prototype output is an input.

```sh
uv sync --frozen
uv run --no-sync python -m build_data.rebuild_golden --data-dir data --through pilot
uv run --no-sync python -m build_data.normalize_cells review --data-dir data \
  --review docs/city-normalization-pilot-review.json --gate data/work/v2-pilot/gate.json
nohup uv run --no-sync python -m build_data.rebuild_golden --data-dir data \
  --through world > data/work/v2-world.log 2>&1 < /dev/null &
# Only after final world verification; do not tune against this result:
uv run --no-sync python -m build_data.normalize_cells score \
  --output data/golden-v2 --points eval/city_points/points.csv --split holdout
# Reuses the verified output and retains the old golden directory:
uv run --no-sync python -m build_data.rebuild_golden --data-dir data --through publish
```

A review-notes JSON contains `accepted`, a nonempty `review`,
`unresolved_losses: []`, `minimum_dev_correct`, and `boundary_exceptions` (empty
when none). The `review` command attaches source/base/GHSL/policy/code identities
and verified pilot, normalization and development file records, and refuses
failed spatial checks or unexamined accepted-boundary losses. Every exception
requires country, city ID, exact lost-cell count/destination counts, reason and
source reference. These review receipts cannot influence the assignment rule.

World completion requires `data/work/v2-run.json` and the output manifest to say
`completed: true`, with verified table and quality artifact hashes. The controller
marker `data/work/rebuild/run.json` identifies the current stage and its log.
An interruption resumes country/block checkpoints. `data/work/v2-progress.md`
records the live process state. Local activation keeps v2 artifact paths stable
and retains v1 as `data/golden-v1`; it does not delete or publish anything remotely.

## Rules and evidence

Absorbing candidates require an active settlement with population at least 15,000,
a national/first-order capital, or town/city classification with a seat or at least
5,000 people. Lower seats with only village/hamlet evidence cannot obtain urban
or radius authority simply from their seat code. Retain them as settlements.
The six existing linked city/PPLX conflicts retain reconciliation's explicit
shared-Wikidata city evidence. Existing city-state conventions remain policy.

Accepted municipal boundaries and approved policy unions precede inference.
A territorial locality may own a boundary even when its local title is village or
hamlet. A point-only weak village seat still cannot obtain a footprint. The source
anchor must be inside, or within 250 metres with a linked alternate anchor inside;
this accepts small source-coordinate discrepancies without enlarging a boundary.
Distant namesake polygons (Dhaka's tiny linked village) remain rejected.
Unapproved county/localadmin/region promotions and source-identified US townships
remain excluded. Salem's independent-city county representation is an explicit
policy approval. Yichang and Fuxin retain only GHSL-clipped prefecture cores.
Rejected broad area answers are repaired from remaining rural polygons and then
same-country nearest settlements. Chongqing's region-wide promotion is replaced
by its connected GHSL core and repaired rural alternatives.

Retained independent municipal boundaries win overlapping source territory.
Preserve the source precedence of linked municipalities over unlinked localities.
Store disjoint effective footprints, with the excluded boundary IDs and original
source-area evidence. This makes the 99% footprint measurement a **consistency
check**, not independent proof of a municipal boundary. Source boundary overlaps
such as Kolkata/Rajpur Sonarpur and Amherst/Williamsville stay inspectable.

Within GHSL, unbounded same-country candidates compete by distance divided by
square root of population (15,000 floor), with a 1 km nearest core. A candidate
within 1 km of a GHSL raster edge may join that centre: Safranbolu demonstrated
that exact anchor membership can exclude a town while its snapped cell lies
inside. This associates an anchor; it does not enlarge the GHSL geometry. Cities
with accepted boundaries cannot expand into the remaining metropolitan area.

Dhaka still has no verified municipal boundary. Its linked village polygon is
incompatible evidence; the output uses GHSL allocation among eligible cities and
towns. GHSL is a 1 km-grid urban extent, not a municipal boundary. Do not label its
Dhaka share as municipal accuracy.

The optional radius is `sqrt(max(population,5000)/(pi*3000))` km, clamped to
0.5–3 km, outside GHSL for unbounded candidates of at most 50,000 people. An overlap
goes to the nearest town whose own radius actually reaches the cell. The policy
currently leaves this **off**; gains at candidate anchors are circular evidence.
Rural nearest keeps an inclusive 50 km cutoff and marks distances above 25 km.
Offshore projection uses a 1e-9-degree numerical edge tolerance only for projected
water rows. The Mumbai development point exposed a 0.036 mm spherical/planar
shoreline discrepancy; this tolerance repairs it without giving a city a buffer.
Synthetic mixed-batch tests ensure land rows do not inherit that tolerance.
Exact boundary queries use prepared polygon coverage (including boundary edges),
not repeated zero-distance calculations against detailed outlines. Three Brazilian
blocks reproduced identical compact rows and transitions in 0.073–0.085 seconds
each, versus roughly 15 seconds with the distance predicate. The pilot was rerun
after this performance change; old world checkpoints are invalidated by code hashes.

## Artifacts and columns

Each country has content-addressed `city_normalized/<digest>/<CC>/index.sqlite`,
`canonical_cities.parquet`, `place_to_city.parquet` and a report. SQLite stores
canonical candidates, original accepted boundaries, effective footprints, explicit
parts and rejected area IDs.
Country keys include reconciled input hash, GHSL manifest, policy, implementation,
shared spatial helpers and runtime versions. Atomic temporary publication and
ledger hash verification make interruption and corruption resumable. A changed
implementation gets a new country output; reconciliation is never modified.

`canonical_cities` contains `city_id`, existing published `place_id`, country,
city/town `kind`, preferred names, anchor, population, eligibility, source IDs,
footprint references and allocation rule. `place_to_city` has a row for every
published place: `place_id`, nullable output `city_id`, `method`, `evidence`.
Methods distinguish self, policy part, identity alias, spatial absorption and
non-settlement. Standalone villages map to themselves; administrative records
without a city-part relationship map explicitly to null.

V2 `places` retains source evidence and adds `normalized_city_id`,
`normalization_method`, and `settlement_kind`. Absorbing identities have role
`city` or `town`; other formerly universal `city` records become `settlement`.
Other administrative roles remain available. Preferred canonical city names
replace conflicting part labels only on their canonical identity.

V2 cells retain all v1 keys and country/state/land fields. `city_method` becomes
`policy_polygon`, `city_polygon`, `urban_allocation`, `town_radius`,
`rural_polygon`, `rural_nearest`, `rural_nearest_distant`, or null. Every base
ancestor expands to its actual r8 descendants, city rules run at those centres,
Accepted city boundaries own their original cell centres, including water.
Otherwise offshore urban inference uses v1's spherical land projection, while
rural nearest distance still uses the original centre. Equal identities **and
methods** compact again. No exact per-cell distance
column interferes with compaction. Country and method transition counts are
recorded during block building, not estimated from a sample.

Spatial postal/airport/trade/IP joins refresh from final v2 cells, whose city IDs
join to canonical places. Direct place-ID consumers use `place_to_city`; no source
lookup names or coordinates are rewritten. Static lookup tables retain verified
source rows. The final verifier checks that every mapped/cell/canonical target
exists and that mappings never cross countries.

## Measurements and evaluation isolation

Pilot reports compare radius off/on over every accepted footprint of an absorbing
place with at least 100,000 people, every GHSL centre intersecting each pilot
country, named fixtures and independent-neighbour anchors, polygons and r8 disk-4
patches. Neighbour polygons come from the original reconciled source, including
polygons rejected by normalization; otherwise rejecting a boundary would hide its
losses. Only eligible same-country centres enter footprint denominators. Reports
include distinct answers, city share, source-point gains/losses and patch-loss
coordinates. These censuses use the production assignment engine on original r8
centres; the final world verifier reads actual stored v2 ancestors instead.

The diagnostic retains all GeoNames P records with population >=15,000, including
sections/history. Exact identity and supported roll-up credit are separate.
Roll-up credit uses the plan's frozen 2,138 supported exceptions (1,905 sections,
212 city-state cases and 21 Kuala Lumpur parts), now committed as pipeline
reference data in `diagnostic_expectations.json`. It never uses the new allocation
winner or newly inferred part maps to redefine expected answers. The original
130 regressions are also audited by `regressions.json`; points outside the pilot
remain untested until a world run. Neither score is independent accuracy.

`python -m build_data.normalize_cells score --output <golden> --points <csv> --split dev`
scores either golden schema through stored ancestors. It supports the hand-check
CSV's expected name, accepted names, GeoNames/Wikidata IDs, country and split.
Ambiguous rows are visible and separately counted. Holdout requires a completed
world manifest; the result is saved once and a changed snapshot is refused after
scoring. `build_data.cities.dev` selects only development rows for pilot tuning.
Nothing under `eval/` is changed or committed by this work.

## Pilot gate and rework results

The reviewed gate passed on **2026-10-02** for the final code and policy. The
world controller is running; final world results below will be filled only after
stored-output verification. V1 remains active during the build.

The nine-country pilot has **29,300 canonical cities/towns**, **2,697,403 place-map
rows**, and **12,503 effective footprints**. The final candidate table still
withholds urban authority from weak point-only village seats.

| Measure | V1 | Final radius off | Final radius on |
| --- | ---: | ---: | ---: |
| Frozen diagnostic, raw exact / 12,857 | 9,944 | 10,961 | 11,243 |
| Frozen diagnostic, supported roll-ups / 12,857 | 10,366 | 11,379 | 11,661 |
| Correct cells in nonempty accepted large-city footprints / 273,309 | 254,658 | 273,309 | 273,309 |
| Summed distinct answers in those footprints | 1,401 | 794 | 794 |
| Summed distinct answers in 5,374 country/urban-centre intersections | 103,277 | 29,416 | 29,416 |
| Named fixtures, including the eight added points | — | 21/21 | 21/21 |
| Required neighbour anchors | — | 6/6 | 6/6 |
| Required neighbour source-polygon cells | 1,479 | 1,479 | 1,479 |
| Hand-checked development points | 32/40 | 38/40 | 38/40 |

All **794 nonempty** accepted large-city footprints are at **100%**; three more
have no eligible same-country resolution-8 centres. Footprint denominators are
summed per geometry, not a unique world-cell count. The urban census covers 5,360
unique GHSL IDs and 491,414 eligible cells; 308 country/centre intersections gain
distinct answers. Reports retain every centre's before/after count, not just the
aggregate reduction.

Compared with the reviewed first implementation, the large-city footprint count
increases from 696 to 794 nonempty footprints, all still 100%; development remains
38/40 and all 21 named checks remain correct. Urban distinct answers increase
slightly from 29,282 to 29,416 as accepted independent municipal boundaries and
conservative extents are retained. The raw diagnostic changes 10,966→10,961 with
radius off; this candidate-anchor check is not the optimization target.

### All accepted boundaries, including small municipalities

The new independent-boundary audit enumerates **12,505 original accepted
boundaries**, before overlap subtraction or part roll-up, covering **2,795,090
summed eligible cells**. It compares each individual cell owned in v1, including
old identity aliases, with its v2 answer. Net gains cannot conceal losses.
Supported identity aliases and owner-approved part roll-ups are reported separately (5,399 cells).
There are **three lost cells across two identities**, all examined:

- **Dearborn: one cell** (`882ab2cda1fffff`) is outside the main municipal relation
  OSM `r134579` but inside both a secondary Dearborn way (`w1276063111`) and
  Dearborn Heights' municipal relation. V1 ranked the small duplicate way first;
  v2 retains Dearborn Heights. No cell is lost from Dearborn's main municipal
  boundary in this case.
- **London: two fringe cells** overlap the London policy union and separately
  retained Sunbury-on-Thames (`88195d368dfffff`) and Buckhurst Hill
  (`88194e684dfffff`) boundaries. Their anchors are outside the London policy
  extent. Independent municipal boundaries precede the broader union; neither
  neighbour loses its own polygon cells. This resolves overlapping source claims,
  rather than asserting an independently surveyed border.

Exact destinations, counts, source area IDs and evidence are bound into the gate
receipt. The audit is part of both pilot and final world quality generation.

### Municipal-village and container fixes

The general distinction is **territorial locality ownership**, not the English
word “city.” Hoffman Estates (`village`) and Loves Park (`hamlet`) have their own
territorial locality polygons; they now own those polygons. Buffalo Grove's
primary anchor is just outside its boundary, but its linked Overture anchor is
inside and the primary anchor is within the global 250 m discrepancy allowance.
The same evidence fixes Hanahan. This does not admit point-only village seats,
nonlocality containers, source-identified townships, or distant namesake polygons.

Salem is an independent city encoded as a county and is approved by data policy.
Yichang and Fuxin are broad prefecture containers: policy accepts only the
connected GHSL urban core, as for Chongqing. Accepted component geometry survives
roll-up to its containing city, preventing neighbour capture of fringe cells
outside a clipped core. Jakarta's five mainland administrative cities form an
explicit policy union; its island regency is excluded. The source grouping is
confirmed by the [Jakarta provincial description](https://jakarta.go.id/index.php/tentang-jakarta).
These named choices and their reasons/source IDs live in `policy.json`.

Mehsi and Krishnagiri have source anchors inside their accepted boundaries, but
the resolution-8 cell centres lie respectively **266.5 m** and **86.3 m** outside.
They return Motipur and Kādiganpalli. Their own polygon interiors survive; the
boundary is not expanded merely to preserve a diagnostic anchor.

### Independent neighbours

Both variants give the following results. All eleven anchors pass. “Polygon”
means the original source geometry, including geometry rejected by normalization;
“patch” is the eligible radius-four resolution-8 disk around the source anchor.

| Neighbour | Polygon before → after / eligible | Patch before → after / eligible |
| --- | --- | --- |
| Howrah | No source polygon | 13 → 49 / 61 |
| Noida | 274 → 274 / 274 | 48 → 48 / 61 |
| Thane | 212 → 212 / 212 | 43 → 42 / 61 |
| Navi Mumbai | 155 → 155 / 155 | 55 → 56 / 56 |
| Yokohama | 724 → 724 / 724 | 61 → 61 / 61 |
| Petaling Jaya | 114 → 114 / 114 | 50 → 50 / 61 |
| Safranbolu | No source polygon | 14 → 21 / 61 |
| Hoffman Estates | 74 → 74 / 74 | 20 → 23 / 61 |
| Buffalo Grove | 35 → 35 / 35 | 26 → 26 / 61 |
| Loves Park | 60 → 60 / 60 | 16 → 16 / 61 |
| Morton Grove | 17 → 17 / 17 | 16 → 16 / 61 |

The rework restores all **25** municipal interior cells previously lost by
Hoffman Estates (14), Buffalo Grove (8), and Loves Park (3). Howrah has no source
polygon: keeping bounded Kolkata inside its accepted geometry leaves Howrah an
inferred urban patch. Thane's single lost patch cell is outside its own boundary
and goes to Mumbai. Safranbolu's anchor can associate with the adjacent GHSL
centre within the global 1 km edge allowance; no footprint is enlarged.

Of the original 130 failed simulation anchors, 80 are in the pilot. Radius off
retains exact identity at 31 and identity or explicit policy target at 78;
radius on gives 26 and 73. Of 38 original mid-sized-town cases in the pilot,
37 retain identity/policy target with radius off, 34 with it on. The two remaining
off mismatches are Zekeriya (inside the Istanbul policy footprint) and Kampong
Baharu Cheras Batu Sebelas (an unresolved identity/extent case). These diagnostics
are separate from the all-boundaries census.

### Radius decision and remaining development failures

**Radius stays off**, as accepted by the owner. On adds a net 282 exact and
credited agreements on the circular source-point diagnostic, but no independent
development, footprint, neighbour or urban-centre benefit. It introduces eleven
new credited source-point mismatches: Cheriyamundam, Kāmthi, Iringal, Zhangfeng,
Gengqing, Nyingchi, Gusong, Didao, Ānwén, Taibai and Simpang Renggam. Nearby-town
capture and conflicting identities remain insufficiently resolved to justify
turning it on for the world.

Development remains **38/40**: large cities 18/20, neighbours 8/8, towns 9/9 and
rural controls 3/3. The pilot transforms only its nine countries; development
rows elsewhere retain the base answer until the final world score. **Uttara→Tongi** is a GHSL allocation edge without a real Dhaka
municipal boundary in the acquired inputs. The **Tianjin edge→Baoyuan** cell is
outside the acquired GHSL urban centre; enlarging the inferred city would need
additional extent evidence. Neither point receives a special guard. The
80-row holdout is reserved for the verified final world.

### Actual stored pilot blocks

Fourteen stored probe blocks contain **202,576 eligible resolution-8 centres**.
Radius off produces **147,394 compact rows**, with **18,560** changed city answers;
on produces **147,490 rows**, with **18,887** changed answers. All 12 named checks
in these blocks pass through stored ancestor lookup. Malaysia's 27,839-row
catalogue exports the new columns; all four mapping-reference checks are zero.
These are selected-block totals, not full-country totals. Per-country method
transition matrices are in `data/work/v2-pilot-blocks/report.json`.

## Final world verification

World build in progress. Counts, stored-output quality, joins, holdout, activation
and final disk state are not yet verified. See `data/work/v2-progress.md`.

Repository validation before the frozen world build: **266 passed, 7 skipped**;
whole-repository Ruff check, Ruff format check and strict mypy pass. No external
CI, push, PR or remote publication is part of this work.
