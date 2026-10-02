# Golden v2 city normalization

**Status: pilot complete; release gate failed; world v2 not built.** Golden v1 and
reconciliation remain intact. Do not interpret the city-plan prototypes, the
source-point diagnostic or a successful country checkpoint as a completed world.
The generated pilot report is `data/work/v2-pilot/summary.json`; the process handoff
is `data/work/v2-progress.md`. Results and the gate decision are recorded below.

## Pipeline and reproduction

The normalizer is production code in `build_data/cities/`. It reads committed
reconciliation country databases and the acquired GHSL manifest. It never imports
or reads `data/work/city-analysis/`. Source membership, city-specific exceptions,
independent neighbours, exclusions, aliases and all numeric thresholds live in
`build_data/cities/policy.json`. Mumbai has 24 pinned source ward IDs, Tokyo 23,
London 33, and New York five pinned borough identities. Delhi includes both the
Delhi and New Delhi municipal polygons.

From a new workspace (one process at a time on the 8 GB machine):

```sh
uv sync --frozen
V2_DATA=/absolute/path/to/data
uv run --no-sync python -m build_data.acquire all --data-dir "$V2_DATA"
uv run --no-sync python -m build_data.reconcile --data-dir "$V2_DATA"
uv run --no-sync python -m build_data.reconcile --world --data-dir "$V2_DATA"
uv run --no-sync python -m build_data.golden run --workers 1 --data-dir "$V2_DATA"
uv run --no-sync python -m build_data.cities --data-dir "$V2_DATA" \
  --countries IN BD TR CN US JP GB MY ID
uv run --no-sync python -m build_data.cities.pilot --data-dir "$V2_DATA" \
  --output "$V2_DATA/work/v2-pilot"
uv run --no-sync python -m build_data.cities.dev --data-dir "$V2_DATA"
```

The existing reconcile world gate also applies. Exact snapshot reproduction needs
its preserved inventories/raw bytes, not a fresh discovery of mutable GeoNames
exports. See [raw custody and restore](DATA_PIPELINE.md#raw-offload-and-restore).
On this machine, reuse `data/reconciled` and `data/golden`; do not rebuild or delete
those inputs. Only the 6.9 MB GHSL package requires an additional acquisition:

```sh
uv run --no-sync python -m build_data.acquire ghsl --data-dir data
```

After reviewing the pilot, a gate JSON must record `accepted: true`, the exact
normalization `builder()` hash, `policy: fingerprint(policy())`, verified source
`inputs`, `base` and `ghsl` hashes, `pilot_summary` and `normalization_manifest`
file records, a nonempty `review`, and an empty `unresolved_losses` list. The
selected off/on variant and all country report artifacts must still verify. An absent, rejected or stale gate refuses a world build.
**No accepted gate has been issued for this implementation yet.** The commands
below describe the implemented continuation; they are not evidence it ran.

```sh
nohup uv run --no-sync python -m build_data.golden_v2 run \
  --data-dir data --output data/golden-v2 --gate data/work/v2-pilot/gate.json \
  > data/work/v2-world.log 2>&1 < /dev/null &
# After cells, places and joins finish:
nohup uv run --no-sync python -m build_data.golden_v2 verify \
  --data-dir data --output data/golden-v2 \
  > data/work/v2-world-verify.log 2>&1 < /dev/null &
uv run --no-sync python -m build_data.golden_v2 score \
  --output data/golden-v2 --points eval/city_points/points.csv --split holdout
```

The world controller writes progress to `data/work/v2-run.json`. Publication is
complete only when **both** that marker and `golden-v2/manifest.json` say
`completed: true`. The verifier checks stored cells, catalogue references and
complete same-country mappings, footprint shares and original neighbour polygons
before setting them. Country quality checkpoints resume independently. V2 builds beside v1; these
commands do not swap or delete v1. No cloud resource or external publication is
part of this stage.

## Rules and evidence

Absorbing candidates require an active settlement with population at least 15,000,
a national/first-order capital, or town/city classification with a seat or at least
5,000 people. Lower seats with only village/hamlet evidence cannot obtain urban
or radius authority simply from their seat code. Retain them as settlements.
The six existing linked city/PPLX conflicts retain reconciliation's explicit
shared-Wikidata city evidence. Existing city-state conventions remain policy.

Approved policy unions precede inference. Generic absorbing footprints require a
compatible typed locality and a contained source anchor. Reject unapproved
county/localadmin/region promotions, incompatible linked village polygons and
US source areas explicitly identified as townships. Existing standalone village
boundaries remain rural evidence even when that village is large enough to be an
urban candidate. The rejected area IDs are recorded; when they supplied the base
answer, recompute other containing rural polygons and then same-country nearest
settlements, rather than keeping the invalid promotion. Chongqing's region-wide
promotion is replaced by its connected GHSL core and repaired rural alternatives.

Retained independent municipal boundaries win overlapping source territory.
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
canonical candidates, effective footprints, explicit parts and rejected area IDs.
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

`python -m build_data.golden_v2 score --output <golden> --points <csv> --split dev`
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

`uv run --no-sync python -m build_data.golden_v2.pilot_blocks` materializes
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
