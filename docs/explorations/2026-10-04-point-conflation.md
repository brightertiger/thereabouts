# GeoReconcile: point correspondence as a Thereabouts expansion

Decision memo — 4 October 2026; exploration at `7aa2e33`, not an implementation. Evidence: [throwaway spike](../../explore/point_spike.py) and
[measurements](../../explore/RESULTS.json). The owner's [idea note](../georeconcile_idea_note.html) was read by extracting its HTML text. Its central
proposition is a reusable correspondence abstraction with explanations and provenance. The point examples are POIs, sensors and addresses; vendor migration
and multi-source fusion also apply. Road topology, polygon splits and cross-geometry relationships remain future extensions.

## Recommendation

Build a small, independently versioned Python package named `georeconcile`, initially in this repository. Thereabouts' build pipeline should become a
client; its offline lookup clients should not depend on it. Start with versioned point correspondence, inspectable evidence and explicit unmatched
decisions. Use a settlement adapter to protect existing behavior, then validate with a real POI design partner. Do not promise a universal identity model,
calibrated confidence or production POI accuracy from this spike. The best reusable asset is the existing evidence-and-policy discipline, not a ready-made
generic matcher.

The measured experiment supports ECEF KD-tree blocking and exposes why identity semantics matter more. Belgium and Japan have usable retained reference
links, but their normalized Overture input is **divisions**. Despite the filename `places`, these are settlement/administrative representative points, not
business POIs. Neither sensor identity, address parsing nor restaurant deduplication was evaluated here. The general library opportunity is credible;
demand for its release-maintenance workflow still needs validation.

## What correspondence means

A feature record is a source's observation of an object at a stated time and level of granularity. A point is its representative position, not its
identity: two objects can occupy the same coordinate. A match asserts a particular relationship between versioned records under an explicit identity
policy. “Same” must be defined before optimizing a score, because different applications want different objects.

| User/workflow | Object whose continuity matters | Dangerous shortcut |
| --- | --- | --- |
| POI deduplication | A particular establishment/site or branch during an operating interval | Same chain, building or phone switchboard means same branch |
| Vendor migration | The customer's chosen object definition, translated into the next vendor's records | Nearest vendor point must be a replacement |
| Multi-source fusion | One agreed object with conflicting observations retained | Repeated upstream claims are independent votes |
| Incremental releases | Object continuity despite source record edits, renames and retirement | An unchanged ID or coordinate proves unchanged identity |
| Settlement lookup | A named settlement, distinguished from its municipality, seat and district | Administrative containment is identity |
| Sensor reconciliation | A physical instrument, installation, or station, as the application chooses | A replacement instrument at the same site is the same sensor |

For POIs, an entrance and a rooftop may represent one establishment; a café inside a hospital usually does not. For settlements, a municipality and its
seat require an explicit equivalence convention or a `seat_of` relation. For sensors, store station identity separately from device identity and
installation validity intervals. A moved device may retain device identity while its installation changes; a changed coordinate alone is inconclusive.
Source country codes are useful blocking hints but cannot be an unconditional identity veto near borders.

The correspondence model is a versioned bipartite graph with relationship groups, not just a joined table. A `1:1` group contains one record on each side;
`1:N` and `N:1` describe source multiplicity explicitly. “Left” and “right” are declared datasets, so reversing a crosswalk reverses cardinality. Unmatched
records remain first-class results, with `no_candidate`, `insufficient_evidence`, or `ambiguous` reasons. Candidate edges may overlap; accepted groups obey
the configured cardinality and relationship rules. An ambiguity set is not a `1:N` match: several plausible alternatives should remain unresolved.

Use `same_as` for identity; reserve `part_of`, `seat_of`, and `replaced_by` for different semantics. A pair of duplicate source records can legitimately
produce a `1:N same_as` group. A campus-to-departments relation can be `1:N part_of`, without pretending all departments are one object. Temporal
split/merge events refer to predecessor/successor groups; multiplicity alone does not prove an event. Keep group members as rows in a membership table so
later `N:N` groups do not require a new storage model. Do not infer identity transitively through weak links: a chain can bridge two neighboring branches.

Each decision carries raw evidence, transformations, missingness, score components, thresholds and rejected rivals. Store `score` separately from nullable
`p_same`; only a validated calibration model may populate the latter. The confidence definition, calibration population and model version belong with the
probability. Confidence that a place exists, positional accuracy, pairwise identity and assignment certainty are distinct. For a group, report its own
evidence and weakest/contested memberships rather than multiplying dependent scores. Human overrides carry an author/reason, timestamp and the input
versions they reviewed.

A persistent crosswalk is an immutable, reusable mapping artifact, independent of either source table. Record dataset namespace, source record ID, release,
content fingerprint, canonical entity ID and relation ID. Also record policy/model hashes, evidence schema version, creation time and superseded decision
IDs. Keep canonical IDs opaque and allocated independently of mutable coordinates or display names. A crosswalk revision can retire a decision without
deleting its history or reusing an entity ID.

On a new release, compare manifests/fingerprints and carry unchanged validated decisions forward. Consume trustworthy source redirects; re-score changed
records and affected neighboring assignment components. New records can displace earlier choices, so processing only rows marked changed is insufficient.
Deleted records close validity intervals; absence from a partial release means unknown coverage, not deletion. Preserve review overrides while flagging
material input changes that invalidate their assumptions. Publish a new atomic snapshot and delta: unchanged, added, revised, retired and unresolved
decisions. This is substantial new work: Thereabouts documents that existing place IDs are not stable across monthly versions. See [dataset identity and
method contracts](../DATASET_README.md), especially `places` and `place_to_city`.

## Coordinate layer

Exchange WGS84 geodetic latitude/longitude in degrees; accept ellipsoidal height in metres when known. Use named fields to prevent the latitude/longitude
versus GeoJSON x/y order mistake. An adapter must know the source CRS, transform it, and retain the original CRS and transformation provenance. Do not
silently relabel a projected, regional-datum or GCJ-02 coordinate as WGS84. Retain a coordinate epoch when the source supplies one, particularly for
precise sensors.

Minimal conceptual type, represented as Arrow columns/structs rather than Python objects per row:

```python
Position(lat_deg: float, lon_deg: float,
         height_m: float | None = None,
         height_datum: str | None = None,
         covariance_enu_m2: tuple[float, ...] | None = None,
         epoch: str | None = None)
# Schema fixes horizontal CRS to WGS84; input provenance retains source CRS.
# Covariance is a tagged symmetric 2x2 horizontal or 3x3 ENU matrix.
```

Height means ellipsoidal height after conversion; retain the original vertical datum in provenance. Orthometric elevation needs a stated geoid model (`h =
H + N`) before combining it with ellipsoidal heights. Missing altitude remains null; assuming zero for the horizontal index is a projection policy, not a
measurement. The available normalized place schema has no altitude or calibrated positional covariance. Most business POI feeds likewise need a horizontal
matching path; floors and units belong in attributes. Two different floors may share horizontal coordinates and still represent distinct establishments.

Convert horizontal positions to WGS84 ECEF at zero ellipsoidal height for an in-memory KD-tree. For latitude φ, longitude λ, semi-major axis a and
eccentricity squared e²: `N = a / sqrt(1 - e² sin²φ)` and `(X,Y,Z) = ((N+h)cosφcosλ, (N+h)cosφsinλ, (N(1-e²)+h)sinφ)`. This gives metre-valued Cartesian
coordinates without dateline discontinuity or polar longitude scaling. [PROJ documents geodetic-to-Cartesian
conversion](https://proj.org/en/stable/operations/conversions/cart.html). Never build a Euclidean KD-tree directly on unscaled latitude/longitude degrees.

On a sphere, a surface arc of length `s` has chord `c = 2R sin(s/(2R))`. Since `0 <= x - sin(x) <= x³/6` for the short arcs of interest, `0 <= s-c <=
s³/(24R²)` and the relative error is bounded by `s²/(24R²)`. For zero-height WGS84 ECEF, use the ellipsoid's conservative minimum curvature radius,
6,335,439 m. The geodesic as a space curve has curvature bounded by its reciprocal; the same short-arc bound is conservative. This bounds ellipsoid surface
distance versus its ECEF chord, not spherical-versus-ellipsoidal distance. The script evaluates that expression: approximately 0.00000104 m at 1 km,
0.00104 m at 10 km, and 1.0381 m at 100 km; these are calculated bounds, not measured dataset errors.

A zero-height chord cannot exceed the connecting surface geodesic, so a KD query at radius `r` is conservative. Use a tiny numerical tolerance at the
boundary in production, then filter candidates by surface distance. Do not mix known physical heights into this horizontal tree: vertical separation could
lose horizontal matches. A separate three-dimensional distance mode is valid only with compatible known height datums. Geodetic latitude on an ellipsoid is
not the geocentric latitude of its ECEF vector.

Use Karney's ellipsoidal inverse geodesic for reported distances and strict thresholds. [GeographicLib's Python
package](https://geographiclib.sourceforge.io/html/python/) is MIT/X11 and solves that problem. Haversine is a useful spherical approximation for broad
screening and continuity with the current engine. Its spherical Earth-model error is separate from the tiny chord error; it matters at tight tolerances.
[geopy's distance documentation](https://geopy.readthedocs.io/en/stable/#calculating-distance) describes both models. For settlement uncertainty of
hundreds of metres, identity and source position quality dominate this distinction. For surveyed sensors, close threshold decisions and difficult global
geometry, prefer the ellipsoid consistently.

Use an ENU frame at a declared origin to express offsets and position-error ellipses in metres. Rotate the ECEF difference into East/North/Up; retain the
origin so covariance is interpretable. A tangent-plane offset is local, not a global replacement for geodesic distance. [PROJ's topocentric
documentation](https://proj.org/en/stable/operations/conversions/topocentric.html) gives this transform. For independent error models, `ΣΔ = ΣA + ΣB +
Σrepresentation` in a common frame. Then `q = ΔENᵀ ΣΔ⁻¹ ΔEN` measures separation relative to expected position uncertainty. Include systematic
datum/geocoder bias and covariance between sources if they share an upstream source. Use an explicit robust outlier model; a large covariance must not
excuse arbitrary identity mismatches.

CEP is a percentile radius, not a per-axis standard deviation or a universal conversion to an ellipse. Under a circular zero-mean Gaussian, `CEP50 = sqrt(2
ln 2) σ`; other percentile conventions differ. Store the supplied percentile/model and derivation when converting to covariance. A rooftop, entrance,
municipal centroid and settlement centre have different representation error distributions. Estimate source/type accuracy priors from held-out trusted
identities, with sample and geography recorded. Missing uncertainty means an explicit policy default with low evidential strength, not zero error. The
spike's exponential distance scale is a heuristic; it does not estimate these distributions.

Recommended distance API: `surface_m(a,b, model="wgs84")`, `ecef(a, height="horizontal")`, `offset_enu(a,b, origin=...)`, and `separation(a,b,
uncertainty=...)` returning distance and evidence. Provide scalar and vector/Arrow-batch forms with identical units, null handling and validation.
`chord_m` is an explicitly named implementation primitive; `spatial_3d_m` rejects missing/incompatible height.

H3 and S2 are useful partition keys and distributed blockers; neither cell equality nor cell adjacency is identity. H3 `grid_disk` is a graph-distance
neighborhood, not a metric-radius guarantee. Cell dimensions vary: choosing k from an average edge length can miss metric-near neighbors. See [H3
traversal](https://h3geo.org/docs/api/traversal/) and [cell statistics](https://h3geo.org/docs/core-library/restable/). S2 can conservatively cover a
spherical cap, with conservative angular inflation for the ellipsoid. [S2 covering examples](https://s2geometry.io/devguide/examples/coverings) illustrate
the extra covered area. Geohash needs neighboring cells and latitude-aware covers; prefix equality alone loses boundary matches. For the MVP choose ECEF
KD-tree per bounded partition, retaining a halo across partition boundaries. Offer H3 as a later storage/distribution adapter; do not force Thereabouts'
serving grid into the matching API.

## Matching, scoring and assignment

Normalize display text without destroying it: preserve originals, language/script and named alias provenance. Build comparison keys with Unicode
normalization, case folding and punctuation/spacing policies. Accent folding, transliteration and removal of administrative suffixes must be explicit,
separate comparisons. A romanized alias can collide with another language's name; Japanese suffixes can distinguish city from district. Token similarity
helps reordered names; character/Jaro–Winkler helps typos but overvalues common prefixes. Embeddings can connect translations, but also connect different
branches or semantically related facilities. Keep embedding/model versions and a local execution option; use them as evidence, not opaque identity
authority.

The existing engine's `key()` uses NFKD, casefold and alphanumeric filtering. It indexes GeoNames primary/English/ASCII/untyped alternative names and
compares exact keys. It does not generate transliterations, perform token/Jaro–Winkler scoring, or use embeddings. Overture primary and English names are
queried; its other multilingual variants are not queried there. Typed GeoNames Wikidata aliases with historic/expired flags are excluded; untyped name
alternatives lack that guard. Those distinctions explain why “name normalization” is not already a complete multilingual matching layer.

Map source taxonomies into versioned compatibility rules: equal, compatible, contradictory or unknown. A hospital and its pharmacy can be close and
similarly named; broad type compatibility is insufficient. Keep original category IDs and the mapping version so a taxonomy update can trigger
reconsideration. Addresses should compare house number, street, unit, locality and postcode separately, with country-aware parsing. A postcode helps with
geography, but is not globally unique and can change over time. Phone normalization needs a country context; a shared chain website/domain is weaker than a
branch-specific URL. Wikidata and typed OSM `(node|way|relation, id)` references are strong but fallible identity evidence. Do not erase identifier type,
namespace or validity; an OSM node and way may both represent one site. Compare temporal intervals: a former tenant and a new tenant at one address should
not automatically merge.

Begin with transparent rules plus configurable additive/logistic features and an abstention zone. The phrase “hand-weighted, ours today” needs correction:
current `matching.py` uses a rule cascade, not weights. Wikidata candidates get a distance guard, then exact-name candidates get another; ambiguity can
reject either. Classification and area priorities are deterministic policies, not calibrated pair probabilities. The spike introduces weights solely as a
deliberately simple comparison baseline.

Fellegi–Sunter models agreement evidence as `log prior odds + Σ log(mγ/uγ)`. Here m is the comparison-level probability among matches and u among
nonmatches. Rare-name agreement can then carry more weight than agreement on a common chain name. Splink can estimate parameters with unlabeled EM and
other estimation routines; labels remain necessary for validation. Correlated name/address/category features, blocking bias and geography shifts can
miscalibrate the result. [Splink's training rationale](https://moj-analytical-services.github.io/splink/topic_guides/training/training_rationale.html)
explicitly discusses conditional independence and why a hybrid estimation strategy is used. Use Splink as an optional scoring experiment, not as an
automatic source of trustworthy probabilities.

A learned pair classifier can capture interactions and missingness after we have representative reviewed examples. Train/test splits must separate
entities, nearby duplicates, source releases and ideally held-out countries. Calibrate on held-out data, report precision/recall by script/type/source, and
measure blocking recall separately. An abstention/review rate is part of the product contract; raw pair accuracy is misleading in a sparse match space. The
corpus's reused source evidence makes current-engine agreement a regression measure, not independent validation.

For `1:1`, greedy assignment is deterministic and cheap but can sacrifice a better joint solution. Maximum-weight bipartite assignment optimizes a whole
candidate component; add dummy unmatched choices and veto edges. A Hungarian-style formulation is suitable for small components; cap component size and
review oversized components. SciPy's
[linear_sum_assignment](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linear_sum_assignment.html) uses a modified Jonker–Volgenant
algorithm; calling its implementation “Hungarian” would be imprecise. Stable marriage satisfies preference stability, not maximum total evidence, and is
not the default identity objective. Neither optimization nor a high score licenses a `1:N` group; a separate rule must justify its semantics. For duplicate
representations, allow explicit capacities/group proposals and record the rule that relaxed uniqueness. For multi-source fusion, validate group consistency
and cannot-link constraints before canonicalization.

## Prior art and licences

These are capability comparisons from primary documentation checked for this memo, not benchmarks of those tools. Software licence and input/output data
licence are separate; permissive library code cannot relicense source data. Absence of a capability in the reviewed docs means “not established here,” not
proof that no implementation exists.

| Project | Verified contribution and licence | Gap relative to the proposed product |
| --- | --- | --- |
| [Hootenanny](https://github.com/ngageoint/hootenanny) | Broad map conflation, including [POI matching](https://github.com/ngageoint/hootenanny/blob/master/docs/algorithms/ConflationAlgsOverview.md) and review; GPL-3.0 project | Substantial platform and valuable algorithmic prior art; not a permissive lightweight Python core to copy |
| [OSMConflator / osmconflator](https://pypi.org/project/osmconflator/) | MIT GeoJSON↔OSM intersection/duplicate utility; documented supported feature is buildings | The note overstates its relevance to general point identity; no documented versioned correspondence contract |
| [MAPS.ME OSM Conflator / osm_conflate](https://github.com/mapsme/osm_conflate) | Different project: Apache-2.0; merges external point feeds with OSM using source profiles and supports subsequent updates | Strong point/import prior art, but source-profile and OSM editing workflow rather than source-neutral object lifecycle |
| [Overture GERS](https://docs.overturemaps.org/gers/) | Shared entity identifiers, source bridge files, registry and release artifacts | Closest operational prior art; a shared data ecosystem rather than arbitrary two-input correspondence library |
| [Foursquare OS Places](https://docs.foursquare.com/data-products/docs/places-os-data-schema) | Dataset IDs, duplicate-quality flags, delta operations and explicit merge redirects; [Apache-2.0 data notice](https://opensource.foursquare.com/places-notice-txt/) | Useful deduplicated corpus and lifecycle feed; the data release does not establish a reusable open dedup algorithm |
| [dedupe / dedupe.io](https://github.com/dedupeio/dedupe) | MIT library learns from human examples, performs deduplication/linkage; dedupe.io is a separate hosted service | Strong learned blocking/linkage component; spatial object semantics, coordinate uncertainty and versioned geospatial crosswalk are ours |
| [Splink](https://github.com/moj-analytical-services/splink) | MIT probabilistic linkage, SQL backends, comparison weights and model diagnostics | Good optional scorer; geodesy, group semantics, temporal crosswalk and geometry provenance need an adapter |
| [recordlinkage](https://github.com/J535D165/recordlinkage) | BSD-3-Clause toolkit for indexing, comparison, classification and evaluation | Components for experimentation, not a complete geospatial correspondence lifecycle |
| [libpostal](https://github.com/openvenues/libpostal) | MIT C address parsing/normalization using statistical models | Address signal provider, not entity matching; model footprint merits an optional extra, not a core dependency |
| [geopy](https://github.com/geopy/geopy) | MIT geocoding/distance library | Supplies distance calculations, not correspondence or assignment |
| [GeoPandas](https://github.com/geopandas/geopandas) | BSD-3-Clause; [sjoin_nearest](https://geopandas.org/en/stable/docs/reference/api/geopandas.sjoin_nearest.html) produces nearest spatial joins, including ties | Planar distances require a suitable projected CRS; nearest geometry is not same object, and altitude is ignored |
| [PostGIS](https://postgis.net/docs/postgis_introduction.html) | [GPL-2.0-or-later](https://github.com/postgis/postgis/blob/master/COPYING) spatial database extension; [ST_DWithin](https://postgis.net/docs/ST_DWithin.html) supports indexed radius predicates | Geography gives metre distances; combine GiST blocking, exact distance and attribute SQL, but identity/assignment/history remain application logic |
| [MapRoulette](https://github.com/maproulette/maproulette-frontend) | MIT frontend for small OSM review/edit tasks | Useful human-review destination, not a point matching engine; this exploration exported nothing to it |
| [JOSM conflation plugin](https://github.com/JOSM/conflation) | GPL-2.0-or-later plugin using Java Conflation Suite for interactive matching/conflation | Editor-centric review and merge workflow, not the proposed Python/Arrow lifecycle API |
| [Mergin Maps GeoDiff](https://github.com/MerginMaps/geodiff) | MIT geospatial database changesets and application/merge of changes | Useful distinction between row changes and semantic object correspondence; coordinate edits alone do not identify objects |

Overture's [Places pipeline](https://docs.overturemaps.org/guides/places/) currently documents history matches, spatial/learned blocking, an XGBoost pair
classifier, and clustering followed by source-record promotion. It uses name/address/category embeddings and other similarities, phone, website and spatial
context. Its documented promotion step selects one source record rather than merging all attributes field by field. Its published feature confidence
measures existence, not calibrated probability that two records match. [Attribution](https://docs.overturemaps.org/attribution/) is source/theme dependent:
divisions here are ODbL; the business Places theme includes CDLA-Permissive-2.0, Apache-2.0 and source-specific terms.

The [GERS stability document](https://docs.overturemaps.org/gers/stability/) commits to identity continuity for registered types, but describes
matcher-dependent churn, a past ID migration, and no published split/merge successor mapping yet. Therefore do not advertise that GeoReconcile invented
persistent identifiers or reusable crosswalks. Foursquare's delta schema already specifies `merge` plus a `redirect` to the surviving ID. Our possible
differentiation is carrying those concepts across arbitrary sources, with inspectable decisions and policy. Whether that integration is commercially useful
is an owner/product question, not an algorithmic novelty claim.

Relevant academic work in the requested period offers established alternatives:

- [Low, Tekler and Cheah (2021)](https://arxiv.org/abs/2109.06073) organize POI conflation into procurement,
  standardization, taxonomy mapping, matching, unification and verification; they evaluate a Singapore case study.
  This supports treating schema and taxonomy work as part of the product, not preprocessing to ignore.
- [Zhao et al. (2022)](https://isprs-annals.copernicus.org/articles/X-3-W2-2022/87/2022/) combine distance,
  edit/Jaro–Winkler and address similarities with analytic-hierarchy weights, then fuse positions and attributes.
  Their article is CC-BY-4.0; its licence does not establish a production code library's licence.
- [Sun et al. (2023)](https://arxiv.org/abs/2310.15320) systematically review POI matching approaches.
  Their categorization makes a useful literature map; it does not validate this spike or a universal matcher.
- [Gao and Widdows (GISTAM 2020; arXiv upload 2024)](https://arxiv.org/abs/2401.08537) compare tree-based
  classifiers using spatial/textual features for restaurant-to-destination linkage in Southeast Asia.
  Their manually constructed test sets reinforce the need for region-specific labels and realistic negatives.

No paper's headline accuracy is imported as an expected result here; datasets and evaluation definitions differ. No reusable code licence was verified for
the cited academic approaches beyond the stated article licence. Use their methods as research evidence and verify implementation/model terms before
adopting any code or weights.

## What the in-house reconciler actually contributes

Read [current pipeline contract](../DATA_PIPELINE.md), [dataset contract](../DATASET_README.md), and the redirect notes
[RECONCILIATION](../RECONCILIATION.md) and [GOLDEN_DATASET](../GOLDEN_DATASET.md). The latter two point to current or historical documents; they are not
separate current algorithms. All module references below are in `pipeline/engines/reconcile/` at the exploration base.

`inputs.py` extracts country partitions and selected Overture division subtypes using bounded DuckDB resources. `matching.py` builds SQLite
GeoNames/name/Wikidata indexes and links each division independently. It tries shared Wikidata within 100 km, then exact normalized names within 10 km. It
requires GeoNames class A for country/dependency/region and class P for other retained division types. Multiple qualifying Wikidata candidates are
rejected; name candidates are rejected when the runner-up is too close (relative to the nearer candidate, with a fixed minimum separation guard). A
previous failed method can leave an issue attached to a later successful link. There is no exclusive global assignment: multiple Overture divisions can
link to the same GeoNames ID.

`entities.py` chooses source-derived country/state/city IDs and English/local display names with provenance. It accumulates multiple source IDs/evidence
under an entity and keeps GeoNames settlement fallback points. `classification.py` separates trusted settlements from administrative containers and
neighborhood subtypes. It includes population/hierarchy dominance checks and priority ordering for competing footprints. `city_identity.py` transfers city
footprint identity across hierarchy roles only with strong shared Wikidata evidence. `rollups.py` implements explicit city conventions such as Tokyo wards
and London borough membership. These are valuable domain decisions; transplanting them into a general POI matcher would create incorrect equivalences.

`quality.py` reports linking, anchor checks, coverage, fixtures and known problems; it is not a confidence calibrator. `evaluation.py` scores country/state
agreement and same-city-or-containing-city answers. Its “containing other” success is geometric lookup agreement, explicitly not independently validated
identity. `spatial.py` contains haversine, dateline-aware windows, SQLite R-trees and bounded geometry caching. `common.py` contains batching,
deterministic JSON, compressed evidence, name keys and read-only SQLite support. GeoBoundaries supplies administrative boundaries/state fallback; it is not
another POI pair-classification corpus.

| Extraction target | Reuse decision | Work needed |
| --- | --- | --- |
| `common.py`, selected `spatial.py` helpers | Closest to generic infrastructure | Remove pipeline/storage assumptions; replace default distance with explicit coordinate API |
| `matching.py` | Preserve as a settlement policy adapter and regression oracle | Split candidate retrieval, features, policy and decision; add explicit candidate/evidence contracts |
| `entities.py` | Reuse provenance/source membership ideas, not the entity schema as-is | Separate generic record/entity IDs from country/state/city roles and naming priorities |
| `quality.py`, `evaluation.py`, audits | Reuse reporting/gating patterns | Add independently labeled edge/group evaluation, calibration and unmatched metrics |
| Classification, hierarchy, rollups, city identity, state votes/codes | Keep in Thereabouts | Inject policy decisions through adapter hooks; avoid city semantics in core |
| Areas, land, coverage, lookup, build/catalog orchestration | Keep in Thereabouts for now | Library outputs feed the pipeline; no polygon extraction in the point MVP |

The script counted 1,941 physical lines across the reconciler; common/spatial together account for 172 lines. Only portions of those utilities transfer
unchanged; the matching/entity/evaluation modules need substantive adaptation. This is a small extraction plus new contracts, not renaming the directory
into a package. Line counts include comments and declarations and do not estimate how much production functionality is reusable. The current tree has no
top-level software licence declaration; confirm ownership/licensing before a public package.

Option (a), a new package in the same repository first, separates library release/API from dataset release/policy. Option (b), `thereabouts.conflate`, is
simpler initially but conflates an offline dataset/client product with authoring tools. Option (c), an immediate separate repository, adds release and
integration coordination before the API is proven. Recommend (a), with a clean dependency direction and separate package metadata; move repository later if
demand warrants. The first extraction must preserve existing pipeline outputs before enabling a new scorer in Thereabouts.

## Spike: design, measurements and interpretation

The spike is deliberately throwaway and below 400 physical Python lines; it has no product imports or pipeline commands. It reads only normalized
GeoNames/Overture manifests and Parquet plus the golden manifest/country catalogues. Historical absolute manifest paths are explicitly rebased to the
authorized real data root. It checks normalized file sizes and golden checksums; manifest/golden hashes and mtimes are checked again afterward. It does not
claim a full content rehash of every normalized partition. Filtered country subsets, correspondence evidence, unmatched IDs and all disagreements live
under `explore/.cache/`. The committed RESULTS file retains the measurements and selected locally inspected disagreement evidence.

Selection is all retained GeoNames points in Belgium/Japan and all default-perspective Overture country/dependency/region/county/localadmin/locality points
there; neighborhoods/microhoods/macrohoods are excluded. There is no random country-row sample or cherry-picked city bounding box and no cross-border halo
in this experiment. Candidate radius is 10 km; missing heights are projected to zero only for horizontal blocking. The score is `0.65 *
max_alias_JaroWinkler + 0.25 * exp(-geodesic_m/2000) + 0.10 * type_compatible`. A winner needs compatible class, score ≥0.83, name similarity ≥0.90 and
runner-up margin ≥0.05. Primary/English names are compared to GeoNames primary/English/ASCII/untyped aliases using the existing key recipe. Weights were
fixed heuristically; they were not learned or tuned against the golden labels.

Process Overture winners in descending score with deterministic ID ties; each has at most one GeoNames target. Allow a used GeoNames target only when every
accepted Overture member has the same non-null Overture Wikidata ID. Thus orientation **GeoNames→Overture** has `1:N` groups; the inverse has `N:1`. This
demonstrates explicit multiplicity rules, not validation that a shared upstream ID is infallible. The strict `1:1` comparison disables these extra accepted
members. No embeddings, real uncertainty estimates, phone/address matching, learned scoring or incremental release run occurred.

Reference edges expand each golden `geonames_id` and contributing `overture_ids` into pairs present in the inputs. `places.link` is retained per entity and
may be null or describe only one attachment after entity merging. Source memberships therefore supply more usable edges than requiring every entity to have
a non-null link object. This measures agreement with retained reconciler identity attachments, not all original division decisions. Missing golden edges
may mean unlinked, omitted or rejected output; they are not confirmed negative labels. Existing golden links were available, so the fallback of
constructing a 200-pair hand-label set was not needed.

| Country | GeoNames points | Overture input rows | Eligible Overture | Retained reference edges | Reference groups with multiple Overture members |
| --- | ---: | ---: | ---: | ---: | ---: |
| BE | 13,337 | 8,416 | 6,274 | 4,823 | 88 |
| JP | 55,498 | 221,031 | 9,832 | 3,687 | 1,372 |

Inputs: GeoNames `20261001T160939Z` and Overture `2026-09-23.1`. The script scans 119 GeoNames and 409 Overture place partitions via manifests. Japan's
reference has 2,304 distinct GeoNames targets for 3,687 edges: strict 1:1 has a structural recall ceiling. The spike's narrow shared-QID multiplicity rule
cannot reproduce all the reconciler's allowed many-to-one attachments.

Define `TP = predicted ∩ reference`, `FP = predicted − reference`, `FN = reference − predicted`. Here FP means *not present in this reference*, not a
verified real-world false match. Strict reference precision is TP/predicted; reference recall is TP/reference. The restricted precision below evaluates
only predictions whose Overture record has a retained reference edge. Even that domain is not independent truth: two GeoNames records can describe the same
settlement.

| Country / assignment | Predicted | TP / FP / FN versus retained reference | Precision | Recall |
| --- | ---: | --- | ---: | ---: |
| BE / strict 1:1 | 4,859 | 4,646 / 213 / 177 | 95.62% | 96.33% |
| BE / rule-based 1:N | 4,869 | 4,655 / 214 / 168 | 95.60% | 96.52% |
| JP / strict 1:1 | 2,029 | 1,920 / 109 / 1,767 | 94.63% | 52.07% |
| JP / rule-based 1:N | 2,045 | 1,936 / 109 / 1,751 | 94.67% | 52.51% |

Combined rule-based micro precision/recall: 95.33%/77.45% (6,591 overlaps, 6,914 predictions, 8,510 reference edges).

| Country | Precision on labeled Overture domain | Predictions outside that domain | Accepted 1:N groups | Unmatched Overture / GeoNames |
| --- | ---: | ---: | ---: | ---: |
| BE | 99.91% | 210 | 10 | 1,405 / 8,478 |
| JP | 99.54% | 100 | 15 | 7,787 / 53,469 |

| Country | Outside radius | Score/name gate | Better candidate | Margin | Assignment |
| --- | ---: | ---: | ---: | ---: | ---: |
| BE | 4 | 85 | 11 | 24 | 44 |
| JP | 20 | 1253 | 18 | 38 | 422 |

Miss reasons use that decision sequence; a pair may have additional underlying problems. The Japanese result is not evidence that non-Latin scripts alone
cause poor matching. Longer representative-point offsets, duplicate GeoNames entries, county/locality multiplicity and strict assignment all matter. The
score threshold gives even a perfect name/type match only a limited distance allowance. Using more names without distinguishing aliases' language and
object level can increase false matches. The rich Japanese aliases also rescue many cross-script matches, so a Latin-only test would hide both effects.

Blocking times include building the index, coordinate encoding, query and pair-set materialization. All methods query the same points; radius recall uses
WGS84 geodesics filtered from the conservative ECEF superset. Geohash uses a latitude-aware rectangular cover at precision 5; S2 uses a cap cover at fixed
level 10. H3 uses resolution 6 with k=2 and k=4; both are measured choices, not global metric-cover guarantees. Cells generate extra candidates; every
production path must apply the same exact radius/type filter afterward.

| Blocker | BE candidates | BE seconds | BE radius recall | JP candidates | JP seconds | JP radius recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ECEF KD-tree | 861,910 | 0.182 | 100.000% | 936,897 | 0.291 | 100.000% |
| H3 r6, k=2 | 1,597,132 | 0.319 | 99.902% | 1,593,900 | 0.446 | 99.941% |
| H3 r6, k=4 | 4,846,038 | 1.057 | 100.000% | 3,739,525 | 0.883 | 100.000% |
| S2 level 10 cap | 1,887,944 | 2.617 | 100.000% | 1,771,075 | 4.378 | 100.000% |
| Geohash precision 5 | 1,562,545 | 0.368 | 100.000% | 1,570,358 | 0.402 | 100.000% |

H3 k=2 misses 844 BE and 553 JP within-radius pairs.

The wider H3 ring, S2 and geohash recover all within-radius pairs in these two countries. That empirical result does not establish a global H3 guarantee at
pentagons, poles or cell boundaries. The narrow H3 ring misses valid radius pairs despite producing more candidates than ECEF. Raw `golden_recall` in
RESULTS can look slightly better for cell methods because they also return beyond-radius pairs; that is not a fair claim of higher recall at a fixed 10 km
cutoff. ECEF's full-radius completeness follows from chord ≤ surface distance, with boundary rounding caveats noted above. S2 timings use pure-Python
`s2sphere`, not optimized C++ S2; backend choice and materialization affect comparisons. Each reported timing is one final local run, with warm filesystem
caches and no concurrent-load control. These are feasibility measurements, not statistically repeated or globally representative throughput benchmarks.

Machine: Apple M2, 8 logical CPUs, 8 GiB RAM, `macOS-27.0-arm64-arm-64bit`, Python 3.12.8. DuckDB and BLAS were restricted to one thread; run timestamp
`2026-10-03T19:03:50Z` is UTC (4 October locally). Final wall time: 93.73 s including extraction and reporting; BE 39.06 s, JP 48.21 s. Exact
distance/filter work: BE 26.79 s, JP 27.73 s; score/assignment/artifact work: BE 7.23 s, JP 8.52 s. Process high-water RSS was 1.535 GB; minimum sampled
free disk was 48.48 GB. Logical file bytes were 0.589 GB under explore and 0.473 GB in the local virtualenv. These counts include downloaded dependency
caches (hardlinked files may be counted twice), comfortably below the 2 GB new-disk budget. The first extraction attempt exceeded its deliberately small
DuckDB spill allowance and failed without publishing results. The successful script scans one manifest partition at a time, avoiding the global sort that
caused that failure. GeographicLib's scalar exact-distance evaluation dominates this spike; compiled/vector geodesics merit the next performance check. Do
not extrapolate these full country in-memory pair sets to the world: stream candidate batches with component limits.

Locally inspected disagreements below are policy/evidence judgments, not independent field verification. The selected examples were chosen to expose
failure modes; no accuracy estimate is derived from them. Full IDs, coordinates, aliases and assessments are in `countries.*.review` in RESULTS.

| Case | Measured disagreement | Judgment and consequence |
| --- | --- | --- |
| BE Ottignies-Louvain-la-Neuve | Spike chooses GeoNames 2789570, Ottignies, at 44.60 m; golden chooses 7647765, full municipality name, at 1,229.63 m | Prefer golden for municipality identity; nearness plus a long fuzzy alias collapses object granularity |
| BE Chaumont | Spike chooses 2800436 at 94.32 m; golden chooses same-name 2800433 at 74,994.92 m | Provisionally prefer spike for a hamlet; audit the shared-ID claim allowed by the reconciler's long Wikidata guard |
| BE Doorn | Spike chooses Doren 2799264 at 21.96 m; golden chooses Doorn 2799282 at 2,877.01 m | Unresolved: plausible spelling variant versus exact homonym; both need local identity evidence |
| BE Petit-Rœulx-lez-Nivelles | New spike edge to Petit-Roeulx-lez-Nivelles 2789047 at 214.19 m | Plausible spike recovery; NFKD does not equate every ligature; retained reference has no decision to validate it |
| JP Mashiki | Spike chooses Mamizu 11147910 at 1,071.56 m; golden chooses Shimada 11147658 with exact Mashiki alias at 4,562.36 m | Prefer golden under settlement naming semantics; the spike confuses Mashiki with the pinyin alias Mashui |
| JP Tsunagi | Spike chooses Kotsunagi 11402804 at 473.04 m; golden chooses Tsunagi 1849633 at 3,454.19 m | Prefer golden; fuzzy name/type compatibility permits a different named settlement |
| JP Yokohama | Golden links 1848354 at 2,360.54 m; the spike abstains | Prefer golden given exact multilingual identity; this heuristic's distance penalty is too severe for representative city points |
| JP Higashi-Hiroshima | Spike chooses PPL 6822110 at 851.12 m; golden chooses PPLA2 11611627 at 2,110.30 m | Unresolved source duplication; golden follows canonical city identity, while names alone cannot prove different real objects |

## Proposed Python-first API and result shapes

This is a design sketch, not runnable code or a commitment to these parameter names. Accept Arrow tables/batch readers directly and GeoDataFrames through
explicit CRS/column adapters. Never rely on a DataFrame's row order as record identity; preserve namespaced source IDs and releases.

```python
import georeconcile as gr
left = gr.points(arrow_a, id="id", lat="lat", lon="lon", dataset="vendor_a", release="r1")
right = gr.points(gdf_b, id="id", dataset="vendor_b", release="r7")
result = gr.match(left, right, policy=poi_policy, cardinality="one_to_one")
result.decisions       # Arrow: relation_id, left_id, right_id, status, relation,
                       # score, p_same?, model_id?, evidence_id, provenance_id
result.groups          # group_id, relationship, cardinality, status
result.members         # group_id, side, dataset, release, record_id
result.unmatched       # side, record_id, reason, candidate_count, best_evidence_id?
result.explain(relation_id)  # raw signals, missingness, rivals, rules, assignment trace
xwalk = gr.crosswalk(result, previous=prior_snapshot, version="xwalk-r8")
xwalk.write("crosswalk-r8/")  # immutable manifest + Parquet tables, atomically finalized
attrs = gr.transfer(xwalk, right, fields=["category", "phone"], conflicts="retain")
canonical = gr.conflate(left, right, crosswalk=xwalk, policy=field_selection_policy)
```

`match` produces candidate/decision artifacts without changing either dataset. `explain` works from stored evidence without rerunning a newer model and
changing the historical explanation. `crosswalk` validates memberships, persists decisions and appends predecessor/successor history. `transfer` returns
selected fields with source record/release, original values and conflict/selection reasons. For `1:N`, an explicit aggregation or per-member transfer
policy is mandatory; no implicit duplication of totals. `conflate` selects canonical attributes/position under field-specific policy while retaining
conflicting observations. Default geometry selection should prefer an identified source observation over averaging incompatible representative points.
Covariance-weighted position fusion is an opt-in only for compatible unbiased observations of the same position.

The manifest records input hashes, software/policy/model/calibration versions, CRS, licences and table checksums. Evidence should have typed common fields
plus a versioned signal payload; avoid an unversioned JSON junk drawer. Represent missing, contradictory and not-evaluated separately; include source
dependence and validity in provenance. Expose candidate limits and truncation explicitly so an incomplete search cannot look like high confidence. Keep
`FeatureRef`, relationship groups, evidence and history geometry-neutral. A later geometry adapter can generate candidates/features for lines/polygons and
attach geometry-specific evidence. The public verbs and membership/history tables survive; topology, overlaps and polygon events are intentionally
undesigned.

## Build plan and owner decisions

First fund an evidence-contract and identity-policy package, with this settlement case as a regression consumer. Before launching a general POI product,
obtain two permitted POI feeds and review ambiguous multilingual examples. Success should mean a reusable crosswalk survives a second release with
inspectable changes and stable decisions. It should not mean another matcher happens to return a high score on the data that supplied its labels.

Estimated engineering effort below is planning judgment, not a measured result or delivery promise. Assume one experienced engineer with timely domain
review and accessible, appropriately licensed partner data.

| Work package | Estimated person-weeks | Concrete exit artifact |
| --- | --- | --- |
| Identity/evidence contract and reviewed examples | 1 | Typed record/relation/group schema, object-level policy, independent disagreement labels and success criteria |
| Isolate generic utilities and settlement adapter | 1–2 | Package boundary and regression harness reproducing existing decisions without a policy change |
| Position, blocking and feature engine | 1–2 | WGS84/ECEF/ENU APIs, bounded candidate streaming, alias/type/identifier evidence and boundary cases |
| Decision, assignment and inspection | 1–2 | Rules/score, abstention, component assignment, explained multiplicity and offline review export |
| Crosswalk history and next-release update | 2 | Immutable snapshots, redirects/retirements, affected-component rematching and override validity |
| Transfer, canonical selection and pilot packaging | 1–2 | Arrow/GeoPandas adapters, per-field provenance, POI pilot evaluation and library documentation |

Plan for 7–11 person-weeks for a credible point MVP; domain labeling and acquisition lead time are additional. The first work package is independently
useful even if the owner stops after discovering weak product demand. Adding learned scoring, address parsing at scale or a hosted review UI should be
separate decisions after this MVP.

Reuse the existing name/evidence utilities, resource-bounded I/O patterns and settlement policy as an adapter. Adopt NumPy/SciPy for coordinate arrays and
KD-trees, GeographicLib or PROJ for geodesics, Arrow for interchange, and RapidFuzz for inspectable string features; preserve each dependency's licence
notices. Keep GeoPandas, H3/S2, Splink and libpostal optional according to workflow; no need to buy a hosted matcher first. If a partner already uses
PostGIS, offer an adapter that emits identical evidence rather than requiring data export. Do not bundle Hootenanny/JOSM code into a proposed permissive
core without resolving their licence constraints.

Owner decisions: choose the first external user and object granularity; settlement matching alone does not validate POI demand. Choose whether the
canonical object is establishment, site, branch, device or station and what relocation means. Choose the acceptable false-merge cost, abstention/review
burden and independent evaluation process before thresholds. Choose whether persistent crosswalk maintenance is the first paid/useful capability or merely
an internal pipeline facility. Choose Apache-2.0 versus MIT for new library code, resolve existing code rights, and retain all source-data obligations.
Choose the initial POI data partner and whether manual review overrides are essential in the first release. Lines and polygons remain parked until a point
customer requires the shared contracts to extend.

## Reproduction and custody

All task files and caches are local to this worktree; the authorized git commit uses the worktree's shared git metadata. No pipeline stage, source
mutation, remote push, PR, publication or upload was performed. The original idea-note file was left untouched and untracked; only exploration deliverables
were staged. Public documentation searches and dependency downloads were the only network research/setup activities. No source records or local datasets
were sent to a hosted labeling/model service. The protected real `data/` tree was used only for the permitted reads; sibling worktrees were not used.

```sh
mkdir -p explore/.cache/tmp
UV_CACHE_DIR="$PWD/explore/.cache/uv" TMPDIR="$PWD/explore/.cache/tmp" uv sync --all-extras --frozen
UV_CACHE_DIR="$PWD/explore/.cache/uv" TMPDIR="$PWD/explore/.cache/tmp" uv pip install --python .venv/bin/python \
  geographiclib==2.1 rapidfuzz==3.14.6 s2sphere==0.2.5 pygeohash==3.5.1
TMPDIR="$PWD/explore/.cache/tmp" OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  .venv/bin/python explore/point_spike.py
.venv/bin/ruff check --select F explore/*.py
.venv/bin/python explore/validate_spike.py
```

RESULTS includes package versions, input manifest hashes, code hash, timings, memory, disk and selected review cases. Measurements reflect the final local
run; reproducing it replaces local scratch/results only. The script terminates if sampled RSS or free disk crosses its conservative guard; it is not a
general resource scheduler. The local validator checked budgets, edge counts, multiplicity, evidence thresholds, ECEF axes and polar/dateline chord bounds.
No CI was run because this exploration is local-only; validation is the real-data run and local consistency checks.
