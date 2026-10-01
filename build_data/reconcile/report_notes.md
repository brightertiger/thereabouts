
The complete failure lists, coordinates, feature codes, expected and returned admin codes are in each `*-quality.json`; no large failures are excluded.

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

City-state footprints are SG/MC/HK/MO. The JP policy assigns precisely the 23 locality areas ending in 区 within JP-13 to the linked Q1490 city. A changed membership count fails the unit. Other Tokyo prefecture municipalities retain their own city identities. The GB policy assigns 33 pinned county identities (32 boroughs plus City of London) to Q84, using the [official borough map](https://data.london.gov.uk/download/e55pw/f1d04c59-4590-4291-b4ea-3abc624156b7/London_Borough_Boundary_Map_A4.pdf). No rule uses a fixture coordinate. Nearest fallback uses eligible GeoNames or explicitly classified unmatched Overture locality points, same country, ≤50 km inclusive, and is labelled `nearest`.

Known limitations: large municipalities and consolidated city-counties can swallow distinct nested settlements; population is not proof of municipal identity. Broad metropolitan areas are not inferred from a population radius. Missing city polygons leave nearest matches (including Cayenne where applicable). Unlinked localities can include classification mistakes. Tokyo's convention is explicitly country-specific. No independent holdout accuracy claim is made.

## Output and operation

`data/reconciled/manifest.json` lists the sole committed snapshot. Each country has a SQLite partition with indexed `entities`, `areas`/`area_bounds`, `points`/`point_bounds`, GeoNames and division evidence, identity links, and state crosswalks. Geometry is unsimplified WGS84 WKB; JSON record blobs use lossless zlib (read with `build_data.reconcile.common.unpack`). Provenance and aliases are retained. Country partitions remain disk-backed; a lookup reads only intersecting geometries. The manifest retains all source manifests and the global OSM land index reference.

Land eligibility uses OSM containment or a spherical nearest-boundary projection within 1 km. Labels use that land point; nearest-city distance uses the original query. Overlapping OSM split polygons are never counted as separate coastlines. Ocean beyond the band is ineligible; unresolved land retains empty fields.

Checkpoints use the acquisition workspace, ledger, fingerprints, hash verification and atomic output helpers. Stages: source validation, country extraction, identity links, country assignment, quality, manifest commit. A single advisory lock owns reconciliation. Interrupted units rebuild; completed units verify and skip. A new generation archives the previous manifest and is explicitly incomplete. Each new country is verified before its superseded partition and intermediates are removed. Verified countries resume without recreating deleted intermediates. The land index is one bounded-memory streaming checkpoint; an interruption rebuilds it.

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
