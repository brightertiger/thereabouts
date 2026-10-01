# Reconciliation policy and v0 pilot evidence

The tables below record the **v0** pilot. The current v1 policy, failure audit, sample comparison and rebuild status are in [GOLDEN_V1.md](GOLDEN_V1.md). Source acquisition remains unchanged.

Policy: `reconciliation-1`; builder `dce2f2eaa8bbd58a74767eb520103ef13f6025d223fae8b2b88f9b6483c83d6c`.
Pilot gate: **PASS**. The gate requires all named checks and at least 99.5% large-place answers.

## Actual named lookups

| Point | City | State | Country | Method | Pass |
| --- | --- | --- | --- | --- | --- |
| lower Manhattan | New York | New York | United States (US) | area | True |
| Tokyo | Tokyo | Tokyo | Japan (JP) | area | True |
| Singapore | Singapore | — | Singapore (SG) | area | True |
| Monaco | Monaco | — | Monaco (MC) | area | True |
| Hong Kong Central | Hong Kong | — | Hong Kong (HK) | area | True |
| Lagos | Lagos | Lagos State | Nigeria (NG) | nearest | True |
| London | London | England | United Kingdom (GB) | area | True |
| Cayenne | Cayenne | — | French Guiana (GF) | nearest | True |
| Pristina | Pristina | District of Prishtina | Kosovo (XK) | area | True |
| Bengaluru | Bengaluru | Karnataka | India (IN) | area | True |
| Paris | Paris | Ile-de-France | France (FR) | area | True |
| Cagayan de Oro | Cagayan de Oro | Cagayan de Oro | Philippines (PH) | area | True |
| Eindhoven | Eindhoven | North Brabant | Netherlands (NL) | area | True |

French dependencies retain FR/France as sovereign; HK retains CN/China. SG, MC, HK and the five French territories intentionally have no state.

## Per-country measurements

Land coverage is a **spherical-area sampling estimate**, not an exact polygon-area sum. Each JSON report includes its 95% Wilson interval and sample count. Place coverage uses every GeoNames P record and exact polygon predicates.

| CC | State source / level | Division links | City area links | Land in city area | Places in city area | Large answer | Country | State* | City† |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BE | overture / region | 76.873% | 96.118% | 99.640% | 99.574% | 100.000% | 100.000% | 100.000% | 100.000% |
| FR | overture / region | 22.860% | 93.444% | 99.249% | 99.907% | 100.000% | 100.000% | 100.000% | 100.000% |
| GB | geoboundaries / ADM1 | 53.667% | 43.076% | 65.021% | 75.375% | 100.000% | 100.000% | 99.424% | 97.696% |
| GF | absent / — | 28.715% | 0.000% | 0.009% | 0.135% | 100.000% | 100.000% | n/a | 100.000% |
| GP | absent / — | 86.567% | 100.000% | 99.952% | 99.177% | 100.000% | 100.000% | n/a | 100.000% |
| HK | absent / — | 44.706% | 67.442% | 100.000% | 99.851% | 100.000% | 100.000% | n/a | 100.000% |
| IN | overture / region | 32.753% | 17.669% | 1.074% | 1.080% | 100.000% | 100.000% | 99.444% | 99.391% |
| JP | overture / region | 37.500% | 77.275% | 98.841% | 99.652% | 100.000% | 100.000% | 99.846% | 99.846% |
| MC | absent / — | 33.333% | 0.000% | 100.000% | 100.000% | 100.000% | 100.000% | n/a | 100.000% |
| MQ | absent / — | 78.804% | 97.222% | 100.000% | 99.614% | 100.000% | 100.000% | n/a | 100.000% |
| NG | overture / region | 60.838% | 36.516% | 42.069% | 25.420% | 100.000% | 100.000% | 98.141% | 99.628% |
| NL | overture / region | 90.548% | 99.135% | 99.924% | 99.718% | 100.000% | 100.000% | 100.000% | 100.000% |
| PH | overture / county | 50.972% | 74.500% | 53.779% | 56.547% | 100.000% | 100.000% | 96.792% | 99.623% |
| RE | absent / — | 80.882% | 81.081% | 100.000% | 99.617% | 100.000% | 100.000% | n/a | 100.000% |
| SG | absent / — | 62.121% | 100.000% | 100.000% | 99.483% | 100.000% | 100.000% | n/a | 100.000% |
| US | overture / region | 89.511% | 74.965% | 15.673% | 47.407% | 100.000% | 100.000% | 100.000% | 99.150% |
| XK | overture / region | 70.677% | 75.771% | 11.720% | 13.402% | 100.000% | 100.000% | 80.952% | 100.000% |
| YT | absent / — | 86.316% | n/a | 0.000% | 0.000% | 100.000% | 100.000% | n/a | 83.333% |

Large-place counts: `{'answer': 11596, 'city_containing_other': 1886, 'city_present': 11596, 'city_same_identity': 9632, 'city_same_or_containing': 11518, 'country_agrees': 11596, 'state_agrees': 11292, 'state_applicable': 11346, 'state_unmapped': 15, 'total': 11596}`.

*State comparison uses GeoNames ADM1 identities, unique ADM1 names, or the parent region for province-equivalent states. Unmapped states count as failures; intentionally absent states and empty GeoNames admin1 are excluded from this denominator.

†City means the same GeoNames identity **or** an assigned city polygon containing the point. Containing another city is not independently adjudicated identity accuracy. Every class P record with population ≥15,000 remains in the denominator, including PPLX and historical places. Reports separate own-identity and containing-other counts.

## Largest disagreements

| Place / GN ID | Population | Actual city, state, country | Failed comparisons |
| --- | ---: | --- | --- |
| Teni / 1254745 | 1,034,724 | Allinagaram, Tamil Nadu, IN | city |
| Shivaji Nagar / 6943660 | 1,000,000 | Pune, Maharashtra, IN | city |
| Jājmau / 10581114 | 652,831 | Purwa Bhikhāri, Uttar Pradesh, IN | city |
| Honchō / 1863905 | 644,668 | Ichiba, Chiba Prefecture, JP | city |
| Pristina / 786714 | 550,000 | Pristina, District of Prishtina, XK | state |
| Āsansol / 1278314 | 504,271 | Jaykaynagar, West Bengal, IN | city |
| Iligan City / 1711082 | 312,323 | Iligan, Iligan, PH | state |
| Kawanishi / 1859675 | 155,165 | Ikeda, Osaka Prefecture, JP | state |
| Metairie Terrace / 4333190 | 142,489 | Beverly Knoll, Louisiana, US | city |
| Fukayachō / 1864031 | 141,268 | Kokusaiji, Saitama Prefecture, JP | city |
| Nimach / 8441115 | 128,561 | Neemuch, Madhya Pradesh, IN | state |
| Amaigbo / 2350249 | 127,300 | Amaigbo, Ebonyi State, NG | state |
| Poblacion / 7391141 | 124,554 | Muntinlupa, Muntinlupa, PH | state |
| Universal City / 5404794 | 105,000 | Burbank, California, US | city |
| Putatan / 1692327 | 102,146 | Muntinlupa, Muntinlupa, PH | state |
| Jolo / 1710141 | 101,002 | Jolo, Sulu, PH | state |
| Chinatown / 5336477 | 100,574 | Financial District, California, US | city |
| Birgaon / 10448053 | 96,294 | Rānwābhāta, Chhattisgarh, IN | city |
| Makoko / 2331158 | 85,840 | Ebute-Metta, Lagos State, NG | city |
| Oke Mesi / 2327223 | 79,563 | Oke Mesi, Ekiti State, NG | state |
| Pammal / 9972720 | 75,870 | Anakaputtur, Tamil Nadu, IN | city |
| Ode / 2328090 | 75,463 | Ode, Ekiti State, NG | state |
| Kalamassery / 10630431 | 71,038 | Kalamasseri, Kerala, IN | city |
| Atascocita / 4671524 | 65,844 | Atascocita Timber, Texas, US | city |
| Nipāni / 1261309 | 62,865 | Nipāni, Karnataka, IN | state |
| Nani Daman / 13665129 | 62,000 | Daman, Dadra and Nagar Haveli and Daman and Diu, IN | city |
| Buluan / 1722818 | 60,931 | Buluan, Maguindanao del Sur, PH | state |
| West Hollywood / 4177834 | 60,806 | Okomo Mobile Home Park, Florida, US | city |
| Jaitpur / 10265191 | 59,330 | Delhi, Delhi, IN | state |
| Glogovac / 790701 | 58,579 | Drenas, District of Prishtina, XK | state |

The complete failure lists, coordinates, feature codes, expected and returned admin codes are in each `*-quality-*.json`; no large failures are excluded.

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
locality; a state's capital or a similar name is insufficient. Such a footprint
ranks above untyped administrative localities and below independently classified
municipalities. No city names or probe coordinates enter these decisions.

City-state footprints are SG/MC/HK/MO. The JP policy assigns precisely the 23 locality areas ending in 区 within JP-13 to the linked Q1490 city. A changed membership count fails the unit. Other Tokyo prefecture municipalities retain their own city identities. The GB policy assigns 33 pinned county identities (32 boroughs plus City of London) to Q84, using the [official borough map](https://data.london.gov.uk/download/e55pw/f1d04c59-4590-4291-b4ea-3abc624156b7/London_Borough_Boundary_Map_A4.pdf). No rule uses a fixture coordinate. Nearest fallback uses eligible GeoNames or unmatched Overture locality points, same country, ≤50 km inclusive, and is labelled `nearest`.

Known limitations: large municipalities and consolidated city-counties can swallow distinct nested settlements; population is not proof of municipal identity. Broad metropolitan areas are not inferred from a population radius. Missing city polygons leave nearest matches (including Cayenne where applicable). Unlinked localities can include classification mistakes. Tokyo's convention is explicitly country-specific. No independent holdout accuracy claim is made.

## Output and operation

`data/reconciled/manifest.json` lists the sole committed snapshot. Each country has a SQLite partition with indexed `entities`, `areas`/`area_bounds`, `points`/`point_bounds`, GeoNames and division evidence, identity links, and state crosswalks. Geometry is unsimplified WGS84 WKB; JSON record blobs use lossless zlib (read with `build_data.reconcile.common.unpack`). Provenance and aliases are retained. Country partitions remain disk-backed; a lookup reads only intersecting geometries. The manifest retains all source manifests and the global OSM land index reference.

Land eligibility uses OSM containment or a spherical nearest-boundary projection within 1 km. Labels use that land point; nearest-city distance uses the original query. Overlapping OSM split polygons are never counted as separate coastlines. Ocean beyond the band is ineligible; unresolved land retains empty fields.

Checkpoints use the acquisition workspace, ledger, fingerprints, hash verification and atomic output helpers. Stages: source validation, country extraction, identity links, country assignment, quality, manifest commit. A single advisory lock owns reconciliation. Interrupted units rebuild; completed units verify and skip. A new generation first archives the old manifest and commits an explicitly
incomplete manifest. Each replacement SQLite country is checked and hash-verified
before retiring that country's old partition and extract/link intermediates.
Resume skips verified countries without recreating their deleted intermediates.
An interrupted replacement keeps the previous partition; an interrupted cleanup
is retried. `load()` rejects an incomplete generation, while golden discovery
uses matching committed country checkpoints. The land index is one bounded-memory streaming checkpoint; an interruption rebuilds it.

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
Published country bytes: 6,865,383,424; land index bytes: 1,704,595,456.

## Aggregate results and state choices

The 11,596 GeoNames populated places with population at least 15,000 all return a country and city: **100% answer coverage and country-code agreement**. State agreement is **11,292/11,346 (99.524%)**, with 54 failures, including 15 unmapped identities. City identity or containing-area agreement is **11,518/11,596 (99.327%)**; 9,632 are the same identity and 1,886 are a different city whose assigned polygon contains the point. There are 78 city comparison failures. These percentages measure agreement with the downloaded sources, with the limitations described above.

Across the pilot, **365,111/843,257 (43.298%)** candidate Overture divisions link to GeoNames; **77,710/107,701 (72.153%)** accepted Overture city-area entities link. The JSON reports separate Wikidata, name/distance, ambiguous and unmatched cases, retained Wikidata availability, classification conflicts and city anchors outside their assigned polygons.

**GB is the only pilot country taking its state layer from geoBoundaries**: ADM1 supplies the constituent countries that people expect as the state, while Overture's region level is unsuitable. PH uses Overture counties (provinces), supplemented by independent city localities directly below regions, because the region level does not represent provinces. Other pilot countries use Overture regions where a state is meaningful. SG/MC/HK and the five French dependencies deliberately omit state. Each country JSON records the policy and reason. State disagreements include coastal gaps, unresolved code crosswalks, changed administrative boundaries and conflicting downloaded codes; a correct-looking name does not silently count as agreement with an unmapped code.

## Validation and measured resources

The complete repository checks passed with `uv run --no-sync`: `pytest` (**172 passed, 7 skipped**), `ruff check`, `ruff format --check` (141 files), and `mypy` (139 source files). Synthetic reconciliation tests use no network. No dependencies were added. No Git branch, index or commit was changed.

The final pilot took **943.272 seconds**, with peak resident memory **1,089,011,712 bytes**. A verified repeat took **90.368 seconds**, peak **180,453,376 bytes**, and reused every completed stage. Logs are `data/work/reconcile/pilot-final.log`, `pilot-resume.log`, and `pytest-final.log`; measurements are in `pilot-resources.json`. Published pilot partitions total **6,865,383,424 bytes**, the land index **1,704,595,456 bytes**, and quality reports **466,864 bytes**, plus the small manifest. Work caches occupy about 4.1 GB. The workspace resource guards remain enabled; outputs have no artificial size target.

## Detached world run

Started on 2026-10-02 at 00:39 IST (2026-10-01 19:09 UTC), with launch PID **25103**, using a new process session and redirected standard streams:

```sh
uv run --no-sync python -m build_data.reconcile --world
```

Log: `data/work/reconcile-world.log`. Launch metadata: `data/work/reconcile/world-launch.json`. The process is resumable with the same command. Monitor with `tail -f data/work/reconcile-world.log` and the `status` command above. A completed world run requires `data/work/reconcile/run.json` to contain both `"world": true` and `"completed": true`, and the published manifest to list the world countries. Until publication, the pilot manifest remains usable. World output and world quality have **not yet been validated**; failure or a resource guard leaves completed units available for resumption.

Startup was verified: all six source groups passed verification, the pilot gate was accepted, and AD and AE country checkpoints completed before handoff. PID 25103 remained detached under PID 1, with Python worker PID 25104.
