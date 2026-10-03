# Thereabouts reconcile: observations, entities and correspondence

Status: draft for owner review, 2026-10-04. Builds on the exploration memo
`docs/explorations/2026-10-04-point-conflation.md` (branch
`explore/georeconcile`) and the owner's decisions of the same day.

## 1. Purpose

Different datasets describe the same real-world objects with different
identifiers, positions, names and attributes, and the same source describes an
object many times over time. Thereabouts already solves one instance of this —
settlements across Overture, GeoNames and geoBoundaries — inside its pipeline
with hand-written policy. The owner wants that capability generalised and made
part of the product: a reconciliation layer that takes **observations** from
any number of sources, decides which observations are of the **same object**,
and produces **entities** with evidence, provenance and history.

Owner decisions (2026-10-04):

- it is part of Thereabouts, not a separate package;
- the correspondence model is the graph from the memo, generalised beyond two
  datasets to many sources and many observations per object;
- positions may be 2D or 3D;
- the data model is generic: a place, a POI, a sensor and its readings are all
  observations; time is optional (an instant, an interval, or none);
- points only for now; lines and polygons are parked.

Success means:

1. The existing settlement reconciliation can be expressed as a *policy* on
   this layer and reproduces today's decisions on the pilot countries.
2. A user with two POI feeds, or one sensor feed over time, gets entities,
   a crosswalk, explanations and an incremental update on the next release
   without writing matching code — only a policy.
3. Every decision is explainable from stored evidence, and every number in
   the docs comes from a script.

## 2. Where it lives

`src/thereabouts/reconcile/` — a subpackage of the `thereabouts` distribution,
importable only when the `reconcile` extra is installed:

```
pip install "thereabouts[reconcile]"      # numpy, scipy, pyarrow, geographiclib, rapidfuzz
```

The lookup client (`thereabouts.Geocoder`, the CLI, the Rust core) never
imports it. The pipeline depends on it: `pipeline/engines/reconcile/` becomes
a *policy adapter* over `thereabouts.reconcile` (section 9), and its
place-specific rules stay in the pipeline. Interchange is Arrow; GeoPandas is
supported through an adapter, never required.

## 3. Data model

All tables are Arrow; identifiers are opaque strings; every row carries its
source and release.

**Source** — `source_id`, `release`, `licence`, `crs` (horizontal and
vertical datum of its positions), `position_accuracy` prior (optional:
covariance or CEP with percentile), `trust` notes.

**Observation** — one source's record of one object at one time:

| field | type | notes |
|---|---|---|
| `obs_id` | string | `<source_id>/<release>/<record_id>` |
| `source_id`, `release`, `record_id` | string | |
| `kind` | string | source's object type (`settlement`, `restaurant`, `air_quality_station`, `reading`…) |
| `position` | struct, nullable | section 4; 2D or 3D with optional covariance |
| `time` | struct, nullable | `instant` or `{valid_from, valid_to}` (half-open, UTC); null = atemporal |
| `names` | list<struct{text, language, script, role}> | role: primary, alternate, abbreviation… |
| `identifiers` | list<struct{scheme, value}> | wikidata, osm, phone, website, device serial… |
| `attributes` | map<string, value> | typed values; schema per `kind` optional |
| `fingerprint` | string | content hash for change detection |
| `provenance` | struct | original CRS, transformations applied, ingest time |

**Candidate** — a proposed pairing from blocking: `obs_a`, `obs_b`,
`blocker`, `distance_m`.

**Evidence** — per candidate, typed and versioned: raw signals (distance and
its uncertainty, name comparisons per pair of names, identifier agreements,
kind compatibility, temporal overlap), missingness flags, policy version.

**Decision** — `decision_id`, `obs_a`, `obs_b`, `relation`
(`same_as` | `part_of` | `seat_of` | `replaced_by`), `status`
(`accepted` | `rejected` | `ambiguous` | `not_evaluated`), `score`,
`p_same` (nullable; only a calibrated model may set it), `evidence_id`,
`rivals` (the next-best candidates considered), `decided_by`
(`policy` | `model` | `review`), `policy_hash`.

**Entity** — a resolved object: `entity_id` (opaque, stable across releases
once assigned), `kind`, `members` (observations with `valid_from/valid_to` of
membership), `representative_position` (chosen or fused, with method),
`canonical_attributes` (per field: value, chosen-from observation, rule),
`history` (predecessor/successor entity ids with event: `created`, `merged`,
`split`, `retired`).

**Correspondence graph** — observations are nodes; accepted `same_as`
decisions are edges; entities are the connected components *under policy
constraints* (cardinality per source, temporal consistency, no transitive
bridging through weak edges). A **crosswalk** between two sources is a view:
for each entity, its members from source A × its members from source B, with
cardinality labels (1:1, 1:N, N:1, N:N) and unmatched records on either side
with reasons.

**Unmatched** is first-class: `obs_id`, `reason`
(`no_candidate` | `insufficient_evidence` | `ambiguous` | `excluded_by_policy`),
`best_candidate`, `best_evidence_id`.

## 4. Coordinate layer

`thereabouts.reconcile.geo`, usable on its own:

```python
Position(lat_deg, lon_deg, height_m=None, height_datum=None,
         covariance_enu_m2=None,   # 2x2 (EN) or 3x3 (ENU), symmetric
         epoch=None)
```

- Exchange form: WGS84 geodetic, named fields. Adapters convert from the
  source CRS and record the transformation; nothing is silently relabelled.
- **ECEF** (`ecef(positions, height="horizontal"|"known")`): metre-valued
  Cartesian coordinates for KD-trees. Horizontal mode projects to zero height
  so a radius query is conservative (chord ≤ geodesic; relative error ≤
  `s²/(24R²)`: 1 mm at 10 km). Known-height mode gives true 3D separation and
  requires compatible height datums; it is the 3D path for sensors and
  buildings.
- **Geodesic** (`surface_m`): Karney's inverse on the ellipsoid for reported
  distances and thresholds; haversine available for screening.
- **ENU** (`offset_enu(a, b, origin)`): local tangent-frame offsets for
  displacement vectors and covariance; `separation(a, b)` returns the metric
  distance and, when covariances exist, the Mahalanobis-type statistic
  `q = Δᵀ(Σa+Σb+Σrep)⁻¹Δ` with the frame recorded.
- Uncertainty: covariance is the stored form; CEP is converted with its
  percentile and model recorded; missing uncertainty becomes an explicit
  policy default with low evidential weight, never zero.
- Blocking: ECEF KD-tree per bounded partition with a halo (the spike
  measured 100% radius recall and the fastest time); H3/S2 available as
  partition keys for distribution, never as identity.

Scalar and Arrow-batch forms share units, null handling and validation.

## 5. Matching pipeline

Stages, each a plain function over Arrow tables, composed by `match()`:

1. **ingest** — adapters produce `Observation` tables (Arrow, GeoDataFrame,
   Parquet directory; the pipeline's normalized Parquet).
2. **block** — candidate pairs within a policy radius (ECEF KD-tree), plus
   identifier blocking (shared Wikidata/OSM/serial) regardless of distance up
   to a cap; across all pairs of sources, or within one source for
   deduplication and temporal tracking.
3. **features** — per candidate: distance and `q`; name comparisons (keys
   from the existing recipe: Unicode normalisation, casefold, diacritics,
   script-aware; per-pair-of-names Jaro-Winkler/token scores, alias roles and
   languages retained); identifier agreement/conflict; kind compatibility via
   a policy taxonomy map; temporal overlap or gap.
4. **score & decide** — the policy decides: rule-based with weights and
   gates (the default, inspectable), or a Fellegi–Sunter model fitted
   unsupervised (optional, Splink-style, produces `p_same`), or a user
   classifier; abstention produces `ambiguous` with rivals.
5. **assign** — connected components of accepted edges, then constraint
   resolution inside each component: cardinality per source (e.g. at most one
   observation per source per entity unless the policy allows duplicates),
   temporal consistency (two observations of the same source cannot be the
   same object if their validity intervals overlap, unless policy says a
   source may double-report), no transitive bridging through edges below a
   strong-link threshold. Exclusive 1:1 uses a maximum-weight matching.
6. **entities** — assign or carry forward `entity_id`s, choose representative
   position (policy: identified-source preference, or covariance-weighted
   fusion for compatible observations), select canonical attributes with
   per-field rules and provenance, and record history.
7. **explain** — `explain(decision_id | entity_id)` renders evidence, rules
   fired, rivals and assignment trace from stored artifacts, never by
   recomputation with newer code.

## 6. Time

Time is optional and generic:

- An observation has no time (reference data), an instant (a reading, a
  survey), or a validity interval (a listing active from–to).
- Temporal signals are features like any other: overlap, gap, order.
- **Tracking** is the same machinery within one source: observations of a
  sensor over time resolve into one entity with a membership timeline;
  a device replaced at the same station becomes `replaced_by` under a policy
  that distinguishes `station` from `device` identity.
- Entities carry `valid_from/valid_to` derived from members; retirement is a
  closed interval, absence from a partial release is unknown, not retirement.

## 7. Policy

A `Policy` is data (YAML or a dataclass), hashed into every decision:

```yaml
name: poi-default
object: establishment                 # what "same" means; documented choice
radius_m: 250
kinds: {compatible: [[restaurant, cafe], [pharmacy, chemist]], map: taxonomy.yaml}
signals:
  distance: {scale_m: 50, weight: 0.35}
  names:    {min_similarity: 0.85, weight: 0.45, languages: any}
  identifiers: {agree: +0.5, conflict: -1.0}
  time:     {require_overlap: false}
decide: {accept: 0.80, margin: 0.05, abstain_below: 0.60}
cardinality: {per_source: 1, allow_source_duplicates: false}
strong_link: 0.90                    # no transitive bridging below this
```

The pipeline's settlement rules become `settlement.yaml` plus a small adapter
module for the pieces that are code (class A/P requirements, Wikidata-first
with distance guard, seat/municipality conventions, rollups), kept in the
pipeline. The library has no place semantics of its own.

## 8. Persistence and incremental updates

`crosswalk.write(dir)` writes an immutable snapshot: `manifest.json` (inputs
with fingerprints, policy hash, software and model versions, CRS, licences,
table checksums), Arrow/Parquet tables for observations' identity columns,
decisions, evidence, entities, members, unmatched, history.

`update(previous_snapshot, new_observations)`:

- fingerprints decide which observations changed, appeared or disappeared;
- unchanged validated decisions carry forward; changed records and their
  assignment components are re-blocked and re-decided; new records may
  displace earlier choices, so components, not rows, are the unit of rework;
- entity ids are preserved; merges and splits are recorded as history events;
- review overrides carry forward and are flagged when their inputs changed;
- output is a new snapshot plus a delta (`unchanged`, `added`, `revised`,
  `retired`, `unresolved`).

## 9. Public API

```python
from thereabouts import reconcile as rc

a = rc.observations(table_a, source="vendor_a", release="2026-10", position=("lat", "lon"), names=["name"], kind="restaurant")
b = rc.observations(gdf_b,  source="vendor_b", release="r7")                     # GeoDataFrame adapter
s = rc.observations(readings, source="aq-net", release="2026-10-04", time=("observed_at",), position=("lat","lon","alt_m"))

result = rc.match([a, b], policy=rc.policy("poi-default"))      # any number of sources
result.entities; result.decisions; result.unmatched; result.crosswalk("vendor_a", "vendor_b")
result.explain(decision_id)

snap = rc.write(result, "xwalk-2026-10/")
nxt  = rc.update(snap, [a2, b2])                                 # next release
attrs = rc.transfer(result.crosswalk("vendor_a", "vendor_b"), b, fields=["phone", "category"], conflicts="retain")
canon = rc.conflate(result, position="prefer:vendor_a", attributes=field_policy)
```

Command line, in the existing `thereabouts` grammar, only after the Python
API has a user: `thereabouts reconcile match|explain|update …`.

## 10. Testing and validation

- Synthetic fixtures for every stage (two and three sources, duplicates
  within a source, temporal tracks, 3D positions, dateline and poles).
- Property tests for the coordinate layer (ECEF round trip, chord bound,
  ENU symmetry, covariance propagation).
- **Regression oracle:** the settlement policy on Belgium and Japan must
  reproduce the pipeline's current retained links (the spike's reference
  edges: 4,823 and 3,687) at ≥ 99.5% agreement, with every disagreement
  listed; the pipeline's byte-identical pilot proof then runs through the
  adapter.
- An independent labelled set (the memo's eight cases plus 200 reviewed
  pairs) for the generic POI policy, reporting precision, recall and
  abstention rate; no claim of POI accuracy beyond that set.
- Measured timings and memory from scripts on the M2 and recorded in docs.

## 11. Work packages

Each is one implementation plan, Codex-implemented and independently
reviewed, on branch `feat/reconcile` in its own worktree; the real workspace
stays read-only; nothing is published.

1. **Data model and coordinate layer** — Arrow schemas, `Position`, ECEF/
   geodesic/ENU/separation with 2D and 3D paths, blocking (KD-tree with
   halo, identifier blocking), adapters (Arrow, Parquet, GeoDataFrame),
   property tests; the `reconcile` extra in `pyproject.toml`.
2. **Features, policy, decisions, assignment, entities, explain** — the
   matching pipeline of §5 with the rule-based decider, constraint
   resolution, entity formation and `explain`; synthetic multi-source and
   temporal tests.
3. **Settlement adapter** — the pipeline's reconcile engine re-expressed as
   `settlement.yaml` + adapter over the library; regression oracle at
   ≥ 99.5% on BE/JP; the pipeline's reconcile stage switched to it only when
   the oracle passes and the identity handover shows zero stale.
4. **Persistence and incremental update** — snapshots, `update`, history
   events, override validity, delta report.
5. **Transfer, conflate, Fellegi–Sunter option, docs** — `transfer`,
   `conflate`, the optional unsupervised model producing `p_same`, the user
   guide with a POI walkthrough and a sensor-tracking walkthrough.

## 12. Out of scope

Lines and polygons (the contracts leave room: `Observation.geometry` can be
added beside `position` later); a hosted review UI; learned scoring beyond
the Fellegi–Sunter option; publishing; changes to the dataset's rules.

## 13. Open decisions for the owner

- Licence for the new code (the repo has no licence declaration yet).
- Whether the settlement switch-over (package 3) happens before or after the
  next dataset release.
- First external validation data: two POI feeds, or a sensor network feed,
  that we are permitted to use.
