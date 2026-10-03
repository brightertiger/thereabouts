# Pipeline redesign status

Packages 1–3 and the package-1 review fixes are implemented on `feat/pipeline`,
with local commits only. The protected workspace remains unmigrated and has only
been read. Packages 4–5 await the next review. Commands and configuration are in
[DATA_PIPELINE.md](DATA_PIPELINE.md); the current table schema remains
[GOLDEN_DATASET.md](GOLDEN_DATASET.md).

## Package 2–3 review checkpoint: fixes 1–4

Stage identities now hash transitive pipeline imports, with runtime, contract
and schema exclusions. Each source unit hashes only its own pin, settings,
adapter closure and policy files. Tests prove that changing one source pin or
adapter leaves another source and its readers current. Large plate policies
moved to six YAML files; the resolved policy evidence is unchanged. The lock
retains inventory fingerprints and required metadata without duplicate payload
inventories; workspace pin verification and reconstructed-inventory round trips
pass.

On the same M2 / 8 GiB laptop, cold configuration load fell from **2.646 s** to
**0.180 s** (subsequent independent loads: 0.172 and 0.156 s). The ordinary suite
fell from the package-3 checkpoint's **187.68 s** to **46.62 s**, with **644 passed,
8 skipped**. The review separately measured approximately 175 s before these
changes. Import-closure parsing is cached by source bytes; native versions are
cached for the lifetime of the process, while lock bytes are checked each time.
Policy schema validation is cached by canonical policy bytes, not timestamps.

Post-fix real-workspace plan: **85,577 current / 0 stale / 0 new**, **367.32 s**,
**1,413,775,360 bytes peak RSS**. This is simulated adoption: zero stale checks
mapping and recorded/output hashes only, not full-world engine equivalence.
Handover: **85,577 identity/parameter/input-hash updates**, **365.78 s**,
**1,390,477,312 bytes peak RSS**. All output records remain unchanged. Detailed
measurements and old → new identities:
[PIPELINE_REVIEW_MEASUREMENTS.json](PIPELINE_REVIEW_MEASUREMENTS.json).

| Stage | Plan current | Stale | New | Handover units |
| --- | ---: | ---: | ---: | ---: |
| download | 13 | 0 | 0 | 13 |
| normalize | 13 | 0 | 0 | 13 |
| reconcile | 1,111 | 0 | 0 | 1,111 |
| cells | 41,442 | 0 | 0 | 41,442 |
| cities | 555 | 0 | 0 | 555 |
| evaluate | 1 | 0 | 0 | 1 |
| normalize_cells | 41,716 | 0 | 0 | 41,716 |
| lookups | 726 | 0 | 0 | 726 |
| **Total** | **85,577** | **0** | **0** | **85,577** |

Migration scope remains 588 rewritten JSON files plus 6 imports, 42,334 retired
rows and 2,578 explicitly absent paths under the previously approved prefixes.
The protected ledger SHA256 remains `d71802b9…a37` (full value in measurements).
The import-closure initializer regression fix was checked against every declared
stage and source: their hashed file sets and digests are unchanged from these
acceptance runs.

Before work, **1,049,266,242 bytes** of redundant copied migration metadata and
an older pilot reconstruction were removed inside this worktree. Measurement
reports and the final pilot proof remain. Historical copied-ledger directories
referenced below no longer remain; their recorded results are retained.

Safety exception during this checkpoint: one targeted fingerprint-test invocation
omitted `TMPDIR` and wrote small synthetic fixtures under the macOS temporary
pytest directory (`pytest-233`), outside the worktree. No real-workspace data was
touched. Pytest now defaults to `--basetemp=.cache/pytest` in this checkout as an
additional safeguard. The external fixtures have not been modified or removed.

## Package 2–3 review checkpoint: fixes 5–6

Every adapter now exposes `propose(settings)`. `pins update [source...]` writes a
candidate plus a file-level JSON diff; only `--accept` replaces the lock. A saved
proposal can be accepted without contacting upstream. Catalogs select exact
files and GitHub trees, resolve complete Git commits, timezone and IANA releases,
GeoNames/OSM publisher dates, geoBoundaries layer commits and paginated Overture
releases. GHSL's reviewed release remains configured and its SHA256 is measured.
Plate proposals use the reviewed policy URLs, including frozen Wikipedia
revisions. Tests use loopback HTTP only; real upstream availability is untested.
The disabled plate-country catalog requires owner-selected evidence URLs.

The expanded Malaysia proof now reconstructs the base block, MY city index,
canonical-city table and place-to-city mapping before using those products for
both pilot variants. All six output SHA256 values match the retained records.
It checks every one of the block's 16,807 finest cell centres. Measurements:
**20.55 wall seconds**, **538,935,296 peak RSS bytes**, **141,524,404 output bytes**.

The first extended proof exposed native-runtime drift: this worktree's existing
venv used Python 3.12.2 / SQLite 3.46.0, while the retained city index records
SQLite 3.47.1. Logical tables and the city Parquet were identical, but eight
SQLite pages differed. Reusing the locally installed Python 3.12.8 interpreter
with this worktree's existing dependencies reproduced the full index bytes.
`.python-version` now selects that interpreter, and affected stages hash the
actual SQLite library version. No dependency or interpreter was downloaded.
The fixes-1–4 measurements have been corrected to name their actual Python
3.12.2 runtime; their reported timings and hashes are unchanged.

On Python 3.12.8, configuration loads in **0.139 s**; the full suite is **663
passed, 8 skipped in 44.79 s**. Final plan: **85,577 current / 0 stale / 0 new under simulation**, **320.71 s**,
**1,298,595,840 bytes peak RSS**. Handover passed for **85,577 units**,
**312.99 s**, **1,365,983,232 bytes peak RSS**; all eight stage counts match the
fixes-1–4 table above, with zero stale/new after simulated handover. The ledger remains unmigrated and all engine proof writes stay
inside this checkout. No upstream or cloud source requests were made.

## Package 2–3 review checkpoint: fix 7

Geographic stages own parameter callbacks for their policies, resources and
refresh behavior. The shared `GeographicStage` has no stage-name branches.
Land, urban, registration and plate-country inputs are explicit engine roles;
place/area inventory and static lookup decisions use source kinds. Tests cover
renamed source roles, country-scoped invalidation, resource reservations and
invalid source references. The one-source migration fixture now declares only
its two source stages. Full gate: **666 passed, 8 skipped in 45.63 s**;
Ruff and strict mypy pass. Real plan: **85,577 current / 0 stale / 0 new** in
**325.65 s**, **1,097,646,080 bytes RSS**.
Handover dry-run: **85,577 updates**, **317.48 s**,
**1,483,177,984 bytes RSS**; the per-stage table above is unchanged.
Both checks simulate adoption and verify mapping and hashes only. The real ledger
SHA256 remains unchanged; no engine ran against that workspace.

## Package 3: engines and independent handover

The executable registry now covers reconcile, cells, cities, evaluate,
normalize_cells, lookups and optional plate_country. `build_data/` is deleted.
Build-side geometry, table, index, model and serving/pack helpers live under
`pipeline/`, importing only `thereabouts.format` from the client. No client file
changed in this package. Retained stand-ins remain solely for initial migration;
they are not production stage implementations.

Reconciliation and city policies moved mechanically to YAML. Equivalence tests
cover all 676 two-letter country projections and preserve the previous canonical
JSON fingerprints. The historical city review still binds
`a065e704b04fd3340c5e212d1cd70f1f6212275a56e754747672db655230ce9c`.
The previous JSON is retained only as test evidence. Country units include only
the common and relevant country policy; block units include contributing countries.
Evaluation is a required execution gate, rather than a consumed geographic input.
Changing its receipt alone does not rebuild unaffected countries, and a failed
gate still prevents execution, including a run targeting only normalization.

Independent engine discovery initially reproduced all **85,551 engine keys**
from normalized country columns and the retained block inventory in 9.35 s at
511,049,728 bytes peak RSS. It does not enumerate saved recipes. Engine inspection
then corrected four dependency details in both initial adoption and discovery:

- Country-quality reports read the complete reconciled country set and land.
- Static code/phone joins read reconciled aliases and state crosswalks.
- Reconciliation manifest publication requires a successful pilot gate.
- Normalization requires evaluation success without consuming its receipt bytes.

Handover still refuses changed dependencies. **A ledger initially adopted with
the older mapping will refuse these engine handovers; use a fresh initial
adoption with this final code.** The owner's workspace is still unmigrated.
These corrections change dependency/input hashes, never retained output bytes,
unit keys, absence permissions or the approved metadata repair scope. The copied
ledger proof below exercises fresh adoption and then explicit handover. Reports
from the package-2 copy are retained; its copied metadata was removed to keep the
worktree below 3 GB.

Runtime tests exercise fresh and changed block discovery, all geographic stages
through a verified lookup manifest, corruption repair, absent-input regeneration,
and failed-gate ordering. Source/engine decision coverage retained from the old
controllers is listed in [PIPELINE_TEST_COVERAGE.md](PIPELINE_TEST_COVERAGE.md).
Plate-country builds and verifies small synthetic bundles; it has zero real units
because its source is disabled pending a reviewed pin.

One Malaysia block (`836505fffffffff`) was reconstructed from read-only normalized
sources and compared with both retained radius variants. Both are byte-identical:

| Variant | Rows | Parquet bytes | SHA256 |
| --- | ---: | ---: | --- |
| OFF | 8,019 | 79,690 | `f83e156e9b966c3b442cbaf2e08e08f35c40fb331e2d3f81cd484ff75d42cfd4` |
| ON | 8,007 | 79,733 | `02f3b7bee9e6204f22928af12fdbbac3283b730189678be3c356eaa092fc4fb3` |

The reproducible opt-in test passed in **25.64 wall seconds**, with
**577,142,784 bytes peak RSS** and **140,388,737 created bytes**, including 97
complete land features. These are one block's measured results, not a full-world
rebuild claim. The reference input was read-only; reconstructed intermediates and
outputs are inside this checkout. Evidence:
`data/pipeline-work/pilot-proof/test_retained_pilot_bytes0/measurements.json`.

Porting source tests exposed a GHSL attribution regression in package 2. Its YAML
now exactly names CC-BY-4.0 and the original JRC/Pesaresi attribution. Archive
extraction also rejects traversal member names before any write. Final source
handover includes these corrections.

A first final handover passed but peaked at **2,304,770,048 bytes RSS**, exceeding
the intended roughly 2 GB process budget. Planning no longer decodes every saved
recipe merely to list stages, and handover now reads completion/recipe pairs one
at a time. A regression test prevents the former full-recipe allocation. Final
measurements below supersede the initial run; this over-budget run is retained
here explicitly rather than described as within the limit.

Final acceptance on Apple M2 / 8 GiB / macOS / CPython 3.12.8:

| Check | Result | Wall seconds | Peak RSS bytes |
| --- | --- | ---: | ---: |
| Real-workspace handover dry-run | 85,577 handovers; zero stale/new | 359.29 | 1,607,909,376 |
| Real-workspace plan | 85,577 current; zero stale/new under simulation | 346.18 | 1,407,909,888 |
| Copied-ledger adoption, handover, ordinary plan and idempotence | passed; zero stale/new without simulation | 541.96 | 1,480,228,864 |
| Pilot block, both variants | byte and logical equality | 25.64 | 577,142,784 |

The copied ledger is **523,980,800 bytes**; copied rewritten/imported JSON totals
**30,689,281 bytes**. No Parquet tree was copied for migration. Handover preserved
output records and completion timestamps; the real ledger hash/mtime and every
original JSON remained unchanged. The final ledger SHA256 is still
`d71802b95e36aeed8b95b53b3613e3499a4cfc7eb051dbac8880856fa5d73a37`.
Worktree files total **2,294,064,634 bytes**, with **49,010,413,568 bytes free** at
final measurement. The proof checks both limits before copying and reserves
measured SQLite growth plus rollback-journal space before handover application.

Full suite: **639 passed, 8 skipped** in 187.68 s. The two explicitly selected
world proofs above also passed. Ruff check and formatting passed (485 files);
strict mypy passed (472 source files). `pins check --from-workspace` passed.
The production `resolve()` calls were reviewed: they validate/locate filesystem
paths or are geographic resolver methods; persisted artifact records remain
workspace-relative. There are no production `build_data` imports and no pipeline
imports from the client except `thereabouts.format`.

[PIPELINE_ENGINE_MEASUREMENTS.json](PIPELINE_ENGINE_MEASUREMENTS.json) records
stage-by-stage old → new identities, counts, pilot hashes and measurements.
Full reports: `.cache/pipeline/engines-handover-final.json` and
`.cache/pipeline/engines-plan-final.json`; copied-proof evidence is under
`data/pipeline-work/engines-world-proof/`. The final dry-run hashes
17,677,116,404 present payload bytes; remote custody remains unverified.

## Package 2: sources

Download and normalize are executable stages with fourteen typed source
configurations, thirteen enabled sources, bounded source adapters, and a
reviewed `pins.lock`. The source registry has no hard-coded source-name list.
Simple adapters are single modules; complex geometry/name/plate parsers retain
small modules by responsibility. `plate_country` has a declared evidence adapter
and disabled configuration because no built payload or inventory exists in the
retained workspace. Its inference engine belongs to package 3; enabling the
source requires an explicit reviewed pin.

[DATA_PIPELINE.md](DATA_PIPELINE.md#sources-and-frozen-versions) gives the source,
lock and restore commands. `pins update` accepts an explicit candidate lock or
an existing workspace's exact manifest inputs. It never selects latest during
execution. The download stage verifies frozen sizes/checksums, reuses local or
mirrored bytes, and verifies a content-addressed mirror copy before completion.
Historical GCS prefixes remain fallback restore locations with bound custody
receipts. Tests use fsspec memory and local directory backends. No real mirror
or upstream data request was made. The GCS driver is installed and locked;
package dependencies were downloaded without uploading project data.

Normalizers stream source rows, retain attribution/rejection evidence, publish
root-relative manifests and track caches. Missing GeoNames and Overture caches
are regenerated before normalization. Plate rules moved mechanically to YAML;
PDF parsing checks the configured Poppler version, measured locally as 25.11.0.
This does not establish Poppler's version for historical builds. HTTP recovery
resumes at file boundaries. Existing engines and the old `build_data` package
are still unchanged at this checkpoint.

The lock has **1,098 payload records for thirteen built sources**, plus the
explicit unavailable `plate_country` record. `pins check --from-workspace`
passes against the protected workspace. Versions include:

| Source | Retained version or evidence |
| --- | --- |
| Overture | `2026-09-23.1`, nine objects |
| GeoNames | dump `20261001`, inventory `20261001T160939Z` |
| geoBoundaries | manifest-selected `gbOpen-a5b064cdf7dc8c3cb70b`, 430 pinned layers/commits |
| GHSL | `R2024A-V1.2`; SHA256 `bc879d82320504f89df2041b7936221c8239cd808abe93980493aed062b4f3d6` |
| OSM land | `2026-10-01T03:37:19Z`; ETag `"374dfb18-65cbf220083e3"` |
| DB-IP | `2026-10`; 7,786,864 publisher rows |
| Time zones | boundary `2026d`, IANA `2026e` |
| Phone | commit `0ae309f1940227efe688f5eb1815ef45a6fbee8d` |
| Codes | country-list `2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1`, pycountry `4c6a69927a25326a69bf753671fb571bb437cd7d` |
| UN/LOCODE | commit `b1309b37edea63334a819a78c22b8967f61c37ad` |
| Plates | inventory `5cfeab8a47dec58b3725c42a41a097ad74d138ac88d02d252ca3eda7ba987606` |
| Airports / postal | exact retained inventory timestamps and per-file SHA256 in `pins.lock` |

geoBoundaries' newer unused raw inventory is deliberately not substituted for
the manifest-selected build inputs. Pins record the actual per-file licences,
not a single guessed licence for mixed-source tables.

The stage table below remains **85,577 current / 0 stale / 0 new**. Source
handover verifies exact key equality, all present output bytes, and the approved
absent-output evidence, then proposes thirteen download and thirteen normalize
identity/parameter/input-hash updates. The simulated zero-stale result checks
mapping and hashes only; it does not prove source-output equivalence on world
inputs. Synthetic source tests cover every adapter, malformed configuration,
mirror restore/corruption/failure, resumption, portable paths after a move,
licence/provenance and name/geometry decisions.

The explicit world test applied adoption to a copied ledger and JSON only,
then applied all 26 handovers to that copy. Reopening it reports zero stale;
output records are unchanged and a repeated migration is idempotent. It also
checks the protected ledger hash/mtime and all original JSON bytes unchanged.
Measured on the M2 / 8 GiB laptop: **493.645 s**, **850,755,584 bytes peak RSS**,
**152,739,840 ledger bytes** and **30,689,281 overlaid JSON bytes**. Evidence:
`data/pipeline-work/sources-world-proof/test_world_copy_application0/measurements.json`.
The preceding approved-absence copy proof passed in 332.095 s, peak RSS
1,195,245,568 bytes, copied ledger 151,154,688 bytes and the same JSON bytes.

Final handover dry-run: **26 changes**, **261.52 s**, **1,065,615,360 bytes
maximum RSS**. Its report's identities equal the final source identities:

| Ported stage | Discovered / adopted | Changed | Old → new identity |
| --- | ---: | ---: | --- |
| download | 13 | 13 | `24cfed679d15e584897e265554f0849727ad85bceb0f218404e0d590fc639600` → `bdb2d51cb502a516e06818254265809d12a9918752cc4fcf1d512ddc4e2d8175` |
| normalize | 13 | 13 | `bf86e23ded2aa3f26c943b4f0cad9181f6652871829db2efb6a7e42ca6b7b36f` → `d9bcdad2f63bd1f6773779393c8924647206a8be8b7a5ae6c89ea659bd318f20` |

Reports: `.cache/pipeline/sources-handover.json` and
`.cache/pipeline/sources-plan.json`; logs under `data/pipeline-work/sources-*`.
Full checks: **737 passed, 8 skipped** in 134.37 s; Ruff and formatting passed
(552 files); strict mypy passed (536 source files). The opt-in world proof is an
additional passing test. Final read-only plan: **254.88 s**, **1,255,784,448 bytes maximum RSS**,
85,577 current / 0 stale / 0 new. Worktree allocation was 2,524,268 KiB
and free disk 46 GiB before commit, within the 3 GB / 5 GB limits.


## Review fixes 1–3

Fixes H1, H2 and M4 are implemented together: verified one-time identity handover,
permission preflight before lock/backup/journal creation (including recovery), and
original-backup verification across separate paths/adopt operations. The source
ledger remains `d71802b95e36aeed8b95b53b3613e3499a4cfc7eb051dbac8880856fa5d73a37`.
Checks: 685 tests passed, 8 skipped; Ruff/format passed (468 files); strict mypy
passed (452 source files). Read-only plan and handover dry-run both reproduce the
stage table below: 85,577 current, zero stale/new.

`migrate handover --dry-run` on an adopted ledger compares independently discovered
ported-stage keys with the saved keys, verifies outputs, and proposes only new
identity, parameters and input hash. Outputs, completion times, custody and absent
markers stay intact. It refuses changed dependencies and a second identity change
after handover. The handover audit lives separately in SQLite. At the review-fix checkpoint no stage was ported, so its real-workspace dry run
had zero eligible ported stages;
the transition is exercised on synthetic applied ledgers.

The protected workspace still has its legacy ledger. A handover dry run there
first simulates adoption using `config/adoption.yaml`, then checks any ported
stages' independent discovery. Plan prints explicitly that zero stale under this
simulation is by construction: it checks mapping and hashes, not engine
semantics. Packages 2 and 3 must additionally pass handover on an applied copied
ledger and the independent source/engine tests. Ordinary plan against an applied
ledger remains strict and does not silently hand over changed identities.

For reviewer application, generate a fresh dry-run report first. It lists exactly
the existing directories needing temporary write permission in
`writable_directories` (302 at this checkpoint). Apply and recover also print each
exact `chmod u+w` command and its matching `chmod a-w` command if permission is
missing. Neither command runs chmod itself. Run these commands **only as the
reviewer applying the approved migration**, from this worktree:

```sh
set -eu
PIPELINE_DATA=/Users/ujjwal/Downloads/solo/thereabouts/data
.venv/bin/python -m pipeline migrate --dry-run --root "$PIPELINE_DATA" --report .cache/pipeline/migration.json
.venv/bin/python -c 'import json; print("\n".join(json.load(open(".cache/pipeline/migration.json"))["writable_directories"]))' > .cache/pipeline/writable-directories.txt
while IFS= read -r directory; do
  [ -z "$directory" ] || chmod u+w "$PIPELINE_DATA/$directory"
done < .cache/pipeline/writable-directories.txt
.venv/bin/python -m pipeline migrate --root "$PIPELINE_DATA" --report .cache/pipeline/migration-applied.json
.venv/bin/python -m pipeline migrate check --root "$PIPELINE_DATA"
while IFS= read -r directory; do
  [ -z "$directory" ] || chmod a-w "$PIPELINE_DATA/$directory"
done < .cache/pipeline/writable-directories.txt
```

Keep the directory list until application/recovery has completed and protections
are restored. It is generated before chmod and is not replaced by the application
report. No chmod command above was executed against the real workspace.
The shell sequence stops on a failed dry run, so it cannot use a stale report.
Real application remains a reviewer action; none of these chmod/apply commands
was executed against the protected workspace.

## Review fixes 4–9 and the approved auxiliary absence

Fix 4 preserves JSON token layout and reports every repair class; the complete
extra-file list follows below. Fix 5 restricts reconcile absence to two explicit
prefixes. A fresh read-only inspection found 834 absent files under `reconciled/`
and 1,662 under `work/reconcile/` (extract/link intermediates). No other reconcile
path is excused. Four raw-source offload receipts retain the existing separately
bound raw-absence exception.

Fix 6 retains all five old `geonames.extract`, `geonames.index` and
`overture.index` rows as auxiliary normalize outputs, with eight output records.
Four small outputs totaling 138,527 bytes are present and hash correctly. The
four large payloads below are already absent. Together their recorded sizes
are **3,260,159,017 bytes**; their hashes are evidence, not verified local bytes.

| Missing output (relative to root) | Recorded bytes | Recorded SHA256 |
| --- | ---: | --- |
| `work/geonames/extracted/e4c7baccd1db52649d87949e69c93083b57ddf7e3c12d4b630b135dc295097d7/allCountries.txt` | 1,788,639,329 | `1a3337f7bd9154dac6130aa7afa235eaea90423c739b1d27b4fd648c8701d110` |
| `work/geonames/extracted/c239df53b3a4653fefb7a8490a3bb61d3b6c0b6996204f6089a9293d94f91e54/alternateNamesV2.txt` | 785,574,856 | `0f372173b2c76b82cf79870cc280a1e68e4b99b6f5875fd3d1951305d661fd46` |
| `work/geonames/62937f7ffe0bec0f8385fc69ce1d9a75be318abeac8b52bf1e52622e0f7ba83b/lookup.sqlite3` | 271,413,248 | `a6d6f870e357eb45918d7f483c850f7c4da578cb062bef95b851f4f606982d5e` |
| `work/overture/entities.sqlite3` | 414,531,584 | `375cda6f79cd4a557161c508185d4a18b65a559d017f1e804bf2b24555556ad7` |

**Owner decision, 2026-10-03:** these four payloads were deliberately deleted
in an earlier disk cleanup and are regenerable caches of raw inputs mirrored in
GCS. Adoption retains their recorded hashes and marks `outputs_absent`, only
under `work/geonames/` and `work/overture/`, tied to the corresponding normalize
source. **A future rebuild of normalize for these sources must regenerate these
caches first.** Present corrupt payloads and missing outputs anywhere else still
refuse adoption. Remote mirror custody is owner-provided evidence, not verified
by these read-only checks.

Fix 7 restores `docs/GOLDEN_DATASET.md` as the current schema, leaves links at
`GOLDEN_V2.md` and `CITY_NORMALIZATION_PLAN.md`, and clarifies scratch locations.
Fix 8 caches workspace-size scans for the configured interval (default 60 s),
accounts for reservations/completed bytes incrementally, and moves filesystem
walks out of the admission lock. Free disk and RSS remain per-admission checks.
A synthetic 1,000-admission test performs one walk until the interval elapses.
Fix 9 separates CLI validation/handlers, removes runtime→migration imports and
production asserts, requires configured writable-ledger timeouts, rejects
non-Python identity files, validates the codec block resolution, and names the
fixed historical migration paths separately from configurable future paths.

| Latest read-only command | Current | Stale | New | Absent units |
| --- | ---: | ---: | ---: | ---: |
| `plan` | 85,577 | 0 | 0 | 1,117 |
| `migrate handover --dry-run` | 85,577 | 0 | 0 | 1,117 |

Both checks succeeded after the owner-approved extension. At the approved-absence checkpoint no stage had been ported, so that report
had zero actual-stage identity handovers. Package 2 now hands over 26 units.
Simulation checks mapping and hashes only; it does not prove engine equivalence.

| Approved absent prefix | Files |
| --- | ---: |
| `reconciled/` | 834 |
| `work/reconcile/` | 1,662 |
| `work/geonames/` | 3 |
| `work/overture/` | 1 |
| `raw/geoboundaries/` | 63 |
| `raw/geonames/` | 2 |
| `raw/osm_land/` | 4 |
| `raw/overture/` | 9 |
| **Total** | **2,578** |

Read-only evidence is in `.cache/pipeline/approved-absence-plan.json` and
`approved-absence-handover.json`; logs are under this checkout's
`data/pipeline-work/review/approved-absence-*.log`. The real ledger SHA256 remains
`d71802b95e36aeed8b95b53b3613e3499a4cfc7eb051dbac8880856fa5d73a37`.
The plan took 186.70 s with 960,806,912 bytes maximum RSS on the M2 / 8 GiB laptop.
The dry run verified 17,677,116,404 local bytes. Full synthetic checks: **708
passed, 8 skipped**; Ruff and formatting passed (477 files); strict mypy passed
(461 source files). The absence regression tests cover both approved sources,
present corruption, wrong directories and cross-source paths.

At that checkpoint, source and engine ports were still outstanding. Package 2
now supplies source discovery and the lock; engine ports and pilot-block
comparisons remain for package 3. No source or engine was run
against the real workspace.

## metadata repairs needing owner approval

The owner approved these repair classes in the review follow-up, conditional
on preserving JSON formatting and listing every extra file. Application to the
real workspace remains a reviewer action. Repairs now replace only changed
scalar tokens: original indentation, separators, key order, newline style and
unchanged string escapes survive byte-for-byte. Shape changes are refused.

The exact spec set used for this inventory is the thirteen normalized source
manifests, city manifest, original `work/v2-pilot/gate.json`, and GHSL inventory.
The newer `thereabouts-gate.json` is conservatively included in the extra list.
No listed repair changes Parquet or geographic results. Six imported JSON
evidence files keep their original bytes.

| File class | Files | Outside spec | Path tokens | Cascaded hashes | Repointed tables |
| --- | ---: | ---: | ---: | ---: | ---: |
| active dataset metadata | 2 | 2 | 0 | 3 | 0 |
| city country metadata | 554 | 554 | 831 | 0 | 0 |
| city manifest | 1 | 0 | 31 | 1 | 0 |
| imported repository evidence | 6 | 6 | 0 | 0 | 0 |
| normalized auxiliary metadata | 1 | 1 | 1 | 0 | 0 |
| normalized source manifest | 13 | 0 | 11884 | 10 | 0 |
| pilot gate receipt | 2 | 1 | 3 | 3 | 0 |
| pilot summary | 1 | 1 | 36 | 0 | 0 |
| raw source inventory | 9 | 8 | 651 | 0 | 0 |
| retained base manifest | 1 | 1 | 42160 | 0 | 42160 |
| source custody receipt | 4 | 4 | 0 | 4 | 0 |

There are 588 existing-file repairs and six imports; 578 files are outside
the explicit spec set. The list below names every one, relative to the data
root. `golden-base-thereabouts/manifest.json` repoints all 42,160 table paths
to retained immutable base files. `golden-thereabouts/manifest.json` and
`normalization.json` receive only cascaded metadata hashes/sizes.

<details>
<summary>All 578 files outside the explicit spec set</summary>

**active dataset metadata (2)**

- `golden-thereabouts/manifest.json`
- `golden-thereabouts/normalization.json`

**city country metadata (554)**

- `city_normalized/00d40ab03970e48ed13a000c2fdb6489ca91f71d005fa37c46b00ec1670e4b48/XU/mapping.json`
- `city_normalized/00d40ab03970e48ed13a000c2fdb6489ca91f71d005fa37c46b00ec1670e4b48/XU/report.json`
- `city_normalized/042204fb6b8eb19bda6d9d0d48337fdbb8136e878434a946299dbda20619e0e3/AL/mapping.json`
- `city_normalized/042204fb6b8eb19bda6d9d0d48337fdbb8136e878434a946299dbda20619e0e3/AL/report.json`
- `city_normalized/064633bdcb1940dbcca12bbf6d2c1c96fd53e0dd03c570933b679c8f2789bb98/PG/mapping.json`
- `city_normalized/064633bdcb1940dbcca12bbf6d2c1c96fd53e0dd03c570933b679c8f2789bb98/PG/report.json`
- `city_normalized/069f12be72720b1a33414e69937ababe7f4a35e37c611fa8d7d19984cef78cd6/XA/mapping.json`
- `city_normalized/069f12be72720b1a33414e69937ababe7f4a35e37c611fa8d7d19984cef78cd6/XA/report.json`
- `city_normalized/07aa1b686b811df035230750b1f2cd7a0b3753c0f8ee1bd0c81058c3959901dd/FR/mapping.json`
- `city_normalized/07aa1b686b811df035230750b1f2cd7a0b3753c0f8ee1bd0c81058c3959901dd/FR/report.json`
- `city_normalized/0830f1ade535e781e20088bfe430c5612db3340fe01db0d3b4f64589fe0594ea/FM/mapping.json`
- `city_normalized/0830f1ade535e781e20088bfe430c5612db3340fe01db0d3b4f64589fe0594ea/FM/report.json`
- `city_normalized/090b7ecd29d996b7f0fcae7ae470b4f19d1b4339a134fcc157fb11a1e7d37c52/AR/mapping.json`
- `city_normalized/090b7ecd29d996b7f0fcae7ae470b4f19d1b4339a134fcc157fb11a1e7d37c52/AR/report.json`
- `city_normalized/09166d87d2810649540aaca601c819283dc7faf599e8f0d0c418ffb41d1f4750/XR/mapping.json`
- `city_normalized/09166d87d2810649540aaca601c819283dc7faf599e8f0d0c418ffb41d1f4750/XR/report.json`
- `city_normalized/095c66d652b61441f104d531c4e1cda78b334600b911711594863a344b459f2e/GY/mapping.json`
- `city_normalized/095c66d652b61441f104d531c4e1cda78b334600b911711594863a344b459f2e/GY/report.json`
- `city_normalized/09b7a6a421fc464caa2966d759f6317c88500a7539543499de1a27c4db2561d4/AW/mapping.json`
- `city_normalized/09b7a6a421fc464caa2966d759f6317c88500a7539543499de1a27c4db2561d4/AW/report.json`
- `city_normalized/0b927ce2eda9e7cd3f657a87dbf1803dcb720b7b8071973588c5f775660921f3/AE/mapping.json`
- `city_normalized/0b927ce2eda9e7cd3f657a87dbf1803dcb720b7b8071973588c5f775660921f3/AE/report.json`
- `city_normalized/0bdc4db7d87b79ed94c8783d42d56402a6459f2faa8ad9abebd35e07322edfd6/DZ/mapping.json`
- `city_normalized/0bdc4db7d87b79ed94c8783d42d56402a6459f2faa8ad9abebd35e07322edfd6/DZ/report.json`
- `city_normalized/0c10a9d4fef2d1967d442b8d5411fbd58af4802eaa3130cb74a91f80c602e99b/GS/mapping.json`
- `city_normalized/0c10a9d4fef2d1967d442b8d5411fbd58af4802eaa3130cb74a91f80c602e99b/GS/report.json`
- `city_normalized/0f0ff32df19efeea08920a57fe75d33a5c09555bd416cb27a73834ce575626d3/SM/mapping.json`
- `city_normalized/0f0ff32df19efeea08920a57fe75d33a5c09555bd416cb27a73834ce575626d3/SM/report.json`
- `city_normalized/0f8495b692847d2ee42cb4a33f7e27e8e2cbce5b1ebf430456a8ccddb21d3aa8/VN/mapping.json`
- `city_normalized/0f8495b692847d2ee42cb4a33f7e27e8e2cbce5b1ebf430456a8ccddb21d3aa8/VN/report.json`
- `city_normalized/1065d776eaf86dcb37da283ad14af0a22079252ae5d9f1a5458e9764213b2e1c/NP/mapping.json`
- `city_normalized/1065d776eaf86dcb37da283ad14af0a22079252ae5d9f1a5458e9764213b2e1c/NP/report.json`
- `city_normalized/132d85e3fa8f3d1361a4406ff07ebea373ea785e3715e55c65d9ddab7f4e0f7b/GW/mapping.json`
- `city_normalized/132d85e3fa8f3d1361a4406ff07ebea373ea785e3715e55c65d9ddab7f4e0f7b/GW/report.json`
- `city_normalized/138a323dcf006704e59b3d1a0591332ba8d80d22270982cb8884112394b9196f/SY/mapping.json`
- `city_normalized/138a323dcf006704e59b3d1a0591332ba8d80d22270982cb8884112394b9196f/SY/report.json`
- `city_normalized/13c55944f4cfb221befbe2b34a49a7f0357cf42a93797a56256d32fb0b8323df/DM/mapping.json`
- `city_normalized/13c55944f4cfb221befbe2b34a49a7f0357cf42a93797a56256d32fb0b8323df/DM/report.json`
- `city_normalized/15b6189da5253fde86985f085422419a19076c92259a470752aa772e178bc688/CW/mapping.json`
- `city_normalized/15b6189da5253fde86985f085422419a19076c92259a470752aa772e178bc688/CW/report.json`
- `city_normalized/175554214811711389b736e0c65c4e31d233bf0c43a602fbc7d3f8062d862458/TW/mapping.json`
- `city_normalized/175554214811711389b736e0c65c4e31d233bf0c43a602fbc7d3f8062d862458/TW/report.json`
- `city_normalized/17fbe583099e93d2f04d1312dae2bc64049f97615f2b8b3ab8826e53ec968bf5/KG/mapping.json`
- `city_normalized/17fbe583099e93d2f04d1312dae2bc64049f97615f2b8b3ab8826e53ec968bf5/KG/report.json`
- `city_normalized/1809ac9d1d366049a959424b959da00110d73d8487a024e7d37bd1bacb9b277f/TR/mapping.json`
- `city_normalized/1809ac9d1d366049a959424b959da00110d73d8487a024e7d37bd1bacb9b277f/TR/report.json`
- `city_normalized/18240ac26edc9cb954d92a7488883798842b9a64f6b6cd53f599b8a655f24f27/JM/mapping.json`
- `city_normalized/18240ac26edc9cb954d92a7488883798842b9a64f6b6cd53f599b8a655f24f27/JM/report.json`
- `city_normalized/1891a17e337b6a09fcbcab860476de64bf89d0ad1dd089efcb152b045af5f801/MV/mapping.json`
- `city_normalized/1891a17e337b6a09fcbcab860476de64bf89d0ad1dd089efcb152b045af5f801/MV/report.json`
- `city_normalized/194557fd4353e4b09fff2c0d351ae9132da2b1afdb24edab6ae928416a22c5be/BE/mapping.json`
- `city_normalized/194557fd4353e4b09fff2c0d351ae9132da2b1afdb24edab6ae928416a22c5be/BE/report.json`
- `city_normalized/1a5a5ebaeb80c10e95a72e03f1a6a1c65c0e39b240ffc7c11e06d7be7c75eaf1/XZ/mapping.json`
- `city_normalized/1a5a5ebaeb80c10e95a72e03f1a6a1c65c0e39b240ffc7c11e06d7be7c75eaf1/XZ/report.json`
- `city_normalized/1ae55eb95482f2fe848cf0f60d2b6d2ede7f05541e220692b0efcafe566de10a/CS/mapping.json`
- `city_normalized/1ae55eb95482f2fe848cf0f60d2b6d2ede7f05541e220692b0efcafe566de10a/CS/report.json`
- `city_normalized/1ca0e828d8b47cdff122ebc7fdf084d989ce14e0c996f77f57a2988f3ebe18e5/YU/mapping.json`
- `city_normalized/1ca0e828d8b47cdff122ebc7fdf084d989ce14e0c996f77f57a2988f3ebe18e5/YU/report.json`
- `city_normalized/1ca591286f479d774c7e36a7a6c0f937d8736f03ac1c60631f51747f9a3b43db/CG/mapping.json`
- `city_normalized/1ca591286f479d774c7e36a7a6c0f937d8736f03ac1c60631f51747f9a3b43db/CG/report.json`
- `city_normalized/1ece164bd2d6a77a4dab7b0c917c957f0afc9957d0d315969138b44c55deca6f/CN/mapping.json`
- `city_normalized/1ece164bd2d6a77a4dab7b0c917c957f0afc9957d0d315969138b44c55deca6f/CN/report.json`
- `city_normalized/21efc11550be23c4c0da9095c12515606bf71b14bbb790445294059df12ab4e0/SK/mapping.json`
- `city_normalized/21efc11550be23c4c0da9095c12515606bf71b14bbb790445294059df12ab4e0/SK/report.json`
- `city_normalized/24227194f925907924acb5a45fa870923347ab8845b3fa202c4b56fef66da89a/PR/mapping.json`
- `city_normalized/24227194f925907924acb5a45fa870923347ab8845b3fa202c4b56fef66da89a/PR/report.json`
- `city_normalized/2431f7f649753a26eb314f450a98d4f6b3cefb57df4c4f6b3d8339f97aa9d550/KP/mapping.json`
- `city_normalized/2431f7f649753a26eb314f450a98d4f6b3cefb57df4c4f6b3d8339f97aa9d550/KP/report.json`
- `city_normalized/2462b064aeeaa9a53f9833f52dccc98413c600461eba5c039bee1491120b89b5/GI/mapping.json`
- `city_normalized/2462b064aeeaa9a53f9833f52dccc98413c600461eba5c039bee1491120b89b5/GI/report.json`
- `city_normalized/29351102a2a60aee4248b523f0a9977ba5ee2f9df6d0f7501581ff334203f972/MO/mapping.json`
- `city_normalized/29351102a2a60aee4248b523f0a9977ba5ee2f9df6d0f7501581ff334203f972/MO/report.json`
- `city_normalized/2a27b88d6e9d0bd57c03870d5f49ceb619d63b082fd851a47988b0c14f2bbfcf/XG/mapping.json`
- `city_normalized/2a27b88d6e9d0bd57c03870d5f49ceb619d63b082fd851a47988b0c14f2bbfcf/XG/report.json`
- `city_normalized/2a71d2b999ea64e74fd4e752e30736f3702746bbd987d1fe34fc006beac03f81/VG/mapping.json`
- `city_normalized/2a71d2b999ea64e74fd4e752e30736f3702746bbd987d1fe34fc006beac03f81/VG/report.json`
- `city_normalized/2b9d384c970b416c59f371b50fe1e448ea47979629930189cfd46fd63e6ac157/GD/mapping.json`
- `city_normalized/2b9d384c970b416c59f371b50fe1e448ea47979629930189cfd46fd63e6ac157/GD/report.json`
- `city_normalized/2c6d2d14fa29e4da2af7c96a6680c72dad617d0f836e82c39f15556864d440ea/XP/mapping.json`
- `city_normalized/2c6d2d14fa29e4da2af7c96a6680c72dad617d0f836e82c39f15556864d440ea/XP/report.json`
- `city_normalized/2cd00775d0c5eb9641278ad354655d4ebecdf75d2afeb441d4ddc54ba2bb529a/WF/mapping.json`
- `city_normalized/2cd00775d0c5eb9641278ad354655d4ebecdf75d2afeb441d4ddc54ba2bb529a/WF/report.json`
- `city_normalized/2d4e5dfe3b67de1ef7c2e1389f02bf027e2563bfa8eb38ef61453a5884aae5e4/CM/mapping.json`
- `city_normalized/2d4e5dfe3b67de1ef7c2e1389f02bf027e2563bfa8eb38ef61453a5884aae5e4/CM/report.json`
- `city_normalized/2d82009167f5a31bed0b10121a5d6bb0f4e78a2b1531d9c3da85ea845188cc1c/XL/mapping.json`
- `city_normalized/2d82009167f5a31bed0b10121a5d6bb0f4e78a2b1531d9c3da85ea845188cc1c/XL/report.json`
- `city_normalized/2e16a2f74affe9394512950165dc1d6dacea17a91d03d04910886ea133691085/VC/mapping.json`
- `city_normalized/2e16a2f74affe9394512950165dc1d6dacea17a91d03d04910886ea133691085/VC/report.json`
- `city_normalized/2e490c5a3ae76dc00f43015427fe225ee6b6e65e96272aef32ebb7075e866ae2/BA/mapping.json`
- `city_normalized/2e490c5a3ae76dc00f43015427fe225ee6b6e65e96272aef32ebb7075e866ae2/BA/report.json`
- `city_normalized/2e52451c642c1d98e6a112771c3a034ec4caea5bc1e3690ef98ec0ca9bc7fd62/FJ/mapping.json`
- `city_normalized/2e52451c642c1d98e6a112771c3a034ec4caea5bc1e3690ef98ec0ca9bc7fd62/FJ/report.json`
- `city_normalized/30a06f578d5bcbe2d0f0dd693ad85f036dfa0ed9fb0918cbc9e3a888728bf7f3/BL/mapping.json`
- `city_normalized/30a06f578d5bcbe2d0f0dd693ad85f036dfa0ed9fb0918cbc9e3a888728bf7f3/BL/report.json`
- `city_normalized/30c75c4012838238838e417bda2fc53ec8ebd518428e1cd571afd8964a3e69e2/SX/mapping.json`
- `city_normalized/30c75c4012838238838e417bda2fc53ec8ebd518428e1cd571afd8964a3e69e2/SX/report.json`
- `city_normalized/314de65090e9b1a30d0d8f92c26aa00c2a19087c60319d8e985bc8c9b9b456fa/XY/mapping.json`
- `city_normalized/314de65090e9b1a30d0d8f92c26aa00c2a19087c60319d8e985bc8c9b9b456fa/XY/report.json`
- `city_normalized/322d0b7e21194e18099e0600b9c11cf981834b06429b002e8e5879e62b644a0d/CR/mapping.json`
- `city_normalized/322d0b7e21194e18099e0600b9c11cf981834b06429b002e8e5879e62b644a0d/CR/report.json`
- `city_normalized/324dfefc1a8f9a8c857306663b5718c357f67147c7ea305dfbb2bcc7d3cf05c4/AX/mapping.json`
- `city_normalized/324dfefc1a8f9a8c857306663b5718c357f67147c7ea305dfbb2bcc7d3cf05c4/AX/report.json`
- `city_normalized/33dab940e64ed6876e456d2575ef5a3641249f90bf680d618558cfb18f0d1636/LT/mapping.json`
- `city_normalized/33dab940e64ed6876e456d2575ef5a3641249f90bf680d618558cfb18f0d1636/LT/report.json`
- `city_normalized/33f137662e6cbcabc67ca09f0b8500ae22c3ff96dd94af44f31f7deaca578def/PY/mapping.json`
- `city_normalized/33f137662e6cbcabc67ca09f0b8500ae22c3ff96dd94af44f31f7deaca578def/PY/report.json`
- `city_normalized/35379743f5150e01c3c46aa22ac3641ea1cd90f68b78318056d293ad73c36e45/BF/mapping.json`
- `city_normalized/35379743f5150e01c3c46aa22ac3641ea1cd90f68b78318056d293ad73c36e45/BF/report.json`
- `city_normalized/372866aaedab1880f46dccfb4e5de686e4c846b85f98007cd7c1b5bda6616e67/AD/mapping.json`
- `city_normalized/372866aaedab1880f46dccfb4e5de686e4c846b85f98007cd7c1b5bda6616e67/AD/report.json`
- `city_normalized/374563c5eab6980c3f9f5a72a6aa82ff721eb2c557240aacfaf9e2b061c47c3d/CY/mapping.json`
- `city_normalized/374563c5eab6980c3f9f5a72a6aa82ff721eb2c557240aacfaf9e2b061c47c3d/CY/report.json`
- `city_normalized/3782f103caf7fba130016c7e4b6a546b0c2967a91159f1c32cada9a663d155de/TK/mapping.json`
- `city_normalized/3782f103caf7fba130016c7e4b6a546b0c2967a91159f1c32cada9a663d155de/TK/report.json`
- `city_normalized/37966421c9ce87f89c508e1387ccbf7cac49ed352564e6d1977e4c9f69c096ad/SC/mapping.json`
- `city_normalized/37966421c9ce87f89c508e1387ccbf7cac49ed352564e6d1977e4c9f69c096ad/SC/report.json`
- `city_normalized/3bbff91537e9fdd3c4441f8f25321123d4342ff010def7b525a53b43c86a1430/YT/mapping.json`
- `city_normalized/3bbff91537e9fdd3c4441f8f25321123d4342ff010def7b525a53b43c86a1430/YT/report.json`
- `city_normalized/3bf7ae8bb85995285e957f77976c09a81be1a0debd60f9549baf024a12a11e1f/MY/mapping.json`
- `city_normalized/3bf7ae8bb85995285e957f77976c09a81be1a0debd60f9549baf024a12a11e1f/MY/report.json`
- `city_normalized/3d01e2403546b2459fde111000b0a32101e473859f7b682a5509930fe4a22c2c/LC/mapping.json`
- `city_normalized/3d01e2403546b2459fde111000b0a32101e473859f7b682a5509930fe4a22c2c/LC/report.json`
- `city_normalized/3dad8f6b7ba45737c97e31f297c0c08d4b69de18f7ad458dfac4df2e9dacbfe5/IT/mapping.json`
- `city_normalized/3dad8f6b7ba45737c97e31f297c0c08d4b69de18f7ad458dfac4df2e9dacbfe5/IT/report.json`
- `city_normalized/3e1287cfd84dd1ae867ea0b4cac85da3d8242d841e09d02de82174234f98d29f/XE/mapping.json`
- `city_normalized/3e1287cfd84dd1ae867ea0b4cac85da3d8242d841e09d02de82174234f98d29f/XE/report.json`
- `city_normalized/3e13d135259259dc1a63ce69ab72d554072f09e80de1e7e785f6a9197dd424c9/LS/mapping.json`
- `city_normalized/3e13d135259259dc1a63ce69ab72d554072f09e80de1e7e785f6a9197dd424c9/LS/report.json`
- `city_normalized/3ed516359197b6de4be898ff71c8931dce6a54e78e769e6359ab8100cb8c7eb0/MF/mapping.json`
- `city_normalized/3ed516359197b6de4be898ff71c8931dce6a54e78e769e6359ab8100cb8c7eb0/MF/report.json`
- `city_normalized/3f50b11f9be08585829f8cd74c4170b85898a4346e25fe0dcc9440ddc63e6c7e/SZ/mapping.json`
- `city_normalized/3f50b11f9be08585829f8cd74c4170b85898a4346e25fe0dcc9440ddc63e6c7e/SZ/report.json`
- `city_normalized/414c169d47ef3152c45e1c3f7819d731ea02d56a31e17c9438ece866a811556a/SB/mapping.json`
- `city_normalized/414c169d47ef3152c45e1c3f7819d731ea02d56a31e17c9438ece866a811556a/SB/report.json`
- `city_normalized/4234cbca1ece0ebb9b7613bb7712b29836041493adfa6420017ce75f5ce9a9cf/AU/mapping.json`
- `city_normalized/4234cbca1ece0ebb9b7613bb7712b29836041493adfa6420017ce75f5ce9a9cf/AU/report.json`
- `city_normalized/42e685aeb23995941b651ce4991352c9b3a51464d215c391e102a86ea9b822d0/MA/mapping.json`
- `city_normalized/42e685aeb23995941b651ce4991352c9b3a51464d215c391e102a86ea9b822d0/MA/report.json`
- `city_normalized/43e0b86fa2341e5c8dffce841dd779031d2dc4238f4de461ca1d0b1d92d71edc/AF/mapping.json`
- `city_normalized/43e0b86fa2341e5c8dffce841dd779031d2dc4238f4de461ca1d0b1d92d71edc/AF/report.json`
- `city_normalized/44485ec222c9b7d29336ceda2ba63bdeb6840a00f64cf7325e39170c038a6c3f/PF/mapping.json`
- `city_normalized/44485ec222c9b7d29336ceda2ba63bdeb6840a00f64cf7325e39170c038a6c3f/PF/report.json`
- `city_normalized/447d9009b087ea9085f7e6bed94c161bf67ec1e34ab8fb6a1e466d13f5f30360/TJ/mapping.json`
- `city_normalized/447d9009b087ea9085f7e6bed94c161bf67ec1e34ab8fb6a1e466d13f5f30360/TJ/report.json`
- `city_normalized/44ddab2fafec1d7a0b204cb0e78599c8afde75924f6b9efeb339bff3b66b4e21/BD/mapping.json`
- `city_normalized/44ddab2fafec1d7a0b204cb0e78599c8afde75924f6b9efeb339bff3b66b4e21/BD/report.json`
- `city_normalized/453f48b38b861cedd2c837649413f1b2191ed7ebcde2af4a14dced8ccef04214/KI/mapping.json`
- `city_normalized/453f48b38b861cedd2c837649413f1b2191ed7ebcde2af4a14dced8ccef04214/KI/report.json`
- `city_normalized/454d179592339447c42c1d46ed3018af3057c67d9a1cf9fbecbfeb8b5d658b66/TD/mapping.json`
- `city_normalized/454d179592339447c42c1d46ed3018af3057c67d9a1cf9fbecbfeb8b5d658b66/TD/report.json`
- `city_normalized/47cd90120d7a642be616b2434389b19ae803cc977f514aa8f3dca404c2771b06/KR/mapping.json`
- `city_normalized/47cd90120d7a642be616b2434389b19ae803cc977f514aa8f3dca404c2771b06/KR/report.json`
- `city_normalized/48d14dd85352ed146f3c6631c187cb36b9681b3d3939ddf37ff03e9bd9c2aa53/TG/mapping.json`
- `city_normalized/48d14dd85352ed146f3c6631c187cb36b9681b3d3939ddf37ff03e9bd9c2aa53/TG/report.json`
- `city_normalized/4c566d197480b2be254950fad090c8188a771bba9f2f67d7fcaaa5719b3e8b89/SE/mapping.json`
- `city_normalized/4c566d197480b2be254950fad090c8188a771bba9f2f67d7fcaaa5719b3e8b89/SE/report.json`
- `city_normalized/4ccce8f971c29085609e6f11e3ad4327cd1c1b4ac59a3f8c07c95e545e05dfaf/NE/mapping.json`
- `city_normalized/4ccce8f971c29085609e6f11e3ad4327cd1c1b4ac59a3f8c07c95e545e05dfaf/NE/report.json`
- `city_normalized/4e78ee84a76e2a20c1c7074ec93153b781b37b882622de689cd0f5d2d4ac8b19/XQ/mapping.json`
- `city_normalized/4e78ee84a76e2a20c1c7074ec93153b781b37b882622de689cd0f5d2d4ac8b19/XQ/report.json`
- `city_normalized/4e9f2c6bea1a5020c17836417b69033b095a66279da289b20c2b1d062f81d92b/PH/mapping.json`
- `city_normalized/4e9f2c6bea1a5020c17836417b69033b095a66279da289b20c2b1d062f81d92b/PH/report.json`
- `city_normalized/4ffa99f32ce5df1d4a3a7028dc6e9e309a822edf5b65a4e82886b780072488a7/UM/mapping.json`
- `city_normalized/4ffa99f32ce5df1d4a3a7028dc6e9e309a822edf5b65a4e82886b780072488a7/UM/report.json`
- `city_normalized/5007e81789948d2398ecdaf12c46362aa003b571b81937628c153b698f9594ae/ES/mapping.json`
- `city_normalized/5007e81789948d2398ecdaf12c46362aa003b571b81937628c153b698f9594ae/ES/report.json`
- `city_normalized/508221dc3801c4576c69be159215267a04b22ff8036a98e25745b49a62822d48/MU/mapping.json`
- `city_normalized/508221dc3801c4576c69be159215267a04b22ff8036a98e25745b49a62822d48/MU/report.json`
- `city_normalized/50f4280c3d503ca5de65464b22919ea1a35d48570088dbf3eb60e06891dd1d71/SA/mapping.json`
- `city_normalized/50f4280c3d503ca5de65464b22919ea1a35d48570088dbf3eb60e06891dd1d71/SA/report.json`
- `city_normalized/518cfbe073a0e1ffd9ffb0555c79bc45009a89487c24219eadcd756586c3af06/IQ/mapping.json`
- `city_normalized/518cfbe073a0e1ffd9ffb0555c79bc45009a89487c24219eadcd756586c3af06/IQ/report.json`
- `city_normalized/52934ca267a937b0fb7bb68f72e58f65580b0d419a90a310facf397dfb45ef11/CP/mapping.json`
- `city_normalized/52934ca267a937b0fb7bb68f72e58f65580b0d419a90a310facf397dfb45ef11/CP/report.json`
- `city_normalized/5299fc81d51fe882213ecab71465de60eb30243f3d8569ea76bbe69294aba6a8/PW/mapping.json`
- `city_normalized/5299fc81d51fe882213ecab71465de60eb30243f3d8569ea76bbe69294aba6a8/PW/report.json`
- `city_normalized/52ff14c2668e27aa463155f9abd4f268e1d9c79fdcbeaab2e9dbdb79c14e21e0/ML/mapping.json`
- `city_normalized/52ff14c2668e27aa463155f9abd4f268e1d9c79fdcbeaab2e9dbdb79c14e21e0/ML/report.json`
- `city_normalized/547eb9e4c2c6af7b4c55930e0ee4b3ee804305adeab9f8c9f5dde73c5968763e/XB/mapping.json`
- `city_normalized/547eb9e4c2c6af7b4c55930e0ee4b3ee804305adeab9f8c9f5dde73c5968763e/XB/report.json`
- `city_normalized/55215d485306efb4eda66df2db07bf0ccd32304abde6af4f7ef78635cee33700/FK/mapping.json`
- `city_normalized/55215d485306efb4eda66df2db07bf0ccd32304abde6af4f7ef78635cee33700/FK/report.json`
- `city_normalized/575ffb88462a12cefb674dfc09f8d1c86018c5a7750ff38bed79d56e8b605c60/CF/mapping.json`
- `city_normalized/575ffb88462a12cefb674dfc09f8d1c86018c5a7750ff38bed79d56e8b605c60/CF/report.json`
- `city_normalized/57678a89bc51c30297ebdc99d0d23be4c520b1d20b64ad29b169f1700d18e84d/CU/mapping.json`
- `city_normalized/57678a89bc51c30297ebdc99d0d23be4c520b1d20b64ad29b169f1700d18e84d/CU/report.json`
- `city_normalized/587f47a26d2413baa8beb89cfee21a2c86610238b9fca78295d3228ee84606e6/SS/mapping.json`
- `city_normalized/587f47a26d2413baa8beb89cfee21a2c86610238b9fca78295d3228ee84606e6/SS/report.json`
- `city_normalized/5b5549a568cb0d3f69aa008129820eae616850e7e80957ac9eda62e45bedbc7a/KH/mapping.json`
- `city_normalized/5b5549a568cb0d3f69aa008129820eae616850e7e80957ac9eda62e45bedbc7a/KH/report.json`
- `city_normalized/5ee4951dbe51cd18b29420732e62acc1da2ba74dac37952aa5a30f8002e38b12/LA/mapping.json`
- `city_normalized/5ee4951dbe51cd18b29420732e62acc1da2ba74dac37952aa5a30f8002e38b12/LA/report.json`
- `city_normalized/5f4c13356e785d3401fcc09f06931dc4a025aeb59f03abd904e94c3c521f5d40/BW/mapping.json`
- `city_normalized/5f4c13356e785d3401fcc09f06931dc4a025aeb59f03abd904e94c3c521f5d40/BW/report.json`
- `city_normalized/60cb7cf53225555ead70f822cb0239c7b591cb7179b39996bc53ab3cd25b753c/VE/mapping.json`
- `city_normalized/60cb7cf53225555ead70f822cb0239c7b591cb7179b39996bc53ab3cd25b753c/VE/report.json`
- `city_normalized/612d45a6a4a447e10b6f269c6379ad5273560bb1b5e0b73654ed3ef3e3935534/EG/mapping.json`
- `city_normalized/612d45a6a4a447e10b6f269c6379ad5273560bb1b5e0b73654ed3ef3e3935534/EG/report.json`
- `city_normalized/616ba5be5b220379344cfb98f80d0a79fae61a33c640bb4d465fb20a39d79130/DO/mapping.json`
- `city_normalized/616ba5be5b220379344cfb98f80d0a79fae61a33c640bb4d465fb20a39d79130/DO/report.json`
- `city_normalized/62590c024fff2d0edd4d806af8353343e21536722ced0add969a300611bee432/AM/mapping.json`
- `city_normalized/62590c024fff2d0edd4d806af8353343e21536722ced0add969a300611bee432/AM/report.json`
- `city_normalized/635e03f6e15bcdcd24d8dc121de57d1beaeff6c29907511727bcc4b68f433f90/BR/mapping.json`
- `city_normalized/635e03f6e15bcdcd24d8dc121de57d1beaeff6c29907511727bcc4b68f433f90/BR/report.json`
- `city_normalized/63d403096b5c69989ff6e9d9cf11c54edaa9b8aa94afe978cb16f5828635c92f/NG/mapping.json`
- `city_normalized/63d403096b5c69989ff6e9d9cf11c54edaa9b8aa94afe978cb16f5828635c92f/NG/report.json`
- `city_normalized/659807337164fdcc9fbd12dbf16dc77df17ab44b8223b7dd48b259e507d46ec0/KZ/mapping.json`
- `city_normalized/659807337164fdcc9fbd12dbf16dc77df17ab44b8223b7dd48b259e507d46ec0/KZ/report.json`
- `city_normalized/668f68ca4d71fc51c8ed95e62d4e3c2c1963800d3090f51a64f2d75992e2c842/HN/mapping.json`
- `city_normalized/668f68ca4d71fc51c8ed95e62d4e3c2c1963800d3090f51a64f2d75992e2c842/HN/report.json`
- `city_normalized/68a727d0b08e49f7f0a6b38471b2d5275349a7517c2de6d4cc5f03d7064e189e/XW/mapping.json`
- `city_normalized/68a727d0b08e49f7f0a6b38471b2d5275349a7517c2de6d4cc5f03d7064e189e/XW/report.json`
- `city_normalized/6db14b41de5eb1a0311adbd12b42a26825a6ea82fec1ab3bd1655ad787b58a75/ME/mapping.json`
- `city_normalized/6db14b41de5eb1a0311adbd12b42a26825a6ea82fec1ab3bd1655ad787b58a75/ME/report.json`
- `city_normalized/6dd991478d0d3ff56d2805515594adf72cf5306d854ff639dfa404e431066c61/XS/mapping.json`
- `city_normalized/6dd991478d0d3ff56d2805515594adf72cf5306d854ff639dfa404e431066c61/XS/report.json`
- `city_normalized/6e06d1efd328118bcabc5ba864e45b5a865f3717cf4da7fcef4136efae513081/NC/mapping.json`
- `city_normalized/6e06d1efd328118bcabc5ba864e45b5a865f3717cf4da7fcef4136efae513081/NC/report.json`
- `city_normalized/6f3dc5cd21f91ffbf25c73e883f32a06bb6b60f4dab174b56338b3904928092b/HU/mapping.json`
- `city_normalized/6f3dc5cd21f91ffbf25c73e883f32a06bb6b60f4dab174b56338b3904928092b/HU/report.json`
- `city_normalized/7017244553f25c8602936378e6c47a9ce95485053ca9cc899a428b15f467efbc/GL/mapping.json`
- `city_normalized/7017244553f25c8602936378e6c47a9ce95485053ca9cc899a428b15f467efbc/GL/report.json`
- `city_normalized/7078e96d81168ab990406e390bf1504f44d688f3e0f5eb0746140d23075808b4/GN/mapping.json`
- `city_normalized/7078e96d81168ab990406e390bf1504f44d688f3e0f5eb0746140d23075808b4/GN/report.json`
- `city_normalized/719642347023cb570eddb9c9948fbdefadee738122e252f00fa0854d66220ecb/TO/mapping.json`
- `city_normalized/719642347023cb570eddb9c9948fbdefadee738122e252f00fa0854d66220ecb/TO/report.json`
- `city_normalized/729b2c699b5ebcc8793b6b720bdeb147b0b10a25f373968dca15b9ec84fd3cb3/MM/mapping.json`
- `city_normalized/729b2c699b5ebcc8793b6b720bdeb147b0b10a25f373968dca15b9ec84fd3cb3/MM/report.json`
- `city_normalized/72b07539906bc6f42f595f581e0f20538409ad59abf140c226201cd85a20507d/BO/mapping.json`
- `city_normalized/72b07539906bc6f42f595f581e0f20538409ad59abf140c226201cd85a20507d/BO/report.json`
- `city_normalized/734ffe2fa9978db6bfd98cbd7837322b88ba8328fd0e0adb7bf13906cc1282e2/TN/mapping.json`
- `city_normalized/734ffe2fa9978db6bfd98cbd7837322b88ba8328fd0e0adb7bf13906cc1282e2/TN/report.json`
- `city_normalized/73a68968d6152fd9c9fcf3c3c676975c27a1912a144c4216b48ff418781f46da/TC/mapping.json`
- `city_normalized/73a68968d6152fd9c9fcf3c3c676975c27a1912a144c4216b48ff418781f46da/TC/report.json`
- `city_normalized/7511d7d1e943e42979ccbe03f7ce807d4d683bdf7861eb1139455cd363b1b4cb/IE/mapping.json`
- `city_normalized/7511d7d1e943e42979ccbe03f7ce807d4d683bdf7861eb1139455cd363b1b4cb/IE/report.json`
- `city_normalized/769883751ceab6af8db2e3a12ecd43d4d7b04c2cb55645e989faf49c73c596b7/SH/mapping.json`
- `city_normalized/769883751ceab6af8db2e3a12ecd43d4d7b04c2cb55645e989faf49c73c596b7/SH/report.json`
- `city_normalized/76e930b08bea9f0c15fc9035064e78f6e3aba343c6c7ea1a7e7d72f657dbe505/HT/mapping.json`
- `city_normalized/76e930b08bea9f0c15fc9035064e78f6e3aba343c6c7ea1a7e7d72f657dbe505/HT/report.json`
- `city_normalized/77fa9098ea45e4f97f83ee640d13855958f07051536050f2fa504d3f849c6b7a/IN/mapping.json`
- `city_normalized/77fa9098ea45e4f97f83ee640d13855958f07051536050f2fa504d3f849c6b7a/IN/report.json`
- `city_normalized/7ba7d3397379aeb16574c98e5a27fe5e3f7bebd658af83bd6408d4f4d6a54535/KM/mapping.json`
- `city_normalized/7ba7d3397379aeb16574c98e5a27fe5e3f7bebd658af83bd6408d4f4d6a54535/KM/report.json`
- `city_normalized/7d377138fc8f00d18d4f927ef32a8ddfd3b8d57241ed32e4295a9699d3b75949/PT/mapping.json`
- `city_normalized/7d377138fc8f00d18d4f927ef32a8ddfd3b8d57241ed32e4295a9699d3b75949/PT/report.json`
- `city_normalized/7de7bc25b38b5749154731c72195f36abbc1be750440e4d395475f26c2ce947c/GA/mapping.json`
- `city_normalized/7de7bc25b38b5749154731c72195f36abbc1be750440e4d395475f26c2ce947c/GA/report.json`
- `city_normalized/7e76ee7859c179d7f1ae288ccca8028555ebeb94b15363379a4f445731247bfa/MS/mapping.json`
- `city_normalized/7e76ee7859c179d7f1ae288ccca8028555ebeb94b15363379a4f445731247bfa/MS/report.json`
- `city_normalized/8083cd463575d1c36463212d8c7f598659355ad1947233a5148d795ee84e38f4/NA/mapping.json`
- `city_normalized/8083cd463575d1c36463212d8c7f598659355ad1947233a5148d795ee84e38f4/NA/report.json`
- `city_normalized/810f3568e7bcdb635cc66e4d2c0ef43db9ffd2182170c9607ad2fce7148e98be/TF/mapping.json`
- `city_normalized/810f3568e7bcdb635cc66e4d2c0ef43db9ffd2182170c9607ad2fce7148e98be/TF/report.json`
- `city_normalized/81ffb4ffdc67869caa564baf67d32441e11988e1a3a5c250e91511809f20adf2/BV/mapping.json`
- `city_normalized/81ffb4ffdc67869caa564baf67d32441e11988e1a3a5c250e91511809f20adf2/BV/report.json`
- `city_normalized/826a2545d1843b1187bfc5f194c065a4c0e5b8fbb44ff62b74b4ac341a8da948/GB/mapping.json`
- `city_normalized/826a2545d1843b1187bfc5f194c065a4c0e5b8fbb44ff62b74b4ac341a8da948/GB/report.json`
- `city_normalized/829945057c78c81e1881a6f1c3d54820f6329bd00361efaab91bfd597e8c9d41/MK/mapping.json`
- `city_normalized/829945057c78c81e1881a6f1c3d54820f6329bd00361efaab91bfd597e8c9d41/MK/report.json`
- `city_normalized/83de374a79798c390d96eef5062f4042b5f5b4a83a020826e51ba60f5a85e526/YE/mapping.json`
- `city_normalized/83de374a79798c390d96eef5062f4042b5f5b4a83a020826e51ba60f5a85e526/YE/report.json`
- `city_normalized/8450812e4df622facf9de3304cdf0c61a802c75f42401fee30de787291e4e84b/UG/mapping.json`
- `city_normalized/8450812e4df622facf9de3304cdf0c61a802c75f42401fee30de787291e4e84b/UG/report.json`
- `city_normalized/85055ba80baa9285e3fd80bf16098a3f52a2988b8702b362710e107855116061/TH/mapping.json`
- `city_normalized/85055ba80baa9285e3fd80bf16098a3f52a2988b8702b362710e107855116061/TH/report.json`
- `city_normalized/85cd5c14f1fafe493fc6f9a7375f26faf25bcd679b79e70f8914f06ad11727cc/BI/mapping.json`
- `city_normalized/85cd5c14f1fafe493fc6f9a7375f26faf25bcd679b79e70f8914f06ad11727cc/BI/report.json`
- `city_normalized/865a6cb8315d199df4b313594eb3962c09ae2c98fe550e96aaae44bdf4b8324c/ID/mapping.json`
- `city_normalized/865a6cb8315d199df4b313594eb3962c09ae2c98fe550e96aaae44bdf4b8324c/ID/report.json`
- `city_normalized/86b8f9d25055a5a61062459286c397d4f6bb324d2d4c8649c6ced4d5bf953867/AS/mapping.json`
- `city_normalized/86b8f9d25055a5a61062459286c397d4f6bb324d2d4c8649c6ced4d5bf953867/AS/report.json`
- `city_normalized/8774619c3cb065bb1131ffefa2f092280cd71b3d6478e2f1842a171805e531a0/AQ/mapping.json`
- `city_normalized/8774619c3cb065bb1131ffefa2f092280cd71b3d6478e2f1842a171805e531a0/AQ/report.json`
- `city_normalized/877540292ec48d14bb727715c74a2deed72d93854bd3610830c1f634cc8b55e2/AO/mapping.json`
- `city_normalized/877540292ec48d14bb727715c74a2deed72d93854bd3610830c1f634cc8b55e2/AO/report.json`
- `city_normalized/887987ef8b78a8085198e167ba98aedd71ae741912101c6a7769feeb6f8408db/PL/mapping.json`
- `city_normalized/887987ef8b78a8085198e167ba98aedd71ae741912101c6a7769feeb6f8408db/PL/report.json`
- `city_normalized/89ac81226942e574bcea1db73a241de86962704fcd0436bb0abc928ead835042/NO/mapping.json`
- `city_normalized/89ac81226942e574bcea1db73a241de86962704fcd0436bb0abc928ead835042/NO/report.json`
- `city_normalized/89c8216c09bb0e1bbddb0165bfd920c45144b34ac47103e933a333ffeb6d942b/UA/mapping.json`
- `city_normalized/89c8216c09bb0e1bbddb0165bfd920c45144b34ac47103e933a333ffeb6d942b/UA/report.json`
- `city_normalized/89ef0982a6befab1c1fc039986d55318be7dd323d3ef17d9e70a996891c8459d/VA/mapping.json`
- `city_normalized/89ef0982a6befab1c1fc039986d55318be7dd323d3ef17d9e70a996891c8459d/VA/report.json`
- `city_normalized/8c0168eac8abc20c5174ef41207c3687ebf20cfeb8f6c31e92c2ebf513bc4826/GT/mapping.json`
- `city_normalized/8c0168eac8abc20c5174ef41207c3687ebf20cfeb8f6c31e92c2ebf513bc4826/GT/report.json`
- `city_normalized/8eacb580d831033723b9b6108a2df4e83d91312fbef9f35ab5dc3f16bc0938e3/CH/mapping.json`
- `city_normalized/8eacb580d831033723b9b6108a2df4e83d91312fbef9f35ab5dc3f16bc0938e3/CH/report.json`
- `city_normalized/8f4f32f80d882b83b0b19900287006fab14e1890a4565eb56d50f3439205ffcf/ST/mapping.json`
- `city_normalized/8f4f32f80d882b83b0b19900287006fab14e1890a4565eb56d50f3439205ffcf/ST/report.json`
- `city_normalized/8fed4ab6f8d25245ed3570f3ddc569e67e349730ed9428a5313ae50695f46d04/BM/mapping.json`
- `city_normalized/8fed4ab6f8d25245ed3570f3ddc569e67e349730ed9428a5313ae50695f46d04/BM/report.json`
- `city_normalized/91477c4fa6c0a72667df6e035be687717d449b083aa1692df5718beda6d2947b/CL/mapping.json`
- `city_normalized/91477c4fa6c0a72667df6e035be687717d449b083aa1692df5718beda6d2947b/CL/report.json`
- `city_normalized/919a50453afe030dcba45e8db33d36b0da31ef3fcc9e2238fa3d01b1ee05768a/PN/mapping.json`
- `city_normalized/919a50453afe030dcba45e8db33d36b0da31ef3fcc9e2238fa3d01b1ee05768a/PN/report.json`
- `city_normalized/926219535ed1357587cef0adfe516c9215565112585acd3ff21e51dcd06cbf4a/GR/mapping.json`
- `city_normalized/926219535ed1357587cef0adfe516c9215565112585acd3ff21e51dcd06cbf4a/GR/report.json`
- `city_normalized/93b6396d1d3db40b8789ebd18de1227c719f4617aa64d36239f0639a2d9222f1/LV/mapping.json`
- `city_normalized/93b6396d1d3db40b8789ebd18de1227c719f4617aa64d36239f0639a2d9222f1/LV/report.json`
- `city_normalized/9416e112a73fafbd280bf2454f2c79a0e131779036a3ea1eb2f9e3eca6051de5/LR/mapping.json`
- `city_normalized/9416e112a73fafbd280bf2454f2c79a0e131779036a3ea1eb2f9e3eca6051de5/LR/report.json`
- `city_normalized/948b114536953f954a6785bd7c22a2d77d90519dc2dcf6f4ce3139f66b9977c4/VU/mapping.json`
- `city_normalized/948b114536953f954a6785bd7c22a2d77d90519dc2dcf6f4ce3139f66b9977c4/VU/report.json`
- `city_normalized/96aa29594c58bd24cc98360cb5dc71c4cef88cd296e4aab13552eeb8fca49014/DK/mapping.json`
- `city_normalized/96aa29594c58bd24cc98360cb5dc71c4cef88cd296e4aab13552eeb8fca49014/DK/report.json`
- `city_normalized/98d759ac2fa15792af656773997276540efd2ed0d3e48b8bdf73cd15c85279b4/XI/mapping.json`
- `city_normalized/98d759ac2fa15792af656773997276540efd2ed0d3e48b8bdf73cd15c85279b4/XI/report.json`
- `city_normalized/9ae8a3677514f46f26cd33de5616fb466b59ddb9524db1fecfe81595c61f1047/GE/mapping.json`
- `city_normalized/9ae8a3677514f46f26cd33de5616fb466b59ddb9524db1fecfe81595c61f1047/GE/report.json`
- `city_normalized/9b66eab7f105f89be49340afe12e5e09df44e9a744ed61bceb663504e56fd96f/XT/mapping.json`
- `city_normalized/9b66eab7f105f89be49340afe12e5e09df44e9a744ed61bceb663504e56fd96f/XT/report.json`
- `city_normalized/9bf71d3555dc196f7ea8fdf418b1e3d3da14aae8bb814afeff7ecdce5b7ad3f0/SD/mapping.json`
- `city_normalized/9bf71d3555dc196f7ea8fdf418b1e3d3da14aae8bb814afeff7ecdce5b7ad3f0/SD/report.json`
- `city_normalized/9d23ab6f147c68b538069f44fd67816c989de545027e574d6b541158eb8d7c90/SL/mapping.json`
- `city_normalized/9d23ab6f147c68b538069f44fd67816c989de545027e574d6b541158eb8d7c90/SL/report.json`
- `city_normalized/9dd3f269f9b4f17fa249a77eefebb26f3a24c2777483435bf17c2f7635e03358/PK/mapping.json`
- `city_normalized/9dd3f269f9b4f17fa249a77eefebb26f3a24c2777483435bf17c2f7635e03358/PK/report.json`
- `city_normalized/9de1141c5e1581e333f0aee1e2327209fc48b9660cf6082e0fb9cd56728058b4/CK/mapping.json`
- `city_normalized/9de1141c5e1581e333f0aee1e2327209fc48b9660cf6082e0fb9cd56728058b4/CK/report.json`
- `city_normalized/9e5cf8a47be3b0460ea7f5dfb2e2d127312dc724106a806854245b47cbd3ee39/CO/mapping.json`
- `city_normalized/9e5cf8a47be3b0460ea7f5dfb2e2d127312dc724106a806854245b47cbd3ee39/CO/report.json`
- `city_normalized/9e7a60d7785568ca4e0b77ef791851a70759d63cfeccea7d5c9171f9165b6d9e/BY/mapping.json`
- `city_normalized/9e7a60d7785568ca4e0b77ef791851a70759d63cfeccea7d5c9171f9165b6d9e/BY/report.json`
- `city_normalized/9ea139b63691be0dc405da71ed3bbb8da2b59008a910e1bc5ae7b6503e82e7da/US/mapping.json`
- `city_normalized/9ea139b63691be0dc405da71ed3bbb8da2b59008a910e1bc5ae7b6503e82e7da/US/report.json`
- `city_normalized/a04378b57bc29980db940a998a5762540c14254ded9795d9f00be3a86fa1df6b/XN/mapping.json`
- `city_normalized/a04378b57bc29980db940a998a5762540c14254ded9795d9f00be3a86fa1df6b/XN/report.json`
- `city_normalized/a0a16e9806b33e07fbc0622204376c079708027afa2667302299c4e87e49034b/CA/mapping.json`
- `city_normalized/a0a16e9806b33e07fbc0622204376c079708027afa2667302299c4e87e49034b/CA/report.json`
- `city_normalized/a1c5dc6a0ad7c6ed81ebc4422021890cd509100c9d513606f7c3b6f13b1a3372/MZ/mapping.json`
- `city_normalized/a1c5dc6a0ad7c6ed81ebc4422021890cd509100c9d513606f7c3b6f13b1a3372/MZ/report.json`
- `city_normalized/a219fa79724b3f4807599ca870e8ea778f174bc62a2f3570f40afbba6f8a4c74/SN/mapping.json`
- `city_normalized/a219fa79724b3f4807599ca870e8ea778f174bc62a2f3570f40afbba6f8a4c74/SN/report.json`
- `city_normalized/a230a4be44ea8af44ee847001608a18e4ff22ffd57168f1f4394b72615d1f0be/PA/mapping.json`
- `city_normalized/a230a4be44ea8af44ee847001608a18e4ff22ffd57168f1f4394b72615d1f0be/PA/report.json`
- `city_normalized/a30f0dcfe75f1d38beeecb1c9746225b909dcadba9fcf4d1c5581c6f9a9e6568/AT/mapping.json`
- `city_normalized/a30f0dcfe75f1d38beeecb1c9746225b909dcadba9fcf4d1c5581c6f9a9e6568/AT/report.json`
- `city_normalized/a504802ba423ac6c123af95fc7089fd09d0fcc71befa37ea5895406404b1f009/SI/mapping.json`
- `city_normalized/a504802ba423ac6c123af95fc7089fd09d0fcc71befa37ea5895406404b1f009/SI/report.json`
- `city_normalized/a591731ce81e9f3cdeec6ada6d25a2e556ca88c184ad57d5a40799e616d56190/NZ/mapping.json`
- `city_normalized/a591731ce81e9f3cdeec6ada6d25a2e556ca88c184ad57d5a40799e616d56190/NZ/report.json`
- `city_normalized/a5aae4d3ca63112f9d466a5448cf099fb414942e72339f120d4820ee44d8dd0b/UY/mapping.json`
- `city_normalized/a5aae4d3ca63112f9d466a5448cf099fb414942e72339f120d4820ee44d8dd0b/UY/report.json`
- `city_normalized/a66d800f706fab9f2a20ac28ce781c6a756363870e937327f52623cc28f7b9fb/BG/mapping.json`
- `city_normalized/a66d800f706fab9f2a20ac28ce781c6a756363870e937327f52623cc28f7b9fb/BG/report.json`
- `city_normalized/a8384384ed95cbc25393d6fe1a7d4a02e5f33ba1ea8992e1bad45bfbd7f5f0a2/RS/mapping.json`
- `city_normalized/a8384384ed95cbc25393d6fe1a7d4a02e5f33ba1ea8992e1bad45bfbd7f5f0a2/RS/report.json`
- `city_normalized/aa06cbdb5739c3037409c7b5028a98cdfa5622ca178125f4395f74c7bb5d1a64/MX/mapping.json`
- `city_normalized/aa06cbdb5739c3037409c7b5028a98cdfa5622ca178125f4395f74c7bb5d1a64/MX/report.json`
- `city_normalized/aaadc693c18737604ddebfcd605a4a11b9aed22f6784af6fee12f10017459d21/FI/mapping.json`
- `city_normalized/aaadc693c18737604ddebfcd605a4a11b9aed22f6784af6fee12f10017459d21/FI/report.json`
- `city_normalized/ac0667caa7a0ef4a29b21df64040d30f8beb93a40ca34c4ef111969e732ca3ac/KE/mapping.json`
- `city_normalized/ac0667caa7a0ef4a29b21df64040d30f8beb93a40ca34c4ef111969e732ca3ac/KE/report.json`
- `city_normalized/ac0d6d264a99294e4e019f90786044a7aa50f6b4154c7d0d70c51c25f4f19924/BB/mapping.json`
- `city_normalized/ac0d6d264a99294e4e019f90786044a7aa50f6b4154c7d0d70c51c25f4f19924/BB/report.json`
- `city_normalized/af53dcd367084934e0b4ed2159a96558ab3a6e9180b4fd1fd7ef37dcdc2db67c/NL/mapping.json`
- `city_normalized/af53dcd367084934e0b4ed2159a96558ab3a6e9180b4fd1fd7ef37dcdc2db67c/NL/report.json`
- `city_normalized/b0f4a61f0183f4c1ae6d572740e58d5849c12ba5a4cc0aff65ab3c651397a444/MG/mapping.json`
- `city_normalized/b0f4a61f0183f4c1ae6d572740e58d5849c12ba5a4cc0aff65ab3c651397a444/MG/report.json`
- `city_normalized/b2b56b60f7a883de2c0200cefdb423330ad0843eba16879829396f6e176d036e/KN/mapping.json`
- `city_normalized/b2b56b60f7a883de2c0200cefdb423330ad0843eba16879829396f6e176d036e/KN/report.json`
- `city_normalized/b305595280c979c6f7c8e15581c0f69fa1c4f0e8e4c7b948963f80bf74e77713/NU/mapping.json`
- `city_normalized/b305595280c979c6f7c8e15581c0f69fa1c4f0e8e4c7b948963f80bf74e77713/NU/report.json`
- `city_normalized/b759ddab9eb9002761b757efdb6972d32f330e0eaa4ebea9e3fc4e62099fe390/TZ/mapping.json`
- `city_normalized/b759ddab9eb9002761b757efdb6972d32f330e0eaa4ebea9e3fc4e62099fe390/TZ/report.json`
- `city_normalized/b790268844c89930b0f842b562fcf4be8bad51b4f1333cbd225d58a4d1dd481d/HR/mapping.json`
- `city_normalized/b790268844c89930b0f842b562fcf4be8bad51b4f1333cbd225d58a4d1dd481d/HR/report.json`
- `city_normalized/b84d8dfe41a292126c4b2438f219c91c7b61cff144cb16bf4910e8c7accadbf2/LB/mapping.json`
- `city_normalized/b84d8dfe41a292126c4b2438f219c91c7b61cff144cb16bf4910e8c7accadbf2/LB/report.json`
- `city_normalized/b9fdb257db89c09b377286bc4e2179e4881aaeb6b53d56e414805ae9f0f6c744/UZ/mapping.json`
- `city_normalized/b9fdb257db89c09b377286bc4e2179e4881aaeb6b53d56e414805ae9f0f6c744/UZ/report.json`
- `city_normalized/bd08e35ebf7f04dec75d04157b65300db0939423b92e35b56fc44bf71f04da2e/ER/mapping.json`
- `city_normalized/bd08e35ebf7f04dec75d04157b65300db0939423b92e35b56fc44bf71f04da2e/ER/report.json`
- `city_normalized/bd997b9e28c8ecab8d60f2e91d13fa68804ad94bf8e74062fbc33cb73a860df6/HM/mapping.json`
- `city_normalized/bd997b9e28c8ecab8d60f2e91d13fa68804ad94bf8e74062fbc33cb73a860df6/HM/report.json`
- `city_normalized/bef1d52d3d433cba7ed7b0a3c0fa480db66bb14980d75a005956449703a12a95/MW/mapping.json`
- `city_normalized/bef1d52d3d433cba7ed7b0a3c0fa480db66bb14980d75a005956449703a12a95/MW/report.json`
- `city_normalized/bf49fc8addc284908f94876e60b77ca640085bc5b39995704f98d4dc0d3cd9c9/TT/mapping.json`
- `city_normalized/bf49fc8addc284908f94876e60b77ca640085bc5b39995704f98d4dc0d3cd9c9/TT/report.json`
- `city_normalized/bf9c909f49e3ce9d52ac1c0a467c4368ff7dd3a88d636752c7f22606afa40785/XK/mapping.json`
- `city_normalized/bf9c909f49e3ce9d52ac1c0a467c4368ff7dd3a88d636752c7f22606afa40785/XK/report.json`
- `city_normalized/c22c9d3c5efc2b094ec1669883baae387e239937f31bb32b247618a2d47a2436/XX/mapping.json`
- `city_normalized/c22c9d3c5efc2b094ec1669883baae387e239937f31bb32b247618a2d47a2436/XX/report.json`
- `city_normalized/c29650e59b685838911ca8b316c90e073e9e4bb84ffddec472f2556ac7ca2770/GM/mapping.json`
- `city_normalized/c29650e59b685838911ca8b316c90e073e9e4bb84ffddec472f2556ac7ca2770/GM/report.json`
- `city_normalized/c3f440d5734bb1d3e93329540c840784ee414f4e093e48951da4fa81087edab4/XM/mapping.json`
- `city_normalized/c3f440d5734bb1d3e93329540c840784ee414f4e093e48951da4fa81087edab4/XM/report.json`
- `city_normalized/c418b55086cfadc823e6e0c5061d52a2300d8d2cff71e9d8e1ee566f957cdec6/SJ/mapping.json`
- `city_normalized/c418b55086cfadc823e6e0c5061d52a2300d8d2cff71e9d8e1ee566f957cdec6/SJ/report.json`
- `city_normalized/c4924b4a8f62ed756bc411ed7e5d9f6cde3c56a977c1357266e87da7ae635882/XC/mapping.json`
- `city_normalized/c4924b4a8f62ed756bc411ed7e5d9f6cde3c56a977c1357266e87da7ae635882/XC/report.json`
- `city_normalized/c4fd8ccb6c57cdc6041ef443ee5bf002c43c33009244cda8d4046f8a122760d3/BQ/mapping.json`
- `city_normalized/c4fd8ccb6c57cdc6041ef443ee5bf002c43c33009244cda8d4046f8a122760d3/BQ/report.json`
- `city_normalized/c6755ef5277027494b1c22ed60a551a3de76692f3ac750aa669ee4067e80ef01/MP/mapping.json`
- `city_normalized/c6755ef5277027494b1c22ed60a551a3de76692f3ac750aa669ee4067e80ef01/MP/report.json`
- `city_normalized/c6b4a0214b6b4fa64d248e36e7f41c31b6e130f66fd55f103d5d750f53b2ff07/DJ/mapping.json`
- `city_normalized/c6b4a0214b6b4fa64d248e36e7f41c31b6e130f66fd55f103d5d750f53b2ff07/DJ/report.json`
- `city_normalized/c7724fd917dc23ca32e3ab9fda2e748a65c696da757f53ffd0683a89c040f085/IL/mapping.json`
- `city_normalized/c7724fd917dc23ca32e3ab9fda2e748a65c696da757f53ffd0683a89c040f085/IL/report.json`
- `city_normalized/c773597d89f91353dcf860899d1158b05f018a534e0a8988b820119de2e0850f/KW/mapping.json`
- `city_normalized/c773597d89f91353dcf860899d1158b05f018a534e0a8988b820119de2e0850f/KW/report.json`
- `city_normalized/c77b7dd71e0e15d04b2a43ce5cfd711eab8560b20da43525a0c4ca37b71dc392/ZM/mapping.json`
- `city_normalized/c77b7dd71e0e15d04b2a43ce5cfd711eab8560b20da43525a0c4ca37b71dc392/ZM/report.json`
- `city_normalized/c7f75669d7bc4b14a3a742261f24cff36ce8fab391ddb5d6a2402abe5be4e879/MT/mapping.json`
- `city_normalized/c7f75669d7bc4b14a3a742261f24cff36ce8fab391ddb5d6a2402abe5be4e879/MT/report.json`
- `city_normalized/c89a591262b62eba2e12fa60836e3f206b5de99a2ab8f78b9d74969ab08d0e78/AN/mapping.json`
- `city_normalized/c89a591262b62eba2e12fa60836e3f206b5de99a2ab8f78b9d74969ab08d0e78/AN/report.json`
- `city_normalized/c9cebfae4a99ab9441503d6a128f012b83d26bf376486153e669e0eb746a4b90/SR/mapping.json`
- `city_normalized/c9cebfae4a99ab9441503d6a128f012b83d26bf376486153e669e0eb746a4b90/SR/report.json`
- `city_normalized/cc08d8ade6ea9b3f623bf7412b2850d2be53d21810ca57ca13e3bb960febf8e5/CX/mapping.json`
- `city_normalized/cc08d8ade6ea9b3f623bf7412b2850d2be53d21810ca57ca13e3bb960febf8e5/CX/report.json`
- `city_normalized/cc400422c9e97df4e8d3c48a5726f852a13f9d0d8e212f4f40eb4b9e76aa7f8e/IO/mapping.json`
- `city_normalized/cc400422c9e97df4e8d3c48a5726f852a13f9d0d8e212f4f40eb4b9e76aa7f8e/IO/report.json`
- `city_normalized/cc842d107a43617233ea70732900e886867afa8fed259464f34198a6142297b6/MR/mapping.json`
- `city_normalized/cc842d107a43617233ea70732900e886867afa8fed259464f34198a6142297b6/MR/report.json`
- `city_normalized/ccda222eb92e1b83fb14d126f9f7278053aad41b220c92609fc1f12c8c225d42/AI/mapping.json`
- `city_normalized/ccda222eb92e1b83fb14d126f9f7278053aad41b220c92609fc1f12c8c225d42/AI/report.json`
- `city_normalized/ce1766f2d348c83183cf932b84e9f22f473b52d50c6c2f27093b812e270043ac/TL/mapping.json`
- `city_normalized/ce1766f2d348c83183cf932b84e9f22f473b52d50c6c2f27093b812e270043ac/TL/report.json`
- `city_normalized/ce57f867c91e32037d53a681886acdb65941a1250ab90c5b7e02bfcf9de0ca41/CC/mapping.json`
- `city_normalized/ce57f867c91e32037d53a681886acdb65941a1250ab90c5b7e02bfcf9de0ca41/CC/report.json`
- `city_normalized/cecdf0b5fc19372295328b19c272d33862abc5dbd409792691a20e694ee585fa/WS/mapping.json`
- `city_normalized/cecdf0b5fc19372295328b19c272d33862abc5dbd409792691a20e694ee585fa/WS/report.json`
- `city_normalized/d0b3fffe45683dece770466b1e0601de4ec1fb06c7bd792f2e45f4af48a82cfc/GG/mapping.json`
- `city_normalized/d0b3fffe45683dece770466b1e0601de4ec1fb06c7bd792f2e45f4af48a82cfc/GG/report.json`
- `city_normalized/d15aeaad7ba6e33d6b06728be12ddc5e5bef6e66bf07a1e89c140ff7e41d6678/JE/mapping.json`
- `city_normalized/d15aeaad7ba6e33d6b06728be12ddc5e5bef6e66bf07a1e89c140ff7e41d6678/JE/report.json`
- `city_normalized/d1b5f44180ec7cdf60fcd1b5a6004d62d36b90867d929f2a9a90e812943e6f78/CI/mapping.json`
- `city_normalized/d1b5f44180ec7cdf60fcd1b5a6004d62d36b90867d929f2a9a90e812943e6f78/CI/report.json`
- `city_normalized/d2a3de62893b8ebd934297fff711ccd95f05a74d3b4018561e3e9033775a20b1/BT/mapping.json`
- `city_normalized/d2a3de62893b8ebd934297fff711ccd95f05a74d3b4018561e3e9033775a20b1/BT/report.json`
- `city_normalized/d33d619b77bc978fa820bd8fff405ee584ca82c1d249b86f39b4580bf86c672a/XO/mapping.json`
- `city_normalized/d33d619b77bc978fa820bd8fff405ee584ca82c1d249b86f39b4580bf86c672a/XO/report.json`
- `city_normalized/d3ad842c6762cae65f670a15e3b251e083434aaf523f2867256ed477193cfffa/GU/mapping.json`
- `city_normalized/d3ad842c6762cae65f670a15e3b251e083434aaf523f2867256ed477193cfffa/GU/report.json`
- `city_normalized/d4d217db1ad91ca3650d7c841510ad64362218f19df38e0f90ada178cceb37a0/MQ/mapping.json`
- `city_normalized/d4d217db1ad91ca3650d7c841510ad64362218f19df38e0f90ada178cceb37a0/MQ/report.json`
- `city_normalized/d532e422219f7bcc9401be11269ea22f5a56bbf5dcfb11630dc8df0caa69872f/EC/mapping.json`
- `city_normalized/d532e422219f7bcc9401be11269ea22f5a56bbf5dcfb11630dc8df0caa69872f/EC/report.json`
- `city_normalized/d595d13515c96d60bc92009b9eadabb574b75e980595d3c52295c210945a6149/PM/mapping.json`
- `city_normalized/d595d13515c96d60bc92009b9eadabb574b75e980595d3c52295c210945a6149/PM/report.json`
- `city_normalized/d6c2229890245c185173595f3227f3bdecba8385dc733f7592fc87269cc784ba/MH/mapping.json`
- `city_normalized/d6c2229890245c185173595f3227f3bdecba8385dc733f7592fc87269cc784ba/MH/report.json`
- `city_normalized/d738346492272311c6fd73a38baaa2e2a59a7df00691ee1b2baa0df6f8b2e07c/MN/mapping.json`
- `city_normalized/d738346492272311c6fd73a38baaa2e2a59a7df00691ee1b2baa0df6f8b2e07c/MN/report.json`
- `city_normalized/d7457ba532d6fed03b4c76aa3a96dad929faeeb081427e2eea5df205bf40e475/MC/mapping.json`
- `city_normalized/d7457ba532d6fed03b4c76aa3a96dad929faeeb081427e2eea5df205bf40e475/MC/report.json`
- `city_normalized/d747de34a372ff12c88f6b70c1b0c277fbac1b796a44030488773dbf5e709f9b/QA/mapping.json`
- `city_normalized/d747de34a372ff12c88f6b70c1b0c277fbac1b796a44030488773dbf5e709f9b/QA/report.json`
- `city_normalized/d7e78d3b624519897af177349a5e90cafa81024d84edbf9e55ca22350d519f6c/BJ/mapping.json`
- `city_normalized/d7e78d3b624519897af177349a5e90cafa81024d84edbf9e55ca22350d519f6c/BJ/report.json`
- `city_normalized/d8b60f4cc4e77f5b67e86c8cedae035ee31d89c96c20dbbed7efc01d4c93a29e/HK/mapping.json`
- `city_normalized/d8b60f4cc4e77f5b67e86c8cedae035ee31d89c96c20dbbed7efc01d4c93a29e/HK/report.json`
- `city_normalized/d8b8a25ffe529ef2548a4929988049d2b845d5892372d67d53195cf0a881fdf9/RO/mapping.json`
- `city_normalized/d8b8a25ffe529ef2548a4929988049d2b845d5892372d67d53195cf0a881fdf9/RO/report.json`
- `city_normalized/d95467592ab0fe233ae720d4082ea04b580f4c73e15ba453bebc23207062ab8f/EH/mapping.json`
- `city_normalized/d95467592ab0fe233ae720d4082ea04b580f4c73e15ba453bebc23207062ab8f/EH/report.json`
- `city_normalized/d9dec4c938eeae96db41b9938f990899c1409456d61bbf0100ac6c0b756aea27/LY/mapping.json`
- `city_normalized/d9dec4c938eeae96db41b9938f990899c1409456d61bbf0100ac6c0b756aea27/LY/report.json`
- `city_normalized/daaf2cb6788ba9faecacefaf748dd4a040d5f65d5d2a9e76e715bfa9726e5ec1/BZ/mapping.json`
- `city_normalized/daaf2cb6788ba9faecacefaf748dd4a040d5f65d5d2a9e76e715bfa9726e5ec1/BZ/report.json`
- `city_normalized/dbe4550ee23f2dfa6f17ce37204ed9042eb453bc47bb2da1036a337f56fdbbbf/ZW/mapping.json`
- `city_normalized/dbe4550ee23f2dfa6f17ce37204ed9042eb453bc47bb2da1036a337f56fdbbbf/ZW/report.json`
- `city_normalized/dc958ea81619bfd653389a5874b3adb6efae8e5f40107d52d2568e5cdb767e0a/XH/mapping.json`
- `city_normalized/dc958ea81619bfd653389a5874b3adb6efae8e5f40107d52d2568e5cdb767e0a/XH/report.json`
- `city_normalized/dd1e0b93352a73cd033ab1759f998b192dd7af1a265dcadd11027ae1c026b2a0/NI/mapping.json`
- `city_normalized/dd1e0b93352a73cd033ab1759f998b192dd7af1a265dcadd11027ae1c026b2a0/NI/report.json`
- `city_normalized/dd938dca7129386d1a70cebb87a8a6ada0ebcbbe9e1a7b0a3cc49ef16206e31b/RW/mapping.json`
- `city_normalized/dd938dca7129386d1a70cebb87a8a6ada0ebcbbe9e1a7b0a3cc49ef16206e31b/RW/report.json`
- `city_normalized/ddcfbfc792fadd8450b0d595ad0d091de3d587415efc2d2c48968c8453ff7421/IM/mapping.json`
- `city_normalized/ddcfbfc792fadd8450b0d595ad0d091de3d587415efc2d2c48968c8453ff7421/IM/report.json`
- `city_normalized/de0bd9eb46fabff34e5682e62497f85a8f7caeed5c4cb1f7221be719aea629e8/FO/mapping.json`
- `city_normalized/de0bd9eb46fabff34e5682e62497f85a8f7caeed5c4cb1f7221be719aea629e8/FO/report.json`
- `city_normalized/de1900315f547606d452d78c55ec6819da55777b3bc4abdfd3dab30ecf5426e7/PS/mapping.json`
- `city_normalized/de1900315f547606d452d78c55ec6819da55777b3bc4abdfd3dab30ecf5426e7/PS/report.json`
- `city_normalized/de5c33e853b5dcefd3b084328d1227d93210af80ea3b5d550545b0995c77b77e/TV/mapping.json`
- `city_normalized/de5c33e853b5dcefd3b084328d1227d93210af80ea3b5d550545b0995c77b77e/TV/report.json`
- `city_normalized/de611c22dcd7915ded43deeec5155e88f7b34e498a4d9f1fbef26f38cbd6d823/VI/mapping.json`
- `city_normalized/de611c22dcd7915ded43deeec5155e88f7b34e498a4d9f1fbef26f38cbd6d823/VI/report.json`
- `city_normalized/df65b6abbdc65f0caf047328aa28a82aefeee46a5355ed7f5d8fb006440612c5/LU/mapping.json`
- `city_normalized/df65b6abbdc65f0caf047328aa28a82aefeee46a5355ed7f5d8fb006440612c5/LU/report.json`
- `city_normalized/dfaa240ddd4cdc273529d14bcd7d6f3319072fcc72d3477fbf1faa7d20b30cb2/RU/mapping.json`
- `city_normalized/dfaa240ddd4cdc273529d14bcd7d6f3319072fcc72d3477fbf1faa7d20b30cb2/RU/report.json`
- `city_normalized/e08dccb9c6924a7131ebc804accba6006757606bf3ff06e3b0fd9030a0db2cab/PE/mapping.json`
- `city_normalized/e08dccb9c6924a7131ebc804accba6006757606bf3ff06e3b0fd9030a0db2cab/PE/report.json`
- `city_normalized/e1581fb7eee188e4f6a9b295fe33868fc092cdaa9eeb9a6bb35d828c9089a3ac/RE/mapping.json`
- `city_normalized/e1581fb7eee188e4f6a9b295fe33868fc092cdaa9eeb9a6bb35d828c9089a3ac/RE/report.json`
- `city_normalized/e1cd169f6ed3ccefa2cf3172aa042431327ef265735f9dbe0fd7d117c1f0d4ae/NR/mapping.json`
- `city_normalized/e1cd169f6ed3ccefa2cf3172aa042431327ef265735f9dbe0fd7d117c1f0d4ae/NR/report.json`
- `city_normalized/e34ee1c1941d27838e0069b9b860ebbf4a5082057b61695e9187561a9cb01b28/GP/mapping.json`
- `city_normalized/e34ee1c1941d27838e0069b9b860ebbf4a5082057b61695e9187561a9cb01b28/GP/report.json`
- `city_normalized/e37252a9c5ed27079b78673999317b3f986d3d418ddf1771785ba4acf2810a38/LK/mapping.json`
- `city_normalized/e37252a9c5ed27079b78673999317b3f986d3d418ddf1771785ba4acf2810a38/LK/report.json`
- `city_normalized/e585cd17e10f0789c0d5f55db349386471055e2ce5ffd60b620df80ef8be31a5/ZA/mapping.json`
- `city_normalized/e585cd17e10f0789c0d5f55db349386471055e2ce5ffd60b620df80ef8be31a5/ZA/report.json`
- `city_normalized/e693b257032c3ab25583db1b92a465717e65dbb3843d6dfd5836f922750f13ee/LI/mapping.json`
- `city_normalized/e693b257032c3ab25583db1b92a465717e65dbb3843d6dfd5836f922750f13ee/LI/report.json`
- `city_normalized/e6a5fa41538158520b9e3e23c7f1c2fca23ab266069c96451f3ae585f876bbd3/SV/mapping.json`
- `city_normalized/e6a5fa41538158520b9e3e23c7f1c2fca23ab266069c96451f3ae585f876bbd3/SV/report.json`
- `city_normalized/e7079dc27c471f45c4ab330c4bb0ac39a954d235bd60fdcde8b9f7d5f57ca227/BH/mapping.json`
- `city_normalized/e7079dc27c471f45c4ab330c4bb0ac39a954d235bd60fdcde8b9f7d5f57ca227/BH/report.json`
- `city_normalized/e71c12531ef7d21e8426336ff7dfaa3e57e3901e5c2f8319b2dfe7adb1485b2b/DE/mapping.json`
- `city_normalized/e71c12531ef7d21e8426336ff7dfaa3e57e3901e5c2f8319b2dfe7adb1485b2b/DE/report.json`
- `city_normalized/ec407f8d9c83090a9c97be0b9848151059602be0fd16fd23f091f0b0d95aa067/JO/mapping.json`
- `city_normalized/ec407f8d9c83090a9c97be0b9848151059602be0fd16fd23f091f0b0d95aa067/JO/report.json`
- `city_normalized/ed028df1b935acf3bea27e2e2b3bf64b6ef6021650bc2c80a0ef98aa32a2432b/GH/mapping.json`
- `city_normalized/ed028df1b935acf3bea27e2e2b3bf64b6ef6021650bc2c80a0ef98aa32a2432b/GH/report.json`
- `city_normalized/ed7262daaf3c0338f834f9b51fe84f601beda31d841a0265f989ae611e4191f6/JP/mapping.json`
- `city_normalized/ed7262daaf3c0338f834f9b51fe84f601beda31d841a0265f989ae611e4191f6/JP/report.json`
- `city_normalized/ee866659e83bc1a0ca92eebad65529543943933f1a94cac5584b0eb1ffa26eeb/GF/mapping.json`
- `city_normalized/ee866659e83bc1a0ca92eebad65529543943933f1a94cac5584b0eb1ffa26eeb/GF/report.json`
- `city_normalized/f00ba7d242817eecb81180fc2c98ac92193ece88287c74627c3c4af98b431192/CZ/mapping.json`
- `city_normalized/f00ba7d242817eecb81180fc2c98ac92193ece88287c74627c3c4af98b431192/CZ/report.json`
- `city_normalized/f00d0454c0358c53a8a84ecd7b3e8b6431e4af297fd4e7d8c49dd5fd213b3762/BS/mapping.json`
- `city_normalized/f00d0454c0358c53a8a84ecd7b3e8b6431e4af297fd4e7d8c49dd5fd213b3762/BS/report.json`
- `city_normalized/f095e8a9f371b98d422bb518d461189a88ec2ea7918c159d10e01e4b9ac1d17d/NF/mapping.json`
- `city_normalized/f095e8a9f371b98d422bb518d461189a88ec2ea7918c159d10e01e4b9ac1d17d/NF/report.json`
- `city_normalized/f216bdbd27f54da0a130425a31799c937077d44aeed5c2fbef962516435d8837/AZ/mapping.json`
- `city_normalized/f216bdbd27f54da0a130425a31799c937077d44aeed5c2fbef962516435d8837/AZ/report.json`
- `city_normalized/f345d3c607142051033374c74a642a8accfbce8782660d59e841d21c521dce80/IS/mapping.json`
- `city_normalized/f345d3c607142051033374c74a642a8accfbce8782660d59e841d21c521dce80/IS/report.json`
- `city_normalized/f381875f7b5a9e20a8ec36006330c269f5a5aeaca049e2d56639b79e2977ccb5/SG/mapping.json`
- `city_normalized/f381875f7b5a9e20a8ec36006330c269f5a5aeaca049e2d56639b79e2977ccb5/SG/report.json`
- `city_normalized/f395283063f47decdb8b2254b80683e0b54e67e89ecf3f4987ca7abb5f7122d0/CV/mapping.json`
- `city_normalized/f395283063f47decdb8b2254b80683e0b54e67e89ecf3f4987ca7abb5f7122d0/CV/report.json`
- `city_normalized/f3991619f4fdd65959b2bb4a7572d670f6f5075f5de9c30abd63228369eefc4e/SO/mapping.json`
- `city_normalized/f3991619f4fdd65959b2bb4a7572d670f6f5075f5de9c30abd63228369eefc4e/SO/report.json`
- `city_normalized/f4ce517ffce3678c94c21399045f0f0ae8c445a02bb3d30071f951de3b96cea5/KY/mapping.json`
- `city_normalized/f4ce517ffce3678c94c21399045f0f0ae8c445a02bb3d30071f951de3b96cea5/KY/report.json`
- `city_normalized/f59981668756907a5b291c66659922c96468b7263d1c310f4db9d72951f53de8/AG/mapping.json`
- `city_normalized/f59981668756907a5b291c66659922c96468b7263d1c310f4db9d72951f53de8/AG/report.json`
- `city_normalized/f6f3777c8ad85c34c374782b6ddafbe7ae3faf91a74680ab43dabef370828029/GQ/mapping.json`
- `city_normalized/f6f3777c8ad85c34c374782b6ddafbe7ae3faf91a74680ab43dabef370828029/GQ/report.json`
- `city_normalized/f6fb4c9e91d4ce63e8c6cb349726e3ae49b23fe2048260859090a7e87153f007/XJ/mapping.json`
- `city_normalized/f6fb4c9e91d4ce63e8c6cb349726e3ae49b23fe2048260859090a7e87153f007/XJ/report.json`
- `city_normalized/f901af4733adb64f70090eade702d2695cbec2aa2849b31151f10a55b1a3808a/ET/mapping.json`
- `city_normalized/f901af4733adb64f70090eade702d2695cbec2aa2849b31151f10a55b1a3808a/ET/report.json`
- `city_normalized/f95d53226bf32cfcf338e58853b4803eb041248da4ea7987f3fce6d241dea8b5/OM/mapping.json`
- `city_normalized/f95d53226bf32cfcf338e58853b4803eb041248da4ea7987f3fce6d241dea8b5/OM/report.json`
- `city_normalized/fa9abb51ab89ec0185542f4084f7a01440ce414dba6d54d28234055e3baa1d4c/IR/mapping.json`
- `city_normalized/fa9abb51ab89ec0185542f4084f7a01440ce414dba6d54d28234055e3baa1d4c/IR/report.json`
- `city_normalized/fad8d9bb2c1c26713b83d01d419aae7cda45c869eb73fb9f18d070cf2de72074/TM/mapping.json`
- `city_normalized/fad8d9bb2c1c26713b83d01d419aae7cda45c869eb73fb9f18d070cf2de72074/TM/report.json`
- `city_normalized/fb09ee1dfaecc5a49c7a3b54bfcc5ab14021c8139280675dcca79954eec44877/MD/mapping.json`
- `city_normalized/fb09ee1dfaecc5a49c7a3b54bfcc5ab14021c8139280675dcca79954eec44877/MD/report.json`
- `city_normalized/fb4fc6939890d181685bb8f2406f30a8d5717428bc7d689b1905d66f99bb4db4/XD/mapping.json`
- `city_normalized/fb4fc6939890d181685bb8f2406f30a8d5717428bc7d689b1905d66f99bb4db4/XD/report.json`
- `city_normalized/fc8c0e4bcdb3c11a65001e235c2130bccfedb239ad09e35f99fb55f8f123550d/EE/mapping.json`
- `city_normalized/fc8c0e4bcdb3c11a65001e235c2130bccfedb239ad09e35f99fb55f8f123550d/EE/report.json`
- `city_normalized/fd73e02ab00d3c0543060145c8576c60e63af8fd82eca741c4a3235e3ae1bc27/CD/mapping.json`
- `city_normalized/fd73e02ab00d3c0543060145c8576c60e63af8fd82eca741c4a3235e3ae1bc27/CD/report.json`
- `city_normalized/fe17cb57dedcc79a95b39a95009b62043068c1c0c680d6170806574466ac5c1f/BN/mapping.json`
- `city_normalized/fe17cb57dedcc79a95b39a95009b62043068c1c0c680d6170806574466ac5c1f/BN/report.json`

**imported repository evidence (6)**

- `raw/plates/configuration/27583901ea93e06458cf4b7a4784ee6ebe7eb32e4ef735ef126b27af250e8845/survey.json`
- `raw/plates/configuration/5907b95045e635241d1b81cf5d038c21387302cf1771f98c07b9100e8e0e761a/formats.json`
- `raw/plates/configuration/60282f276d17858c8343e5c2027faf20283ced0aa90b2cfa3aedfe3cf835de25/coverage.json`
- `raw/plates/configuration/67dfa6cb8999c01fcc756011d7baf548ef10504823c0764a5a8f520fcb198e3b/sources.json`
- `raw/plates/configuration/af8f0c870e11f85544ca17e4c7d983fd040e250998468987bd40cf208c6bdac4/rules.json`
- `raw/plates/configuration/f788b03a74b93a8956a1810cef91bcd97b8a6f72fe49a41c58cb44a5c1b8b917/wikidata.json`

**normalized auxiliary metadata (1)**

- `normalized/osm_land/verification-b62fbe5d4eac9e8e21f7d3a8615dea3afb18c43a4e5f465dcc9c54fab80191dd.json`

**pilot gate receipt (1)**

- `work/v2-pilot/thereabouts-gate.json`

**pilot summary (1)**

- `work/v2-pilot/summary.json`

**raw source inventory (8)**

- `raw/airports/inventory.json`
- `raw/codes/inventory.json`
- `raw/dbip/inventory.json`
- `raw/phone/inventory.json`
- `raw/plates/inventory.json`
- `raw/postal/inventory.json`
- `raw/timezones/inventory.json`
- `raw/unlocode/inventory.json`

**retained base manifest (1)**

- `golden-base-thereabouts/manifest.json`

**source custody receipt (4)**

- `work/offloaded/geoboundaries.json`
- `work/offloaded/geonames.json`
- `work/offloaded/osm_land.json`
- `work/offloaded/overture.json`

</details>

## What is built

The runtime includes OmegaConf schemas/profiles and overrides, a relative-path
ledger, stage and unit dependency validation, the single fingerprint rule,
bounded worker scheduling, resource admission, atomic publication, run logs,
invalidation and recoverable migration. Low disk or resident-memory headroom
pauses admission. These checks do not impose an operating-system memory limit
on arbitrary stage code. SQLite writer waiting is configurable too.

Source stages now execute frozen pins and discover units independently. Engine
declarations still inspect retained outputs and explicitly refuse rebuilding
until package 3 ports the implementations. Synthetic stages
prove dependencies within a stage, lazy discovery, unchanged-byte propagation,
absent-input restoration and retry after interrupted manifest publication.

The legacy `build_data` package is unchanged. The only client source change is
`CELL_FORMAT_VERSION`; encoding behavior is unchanged. [DATA_PIPELINE.md](DATA_PIPELINE.md)
is the usage guide; superseded build guides remain under [history](history/).
[DATASET_README.md](DATASET_README.md) is the early release-layout draft, not a
generated release reference.

From this worktree, inspect the protected workspace with:

```sh
.venv/bin/python -m pipeline plan --root /Users/ujjwal/Downloads/solo/thereabouts/data
.venv/bin/python -m pipeline status --root /Users/ujjwal/Downloads/solo/thereabouts/data
.venv/bin/python -m pipeline migrate --dry-run \
  --root /Users/ujjwal/Downloads/solo/thereabouts/data \
  --report .cache/pipeline/migration.json
```

Read-only SQLite uses `mode=ro&immutable=1` and refuses a nonempty WAL. For the
unmigrated ledger, `plan` labels its result **SIMULATED ADOPTION**. It verifies
hashes in memory without blessing new identities on disk. An adopted ledger is
checked against its saved identities normally. The world test additionally
applies migration to a copied ledger and JSON inside this worktree, then checks
saved identities against original payloads read-only with copied JSON overlaid.
It copies no Parquet or other data tree.

## Current real-workspace plan and handover dry run

Final package-3 commands report the following table after simulated adoption and
handover. **Zero stale under simulation checks mapping and hashes only, not
engine equivalence.** Independent synthetic and pilot checks are described above.

| Stage | Handover units | Current | Stale | New | Units with absent outputs |
| --- | ---: | ---: | ---: | ---: | ---: |
| download | 13 | 13 | 0 | 0 | 4 |
| normalize | 13 | 13 | 0 | 0 | 2 |
| reconcile | 1,111 | 1,111 | 0 | 0 | 1,111 |
| cells | 41,442 | 41,442 | 0 | 0 | 0 |
| cities | 555 | 555 | 0 | 0 | 0 |
| evaluate | 1 | 1 | 0 | 0 | 0 |
| normalize_cells | 41,716 | 41,716 | 0 | 0 | 0 |
| plate_country (disabled) | 0 | 0 | 0 | 0 | 0 |
| lookups | 726 | 726 | 0 | 0 | 0 |
| **Total** | **85,577** | **85,577** | **0** | **0** | **1,117** |

## Migration changes and evidence

The corrected mapping processes 134,312 old ledger rows and retains the five
auxiliary rows previously dropped. It proposes retiring 42,334 superseded rows
and produces 85,577 verified adopted units (including explicitly absent records). Source-unit aggregation explains the
remaining difference in row counts. It rewrites 588 existing JSON files and
imports six verified JSON evidence files. There are 2,578 intentionally absent
output records across 1,117 units, including the approved four auxiliary payloads.

- The active `golden` symlink points to normalized output. Former base records
  are matched to `base_cells/current.json` by table, block/country and recorded
  hash. The selected base's entire table inventory is verified too.
- Exact-manifest offload receipts authorize absent raw outputs for
  `geoboundaries`, `geonames`, `osm_land` and `overture`. Remote objects are
  **not verified**; their recorded custody is retained explicitly.
- Reconciliation's deleted outputs retain their recorded hashes and
  `outputs_absent`. Restoration is needed only when an actual consumer executes
  or reconciliation is explicitly selected for materialization.
- Six plate-source auxiliary records refer to repository JSON files. Migration
  verifies their bytes and proposes content-addressed copies under
  `raw/plates/configuration/`; their source files are unchanged.
- Overture JSON pointers such as `/properties/names/...` remain JSON pointers.
  Historical review hashes are never rebound to different evidence to make
  them pass. Unknown stages and corrupt retained payloads stop adoption.

The final detailed dry-run report is `.cache/pipeline/engines-handover-final.json`. It records the
original ledger hash, per-row dispositions, relocations, new identities and unit
input hashes, and before/after JSON sizes and hashes. Application saves the exact
old ledger, journals JSON originals, and publishes the prepared ledger last.
Synthetic tests exercise rollback/retry, separate `paths`/`adopt` steps, a move
to a new root, and idempotence.

**Reviewer command, after a fresh dry run succeeds (not run against the real
workspace):**

```sh
.venv/bin/python -m pipeline migrate \
  --root /Users/ujjwal/Downloads/solo/thereabouts/data \
  --report .cache/pipeline/migration-applied.json
```

Stop old builders before application; they must not run against the adopted
ledger. Follow with `migrate check` and `plan` using the same `--root`. The executable geographic stages are now available. The old checkout-name symlink is
left for the reviewer because removing it would write outside this worktree.

## Original package-1 measurements (before review fixes)

Machine: Apple M2, 8,589,934,592 bytes RAM (8 GiB), macOS. The ordinary suite
passed **676 tests, 8 skipped**. Ruff check and formatting passed (461 files);
strict mypy passed (445 source files). The skipped tests require explicit world
fixtures. The explicit migration world proof passed in 352.018 seconds with
1,082,605,568 bytes peak RSS. It preserved the original ledger hash/mtime and
every JSON original, applied the migration to copies, and verified idempotence.
The original ledger copy was 112,971,776 bytes; the adopted copy was 151,146,496
bytes; rewritten/imported JSON totaled 29,404,126 bytes. The final dry-run
verified 17,677,115,785 payload bytes. These are full retained-workspace adoption
measurements, not a production rebuild benchmark. The committed results are in
[PIPELINE_MEASUREMENTS.json](PIPELINE_MEASUREMENTS.json).

The full existing golden content digest was recomputed once: **14 tables,
98,077,250 rows**, matching
`0e543e65bc26987a2714b89f2b23395e11c9e48d482d9ee2315d3a890a0e9614`.
It took 1,261.885 seconds with 541,097,984 bytes peak RSS. The unchanged legacy
digest implementation used a measured merge fan-in of 265 for this verification
process, avoiding a second on-disk copy of its row-hash runs. Row encoding,
sorting and digest framing were unchanged; the scratch bound was
2,119,253,760 bytes and the scratch files were removed by the digest reader.
The helper and detailed digest report remain in `data/pipeline-work/`.
At final review, worktree files totaled 1,111,395,098 bytes and free disk was
50,709,729,280 bytes. Scratch allocation was bounded before starting and copies
were admitted only after checking the 3 GB worktree allowance and 5 GB disk floor.

Dataset and pack sizes: **not generated**. Package 4's subset build, complete
generated README with column references and executed examples, and local publish
are not part of this runtime package. No real stage was run on the protected
workspace and no cloud data operation was performed.

## Next packages and owner follow-ups

1. Package 2: completed above; world source normalization has not been rerun.
2. Package 3: completed above. Full-world geographic rebuilding, remote custody
   verification and real plate-country input validation were deliberately not run.
3. Package 4: measured release subset, coalesced cells, complete generated README,
   manifests/licences/card/changes, packs, local publish and registry output.
4. Package 5: VM and monthly release procedure documentation/scripts, unexecuted.

No geographic-policy decision was made. The owner still needs to review metadata
migration, verify remote custody needed for a future rebuild, and choose release
contact/citation and publication settings in later packages. Nothing was pushed
or published. All task outputs, temporary files, environment and reports are in
this worktree; a local Git commit uses Git's existing shared worktree metadata.
The real `data/` workspace was not modified.
