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
| Untyped locality chosen as city | 2,011 | PK 326, CN 292, VN 251, TH 123, IR 88, TN 88 |
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
In total, **8,116 of the 8,649 non-identities have no polygon linked to the
expected GeoNames city identity**. This includes legitimate suburbs and deliberate
city-state answers, and does not prove that an equivalent unlinked polygon is
absent. The overlapping inventory is `missing-polygon-audit-v0.json`.
The 52 suspected link collisions are not 52 proven bad links. Same-name distinct
GeoNames records and stale/contradictory Wikidata evidence require adjudication.

Within the 2,011 untyped localities, a separate source-label audit finds **621
explicit ward/borough/subdistrict labels** (CN 268, VN 178, TH 97, KE 52, IN 23),
**378 district/county/tehsil labels** (PK 323, YE 24, JP 11), **113 municipal,
commune or parish labels** (VN 70, SN 11, TH 11), and **899 unresolved labels**
(TN 88, IR 87, DE 84, PT 75). These are descriptive source-label categories, not
extra observations or runtime name rules. Overture hierarchy directly confirms
that 1,025 of these administrative localities contain the expected linked
settlement point. Evidence is in `admin-label-audit-v0.json`.

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
The new alias index includes administrative districts and their upstream names.
An uncertain locality retained as a district is excluded from alias matching
unless a GeoNames administrative identity supports it: its storage role alone
does not establish an ISO subdivision. Ambiguous aliases remain multi-candidate.
An exact sovereign/territory code pair can identify a separately represented
country, such as `CN-HK` → `country:HK`. An unrelated country-code suffix is not
sufficient evidence.

When an exact alias is absent, an ISO row's stated subdivision type can qualify
its name: `Bagerhat` + `District` matches the retained administrative alias
`Bagerhat District`. Explicit bracketed alternate names with a same-country ISO
code are also accepted. Neither rule strips arbitrary words or selects a fuzzy
nearest name; existing ambiguous aliases stay ambiguous. A read-only preview
found 130 additional unique matches (MA 51, BD 42, LT 15, GB 14, LK 8).
This final static-join refinement was tested before the golden stage started;
the frozen reconciliation and cell builder hashes did not change. Final published
counts, rather than this mixed-generation preview, determine the world result.

Unmatched countries are EH, AN and CS. EH has a GeoNames TERR record but no
accepted default-perspective country polygon; 49 retained cities consequently
reference a missing country. AN and CS are historical countries.

Phone ambiguity is initially 95,723 rows: calling code 61 accounts for 60,578;
1 for 32,498; 7 for 1,160; 44 for 814; 39 for 353; 47 for 166;
358 for 144; 599 for 10. The source contains territory-specific fixed-line
patterns, so shared calling codes alone overstate ambiguity. Non-geographic
001 service metadata has no geographic country; AC and TA are calling-plan
territories without separate country entities.

Numbering-language analysis leaves 44 candidate ambiguities: 37 Australian/
Indian Ocean territory rows, four Morocco/Western Sahara rows, two Italy/Vatican
rows, and one `134597` row unsupported by the pinned fixed-line patterns. The
first 43 retain overlapping source languages; the last retains all source
candidates rather than inventing support. Counts are rows, including translated
descriptions. `phone-residual-language.json` records the exact prefixes and
candidate sets. Stronger allocation evidence could resolve some of these; they
are not asserted to be inherently unknowable.

## Implementation and rebuild

The general rule now requires settlement evidence, uses hierarchy and population
to reject administrative containers of much larger linked city points, and gives
the most specific classified linked municipality precedence. Separate suburb
municipalities retain their own answers: a person inside a separately represented
town should receive that town even when a larger metropolitan footprint overlaps
it. Existing explicit Tokyo/London and city-state conventions remain data policy.
An exact shared Wikidata identity between a region and an explicit, uniquely
linked city can supply a missing city footprint; a capital/seat relationship or
name resemblance cannot. No new country or city-name exceptions were introduced.
All shared-identity administrative footprints outrank unlinked town/village
classifications, but stay below independently linked localities. The first sample
exposed why both bounds matter: an unlinked town label displaced Karachi's
established identity, while 153 linked Chinese settlements were absorbed by
Shanghai or Chongqing's regional footprint. The final sample and world gate use
the corrected ordering. The original comparison and regression evidence remain
in `sample-first.json` and `sample-first-change-classes.json`.

Rejected administrative localities and source evidence remain in `places` as
districts, with `source_subtype`, `settlement_class` and `city_exclusion` fields.
A per-cell finer-unit column is deferred: carrying its extra boundaries through
certification, compaction and every lookup join is a separate spatial/schema
change. The existing cell-equivalence contract is retained.

Refactoring separates area assignment, shared-identity footprints, catalogue
checkpoints, state crosswalks, settlement scoring and country retirement. Scalar
and vector city selection share one ordering function; both quality evaluators
share one agreement definition. Canonical naming preference no longer discards
additional source identities/provenance. Golden administrative and telephone
linkers are separate modules. All reconciliation/golden modules remain under
250 lines, with strict mypy and no broad exception handlers.

Country references without an accepted border are created only from a unique
source country/territory record. This fixes EH's catalogue reference without
changing the selected territorial perspective. The golden completion gate now
rejects dangling parent and sovereign references as well as dangling cell IDs.
Historical AN/CS and non-geographic phone services are not invented as current
countries.

Final code validation passed **237 tests with 7 existing skips**, including the
envelope-cache regression test. Ruff lint, Ruff format (209 files) and strict
mypy (206 source files) pass. Logs are `data/work/v1/{pytest-final,ruff-final,
format-final,mypy-final}.log`.
Tests cover independent municipalities, administrative containers, exact region
identity, country-only catalogue entries, interrupted replacement and resumed
cleanup, administrative alias ambiguity, source-qualified subdivision names,
numbering-prefix overlap, and exhaustive
scalar/vector/compacted-cell equivalence including seams and pentagons.
The first sample additionally passed certificate/direct-vector and compacted
ancestor equivalence for all **487,403 r8 centres** in the 29 requested probe
blocks, with **1,856 independent scalar checks**. This check is repeated for the
final sample builder before the world run.

Country replacement archives the old manifest and marks the new generation
incomplete. Each verified country replaces its predecessor; that country's
extract and link SQLite are then removed. Retry verifies the final country first
and skips rebuilding deleted intermediates. The source manifests and land index
remain reusable. H3 descendant envelopes have a separate reusable cache;
dependency intersections are rechecked when country envelopes change. Static
joins and place-only schema changes do not invalidate spatial cell code.

## Final sample at resolution-8 centres

Before: stored v0 cells. After: independent scalar oracle at exactly the same r8 centres, using re-reconciled sample countries and v0 neighbours. Final world checks run through stored v1 cells.

All 29 rebuilt countries passed the current full-pilot gate. The final sample
improvement gate passed for builder `e4bb8ae48002bb0d54a0ba59247fb4bb13e86ce2506849f91074856b085a5e8a`.
The 29 probe-root check passed all **487,403 centres**, plus **1,856 independent
scalar checks**, for this final builder. All 13 named fixtures pass.

| Measure | v0 | Final sample |
| --- | ---: | ---: |
| Answer | 16,408/16,409 (99.99%) | 16,408/16,409 (99.99%) |
| Country agreement | 16,402/16,409 (99.96%) | 16,402/16,409 (99.96%) |
| State agreement | 15,867/16,157 (98.21%) | 15,867/16,157 (98.21%) |
| Exact city identity | 11,175/16,409 (68.10%) | 12,238/16,409 (74.58%) |
| Identity or containing city | 15,646/16,409 (95.35%) | 15,499/16,409 (94.45%) |

The final rule recovers **1,198** v0 non-identities and introduces **135**
new identity mismatches, net **+1,063**. Of the new mismatches, **121 are in China**.
Broad regional footprints can still absorb point-only settlements without their
own city polygon. The independent-settlement preference protects linked locality
**polygons**; it cannot recover missing municipal boundaries from point evidence.
This is a remaining limitation, not a claim that every new containing answer is
correct. Removing weak administrative containment also lowers the weaker geometric
identity-or-containing score by 147. The exact source evidence and all regressions
are retained in `sample-change-classes.json`.

| Country | Observations | v0 exact | Final exact | v0 same/containing | Final same/containing |
| --- | ---: | ---: | ---: | ---: | ---: |
| AU | 314 | 71 | 78 | 281 | 281 |
| BE | 224 | 193 | 207 | 224 | 224 |
| CA | 513 | 232 | 242 | 511 | 510 |
| CM | 87 | 72 | 77 | 87 | 87 |
| CN | 2122 | 1008 | 1237 | 2040 | 2003 |
| FR | 692 | 580 | 580 | 692 | 692 |
| GB | 868 | 629 | 688 | 843 | 840 |
| GF | 5 | 4 | 4 | 4 | 4 |
| GP | 9 | 9 | 9 | 9 | 9 |
| HK | 141 | 0 | 0 | 141 | 141 |
| ID | 450 | 227 | 233 | 295 | 285 |
| IN | 3779 | 3210 | 3291 | 3469 | 3460 |
| JP | 1301 | 962 | 963 | 1299 | 1292 |
| KR | 148 | 65 | 93 | 134 | 129 |
| MC | 2 | 0 | 0 | 1 | 1 |
| MQ | 8 | 8 | 8 | 8 | 8 |
| NG | 269 | 224 | 263 | 267 | 265 |
| NL | 252 | 225 | 225 | 252 | 252 |
| PH | 530 | 410 | 412 | 505 | 506 |
| PK | 373 | 30 | 317 | 372 | 330 |
| RE | 14 | 4 | 4 | 14 | 14 |
| SG | 65 | 0 | 0 | 65 | 65 |
| TH | 330 | 165 | 191 | 302 | 299 |
| TN | 130 | 31 | 114 | 130 | 124 |
| US | 3410 | 2764 | 2793 | 3334 | 3332 |
| VN | 315 | 3 | 159 | 315 | 293 |
| XK | 21 | 19 | 19 | 20 | 20 |
| YT | 6 | 4 | 4 | 4 | 4 |
| ZW | 31 | 26 | 27 | 28 | 29 |

### Probe answers checked against final world checkpoints

These are scalar answers at the exact r8 centres. The sample's exhaustive
probe-block check confirmed its cell construction with v0 neighbours. After all
277 world checkpoints finished, a second scalar check confirmed that **every
city, state, country and method below is unchanged**, with all 13 named fixtures
passing. Its evidence is `data/work/v1/world-probes-scalar.json`. Final world
answers through published stored cells remain pending until golden completion.

| Probe | City | State | Country | Method |
| --- | --- | --- | --- | --- |
| lower Manhattan | New York | New York | United States | area |
| Tokyo | Tokyo | Tokyo | Japan | area |
| Singapore | Singapore | — | Singapore | area |
| Monaco | Monaco | — | Monaco | area |
| Hong Kong Central | Hong Kong | — | Hong Kong | area |
| Lagos | Lagos | Lagos State | Nigeria | nearest |
| London | London | England | United Kingdom | area |
| Cayenne | Cayenne | — | French Guiana | nearest |
| Pristina | Pristina | District of Prishtina | Kosovo | area |
| Bengaluru | Bengaluru | Karnataka | India | area |
| Paris | Paris | Ile-de-France | France | area |
| Cagayan de Oro | Cagayan de Oro | Cagayan de Oro | Philippines | area |
| Eindhoven | Eindhoven | North Brabant | Netherlands | area |
| Mumbai | Mumbai | Maharashtra | India | nearest |
| Delhi | New Delhi | Delhi | India | area |
| Kolkata | Kolkata | West Bengal | India | area |
| Chennai | Chennai | Tamil Nadu | India | area |
| Karachi | Karachi | Sindh | Pakistan | area |
| Dhaka | Joār Sāhāra | Dhaka Division | Bangladesh | nearest |
| Jakarta | Jakarta | Special Capital Region of Jakarta | Indonesia | area |
| Manila | Manila | Manila | Philippines | area |
| São Paulo | São Paulo | São Paulo | Brazil | area |
| Mexico City | Mexico City | Mexico City | Mexico | area |
| Cairo | Cairo | Cairo | Egypt | area |
| Istanbul | Mercan Mahallesi | Istanbul | Turkey | nearest |
| Moscow | Moscow | Moscow | Russia | area |
| Seoul | Seoul | Seoul | South Korea | area |
| Shanghai | Shanghai | Shanghai | China | area |
| Sydney | Sydney | New South Wales | Australia | area |

The Dhaka and Istanbul probes remain unresolved in the final world checkpoints: Dhaka's
linked polygon does not cover the probe, and Istanbul has no linked city polygon
in the pinned v0 source partition. The nearest eligible GeoNames observations are
Joār Sāhāra and Mercan Mahallesi, both PPL records with population zero. Evidence
is saved in `remaining-probe-evidence.json`; no city boundary is invented from a
population radius or a probe coordinate.

## Whole-world interim comparison

After world reconciliation completed, all **34,171** observations were compared
at the same resolution-8 centres. Before is the archived v0 stored-cell result;
after is the independent scalar oracle using all 277 final country checkpoints.
**The stored-v1-cell check is still pending.** Evidence is `world-scalar.json`
and `world-scalar-change-classes.json` under `data/work/v1/`.

| Measure | v0 stored cells | Final world scalar |
| --- | ---: | ---: |
| Answer | 34,169/34,171 (99.99%) | 34,169/34,171 (99.99%) |
| Country agreement | 34,102/34,171 (99.80%) | 34,102/34,171 (99.80%) |
| State agreement | 33,259/33,907 (98.09%) | 33,259/33,907 (98.09%) |
| Exact city identity | 25,522/34,171 (74.69%) | 27,195/34,171 (79.59%) |
| Identity or containing city | 32,457/34,171 (94.98%) | 32,382/34,171 (94.76%) |

The rule recovers **1,854** old non-identities and introduces **181** new identity
mismatches, net **+1,673**. Recoveries comprise 1,504 untyped localities, 133
county/localadmin footprints, 100 unlinked classified localities, 84 cases where
another linked city previously defeated the observation's own polygon, 17 other
linked containing cities, ten same-name unlinked polygons and six nearest-centre
displacements. New mismatches concentrate in CN 121, MY 21, DE 6 and BE 5; all
others are three or fewer per country. These remain source-identity measurements,
not independent adjudications of every suburb or administrative boundary.
All 21 Malaysian changes now return Kuala Lumpur and satisfy geometric
containment; examples include Setapak, Wangsa Maju, Bukit Bintang and Bangsar.
Their source PPL classifications alone do not establish separate municipalities.
The detailed evidence is `malaysia-regression-evidence.json`; these changes are
retained in the regression count rather than silently relabelled as correct.

## Completed static joins and place integrity

The golden static exports are complete for all 277 final country checkpoints.
`join-audit-v1-static.json` independently counts their Parquet rows; the remaining
cell build does not affect these administrative/phone joins.

| Table | v0 matched / ambiguous / unmatched | v1 matched / ambiguous / unmatched |
| --- | ---: | ---: |
| Countries | 249 / 0 / 3 | 250 / 0 / 2 |
| All subdivisions | 7,087 / 49 / 1,775 | 8,247 / 96 / 568 |
| ISO subdivisions | 3,516 / 0 / 1,530 | 4,617 / 44 / 385 |
| GeoNames admin1 | 3,571 / 49 / 245 | 3,630 / 52 / 183 |
| Phone prefixes | 332,235 / 95,723 / 5 | 427,912 / 44 / 7 |
| Phone metadata | 242 / 0 / 12 | 243 / 0 / 11 |

There are **1,160 additional unique subdivision matches**. Of the 8,247 matches,
7,104 use explicit codes/crosswalks, 1,013 exact administrative aliases, and 130
the source-qualified aliases described above. Ambiguity increases where additional
administrative evidence exposes multiple candidates; no candidate is silently
selected to improve the match count.

The 385 unmatched ISO rows concentrate in EE 69, LT 41, RS 29, VN 29, HU 22,
MA 17, MC 17, PH 17, PS 15 and GB 14. They include administrative units with
different name/type forms or without a corresponding retained unit in the pinned
boundary hierarchy. Remaining GeoNames admin1 gaps concentrate in MH 30, HK 18,
YT 17, AI 14, VN 9 and MO 8. Source versions and the chosen administrative level
do not always provide a one-to-one crosswalk. These are **not all inherently
unresolvable**: validated administrative crosswalks or better source identities
could recover more. Ambiguous aliases and uncertain locality classifications
require more evidence than a name resemblance.
For example, ISO `Alutaguse` corresponds to the retained name `Alutaguse vald`,
and Lithuanian municipality names use grammatical/type forms absent from the
ISO label. British residuals include inverted names (`London, City of`) and
uncoded bilingual annotations. In Vietnam, some ISO administrative names remain
only as settlement identities in the retained hierarchy. Mapping a city with the
same name would not establish the missing administrative identity.

Countries AN/CS remain historical, with no current single-country target.
The 44 phone ambiguities are the 43 overlapping numbering languages and one
unsupported prefix described above. Seven phone prefixes remain unmatched:
five Ascension (AC) rows and two translated `2908` Tristan da Cunha (TA) rows.
The latter now narrow specifically to TA, which has no separate country entity;
v0 assigned the only represented candidate, SH. The original candidate country
codes remain intact. Phone metadata retains AC, TA and nine non-geographic 001
service rows without invented geographic targets.

An independent Parquet-only audit of all **6,875,329 places** found **zero duplicate
IDs, zero missing parent references and zero missing sovereign references**.
`country:EH` occurs exactly once, resolving the 49 former parent and 49 sovereign
gaps. Evidence is `place-integrity-v1.json`. This check deliberately does not
claim final cell-reference integrity or spatial coverage; those gates run after
the cell rebuild completes.

## Detached rebuild state

The gated world controller started at **2026-10-01 23:58:23 UTC**, PID **48816**.
World reconciliation completed at **2026-10-02 00:49:22 UTC**: all 277 countries,
3,058.7 seconds, peak RSS 1.433 GB. All 277 predecessors were retired; an independent
filesystem audit found one replacement each, no retained extract/link intermediates,
and no partial country files. The reconciled tree is 33 GiB; free disk is about
20 GiB. The controller then started golden PID **49952**, with two workers.
It runs reconciliation then the golden build sequentially. Launch metadata:
`data/work/v1/world-launch.json`; stage status: `data/work/v1/rebuild.json`.
Logs: `data/work/v1/reconcile-world.log`, `golden-world.log`, and `controller.log`.
Completion requires `rebuild.json` to contain `completed:true`; the golden
manifest and golden run marker must also be complete. Resume with:

```sh
uv run --no-sync python -m build_data.rebuild_golden --data-dir data \
  --sample-gate data/work/v1/sample.json --workers 2
```

Operational recovery notes are in `data/work/v1-progress.md`. The detached
continuation supervisor is also resumable with
`uv run --no-sync python -m data.work.v1.continue_rebuild` when it is no longer
running. Do not launch duplicate supervisors. At world launch, free disk was
21 GiB; completed sample countries had no superseded SQLite or extract/link
intermediates remaining. World scalar metrics and static joins are reported above;
the final stored-cell world check and spatial lookup joins remain pending.

The detached read-only auditor (PID **49703**, module
`data.work.v1.after_reconcile`) has completed the scalar and static audits and now
waits for the controller. Its log/status are `data/work/v1/after-reconcile.log`
and `after-reconcile.json`. After golden completion it automatically writes
`join-audit-v1.json` and `world-change-classes.json` from the completed publication.
If this read-only auditor has exited, resume it with
`uv run --no-sync python -u -m data.work.v1.after_reconcile` after resuming the
controller. Its results do not publish or alter pipeline inputs.

Handoff snapshot at **2026-10-02 01:09:53 UTC**: **3,300/41,162** cell blocks
committed, zero waiting countries, **19.61 GiB free**. Cells, spatial lookup
joins and final stored-cell settlement/fixture/integrity checks are still running
or queued. The active golden manifest is incomplete; do not treat the interim
scalar result as the completed publication.
