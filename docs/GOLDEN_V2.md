# Golden v2 city normalization

**Status: boundary fixes and controller rework complete; pilot rerun in progress.** Golden v1 and
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
London 33, and New York five pinned borough identities. Delhi includes both the
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
  --review data/work/v2-pilot/review-notes.json --gate data/work/v2-pilot/gate.json
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

## Results and release decision

**World gate rejected.** `data/work/v2-pilot/gate.json` records `accepted: false`
for these exact sources, code, policy and reports. Golden v1 remains the active
world dataset. No world v2, refreshed world lookups, final world dataset card,
full-country transition census or holdout result exists. Nothing is still running.
The controller and final verifier are implemented but have not completed a world.

The pilot built nine country indexes, **29,319 canonical cities/towns**,
**2,697,403 place-map rows**, and **12,233 effective footprints**. Eligibility
withheld absorption from **13,971 weak administrative seats** in these countries.
This is not a world count of the plan's 37,819 village/hamlet-evidence candidates.

| Measure | Before | Radius off | Radius on |
| --- | ---: | ---: | ---: |
| Frozen diagnostic, raw exact / 12,857 | 9,944 | 10,966 | 11,254 |
| Frozen diagnostic, supported roll-ups / 12,857 | 10,366 | 11,384 | 11,672 |
| Correct cells in 696 accepted large-city footprints / 265,478 | 252,514 | 265,478 | 265,478 |
| Summed distinct answers in those footprints | 1,248 | 696 | 696 |
| Summed distinct answers in 5,374 country/urban-centre intersections | 103,277 | 29,282 | 29,282 |
| Named fixtures, including the eight added points | — | 21/21 | 21/21 |
| Required neighbour anchors | — | 6/6 | 6/6 |
| Required neighbour source-polygon cells | 1,479 | 1,479 | 1,479 |
| Hand-checked development points | 32/40 | 38/40 | 38/40 |

The urban-centre census covers 5,360 distinct GHSL IDs and 491,414 eligible
same-country centres. **307 country/centre intersections gain distinct answers**;
some removals of broad administrative promotions also fragment genuine cities.
The accepted-footprint result is 100% for every measured footprint. It checks
consistency within the accepted/effective geometry, not whether rejecting or
subtracting another source boundary was correct. The independent source-polygon
failures below demonstrate that distinction.

### Country diagnostic results

Each pair is raw exact / frozen roll-up agreement. This is the pilot subset of
the 34,171-point world check; there is no new world score. The reference expectations
are unchanged by tuning. Intended New Delhi→Delhi and Istanbul-part roll-ups can
therefore appear as visible grading conflicts.

| Country | Points | Before | Radius off | Radius on |
| --- | ---: | ---: | ---: | ---: |
| IN | 3,779 | 3,291 / 3,312 | 3,422 / 3,443 | 3,523 / 3,544 |
| BD | 137 | 118 / 118 | 128 / 128 | 130 / 130 |
| TR | 432 | 407 / 407 | 388 / 388 | 389 / 389 |
| CN | 2,122 | 1,237 / 1,249 | 1,877 / 1,885 | 1,942 / 1,950 |
| US | 3,410 | 2,793 / 3,048 | 2,842 / 3,097 | 2,892 / 3,147 |
| JP | 1,301 | 963 / 1,033 | 967 / 1,037 | 969 / 1,039 |
| GB | 868 | 688 / 729 | 697 / 738 | 704 / 745 |
| MY | 358 | 214 / 237 | 231 / 254 | 268 / 291 |
| ID | 450 | 233 / 233 | 414 / 414 | 437 / 437 |

### Neighbours and the failed gate

Both variants give the same following counts. All eleven probe anchors pass.
“Polygon” is the original source polygon, not just the accepted city footprint.
“Patch” is the eligible r8 disk of radius four around the anchor.

| Neighbour | Polygon before → after / eligible | Patch before → after / eligible |
| --- | --- | --- |
| Howrah | No source polygon | 13 → 49 / 61 |
| Noida | 274 → 274 / 274 | 48 → 48 / 61 |
| Thane | 212 → 212 / 212 | 43 → 42 / 61 |
| Navi Mumbai | 155 → 155 / 155 | 55 → 56 / 56 |
| Yokohama | 724 → 724 / 724 | 61 → 61 / 61 |
| Petaling Jaya | 114 → 114 / 114 | 50 → 50 / 61 |
| Safranbolu | No source polygon | 14 → 21 / 61 |
| Hoffman Estates | 74 → 60 / 74 | 20 → 29 / 61 |
| Buffalo Grove | 35 → 27 / 35 | 26 → 34 / 61 |
| Loves Park | 60 → 57 / 60 | 16 → 20 / 61 |
| Morton Grove | 17 → 17 / 17 | 16 → 20 / 61 |

Hoffman Estates loses **14/74**, Buffalo Grove **8/35**, and Loves Park **3/60**
source-polygon cells despite passing their own points. Their source `village`
classification is insufficiently distinguished from a weak rural village seat:
the current screening leaves these municipal boundaries as rural fallback,
then urban allocation can override them. This must be repaired with municipal
status evidence/policy before release; protecting more anchor points is not a fix.

Howrah has no source polygon. Keeping Kolkata inside its accepted boundary lets
Howrah retain an inferred urban patch: 13→49 of 61 cells. Thane's single lost patch
cell is outside its own boundary and goes to Mumbai; its entire source polygon
survives. Navi Mumbai's coastal patch improves to 56/56 after projection handling.
Safranbolu's raster-edge anchor is associated with its adjacent GHSL centre and
its patch improves 14→21/61; it also has no source polygon.

Of the plan's original **130** failed anchors, **80** are in the pilot. Radius off
retains the exact identity at 31 and the identity or explicit policy target at 78;
radius on gives 26 and 73. Of 38 original mid-sized-town cases in the pilot,
37 have the identity/policy target with radius off, 34 with it on. Zekeriya's
snapped cell lands in the Istanbul policy footprint; the other remaining off
identity mismatch is Kampong Baharu Cheras Batu Sebelas. The **50 nonpilot cases
remain unverified**. These are anchor diagnostics, not municipal-interior proof.

### Radius decision and remaining errors

**Leave radius off.** It adds a net 288 agreements on the frozen diagnostic,
introduces nine mismatches relative to off, and changes none of the measured
accepted footprints, neighbour patches, GHSL counts or development scores.
The nine new mismatches are Cheriyamundam, Kāmthi (→Yerkhera), Iringal, Zhangfeng,
Gengqing, Nyingchi, Gusong, Didao and Simpang Renggam. Source identity ambiguity and
nearby-town capture still need adjudication; candidate-point gains do not justify
turning on an inferred footprint with no demonstrated independent gain.
Both variants have 73 losses against the frozen baseline; some are intended
big-city roll-ups and others are real unresolved boundary/identity failures.

The development split improves to **38/40**, with large cities 18/20, neighbours
8/8, towns 9/9 and rural controls 3/3. Its two failures are Uttara in Dhaka→Tongi
and the Tianjin urban edge→Baoyuan. The 80 holdout rows have **not been scored**;
there is no verified final world on which to run the one-time evaluation.
Evaluation CSV SHA256: `9d6e6025775e8fb2ec849f63d3938739c7eae6ef79e2b5c7e219f2e260bdf601`. Nothing under `eval/` was edited by this work.

Dhaka has no verified municipal boundary in these inputs. Within GHSL centre
6090 and the same-country denominator of **8,148 cells**, distinct answers fall
**3,403→24**, and Dhaka's own answer rises **5→5,663 (69.50%)**. The plan's earlier
3,404 count used its prototype footprint/denominator; this census consistently
filters eligible same-country cells. This is a built-up allocation proxy and
still gives the wrong city at the independently labelled Uttara point.

Broad Chongqing promotion is clipped to the connected urban core; removed
administrative areas fall through to village polygons/50 km nearest instead of
remaining region-wide city answers. However, rejecting containers solely from
subtype is overaggressive elsewhere: **Yichang→Xiling, Fuxin→Haizhou,
Salem→Whitefield**. **Hanahan→Highland Park** follows an anchor-outside-boundary
rejection. **Mehsi→Motipur** and **Krishnagiri→Kādiganpalli** occur where the snapped
centre falls just outside an accepted boundary and the bounded city is excluded
from expansion. These are unresolved release blockers, not reasons to tune the
check's expected answers. The next pass must distinguish source/link defects,
municipal status, true parts and genuine independent neighbours.

### Stored pilot and verification

`uv run --no-sync python -m build_data.normalize_cells.pilot_blocks` materializes
14 probe blocks: **202,576** eligible r8 centres, **147,382** compact cells with
radius off and **147,514** with it on. Changed city counts are **18,735 / 19,073**;
all 12 named fixtures falling in these blocks pass through actual stored ancestor
lookup. Malaysia's actual 27,839-row catalogue is exported with the new columns;
all four normalization-reference checks are zero. The synthetic compaction test
also checks every child, verifies a no-op resume and rebuilds a corrupt artifact.

These transitions are **selected-block counts, not whole-country totals**.
Full method-transition matrices are recorded alongside them in
`data/work/v2-pilot-blocks/report.json` and each block checkpoint.

| Country in stored probe blocks | Eligible r8 | City changed, off | City changed, on |
| --- | ---: | ---: | ---: |
| BD | 20,739 | 4,397 | 4,412 |
| GB | 16,807 | 633 | 699 |
| IN | 53,669 | 5,284 | 5,397 |
| JP | 30,061 | 337 | 340 |
| MY | 11,499 | 1,151 | 1,233 |
| TR | 23,115 | 3,936 | 3,948 |
| US | 46,686 | 2,997 | 3,044 |

Local validation: **254 passed, 7 skipped** with `uv run --no-sync pytest`;
whole-repository `ruff check`, `ruff format --check` and strict `mypy` pass.
No external CI, push, PR, cloud publication, world build or v1/v2 swap occurred.
The world controller's resource behaviour, full joins and final stored-world
quality are unverified until the release blockers are fixed and the gate passes.

Disk at handoff: approximately **18 GiB free**; reconciled inputs **33 GiB**,
active golden v1 **2.6 GiB**, retained normalization generations **1.6 GiB**,
stored pilot **6.1 MiB**. No source restoration or cloud offload was needed.
