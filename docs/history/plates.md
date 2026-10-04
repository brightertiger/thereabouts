# Vehicle registration plate evidence

`plates` is a standalone acquisition source for places encoded in vehicle
registration plates. It publishes three Parquet tables: a country survey,
code–place evidence, and plate-format rules. **This is a partial global collection,
not a complete world plate decoder.** Its explicit gaps are part of the data.
No golden-place join is included. The additive reference resolver described below
ranks country candidates and implements geographic fallback over this evidence.

The acquisition tables and survey below retain the accepted `plates` baseline.
Their format counts describe that original source; the additive inventory and
measurements later in this document describe `plates_country`.

A code describes a registration jurisdiction, office or allocation area. It does
not locate the vehicle or its owner today. Vehicles can retain plates after sale
or relocation; codes can survive administrative mergers or be reintroduced.
The same code can denote several units, and a unit can have several codes.
In particular, many Wikidata P395 statements attach a district's code to every
municipality in that district. Those rows are **entity associations**, not evidence
that the plate identifies that municipality uniquely.

Ordinary geographic schemes coexist with vanity, diplomatic, military, dealer,
temporary, nationwide and special-purpose series. Those series often carry no
subnational place. A diplomatic country code is not a registration location.
Printed jurisdiction text, optional identity bands and encoded serial characters
are different evidence. France's optional modern department band is not proof of
residence; Italy's modern province band is optional. Most US, Canadian and
Australian ordinary serials require a printed jurisdiction, but specific US county
and Australian local-area schemes do encode places. Thailand's ordinary car serial
does not encode province; this collection includes a separate official numeric
scheme for special international plates.

## Classification and temporal interpretation

The requested four classes are `usable_now`, `historic_only`,
`printed_not_encoded`, and `none`. An additional **`unverified`** class prevents
missing or contradictory evidence from becoming a false negative. `usable_now`
means at least one evidenced geographic series is current, not that every plate
from that country can be interpreted. The survey's series and notes qualify it.
Some `none` classifications are inferences from source descriptions of sequential
ordinary serials; they do not establish that no historic geographic series existed.

Code rows independently have `current`, `historic`, or `unknown` status. A Wikidata
statement without an end-date is `unknown`, not automatically current. `historic`
means a former issuing series; it does not necessarily mean an existing plate is
invalid. Missing years remain null. Source-written dates and contradictory claims
remain available in `notes` even where they have not been structurally parsed.

## Evidence, licences and pinning

Every code and source specimen is extracted from a fetched file. Parsing choices,
survey interpretations, patterns and coverage checks live in
`plates_data` (`build_data/acquire/plates_data/`, removed), not country branches in Python.
No codes were supplied from memory. The full
`sources.json` (`build_data/acquire/plates_data/sources.json`, removed) catalog records
every upstream URL, SHA-256, byte size, licence, attribution and retrieval timestamp.
The output manifest includes that inventory and the policy fingerprints; a
`licenses-*.json` auxiliary file lists each source's reuse information.

| Source | Licence and use |
| --- | --- |
| [Wikidata P395](https://www.wikidata.org/wiki/Property:P395) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). Country-by-country SPARQL; query text, response hash and retrieval date pinned. Germany uses a smaller query after full queries timed out, so some metadata is absent. |
| Wikipedia plate articles and list articles, including local-language editions | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Each catalog entry links a specific revision and attributes its contributors. English, German, French, Japanese, Chinese, Indonesian, Persian and other editions are retained. Share-alike attribution obligations remain attached to derived rows. |
| [DVLA INF104](https://assets.publishing.service.gov.uk/media/6694e379fc8e12ac3edafc60/inf104-vehicle-registration-numbers-and-number-plates.pdf) | [Open Government Licence 3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/); Crown copyright. Great Britain local memory tags. |
| [Japan MLIT regional-marking list](https://www.mlit.go.jp/jidosha/content/001622186.pdf) | [Public Data License 1.0, MLIT notice](https://www.mlit.go.jp/page/kanbo01_hy_003776.html). Output is an edited derivative of MLIT material, not an official MLIT product. |
| [Thai Government Gazette notification, 27 June 2023](https://ratchakitcha.soc.go.th/documents/140D151S0000000001200.pdf) | `LicenseRef-PD-Thailand-Section7`: official notification excluded from copyright under [Copyright Act section 7(3)](https://www.wipo.int/wipolex/en/legislation/details/3801). The appendix supplies the special international plate province codes. |
| [Polish regulation, 2024 item 1709](https://isap.sejm.gov.pl/isap.nsf/download.xsp/WDU20240001709/O/D20241709.pdf), amended by [2025 item 939](https://isap.sejm.gov.pl/isap.nsf/download.xsp/WDU20250000939/O/D20250939.pdf) and [2026 item 891](https://isap.sejm.gov.pl/isap.nsf/download.xsp/WDU20260000891/O/D20260891.pdf) | `LicenseRef-PD-Poland-Article4`: normative acts are excluded from copyright by [Copyright Act article 4(1)](https://isap.sejm.gov.pl/isap.nsf/download.xsp/WDU20250000024/O/D20250024.pdf). The complete ordinary province/county allocation annex and its additions are parsed; source prefixes are combined with source suffixes. |
| [DataHub country-codes](https://github.com/datasets/country-codes/tree/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1) | [PDDL 1.0](https://opendatacommons.org/licenses/pddl/1-0/), pinned commit. Supplies the survey universe and country identifiers, not plate classifications. |

There is **no single CC0 licence for the combined output**. Preserve each row's
licence and provenance when selecting, combining or redistributing evidence.
OSM was not used; no ODbL-derived rows are included.

Wikipedia revision IDs fix article edits, but rendered HTML can change when
templates or parser behavior change. Wikidata live queries are not time-travel
snapshots. Exact regeneration therefore uses the retained raw bytes; a fresh
upstream response with different bytes fails its hash check. It is not silently
accepted as the old snapshot. Official PDFs are similarly pinned by hash.
Raw files are local, ignored artifacts, not embedded in the git commit. A review or
transfer of this acquisition must preserve `data/raw/plates/snapshot/` together
with `inventory.json`, or matching retained `research/` files. A fresh clone alone
cannot guarantee retrieval of an identical historical Wikidata response.

## Reproduce and inspect

Run from this worktree. Use its own `data/`, never the main checkout's data.
Use this worktree’s own environment; the main checkout is independent:

```sh
uv sync
PYTHON=.venv/bin/python
"$PYTHON" -m build_data.acquire plates --data-dir data
"$PYTHON" -m build_data.acquire plates --data-dir data --stage normalize
"$PYTHON" -m build_data.acquire status --data-dir data
"$PYTHON" -m build_data.acquire.plates_report --data-dir data --output data/work/plates-base-report.md
```

The first command downloads missing catalog entries and normalizes. The second
is offline and reads pinned snapshots only. Successful files are reused across
interruptions. Downloads identify `Thereabouts`, cache every response, and
serialize requests by host at least 1.1 seconds apart (65 seconds for Wikidata).
Small documents resume at file boundaries; failed partial bytes are retained for
inspection. Byte-range resume is available only for sources explicitly marked
range-verified. Normalization restarts its evidence unit after interruption and
publishes through the shared ledger/manifest lifecycle. Installed Poppler's
`pdftotext -layout` is required for the PDF sources; no Python dependency was added.

Raw layers are `data/raw/plates/{research,snapshot}`. Normalized outputs are under
`data/normalized/plates/`; use `manifest.json` to select active partitions rather
than globbing superseded files. `verification.json` contains all code-set
comparisons and coverage measurements. Download/query failures are retained in
the research receipts/logs and tracked in `data/work/plates-progress.md`.

## Table contracts

The authoritative schemas are
`plates_schemas.py` (`build_data/acquire/plates_schemas.py`, removed). No H3 cell or golden
place ID is fabricated for these evidence tables.

| Table | Main fields and meaning |
| --- | --- |
| `plate_codes` | `country_code`, original-script `code`, `name_en`, `name_local`, `local_language`, `unit_kind`, `series_id`, `series_status`, `valid_from`, `valid_to`, `scope`, `subdivision_scope`; `wikidata_id`, JSON-string arrays `geonames_ids`, `subdivision_codes` (ISO 3166-2), `entity_types`; nullable latitude/longitude from the source; `evidence_locator`, raw `notes`. |
| `plate_survey` | One row per country/territory; classification, geographic level, code position, series/dates, captured classification evidence, notes and coverage status. |
| `plate_formats` | Country and series; Python regex for `fullmatch`, named `code_group` when geography is encoded, code position, normalization instructions, dates, source evidence, list of literal examples, and limits. |
| All three | `source`, stable `source_id`, `source_release`, `source_url`, `retrieved_at`, `license`, JSON `provenance` with raw snapshot filename/hash and the original extracted record. |

Codes preserve leading zeroes, Unicode scripts and source spelling. Identical
country/code strings in different sources or periods remain distinct assertions.
Source-written numeric and alphabetic ranges are expanded; every source-listed
code/unit association is retained. Duplicate HTML representations of the same
pair within one source/period are collapsed. Supported explicit Wikidata code
lists are split into individual codes. URI placeholders, vandalized image/link
values and compound expressions that cannot be safely interpreted are excluded
from code rows and retained in `verification.json` under `rejected_assertions`,
with the original value, statement ID and source file. These include genuine
complex assertions that still need parsing; rejection is not a claim that the
underlying place has no code. Country-specific acceptance patterns are in
`plates_data/wikidata.json`. Null names or identifiers mean
missing evidence, not a failed golden-place join. Many local-language rows lack
an English label, and English rows may lack a local label. Thai PDF text-layer
diacritics can be imperfect; the raw PDF remains the authority for those names.

Format regexes are **candidate syntax**, not complete issuance validators. They
do not yet encode all excluded letters, checksums, reserved combinations,
vehicle classes, historic alternatives or special series. Use `fullmatch`, then
the named capture, then a known code and compatible series; a string can match
several countries. No extraction or lookup API is added here. Captured examples
occur literally in sources, but many are illustrative specimens rather than
authenticated live plates. That part of the requested real-example coverage is
incomplete. A zero format count below is an explicit gap.

## Reviewed disagreements and remaining work

* Japan: official MLIT, English Wikipedia and Japanese Wikipedia agree exactly on
  the 138 current ordinary regional markings. Municipal moped plates are outside
  this completeness check. Historical spellings remain separate.
* Indonesia: both lists contain 61 leading motor-vehicle area prefixes. The local
  list adds district associations. Suffix refinements and all their temporal
  allocations are not yet normalized as compound codes.
* Vietnam: all 34 post-July-2025 provincial rows expand to 80 geographic prefixes;
  national-authority `80` is excluded. The retained
  [Lai Chau government list](https://laichau.gov.vn/tin-tuc-su-kien/chuyen-de/tin-trong-nuoc/huong-dan-dang-ky-xe-danh-sach-ky-hieu-bien-so-xe-cac-dia-phuong-sau-sap-xep-hop-nhat.html)
  has the same numeric set but uses Thừa Thiên Huế where Wikipedia uses Huế.
  Its reuse terms were unconfirmed, so it is comparison evidence only and does
  not supply normalized rows.
* Great Britain: DVLA's table has 433 tags, including select-issue allocations
  omitted from Wikipedia. Wikipedia additionally lists `NF`; both assertions
  remain. Northern Ireland, historic transfers and private sales require separate
  interpretation. The exact differences are in the generated cross-check report.
* Iran: Persian Wikipedia includes `۷۰`, absent from the English geographic
  table. Shared province codes remain separate pairs. County letter refinements
  are not complete.
* Poland: the 2024 statutory annex has 380 county/city rows yielding 677 ordinary
  allocations, including alternative province letters. The 2025 amendment adds
  four codes and the 2026 amendment adds eight, for 689. The parser reads the
  province prefix from the original annex when an amendment supplies only a
  county suffix; both source references remain in provenance. Wikipedia omits
  many alternatives and lists `STY` as current although it is absent from these
  acts. Its explicitly former `NOG` entry is historic, ending in 2002. This check
  certifies the reviewed published allocation list, not actual issuance of every
  reserved combination or all special/historic series.
* Malaysia: the source says a series is “Exhausted in 2027”, after this acquisition
  date. That assertion is marked unknown, not accepted as a completed transition.
  Shared names and historical Sabah/Sarawak series need further review.
* China: English and Chinese lists differ and mix withdrawn prefectures, special
  series and current allocations. Only explicitly selected civil entries are
  marked current; unknown-period assertions are preserved. No complete-current
  claim is made. Russia and Ukraine similarly require dated allocation reviews;
  a registration-system label is not a territorial sovereignty judgment.
* India and Germany have substantial collections but no independently
  established complete current denominator. Reintroduced codes, new offices,
  county changes and aliases need further reconciliation. Italy's serial geography
  is historic; optional current province bands are not treated as encoded serials.
* Pakistan's province-specific changes are unresolved; this collection contains
  only a few historic/undated associations. Sri Lanka, Armenia, Taiwan, Ethiopia
  and Mexico retain explicit uncertainty where current applicability is unclear.
* Historic years, all historic series, English/local-name pairing, identifiers
  outside Wikidata, detailed place-association disagreements and complete valid
  plate patterns remain incomplete. Unverified countries must not be treated as
  “no geographic code”. Zero collected codes does not imply zero existing codes.

The German ministry download timed out; a Vietnamese provincial PDF and a Thai
DLT host had TLS validation failures. No TLS checks were disabled. An official
Thai Gazette copy was usable. Polish API hosts also failed TLS verification;
the official ISAP PDF copies were usable. WorldLicensePlates and MatriculasDelMundo
were not imported because reusable licences were not established. No source was imported
despite known terms forbidding reuse; unconfirmed rights are reported as
unconfirmed, not as an asserted prohibition. Government notices used only for
research remain outside the distributed normalized source inventory when their
reuse status is unresolved.

<!-- Generated plate coverage below; run plates_report to refresh. -->

## Snapshot and counts

Retrieved 2026-10-02 through 2026-10-02; 404 pinned files, 217,388,877 bytes. Source release: `5cfeab8a47dec58b3725c42a41a097ad74d138ac88d02d252ca3eda7ba987606`.

143,935 code-place evidence rows; 40,613 distinct (country, code) pairs; 20,790 distinct code strings. Different upstream assertions remain separate evidence rows. Expanded source-written alphabetic ranges account for many Brazilian and Mexican codes; municipal Wikidata assertions account for many rows.

| Survey class | Countries/territories |
| --- | --- |
| historic_only | 31 |
| none | 72 |
| printed_not_encoded | 15 |
| unverified | 35 |
| usable_now | 97 |

159 format rules in 151 countries; 80 rules have literal source specimens. A specimen may be illustrative; live issuance has not been authenticated. Missing examples are empty lists.

98,461 code rows carry Wikidata IDs; 93,652 have source coordinates. Identifiers/names from different sources have not been joined.

108 Wikidata assertions were excluded as non-codes or unsupported compound expressions. Their original values and statement IDs are retained in the verification report and raw files.

## Priority-country coverage

Counts are distinct original-script code strings, including disagreements. Current means explicitly classified by that source's parsing policy. Unknown-period Wikidata statements are included only in the all-period count.

| Country | Rows | Current codes | All periods | Completeness and basis |
| --- | --- | --- | --- | --- |
| IN | 1697 | 1320 | 1545 | Partial: complete current national denominator not established. |
| CN | 2337 | 317 | 470 | Partial: complete current national denominator not established. |
| DE | 15458 | 702 | 796 | Partial: complete current national denominator not established. |
| ID | 1158 | 61 | 62 | Entire English geographic prefix table; every motor-vehicle prefix also occurs in the Indonesian district list. Suffix refinements, exceptions and temporal allocation completeness are not established. |
| TR | 15127 | 81 | 81 | All province-list rows 01–81 extracted; each listed code also occurs in the country Wikidata response. No official current registry cross-check. |
| RU | 921 | 161 | 193 | Partial: complete current national denominator not established. |
| IT | 9826 | 0 | 199 | Partial: complete current national denominator not established. |
| PL | 21515 | 690 | 717 | All 380 county/city rows in Annex 13 yield 677 allocated codes; 2025 amendment adds 4 and 2026 amendment adds 8. Shared provincial alternative letters are combined with county suffixes as prescribed by the table. Wikipedia omits many alternatives and additionally calls STY current; NOG is explicitly former and now historic. Completeness is limited to these published ordinary allocations, not all issued/special plates. |
| GB | 1414 | 434 | 554 | Entire published DVLA table, including continuation lines and ranges; I/Q/Z and explicitly reserved MN excluded; HW mapped using the Isle of Wight footnote. Wikipedia differs on select-issue reservations and NF. Northern Ireland and private transfers need separate interpretation. |
| JP | 804 | 138 | 199 | Entire MLIT regional-marking column extracted; exact code-set equality with both pinned Wikipedia lists. Multiple office seats sharing a marking remain separate rows. |
| VN | 85 | 80 | 83 | All 34 provincial rows in the three geographic tables; ranges expanded. Numeric 80 for national authorities excluded. Separately compared with the retained July-2025 Lai Chau government table; same code set, Hue naming difference. Government reuse terms unconfirmed, so output rows use Wikipedia. |
| MY | 96 | 29 | 54 | Partial: complete current national denominator not established. |
| IR | 185 | 87 | 91 | Partial: complete current national denominator not established. |
| TH | 78 | 78 | 78 | Entire Gazette appendix, 26 rows × 3 columns: 77 provinces/metropolitan area plus Betong. Does not imply that an ordinary Thai car serial identifies province. |
| PK | 5 | 0 | 5 | Partial: complete current national denominator not established. |
| UA | 4510 | 110 | 268 | Partial: complete current national denominator not established. |

No country is certified complete across every current and historic series. The following checks cover only the stated published lists:

| Country | Scope | Observed / expected | Check |
| --- | --- | --- | --- |
| GB | DVLA INF104 Great Britain local memory-tag allocation table | 433 / 433 | published_list_complete |
| ID | Leading area prefixes, excluding non-motorised vehicle codes | 61 / 61 | published_list_complete |
| JP | Current ordinary regional markings (not moped municipal plates) | 138 / 138 | published_list_complete |
| PL | Ordinary statutory province/county prefixes in 2024 regulation plus 2025/2026 amendments | 689 / 689 | published_list_complete |
| TH | 2023 special international plates: province/Betong numeric identifiers | 78 / 78 | published_list_complete |
| TR | Ordinary two-digit province prefixes | 81 / 81 | published_list_complete |
| VN | Province prefixes after July 2025 mergers | 80 / 80 | published_list_complete |

## Survey of every country and territory

Universe: the pinned ISO 3166-1 list (249 entries) plus Kosovo (XK). Disputed/de facto jurisdictions without their own entry are not separately exhaustive. A class describes the evidenced series, with exceptions in the last column. `none` is not a claim about every plate ever issued. A country-universe link on an unverified row provides identity only, not evidence of plate behavior. Blank levels/positions/dates are unknown.

| CC | Country / classification source | Class | Level | Code position | Series (years) | Current / all codes | Formats | Limits / gaps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AD | [Andorra](https://en.wikipedia.org/w/index.php?oldid=1363303908) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary series; historical/special formats not exhaustively reviewed. |
| AE | [United Arab Emirates](https://en.wikipedia.org/w/index.php?oldid=1365209773) | printed_not_encoded | emirate | printed emirate name/design | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 0 | Serial formats overlap across emirates; no unique countrywide numeric region code. |
| AF | [Afghanistan](https://en.wikipedia.org/w/index.php?oldid=1356853566) | usable_now | province | province abbreviation beside serial | ordinary; exceptions described in notes (? to ?) | 34 / 34 | 0 | Classification describes the cited series; special and personalised series need separate handling. |
| AG | [Antigua & Barbuda](https://en.wikipedia.org/w/index.php?oldid=1338001799) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 0 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| AI | [Anguilla](https://en.wikipedia.org/w/index.php?oldid=1338001793) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary series; historical/special formats not exhaustively reviewed. |
| AL | [Albania](https://en.wikipedia.org/w/index.php?oldid=1371058793) | historic_only | district | leading letters | ordinary; exceptions described in notes (? to 2011) | 0 / 39 | 1 | National series since 2011; older plates remain valid. |
| AM | [Armenia](https://en.wikipedia.org/w/index.php?oldid=1371471817) | unverified | province | two-digit group | ordinary; see exceptions (? to ?) | 0 / 66 | 1 | The source qualifies the geographic claim as supposed; no current-validity guarantee. |
| AO | [Angola](https://en.wikipedia.org/w/index.php?oldid=1338001791) | usable_now | province | first three letters | ordinary; exceptions described in notes (? to ?) | 0 / 1 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| AQ | [Antarctica](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| AR | [Argentina](https://en.wikipedia.org/w/index.php?oldid=1367699844) | historic_only | province | leading letter before 1995 | ordinary; see exceptions (? to ?) | 0 / 25 | 1 | Current national Mercosur series has no province encoding; legacy province codes are retained. |
| AS | [American Samoa](https://en.wikipedia.org/w/index.php?oldid=1343912298) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| AT | [Austria](https://en.wikipedia.org/w/index.php?oldid=1367179317) | usable_now | district | first one or two letters | ordinary; exceptions described in notes (? to ?) | 107 / 107 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| AU | [Australia](https://en.wikipedia.org/w/index.php?oldid=1374112729) | usable_now | local_government_area | WA locality letter prefix | ordinary; see exceptions (? to ?) | 121 / 121 | 0 | Most Australian plates require the printed state. Geographic coding here is limited to optional Western Australian LGA plates; other state schemes and historic allocations are gaps. |
| AW | [Aruba](https://en.wikipedia.org/w/index.php?oldid=1338001805) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| AX | [Åland Islands](https://de.wikipedia.org/w/index.php?oldid=248707514) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| AZ | [Azerbaijan](https://en.wikipedia.org/w/index.php?oldid=1371307150) | usable_now | registration_office | first two digits | ordinary; exceptions described in notes (? to ?) | 78 / 82 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| BA | [Bosnia](https://en.wikipedia.org/w/index.php?oldid=1338001871) | historic_only | city | leading city letters | ordinary; exceptions described in notes (? to 1998) | 0 / 52 | 1 | Ordinary plates standardized without district letters in 1998. Historical regional series retained. |
| BB | [Barbados](https://en.wikipedia.org/w/index.php?oldid=1367992026) | usable_now | parish | first one or two letters | ordinary; exceptions described in notes (? to ?) | 11 / 11 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| BD | [Bangladesh](https://en.wikipedia.org/w/index.php?oldid=1365474120) | usable_now | district_or_city | Bengali name on first line | ordinary; exceptions described in notes (? to ?) | 1 / 1 | 0 | Classification describes the cited series; special and personalised series need separate handling. |
| BE | [Belgium](https://en.wikipedia.org/w/index.php?oldid=1369135514) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| BF | [Burkina Faso](https://en.wikipedia.org/w/index.php?oldid=1377255920) | usable_now | province | first digits | ordinary; see notes (? to ?) | 0 / 0 | 0 | Applies to the source-described ordinary series; complete historical and special coverage remains unverified. |
| BG | [Bulgaria](https://en.wikipedia.org/w/index.php?oldid=1372353235) | usable_now | province | first one or two letters | ordinary; exceptions described in notes (? to ?) | 30 / 63 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| BH | [Bahrain](https://en.wikipedia.org/w/index.php?oldid=1338129219) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary series; historical/special formats not exhaustively reviewed. |
| BI | [Burundi](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| BJ | [Benin](https://en.wikipedia.org/w/index.php?oldid=1338001852) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 0 | Classification describes the cited series; special and personalised series need separate handling. |
| BL | [St. Barthélemy](https://en.wikipedia.org/w/index.php?oldid=1338002779) | none | — | — | ordinary; see notes (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary series. This is a series-level inference; historical and special exceptions have not been exhausted. |
| BM | [Bermuda](https://en.wikipedia.org/w/index.php?oldid=1356256004) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary series; historical/special formats not exhaustively reviewed. |
| BN | [Brunei](https://en.wikipedia.org/w/index.php?oldid=1338001881) | historic_only | registration_office | first letter | ordinary; exceptions described in notes (? to 2006) | 0 / 0 | 0 | B/K no longer reliable geography after 2006. |
| BO | [Bolivia](https://en.wikipedia.org/w/index.php?oldid=1341292282) | historic_only | department | first letter | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | Historic serial encoded department; current plate shows department letter in a separate small box (not part of serial). Historic-only here refers to encoding in the serial. |
| BQ | [Caribbean Netherlands](https://en.wikipedia.org/w/index.php?oldid=1345337205) | usable_now | island | initial letter | ordinary; see exceptions (? to ?) | 2 / 2 | 0 | Bonaire, Saba and Sint Eustatius use different prefixes. Vehicle-class prefixes are exceptions. |
| BR | [Brazil](https://en.wikipedia.org/w/index.php?oldid=1361898556) | usable_now | state | first three-letter allocation block | ordinary; exceptions described in notes (? to ?) | 13717 / 13719 | 1 | Allocation blocks identify original issuing state; ownership and moves do not guarantee current location. Partial serial subranges are gaps. |
| BS | [Bahamas](https://en.wikipedia.org/w/index.php?oldid=1358279279) | printed_not_encoded | island | printed text | ordinary; see exceptions (? to ?) | 0 / 0 | 0 | Inference applies to the described ordinary series; complete historical coverage is not established. |
| BT | [Bhutan](https://en.wikipedia.org/w/index.php?oldid=1376978101) | usable_now | registration_region | digit after vehicle-class prefix | ordinary; exceptions described in notes (? to ?) | 5 / 5 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| BV | [Bouvet Island](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| BW | [Botswana](https://en.wikipedia.org/w/index.php?oldid=1338001869) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| BY | [Belarus](https://en.wikipedia.org/w/index.php?oldid=1368347962) | usable_now | region | last digit | ordinary; exceptions described in notes (? to ?) | 0 / 9 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| BZ | [Belize](https://en.wikipedia.org/w/index.php?oldid=1338001838) | usable_now | district_or_city | letter abbreviation | ordinary; exceptions described in notes (? to ?) | 14 / 14 | 0 | Classification describes the cited series; special and personalised series need separate handling. |
| CA | [Canada](https://en.wikipedia.org/w/index.php?oldid=1355657060) | printed_not_encoded | province_or_territory | printed jurisdiction | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 0 | Jurisdiction-specific serial patterns overlap; printed province is needed. Historic exceptional allocations unreviewed. |
| CC | [Cocos Islands](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| CD | [Congo - Kinshasa](https://en.wikipedia.org/w/index.php?oldid=1338002018) | usable_now | province | separate numeric province group | ordinary; see exceptions (? to ?) | 26 / 41 | 0 | Article gives 26 current numeric province codes but does not explain their exact placement in the main text; position needs verification. |
| CF | [Central African Republic](https://en.wikipedia.org/w/index.php?oldid=1303069313) | usable_now | prefecture | last two letters | ordinary; exceptions described in notes (? to ?) | 16 / 16 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| CG | [Congo - Brazzaville](https://en.wikipedia.org/w/index.php?oldid=1338001978) | usable_now | region | last one or two digits | ordinary; see exceptions (? to ?) | 14 / 14 | 0 | Inference applies to the described ordinary series; complete historical coverage is not established. |
| CH | [Switzerland](https://en.wikipedia.org/w/index.php?oldid=1368288237) | usable_now | canton | first two letters | ordinary; exceptions described in notes (? to ?) | 26 / 26 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| CI | [Côte d’Ivoire](https://en.wikipedia.org/w/index.php?oldid=1318022341) | historic_only | region | old final two digits | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | 2023 national format replaced regional suffix; old codes need historical interpretation. |
| CK | [Cook Islands](https://en.wikipedia.org/w/index.php?oldid=1338002003) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| CL | [Chile](https://en.wikipedia.org/w/index.php?oldid=1366530061) | historic_only | region | initial letters | ordinary; exceptions described in notes (? to 1984) | 0 / 2 | 1 | National serial numbering since 1985. |
| CM | [Cameroon](https://en.wikipedia.org/w/index.php?oldid=1338001926) | usable_now | region | first two letters | ordinary; exceptions described in notes (? to ?) | 10 / 10 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| CN | [China](https://en.wikipedia.org/w/index.php?oldid=1374494974) | usable_now | province_and_registration_area | Chinese character plus Latin letter at start | ordinary; exceptions described in notes (? to ?) | 317 / 470 | 2 | Municipal prefixes may encode vehicle categories rather than districts; source has current and former prefixes; temporal adjudication incomplete. |
| CO | [Colombia](https://en.wikipedia.org/w/index.php?oldid=1373706002) | usable_now | registration_region | initial prefix | ordinary; exceptions described in notes (? to ?) | 0 / 1 | 0 | Prefix allocation plus printed municipality. Complete allocation ranges not collected. |
| CR | [Costa Rica](https://en.wikipedia.org/w/index.php?oldid=1338002006) | historic_only | city | old initial letters | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | Inference applies to the described ordinary series; complete historical coverage is not established. |
| CU | [Cuba](https://en.wikipedia.org/w/index.php?oldid=1349341809) | historic_only | province | first letter | ordinary; exceptions described in notes (? to 2013) | 0 / 16 | 1 | Province letter removed in 2013. |
| CV | [Cape Verde](https://en.wikipedia.org/w/index.php?oldid=1376832347) | usable_now | island | first two letters | ordinary; exceptions described in notes (? to ?) | 9 / 9 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| CW | [Curaçao](https://en.wikipedia.org/w/index.php?oldid=1338002012) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary series; historical/special formats not exhaustively reviewed. |
| CX | [Christmas Island](https://en.wikipedia.org/w/index.php?oldid=1310411286) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary series; historical/special formats not exhaustively reviewed. |
| CY | [Cyprus](https://en.wikipedia.org/w/index.php?oldid=1376218876) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| CZ | [Czechia](https://en.wikipedia.org/w/index.php?oldid=1372467542) | usable_now | region | first letter, usually second character | ordinary; exceptions described in notes (? to ?) | 15 / 114 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| DE | [Germany](https://en.wikipedia.org/w/index.php?oldid=1377669488) | usable_now | district_or_city | first one to three letters | ordinary; exceptions described in notes (? to ?) | 702 / 796 | 1 | Vehicles may retain plate after moves; multiple districts share restored codes. |
| DJ | [Djibouti](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| DK | [Denmark](https://en.wikipedia.org/w/index.php?oldid=1338668056) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 1 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| DM | [Dominica](https://en.wikipedia.org/w/index.php?oldid=1338002022) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 0 | No subnational component in the described ordinary series; historical/special formats not exhaustively reviewed. |
| DO | [Dominican Republic](https://en.wikipedia.org/w/index.php?oldid=1338002026) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 1 | 0 | Ordinary scheme described by vehicle type; full historical coverage not established. |
| DZ | [Algeria](https://en.wikipedia.org/w/index.php?oldid=1376724844) | usable_now | province | last two digits | ordinary; exceptions described in notes (? to ?) | 69 / 70 | 0 | Classification describes the cited series; special and personalised series need separate handling. |
| EC | [Ecuador](https://en.wikipedia.org/w/index.php?oldid=1338002030) | usable_now | province | first letter | ordinary; exceptions described in notes (? to ?) | 24 / 24 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| EE | [Estonia](https://en.wikipedia.org/w/index.php?oldid=1338002750) | historic_only | registration_office | first of three letters | ordinary; exceptions described in notes (? to 2019) | 0 / 11 | 1 | Source contradicts itself: introduction says ended 2013; history says random since August 2019. |
| EG | [Egypt](https://en.wikipedia.org/w/index.php?oldid=1338002725) | usable_now | governorate | letter component; Cairo/Giza also digit count | ordinary; exceptions described in notes (? to ?) | 0 / 1 | 0 | Arabic letter codes and variable formats require script-aware handling. |
| EH | [Western Sahara](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| ER | [Eritrea](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| ES | [Spain](https://en.wikipedia.org/w/index.php?oldid=1363970679) | historic_only | province | leading province letters | ordinary; exceptions described in notes (? to 2000-09) | 0 / 74 | 2 | National series since September 2000. |
| ET | [Ethiopia](https://fr.wikipedia.org/w/index.php?oldid=205195458) | unverified | region | letter group | ordinary; see notes (? to ?) | 0 / 2 | 0 | French source describes regional plates; Ethiopian 2026 national redesign is not reconciled. Codes retained with unknown validity, not asserted current. |
| FI | [Finland](https://en.wikipedia.org/w/index.php?oldid=1367179902) | historic_only | province | first letter | ordinary; exceptions described in notes (? to 1989) | 0 / 3 | 1 | Åland has a separate territorial series. |
| FJ | [Fiji](https://en.wikipedia.org/w/index.php?oldid=1341979193) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| FK | [Falkland Islands](https://en.wikipedia.org/w/index.php?oldid=1345582883) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 0 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| FM | [Micronesia](https://en.wikipedia.org/w/index.php?oldid=1338003034) | printed_not_encoded | state | printed state name | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | Plate table shows state names/designs; no serial-based state coding established. |
| FO | [Faroe Islands](https://en.wikipedia.org/w/index.php?oldid=1338668056) | none | — | — | ordinary; see notes (? to ?) | 0 / 0 | 0 | No subnational component in the described ordinary series. This is a series-level inference; historical and special exceptions have not been exhausted. |
| FR | [France](https://en.wikipedia.org/w/index.php?oldid=1360313366) | historic_only | department | historic final department digits | ordinary; exceptions described in notes (? to 2009) | 0 / 621 | 1 | Current SIV number is national; freely chosen printed territorial identifier is not proof of registration location. |
| GA | [Gabon](https://en.wikipedia.org/w/index.php?oldid=1338002796) | historic_only | region | digit after G in old series | ordinary; exceptions described in notes (? to 2013) | 0 / 0 | 1 | Current provincial coding not established from fetched evidence. |
| GB | [UK](https://en.wikipedia.org/w/index.php?oldid=1375613060) | usable_now | registration_office | first two letters for Great Britain since 2001 | ordinary; exceptions described in notes (? to ?) | 434 / 554 | 1 | Northern Ireland and pre-2001 systems differ; private transfers break geographic attribution. |
| GD | [Grenada](https://en.wikipedia.org/w/index.php?oldid=1338002829) | none | — | — | ordinary; see notes (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary series. This is a series-level inference; historical and special exceptions have not been exhausted. |
| GE | [Georgia](https://en.wikipedia.org/w/index.php?oldid=1372335903) | historic_only | region | first letter in former series | ordinary; see exceptions (? to ?) | 0 / 20 | 1 | Geographic allocation removed in 2004 per cited revision; 2014 series national. Abkhazia and South Ossetia have parallel schemes, not collected. |
| GF | [French Guiana](https://fr.wikipedia.org/w/index.php?oldid=238942028) | printed_not_encoded | department_or_territory | optional identity band; no place in SIV serial | current SIV; historic territorial series incompletely surveyed (? to ?) | 0 / 0 | 1 | Current SIV has no encoded registration area; the chosen department band does not establish residence. Historic FNI or local territorial numbering needs separate interpretation and is not fully collected here. |
| GG | [Guernsey](https://en.wikipedia.org/w/index.php?oldid=1350805077) | usable_now | island | AY prefix for Alderney | ordinary; see exceptions (? to ?) | 1 / 1 | 1 | Ordinary Guernsey numeric serials give no parish; AY identifies Alderney within the bailiwick. |
| GH | [Ghana](https://en.wikipedia.org/w/index.php?oldid=1338002819) | usable_now | region | letter prefix | ordinary; exceptions described in notes (? to ?) | 35 / 35 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| GI | [Gibraltar](https://en.wikipedia.org/w/index.php?oldid=1349341906) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 0 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| GL | [Greenland](https://en.wikipedia.org/w/index.php?oldid=1338668056) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| GM | [Gambia](https://en.wikipedia.org/w/index.php?oldid=1338002798) | usable_now | region | initial two or three letters | ordinary; see exceptions (? to ?) | 7 / 12 | 1 | Inference applies to the described ordinary series; complete historical coverage is not established. |
| GN | [Guinea](https://en.wikipedia.org/w/index.php?oldid=1377835056) | usable_now | region | last two digits since 2021; prefix letters in older series | ordinary; exceptions described in notes (? to ?) | 8 / 9 | 0 | Numeric regional suffix since 2021; cited table has eight numeric regions but only one historical letter mapping. |
| GP | [Guadeloupe](https://fr.wikipedia.org/w/index.php?oldid=238942028) | printed_not_encoded | department_or_territory | optional identity band; no place in SIV serial | current SIV; historic territorial series incompletely surveyed (? to ?) | 0 / 0 | 1 | Current SIV has no encoded registration area; the chosen department band does not establish residence. Historic FNI or local territorial numbering needs separate interpretation and is not fully collected here. |
| GQ | [Equatorial Guinea](https://en.wikipedia.org/w/index.php?oldid=1338002738) | usable_now | region | first two letters | ordinary; exceptions described in notes (? to ?) | 7 / 7 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| GR | [Greece](https://en.wikipedia.org/w/index.php?oldid=1367180219) | usable_now | prefecture | first one or two letters | ordinary; exceptions described in notes (? to ?) | 0 / 310 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| GS | [South Georgia & South Sandwich Islands](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| GT | [Guatemala](https://en.wikipedia.org/w/index.php?oldid=1347696568) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| GU | [Guam](https://en.wikipedia.org/w/index.php?oldid=1366265234) | usable_now | municipality | two-letter prefix | ordinary; exceptions described in notes (? to ?) | 42 / 42 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| GW | [Guinea-Bissau](https://de.wikipedia.org/w/index.php?oldid=264340455) | usable_now | region | first two letters | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | Inference applies to the described ordinary series; complete historical coverage is not established. |
| GY | [Guyana](https://en.wikipedia.org/w/index.php?oldid=1376645220) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 0 | No subnational component in the described ordinary series; historical/special formats not exhaustively reviewed. |
| HK | [Hong Kong](https://en.wikipedia.org/w/index.php?oldid=1374661832) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| HM | [Heard & McDonald Islands](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| HN | [Honduras](https://en.wikipedia.org/w/index.php?oldid=1338002850) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 0 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| HR | [Croatia](https://en.wikipedia.org/w/index.php?oldid=1375714451) | usable_now | city | first two letters | ordinary; exceptions described in notes (? to ?) | 34 / 39 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| HT | [Haiti](https://en.wikipedia.org/w/index.php?oldid=1338002849) | printed_not_encoded | region | region printed at bottom | ordinary; exceptions described in notes (? to ?) | 0 / 1 | 0 | Evidence is historical; current geography cannot be inferred from the number. |
| HU | [Hungary](https://en.wikipedia.org/w/index.php?oldid=1372826697) | historic_only | district | historic leading district code | ordinary; exceptions described in notes (? to 1933) | 0 / 0 | 1 | Proposed regional scheme was not adopted in 2022. |
| ID | [Indonesia](https://en.wikipedia.org/w/index.php?oldid=1375240023) | usable_now | registration_area | first one or two letters | ordinary; exceptions described in notes (? to ?) | 61 / 62 | 1 | Region boundaries reflect older divisions; suffix letters can refine locality and are not fully collected. |
| IE | [Ireland](https://en.wikipedia.org/w/index.php?oldid=1375357170) | usable_now | county | middle letter group after year | ordinary; exceptions described in notes (? to ?) | 26 / 103 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| IL | [Israel](https://en.wikipedia.org/w/index.php?oldid=1374923846) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| IM | [Isle of Man](https://en.wikipedia.org/w/index.php?oldid=1352659370) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 0 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| IN | [India](https://en.wikipedia.org/w/index.php?oldid=1372866191) | usable_now | state_and_registration_office | first two letters plus one/two digits | ordinary; exceptions described in notes (? to ?) | 1320 / 1545 | 1 | BH nationwide, diplomatic and military series are excluded; some state codes are statewide and Delhi/suboffice formats vary. |
| IO | [British Indian Ocean Territory](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| IQ | [Iraq](https://en.wikipedia.org/w/index.php?oldid=1338002866) | usable_now | governorate | numeric governorate group | ordinary; exceptions described in notes (? to ?) | 19 / 19 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| IR | [Iran](https://en.wikipedia.org/w/index.php?oldid=1353798607) | usable_now | province | two digits at right; letter may refine county | ordinary; exceptions described in notes (? to ?) | 87 / 91 | 1 | Persian digit strings retained; province coverage collected, county/letter intersections incomplete. |
| IS | [Iceland](https://en.wikipedia.org/w/index.php?oldid=1371704297) | historic_only | district | historic letter prefix | ordinary; exceptions described in notes (? to 1988-12-31) | 0 / 0 | 1 | Current ordinary serials have no geographic coding. |
| IT | [Italy](https://en.wikipedia.org/w/index.php?oldid=1376348433) | historic_only | province | historic province prefix/suffix | ordinary; exceptions described in notes (? to 1994) | 0 / 199 | 2 | Since 1994 serial is national; optional province band is not encoded in current number. Some province abbreviations postdate 1994; see code-row caveat. |
| JE | [Jersey](https://en.wikipedia.org/w/index.php?oldid=1242049100) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary series; historical/special formats not exhaustively reviewed. |
| JM | [Jamaica](https://en.wikipedia.org/w/index.php?oldid=1338002878) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 1 | 1 | No subnational component in the described ordinary series; historical/special formats not exhaustively reviewed. |
| JO | [Jordan](https://en.wikipedia.org/w/index.php?oldid=1338002897) | usable_now | free_trade_zone | AQ prefix in special zone series; ordinary numeric prefixes denote class | 2025 special Aqaba series (2025-08 to ?) | 1 / 1 | 0 | Special Aqaba Free Trade Zone plates encode a place. Ordinary numeric series identify vehicle category, not district; nationwide series must not be geocoded. |
| JP | [Japan](https://en.wikipedia.org/w/index.php?oldid=1375974707) | usable_now | registration_office | Japanese marking before class number | ordinary; exceptions described in notes (? to ?) | 138 / 199 | 1 | Includes named regional marks; full plate examples are source specimens, not confirmed live vehicles. |
| KE | [Kenya](https://en.wikipedia.org/w/index.php?oldid=1376439213) | historic_only | registration_district | historic letter after K | ordinary; exceptions described in notes (? to 1984) | 0 / 0 | 0 | Current regular plates are national sequences. |
| KG | [Kyrgyzstan](https://en.wikipedia.org/w/index.php?oldid=1356365785) | usable_now | province | first two digits | ordinary; exceptions described in notes (? to ?) | 11 / 33 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| KH | [Cambodia](https://en.wikipedia.org/w/index.php?oldid=1357532292) | printed_not_encoded | province | province name above/below serial | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 0 | Classification describes the cited series; special and personalised series need separate handling. |
| KI | [Kiribati](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 1 | No reviewed classification evidence; do not infer absence of geographic coding. |
| KM | [Comoros](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 1 | No reviewed classification evidence; do not infer absence of geographic coding. |
| KN | [St. Kitts & Nevis](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| KP | [North Korea](https://en.wikipedia.org/w/index.php?oldid=1376565406) | usable_now | province_or_city | Korean name at start | ordinary; exceptions described in notes (? to ?) | 13 / 13 | 0 | Source reliability and current administrative changes unverified. |
| KR | [South Korea](https://en.wikipedia.org/w/index.php?oldid=1376656300) | historic_only | province_or_city | old name on upper line | ordinary; exceptions described in notes (? to 2004) | 0 / 0 | 0 | Ordinary private plates lost province names in 2004; commercial exceptions not fully reviewed. |
| KW | [Kuwait](https://en.wikipedia.org/w/index.php?oldid=1366902172) | none | — | — | ordinary; see notes (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary series. This is a series-level inference; historical and special exceptions have not been exhausted. |
| KY | [Cayman Islands](https://en.wikipedia.org/w/index.php?oldid=1338001949) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 0 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| KZ | [Kazakhstan](https://en.wikipedia.org/w/index.php?oldid=1375818980) | usable_now | region | two digits at right | ordinary; exceptions described in notes (? to ?) | 20 / 69 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| LA | [Laos](https://en.wikipedia.org/w/index.php?oldid=1338002945) | printed_not_encoded | province | name above serial | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 0 | Classification describes the cited series; special and personalised series need separate handling. |
| LB | [Lebanon](https://en.wikipedia.org/w/index.php?oldid=1353201548) | usable_now | registration_area | Latin letter | ordinary; exceptions described in notes (? to ?) | 15 / 15 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| LC | [St. Lucia](https://en.wikipedia.org/w/index.php?oldid=1376852335) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 0 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| LI | [Liechtenstein](https://en.wikipedia.org/w/index.php?oldid=1375193249) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| LK | [Sri Lanka](https://en.wikipedia.org/w/index.php?oldid=1377836403) | unverified | province | former province letters | ordinary; see exceptions (? to ?) | 0 / 9 | 0 | Fetched Wikipedia may lag the reported 2023 removal of provincial letters; current validity unresolved. |
| LR | [Liberia](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| LS | [Lesotho](https://pl.wikipedia.org/w/index.php?oldid=77488766) | usable_now | district | first letter | ordinary; see notes (? to ?) | 10 / 28 | 0 | Polish list explicitly describes current district letters; English page only gives older two-letter codes. Both generations retained. |
| LT | [Lithuania](https://en.wikipedia.org/w/index.php?oldid=1367983335) | historic_only | county | second letter of three | ordinary; exceptions described in notes (? to 2004) | 0 / 11 | 2 | Current serial has no regional code. |
| LU | [Luxembourg](https://en.wikipedia.org/w/index.php?oldid=1367984246) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| LV | [Latvia](https://en.wikipedia.org/w/index.php?oldid=1367304934) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 1 | 1 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| LY | [Libya](https://en.wikipedia.org/w/index.php?oldid=1349342004) | usable_now | municipality | first one or two digits | ordinary; exceptions described in notes (? to ?) | 62 / 63 | 0 | Classification describes the cited series; special and personalised series need separate handling. |
| MA | [Morocco](https://en.wikipedia.org/w/index.php?oldid=1368833711) | usable_now | registration_area | rightmost one or two digits | ordinary; see exceptions (? to ?) | 89 / 90 | 0 | Inference applies to the described ordinary series; complete historical coverage is not established. |
| MC | [Monaco](https://en.wikipedia.org/w/index.php?oldid=1371826222) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 0 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| MD | [Moldova](https://en.wikipedia.org/w/index.php?oldid=1369300318) | historic_only | region | first one/two letters before 2015 | ordinary; exceptions described in notes (? to 2015) | 0 / 60 | 2 | Transnistrian series differs and remains a separate coverage gap. |
| ME | [Montenegro](https://en.wikipedia.org/w/index.php?oldid=1367985939) | usable_now | municipality | first two letters | ordinary; exceptions described in notes (? to ?) | 25 / 26 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| MF | [St. Martin](https://en.wikipedia.org/w/index.php?oldid=1338002783) | historic_only | former_department | historic departmental suffix; current serial nationwide within territory | pre-2009 Guadeloupe-linked; modern local serial (? to 2009) | 0 / 0 | 0 | Old 97-1 refers to the former Guadeloupe grouping, not a unique locality in present Saint Martin. Current local serial has no reviewed internal geographic split. |
| MG | [Madagascar](https://en.wikipedia.org/w/index.php?oldid=1368901238) | usable_now | province | first letter after numeric serial | ordinary; exceptions described in notes (? to ?) | 6 / 6 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| MH | [Marshall Islands](https://en.wikipedia.org/w/index.php?oldid=1338003012) | printed_not_encoded | atoll | printed MAJURO ATOLL | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | Fetched examples show atoll name outside numeric serial; other islands need review. |
| MK | [North Macedonia](https://en.wikipedia.org/w/index.php?oldid=1344572551) | usable_now | municipality | first two letters | ordinary; exceptions described in notes (? to ?) | 34 / 38 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| ML | [Mali](https://fr.wikipedia.org/w/index.php?oldid=235672767) | usable_now | region_and_circle | separate region abbreviation and circle/arrondissement number | ordinary; see notes (? to ?) | 20 / 20 | 0 | 2023/2024 series. Region abbreviations collected; circle-number mapping remains a gap. |
| MM | [Myanmar](https://en.wikipedia.org/w/index.php?oldid=1377004889) | usable_now | region_and_township | regional code and township numeral above serial | ordinary; exceptions described in notes (? to ?) | 15 / 15 | 0 | Classification describes the cited series; special and personalised series need separate handling. |
| MN | [Mongolia](https://en.wikipedia.org/w/index.php?oldid=1376727365) | usable_now | province_or_district | first two letters of suffix | ordinary; exceptions described in notes (? to ?) | 29 / 29 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| MO | [Macao](https://en.wikipedia.org/w/index.php?oldid=1377063034) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| MP | [Northern Mariana Islands](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| MQ | [Martinique](https://fr.wikipedia.org/w/index.php?oldid=238942028) | printed_not_encoded | department_or_territory | optional identity band; no place in SIV serial | current SIV; historic territorial series incompletely surveyed (? to ?) | 0 / 0 | 1 | Current SIV has no encoded registration area; the chosen department band does not establish residence. Historic FNI or local territorial numbering needs separate interpretation and is not fully collected here. |
| MR | [Mauritania](https://en.wikipedia.org/w/index.php?oldid=1338003015) | usable_now | region | final two-digit group | ordinary (? to ?) | 13 / 13 | 0 | Special series require separate handling; current completeness must be established against a dated registry. |
| MS | [Montserrat](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| MT | [Malta](https://en.wikipedia.org/w/index.php?oldid=1367984289) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| MU | [Mauritius](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| MV | [Maldives](https://en.wikipedia.org/w/index.php?oldid=1345469488) | none | — | — | ordinary; see notes (? to ?) | 0 / 0 | 0 | No subnational component in the described ordinary series. This is a series-level inference; historical and special exceptions have not been exhausted. |
| MW | [Malawi](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| MX | [Mexico](https://en.wikipedia.org/w/index.php?oldid=1368484692) | unverified | state | allocated letter blocks | ordinary; see exceptions (? to ?) | 0 / 17075 | 0 | Source gives 1992 state allocation ranges; their applicability to current ordinary plates is unverified. Do not equate numbering-scheme IDs with serial characters. |
| MY | [Malaysia](https://en.wikipedia.org/w/index.php?oldid=1377349409) | usable_now | state_or_division | leading one/two letters; Sarawak and Sabah vary | ordinary; exceptions described in notes (? to ?) | 29 / 54 | 2 | Special, commemorative and tendered series may be nationwide; K/V/W and East Malaysian generations need series-specific rules. |
| MZ | [Mozambique](https://en.wikipedia.org/w/index.php?oldid=1338003047) | usable_now | province | last two letters | ordinary; exceptions described in notes (? to ?) | 11 / 11 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| NA | [Namibia](https://en.wikipedia.org/w/index.php?oldid=1353001290) | usable_now | town_or_region | last one or two letters | ordinary; exceptions described in notes (? to ?) | 43 / 70 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| NC | [New Caledonia](https://en.wikipedia.org/w/index.php?oldid=1338002775) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary series; historical/special formats not exhaustively reviewed. |
| NE | [Niger](https://en.wikipedia.org/w/index.php?oldid=1374194988) | usable_now | region | first digit | ordinary; exceptions described in notes (? to ?) | 8 / 8 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| NF | [Norfolk Island](https://en.wikipedia.org/w/index.php?oldid=1302829805) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 0 | No subnational component in the described ordinary series; historical/special formats not exhaustively reviewed. |
| NG | [Nigeria](https://en.wikipedia.org/w/index.php?oldid=1358193040) | usable_now | local_government_area | first three letters | ordinary; exceptions described in notes (? to ?) | 0 / 7 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| NI | [Nicaragua](https://en.wikipedia.org/w/index.php?oldid=1338003071) | usable_now | region | first one or two letters | ordinary; exceptions described in notes (? to ?) | 0 / 11 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| NL | [Netherlands](https://en.wikipedia.org/w/index.php?oldid=1377707144) | historic_only | province | old leading letters | ordinary; exceptions described in notes (? to 1951) | 0 / 17 | 1 | Modern national serials have no place code; historical provincial system ended in 1951. |
| NO | [Norway](https://en.wikipedia.org/w/index.php?oldid=1375361487) | usable_now | registration_office | first two letters | ordinary; exceptions described in notes (? to ?) | 404 / 404 | 1 | Nationwide EV, hydrogen, gas and diplomatic prefixes must be excluded. |
| NP | [Nepal](https://en.wikipedia.org/w/index.php?oldid=1338003064) | usable_now | province | province name/number at start | ordinary; exceptions described in notes (? to ?) | 0 / 1 | 0 | Historic zone scripts and transition to embossed province plates are not exhaustively covered. |
| NR | [Nauru](https://en.wikipedia.org/w/index.php?oldid=1338003058) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary series; historical/special formats not exhaustively reviewed. |
| NU | [Niue](https://en.wikipedia.org/w/index.php?oldid=1338003086) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary series; historical/special formats not exhaustively reviewed. |
| NZ | [New Zealand](https://en.wikipedia.org/w/index.php?oldid=1372963488) | historic_only | region | historic allocation blocks | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 0 | Historic batch correlations are not current geographic guarantees; incomplete historical table. |
| OM | [Oman](https://en.wikipedia.org/w/index.php?oldid=1365425002) | historic_only | district | historic trailing letters | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | Current ordinary region inference not established. |
| PA | [Panama](https://en.wikipedia.org/w/index.php?oldid=1375336244) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| PE | [Peru](https://en.wikipedia.org/w/index.php?oldid=1349342190) | usable_now | registration_zone | leading letter in current series | ordinary; exceptions described in notes (? to ?) | 25 / 26 | 1 | Source mixes historic regional codes and newer allocation; current extraction requires further review. |
| PF | [French Polynesia](https://en.wikipedia.org/w/index.php?oldid=1338002770) | none | — | — | ordinary; see notes (? to ?) | 0 / 0 | 0 | No subnational component in the described ordinary series. This is a series-level inference; historical and special exceptions have not been exhausted. |
| PG | [Papua New Guinea](https://en.wikipedia.org/w/index.php?oldid=1375335304) | usable_now | province | first letter | ordinary; exceptions described in notes (? to ?) | 21 / 21 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| PH | [Philippines](https://en.wikipedia.org/w/index.php?oldid=1375973749) | usable_now | region | first letter (position varies for motorcycles) | ordinary; exceptions described in notes (? to ?) | 26 / 26 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| PK | [Pakistan](https://en.wikipedia.org/w/index.php?oldid=1375579015) | printed_not_encoded | province_or_territory | printed province and design | ordinary; exceptions described in notes (? to ?) | 0 / 5 | 1 | Current district-prefix validity not established; Punjab has changed allocation systems. Treat WD codes as undated evidence. |
| PL | [Poland](https://en.wikipedia.org/w/index.php?oldid=1376479133) | usable_now | district_or_city | first two or three letters | ordinary (? to ?) | 690 / 717 | 1 | Special series require separate handling; current completeness must be established against a dated registry. |
| PM | [St. Pierre & Miquelon](https://en.wikipedia.org/w/index.php?oldid=1375947292) | none | none | none; SPM denotes the territory as a whole | ordinary since 2000 (2000 to ?) | 0 / 0 | 1 | The national/territorial prefix does not distinguish the islands. Earlier SPM suffix also denotes the territory as a whole. |
| PN | [Pitcairn](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| PR | [Puerto Rico](https://en.wikipedia.org/w/index.php?oldid=1377653126) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| PS | [Palestine](https://en.wikipedia.org/w/index.php?oldid=1374923642) | usable_now | governorate | last letter in West Bank; old initial digit | ordinary; see exceptions (? to ?) | 13 / 21 | 1 | Separate West Bank and Gaza systems; source includes reserved unimplemented Gaza letters which are excluded. |
| PT | [Portugal](https://en.wikipedia.org/w/index.php?oldid=1368649490) | usable_now | registration_office | trailer prefix | ordinary; exceptions described in notes (? to ?) | 0 / 1 | 0 | Ordinary cars have national sequences; geography applies to trailers/export series only. |
| PW | [Palau](https://en.wikipedia.org/w/index.php?oldid=1338003244) | printed_not_encoded | state | printed state name | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 0 | Printed-state evidence from plate designs; current serial encoding not established. |
| PY | [Paraguay](https://en.wikipedia.org/w/index.php?oldid=1359377651) | historic_only | department | letter in 1982–2000 series | ordinary; see exceptions (? to ?) | 0 / 0 | 0 | Inference applies to the described ordinary series; complete historical coverage is not established. |
| QA | [Qatar](https://en.wikipedia.org/w/index.php?oldid=1365424249) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| RE | [Réunion](https://fr.wikipedia.org/w/index.php?oldid=238942028) | printed_not_encoded | department_or_territory | optional identity band; no place in SIV serial | current SIV; historic territorial series incompletely surveyed (? to ?) | 0 / 0 | 1 | Current SIV has no encoded registration area; the chosen department band does not establish residence. Historic FNI or local territorial numbering needs separate interpretation and is not fully collected here. |
| RO | [Romania](https://en.wikipedia.org/w/index.php?oldid=1367060445) | usable_now | county | first one or two letters | ordinary; exceptions described in notes (? to ?) | 42 / 63 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| RS | [Serbia](https://en.wikipedia.org/w/index.php?oldid=1371473039) | usable_now | registration_area | first two letters | ordinary; exceptions described in notes (? to ?) | 74 / 78 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| RU | [Russia](https://en.wikipedia.org/w/index.php?oldid=1362238492) | usable_now | federal_subject | right-hand two or three digits | ordinary; exceptions described in notes (? to ?) | 161 / 193 | 1 | Preserve disputed/occupied-territory claims as source assignments, not sovereignty assertions; obsolete reused codes need dates. |
| RW | [Rwanda](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| SA | [Saudi Arabia](https://en.wikipedia.org/w/index.php?oldid=1352834674) | none | — | — | ordinary; see notes (? to ?) | 0 / 0 | 0 | No subnational component in the described ordinary series. This is a series-level inference; historical and special exceptions have not been exhausted. |
| SB | [Solomon Islands](https://en.wikipedia.org/w/index.php?oldid=1338003337) | none | none | none; sequential series | ordinary 2014 series (2014 to ?) | 0 / 0 | 1 | Inference from the described sequential ordinary series. No assertion about every former series. |
| SC | [Seychelles](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| SD | [Sudan](https://en.wikipedia.org/w/index.php?oldid=1338003367) | usable_now | state | letter group | ordinary; exceptions described in notes (? to ?) | 2 / 2 | 0 | Classification describes the cited series; special and personalised series need separate handling. |
| SE | [Sweden](https://en.wikipedia.org/w/index.php?oldid=1366420734) | historic_only | county | historic letter prefix | ordinary; exceptions described in notes (? to 1973) | 0 / 42 | 2 | Current national combination has no geographic connection; pre-1973 county system retained. |
| SG | [Singapore](https://en.wikipedia.org/w/index.php?oldid=1374924505) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 0 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| SH | [St. Helena](https://en.wikipedia.org/w/index.php?oldid=1345582883) | usable_now | island | A for Ascension; TDC for Tristan | ordinary; see notes (? to ?) | 1 / 1 | 0 | Saint Helena itself uses a numeric ordinary serial; prefixes distinguish other islands in the territory. |
| SI | [Slovenia](https://en.wikipedia.org/w/index.php?oldid=1349122519) | usable_now | registration_region | first two letters | ordinary; exceptions described in notes (? to ?) | 11 / 11 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| SJ | [Svalbard & Jan Mayen](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| SK | [Slovakia](https://en.wikipedia.org/w/index.php?oldid=1371504047) | historic_only | district | first two letters before 2023 | ordinary; exceptions described in notes (? to 2022) | 0 / 98 | 2 | Same visual format now uses arbitrary letters; date is needed to interpret old district codes. |
| SL | [Sierra Leone](https://de.wikipedia.org/w/index.php?oldid=260758379) | usable_now | registration_office | two-letter right-hand group | ordinary; see exceptions (? to ?) | 0 / 0 | 0 | Source describes office code above PR/COM at right; code list not acquired. |
| SM | [San Marino](https://en.wikipedia.org/w/index.php?oldid=1365288456) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary series; historical/special formats not exhaustively reviewed. |
| SN | [Senegal](https://en.wikipedia.org/w/index.php?oldid=1338003309) | usable_now | region | separate regional group since 2019; prefix previously | ordinary; see exceptions (? to ?) | 14 / 14 | 0 | Current regional identifier is separate from the seven-character national serial; department suffix codes not collected. |
| SO | [Somalia](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| SR | [Suriname](https://en.wikipedia.org/w/index.php?oldid=1338003369) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| SS | [South Sudan](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| ST | [São Tomé & Príncipe](https://en.wikipedia.org/w/index.php?oldid=1338003303) | none | none | none; STP is the national prefix | ordinary serial (? to ?) | 0 / 0 | 1 | Source describes a common national prefix and serial; no subnational geography evidenced. Historic exceptions not exhaustively surveyed. |
| SV | [El Salvador](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| SX | [Sint Maarten](https://en.wikipedia.org/w/index.php?oldid=1338003322) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| SY | [Syria](https://en.wikipedia.org/w/index.php?oldid=1369673122) | usable_now | region_or_district | three-letter Kurdish code in AANES plates | ordinary; see exceptions (? to ?) | 9 / 23 | 0 | Parallel de facto series; current transitional-government numbering is a gap. Assignments do not imply sovereignty. |
| SZ | [Eswatini](https://en.wikipedia.org/w/index.php?oldid=1338002752) | usable_now | region | final letter | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 0 | Classification describes the cited series; special and personalised series need separate handling. |
| TC | [Turks & Caicos Islands](https://en.wikipedia.org/w/index.php?oldid=1338003430) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 0 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| TD | [Chad](https://en.wikipedia.org/w/index.php?oldid=1376836896) | usable_now | region | first two digits | ordinary; exceptions described in notes (? to ?) | 22 / 22 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| TF | [French Southern Territories](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| TG | [Togo](https://en.wikipedia.org/w/index.php?oldid=1338003392) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary series; historical/special formats not exhaustively reviewed. |
| TH | [Thailand](https://de.wikipedia.org/w/index.php?oldid=253048778) | usable_now | province | numeric group above truck/bus serial | ordinary; see exceptions (? to ?) | 78 / 78 | 1 | Ordinary car serials do not encode province; province name is printed below. Numeric province code applies to trucks/buses and international plates, not ordinary car serials. Complete code list remains a gap. |
| TJ | [Tajikistan](https://en.wikipedia.org/w/index.php?oldid=1350953028) | usable_now | region | two-digit suffix | ordinary; exceptions described in notes (? to ?) | 8 / 27 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| TK | [Tokelau](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| TL | [Timor-Leste](https://en.wikipedia.org/w/index.php?oldid=1340753182) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 0 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| TM | [Turkmenistan](https://en.wikipedia.org/w/index.php?oldid=1376735676) | usable_now | province | two-letter suffix | ordinary; exceptions described in notes (? to ?) | 7 / 13 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| TN | [Tunisia](https://en.wikipedia.org/w/index.php?oldid=1372898331) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 1 | 0 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| TO | [Tonga](https://en.wikipedia.org/w/index.php?oldid=1338003394) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary series; historical/special formats not exhaustively reviewed. |
| TR | [Türkiye](https://en.wikipedia.org/w/index.php?oldid=1359024284) | usable_now | province | first two digits | ordinary (? to ?) | 81 / 81 | 1 | Special series require separate handling; current completeness must be established against a dated registry. |
| TT | [Trinidad & Tobago](https://en.wikipedia.org/w/index.php?oldid=1376191684) | none | none | none; leading letter denotes vehicle class | ordinary serial (? to ?) | 0 / 0 | 1 | Ordinary prefixes identify vehicle class; remaining letters advance as serials. Historic exceptions not exhaustively surveyed. |
| TV | [Tuvalu](https://en.wikipedia.org/w/index.php?oldid=1338003435) | none | — | — | ordinary; see notes (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary series. This is a series-level inference; historical and special exceptions have not been exhausted. |
| TW | [Taiwan](https://en.wikipedia.org/w/index.php?oldid=1367199647) | unverified | jurisdiction | allocated letter combinations | ordinary; see exceptions (? to ?) | 0 / 0 | 0 | Source allocation table does not establish applicability to current issues; printed jurisdiction removed in 2007. |
| TZ | [Tanzania](https://en.wikipedia.org/w/index.php?oldid=1338003384) | historic_only | city | historic leading letters | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | Current mainland and Zanzibar schemes differ; subnational place-code coverage incomplete. |
| UA | [Ukraine](https://en.wikipedia.org/w/index.php?oldid=1370202866) | usable_now | oblast | first two letters | ordinary; exceptions described in notes (? to ?) | 110 / 268 | 1 | Newer online/electronic registration prefixes can be nationwide; retain historical numeric and Cyrillic suffix series separately. |
| UG | [Uganda](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| UM | [U.S. Outlying Islands](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| US | [US](https://en.wikipedia.org/w/index.php?oldid=1377655306) | usable_now | county_in_some_states | state-specific county prefix; state printed separately | ordinary; exceptions described in notes (? to ?) | 43 / 83 | 1 | Most plates require printed state. Some states encode counties (e.g. Idaho, Hawaii); no nationwide state code, state-specific extraction is a gap. |
| UY | [Uruguay](https://en.wikipedia.org/w/index.php?oldid=1341501926) | usable_now | department | first letter | ordinary (? to ?) | 19 / 21 | 0 | Special series require separate handling; current completeness must be established against a dated registry. |
| UZ | [Uzbekistan](https://en.wikipedia.org/w/index.php?oldid=1356025945) | usable_now | region | first two digits | ordinary; exceptions described in notes (? to ?) | 14 / 26 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| VA | [Vatican City](https://en.wikipedia.org/w/index.php?oldid=1338003465) | none | — | — | ordinary; exceptions described in notes (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary series; historical/special formats not exhaustively reviewed. |
| VC | [St. Vincent & Grenadines](https://en.wikipedia.org/w/index.php?oldid=1338003294) | none | — | — | ordinary; see notes (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary series. This is a series-level inference; historical and special exceptions have not been exhausted. |
| VE | [Venezuela](https://en.wikipedia.org/w/index.php?oldid=1338003469) | usable_now | state | last letter | ordinary; exceptions described in notes (? to ?) | 24 / 24 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| VG | [British Virgin Islands](https://en.wikipedia.org/w/index.php?oldid=1338001878) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| VI | [U.S. Virgin Islands](https://en.wikipedia.org/w/index.php?oldid=1321235066) | usable_now | island | initial letter | ordinary; exceptions described in notes (? to ?) | 1 / 3 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| VN | [Vietnam](https://en.wikipedia.org/w/index.php?oldid=1369462169) | usable_now | province | first two digits | ordinary; exceptions described in notes (? to ?) | 80 / 83 | 1 | 2025 provincial mergers retain former codes, so old/new province associations need dates. |
| VU | [Vanuatu](https://en.wikipedia.org/w/index.php?oldid=1338003464) | none | — | — | ordinary; see notes (? to ?) | 0 / 0 | 0 | No subnational component in the described ordinary series. This is a series-level inference; historical and special exceptions have not been exhausted. |
| WF | [Wallis & Futuna](https://en.wikipedia.org/w/index.php?oldid=1359837463) | none | — | — | ordinary; see notes (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary series. This is a series-level inference; historical and special exceptions have not been exhausted. |
| WS | [Samoa](https://en.wikipedia.org/w/index.php?oldid=1338003299) | none | — | — | ordinary; see exceptions (? to ?) | 0 / 0 | 1 | No subnational component in the described ordinary serial. This is a series-level inference; earlier and special systems may differ. |
| XK | [Kosovo](https://en.wikipedia.org/w/index.php?oldid=1368693154) | usable_now | district | first two digits | ordinary; exceptions described in notes (? to ?) | 7 / 7 | 1 | Classification describes the cited series; special and personalised series need separate handling. |
| YE | [Yemen](https://en.wikipedia.org/w/index.php?oldid=1343643680) | usable_now | governorate | numeric governorate group | ordinary; exceptions described in notes (? to ?) | 0 / 22 | 0 | Multiple parallel de facto systems; geographic and temporal scope must be retained. |
| YT | [Mayotte](https://fr.wikipedia.org/w/index.php?oldid=238942028) | printed_not_encoded | department_or_territory | optional identity band; no place in SIV serial | current SIV; historic territorial series incompletely surveyed (? to ?) | 0 / 0 | 1 | Current SIV has no encoded registration area; the chosen department band does not establish residence. Historic FNI or local territorial numbering needs separate interpretation and is not fully collected here. |
| ZA | [South Africa](https://en.wikipedia.org/w/index.php?oldid=1374562098) | usable_now | province_or_registration_area | province suffix or Western Cape prefix | ordinary; exceptions described in notes (? to ?) | 48 / 391 | 0 | KwaZulu-Natal switched to province-wide numbering; older local prefixes retained as historic. |
| ZM | [Zambia](https://raw.githubusercontent.com/datasets/country-codes/2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1/data/country-codes.csv) | unverified | — | — | unknown (? to ?) | 0 / 0 | 0 | No reviewed classification evidence; do not infer absence of geographic coding. |
| ZW | [Zimbabwe](https://en.wikipedia.org/w/index.php?oldid=1340353174) | historic_only | city | historic letter prefix | ordinary; see notes (? to ?) | 0 / 0 | 0 | Modern three-letter/four-digit series has no reviewed geographic allocation; historical Rhodesian schemes incomplete. |

## Reproducible cross-checks

The table compares current code sets when both sources classify current series. Values unique to a source are retained, not silently resolved. Different scopes, withdrawn codes, script variants and office/city names can explain differences. These are not all confirmed factual conflicts. The verification report (`data/normalized/plates/verification.json`, untracked workspace file) contains the complete differing code lists, all-period comparisons (including Wikidata), per-source counts, and completeness checks. Place-name equivalence and overlapping geographic claims remain unadjudicated; consumers must retain the source of each association.

| Country | Left source | Right source | Shared | Left only | Right only |
| --- | --- | --- | --- | --- | --- |
| GB | gb-inf104.pdf | wiki-GB.json | 411 | 22 | 1 |
| ID | wiki-ID-local.json | wiki-ID.json | 61 | 0 | 0 |
| IR | wiki-IR-local.json | wiki-IR.json | 86 | 1 | 0 |
| JP | jp-codes.pdf | wiki-JP-regions.json | 138 | 0 | 0 |
| JP | jp-codes.pdf | wiki-JP.json | 138 | 0 | 0 |
| JP | wiki-JP-regions.json | wiki-JP.json | 138 | 0 | 0 |
| PL | pl-law2024.pdf | pl-law2025.pdf | 0 | 677 | 4 |
| PL | pl-law2024.pdf | pl-law2026-isap.pdf | 0 | 677 | 8 |
| PL | pl-law2024.pdf | wiki-PL.json | 408 | 269 | 1 |
| PL | pl-law2025.pdf | pl-law2026-isap.pdf | 0 | 4 | 8 |
| PL | pl-law2025.pdf | wiki-PL.json | 0 | 4 | 409 |
| PL | pl-law2026-isap.pdf | wiki-PL.json | 0 | 8 | 409 |

## Format evidence gaps

Countries with no format rule: AE, AF, AG, AQ, AU, BD, BF, BI, BJ, BN, BQ, BS, BV, BZ, CA, CC, CD, CG, CO, DJ, DM, DO, DZ, EG, EH, ER, ET, FK, FO, GI, GN, GS, GY, HM, HN, HT, IM, IO, JO, KE, KH, KN, KP, KR, KY, LA, LC, LK, LR, LS, LY, MA, MC, MF, ML, MM, MP, MR, MS, MU, MV, MW, MX, NF, NP, NZ, PF, PN, PT, PW, PY, RW, SA, SC, SD, SG, SH, SJ, SL, SN, SO, SS, SV, SY, SZ, TC, TF, TK, TL, TN, TW, UG, UM, UY, VU, YE, ZA, ZM, ZW.

Rules without literal source specimens: AL/historic-geographic, AO/ordinary, AR/ordinary, AS/ordinary, AW/ordinary, AX/ordinary, BA/ordinary, BH/ordinary, BL/ordinary, BO/ordinary, BT/ordinary, BW/ordinary, CH/ordinary, CI/ordinary, CK/ordinary, CL/ordinary, CR/ordinary, CU/ordinary, CW/ordinary, CX/ordinary, EE/ordinary, ES/historic-geographic, ES/ordinary, FI/ordinary, FJ/ordinary, FM/ordinary, GA/ordinary, GD/ordinary, GE/ordinary, GF/SIV, GG/Alderney, GM/ordinary, GP/SIV, GQ/ordinary, GR/ordinary, GW/ordinary, HK/ordinary, IL/ordinary, IQ/ordinary, IR/ordinary, IT/historic-geographic, KI/ordinary, KM/ordinary, KW/ordinary, LI/ordinary, LU/ordinary, LV/ordinary, MD/historic-geographic, MD/ordinary, MH/ordinary, MN/ordinary, MO/ordinary, MQ/SIV, MT/ordinary, NL/historic-geographic, NR/ordinary, NU/ordinary, OM/ordinary, PA/ordinary, PG/ordinary, PR/ordinary, PS/ordinary, QA/ordinary, RE/SIV, RU/ordinary, SI/ordinary, SM/ordinary, SR/ordinary, SX/ordinary, TR/ordinary, TV/ordinary, TZ/ordinary, US/Idaho-county-1945, VC/ordinary, VG/ordinary, VI/ordinary, WF/ordinary, WS/ordinary, YT/SIV.

## Country candidates and graceful geographic fallback

**Pass the country whenever you know it.** A serial alone generally cannot establish
its country. `ABC 123`-shaped serials are shared by many jurisdictions; flags,
colours, plate shape and printed state names would add information, but are absent
from this string-only interface. The reference lives in
`build_data/plate_country` (`build_data/plate_country/`, removed). It is separate from
acquisition and from the eventual Python/JavaScript client APIs.

With an ISO alpha-2 country or territory hint (including the survey's `XK`),
`Resolver.resolve(plate, country)` returns that country even for an unknown code,
vanity string, unsupported format or empty input. It reports `level="place"`
when eligible evidence identifies an office/district/city; otherwise `"state"`
for an evidenced broader unit; otherwise `"country"`. The explicit unit-kind map
is in `inference.json` (`build_data/plate_country/data/inference.json`, removed).
`place` does not mean a city point is known. Names, identifiers and coordinates
remain source assertions, without a golden-place join or current-location claim.
An invalid country identifier raises `ValueError`, rather than inventing one.

Without a hint, the result has `status="ranked_candidates"` or `"no_match"`,
`country_code=null`, `certain=false`, and all matching candidates with their
scores and evidence. **This release never certifies an unhinted country.** A sole
candidate sets `unique_in_catalog=true`, but the catalogue is incomplete and
special/vanity series are open-ended. A score lead is not proof of uniqueness.
Consumers must not silently convert the first candidate into a certain country.
This abstention is deliberate; there is no calibrated confidence threshold.

### Deterministic reference contract

Use the release's JSON bundle and its included policy. Country-specific formats,
place-code associations, geographic exclusions, script ranges, national marks,
weights and priors are data, not country branches in the resolver.

1. Normalize the input to Unicode NFC, uppercase **ASCII a–z only**, collapse runs
   of Python `str.isspace()` characters to one ASCII space, and trim them. The
   whitespace set is U+0009–000D, U+001C–001F, U+0020, U+0085, U+00A0, U+1680,
   U+2000–200A, U+2028–2029, U+202F, U+205F and U+3000. Do not transliterate scripts,
   fold similar-looking letters, strip flags, run OCR or remove printed labels.
   Empty input or more than 64 Unicode code points produces no unhinted candidates;
   a supplied country still returns `level="country"`, reason
   `empty_or_too_long_input`.
2. Full-match each eligible rule against the normalized serial. With a hint, filter
   to that country; an optional `series` filters by exact `series_id`. Try the
   published `pattern` first, then `relaxed_pattern`. The latter tolerates missing,
   repeated or changed separators **only at separator positions declared by the
   original rule**. It is not arbitrary punctuation stripping. Exact matching
   takes precedence for a rule. Both regexes are exported in the bundle.
3. Extract the named `code_group`, if any. For code-index equality only, remove the
   policy's characters ` -·•./` and map Unicode decimal digits to their decimal
   values (Unicode 15.0 in the reference environment). Preserve leading zeroes
   and native letters. A known code means at least one country/code assertion
   exists, including historical or Wikidata associations; it is useful country
   evidence but not proof of a current, uniquely identifying geographic code.
4. Each matched rule receives the score below. A country uses its **maximum** rule
   score, never the sum of duplicate source assertions. Sort descending score,
   then ascending ISO code for ties. Scores round to six decimal places with
   round-to-nearest, ties-to-even. For matching-rule evidence within a country,
   sort by descending score then `series_id`, preserving input order for remaining
   ties. Deduplicate identical `(country, series_status, matched_pattern,
   extracted_code)` matches in source order; this does not merge code-place
   disagreements. The first identical format assertion supplies its provenance.

```
score = 12 * known_code
      +  4 * fixed_national_mark_present
      +  2 * script_rarity
      +      specificity_bits
      + 0.5 * log2(max(1, road_motor_vehicles))
      -  2 * separator_relaxed_match
```

Booleans are zero or one. `script_rarity` is the largest
`log2(250 / max(1, countries_with_that_script_in_format_metadata))` among observed
scripts other than Latin and ASCII digits; use zero if there are none. Script
ranges are explicit policy regexes, not a general Unicode script classifier.
`fixed_national_mark_present` requires a nonempty configured literal inside the
serial; printed identity bands are not automatically added. `specificity_bits`
is exported by the normalizer: a heuristic based on required character slots
against a 36-character baseline, minimum repeat counts and the least-specific
regex alternative. Optional slots add zero. It is **not** an exact count of valid
plates, and clients should use the exported value rather than recalculate it.

The prior is the **road motor vehicles count**, not vehicles per capita, from
[Wikipedia revision 1377579042](https://en.wikipedia.org/w/index.php?oldid=1377579042),
under CC BY-SA 4.0. There are 178 observed country counts, dated 2007–2025. For the
other 72, the exported median count is 1,531,458.5 and evidence explicitly says
`imputed=true`. Observed rows retain their year, label, table position and source.
Definitions and dates differ across countries; no adjustment or interpolation
is made. A global vehicle-stock prior is a weak default, not a probability for
traffic at a particular camera or a probability that a candidate is correct.
Weights were chosen before the benchmark and were not fitted to its results.

Regexes use explicit letter/digit ranges. For JavaScript, compile their JSON
strings with Unicode mode, change `(?P<name>...)` to `(?<name>...)`, and require
a whole-string match. Count code points, not UTF-16 code units, for the input
limit. Do not use JavaScript's default `\s` or broad case-insensitive matching as
substitutes for the normalization above. The bundle plus these transformations
is the cross-language contract; no client implementation is added in this task.

### Geographic eligibility and reasons

With a country hint, an absence of matches yields `no_matching_format`. A matching
non-geographic series prevents a coincidentally matching geographic series from
claiming a location (`non_geographic_or_ambiguous_series`). US subnational
patterns require state context not supported by this reference interface, so they
return `subdivision_series_context_required`.

Only rows with `scope="registration_unit"`, a mapped unit kind, no narrower
`subdivision_scope` prerequisite and the same verified current/historic status as
the matched format are eligible. Wikidata `entity_association` rows and unknown
temporal status never produce a precise place. Historic matches need an explicit
`series` argument before supplying geography. This guards against an older
allocation silently winning over a reused serial. Validity dates are not yet an
input to the reference; historical status alone is not proof of validity today.

Eligible place rows win over eligible state rows. All distinct assertions at that
level remain in `locations`, including disagreements; differing name pairs set
`ambiguous=true`. That flag is conservative and can include name aliases. Parent
fallback is limited to evidenced state prefixes configured in data (India: two
characters; China: one). India state-prefix rows are parsed from the pinned state
abbreviation table; the resolver does not infer parents from coordinates or from
municipalities repeating a district code. State fallback explains itself as
`known_state_code_no_finer_verified_unit`; otherwise the reason is
`unknown_code_or_unverified_temporal_scope`. Geographic ambiguity does not alter
the caller's supplied country.

### Format sources, scope and remaining limitations

The additive source catalog is
`plate_country/data/sources.json` (`build_data/plate_country/data/sources.json`, removed).
It reuses accepted pins and adds English, German, French, Italian, Ukrainian,
Spanish and Norwegian Wikipedia revisions. US, Canadian and Australian table
cells are parsed as declared serial templates, including listed retained older
series. Scripts, exact and relaxed separators, fixed marks and original evidence
are recorded per rule. Templates describe syntax and may over-accept forbidden
letters, reserved blocks or unissued numbers. A match is not a legal-validity
check. Duplicate source/template evidence is retained in the inventory.

Coverage below is **at least one supported series**, not a claim that every
ordinary, commercial, motorcycle, historic or special plate is recognized.
Some previously covered countries still lack common retained formats; the
benchmark exposes this for older Brazilian and Argentine serials and a Delhi
commercial variant. Greedy regex captures can miss another possible prefix split
in an unseparated serial; all parse alternatives are not enumerated. Letter/digit
confusables and visually indistinguishable scripts are not automatically repaired.

The English Sahrawi article specifies seven numeric characters after `SH`, while
German specifies six; both alternatives are preserved. The `EH` rules describe
SADR-issued series, not a sovereignty judgment or a complete mapping of
Moroccan-administered territory. Svalbard's `ZN` format also matches Norway.
Territory/parent overlap is expected, including overseas departments and other
shared issuing systems; the ISO survey universe is not 250 independent systems.

The WHO legacy GHO vehicle-stock API was rejected because its
[terms restrict use to public health](https://www.who.int/about/policies/publishing/data-policy/terms-and-conditions).
WorldLicensePlates, MatriculasDelMundo and the commercial VideoEdge plate guide
were not imported because reusable terms were not established. The UD smart-city
benchmark's CC BY-NC-ND terms and unclear image rights in other plate benchmarks
were not used. No paid, private or scraped owner-information source is involved.

### Evaluation design and limits

The committed
[scored evaluation rows](../measurements/plate-country-evaluation.json) retain each serial,
country, source/revision/hash, split, candidate ranking and geographic reason.
The extraction/transcription policy is
`evaluation.json` (`build_data/plate_country/data/evaluation.json`, removed).
Metadata was fetched from Wikimedia Commons country categories; image filenames
present in the format articles were excluded. This reduces direct example reuse
but is **not proof of independent publishers**: both collections use Wikimedia,
the string filter is imperfect, and repeated photographers remain possible.
Metadata/category country labels were reviewed during selection, not taken as
universally correct. There is no independent human audit of the transcriptions.

Caption examples are regex extractions from pinned metadata. Photo examples were
visually transcribed from fetched images, with annotations linked to the exact
SHA-256; the normalizer checks that digest and Commons' SHA-1 before accepting an
annotation. Rebuilding consumes those reviewed annotations; it does **not** rerun
vision or claim deterministic OCR. Fifty-five image files are pinned: CC BY-SA
4.0 (16), 3.0 (10), 2.0 (7), CC BY 4.0 (9), 2.0 (6), public domain (6), CC0 (1).
Every row retains its own licence and author. Commons description metadata is
attributed under CC BY-SA 4.0; photo rights remain separate.

The initial formats and weights were committed as `9aa2f29` before evaluation
labels were inspected. Later supplemental rules concern seven countries absent
from this benchmark; benchmark-country patterns and ranking weights were not
changed after label inspection. Their addition did not change the aggregate
scores. A subsequent synthetic regression test exposed a separator compiler bug:
regex alternation was being treated as a literal separator. Fixing that bug
improved one held-out example, changing all-sample top-1/top-3 from 40.2%/54.3%
to 40.9%/55.1%, and holdout from 42.9%/57.1% to 46.4%/60.7%. The table below
measures the corrected implementation. The first run was blind to results;
this implementation correction occurred after that run and is disclosed here.
No benchmark-country source patterns or weights were tuned to the examples.
Country plus normalized serial is deduplicated before splitting; the first eight
hex digits of its SHA-256, interpreted as an unsigned integer, modulo five select
holdout when zero. All other groups are development. The split is fixed, with no
seed search, resampling or weight fitting. It is **not photographer- or
country-disjoint**, and its regional counts are small and uneven.

The sample was selected for legibility and permissive reuse from the first page
(up to 50 files) of 40 country categories. It includes special, older and vanity
plates; captions sometimes use documentary Latin transcriptions rather than
native glyphs. It is neither a representative road sample nor an OCR benchmark.
Thirty-three countries are measured; none of these results validates performance
in the other 217 survey entries. The Americas subset lacks US and Canadian
examples and has no held-out examples. Oceania's zero top-3 score reflects both
missing series and ambiguity; it must not be hidden by reporting only matched
plates. All denominators include no-match inputs. More independent, stratified
examples and a new untouched holdout are needed before tuning this release.

### Rebuild, resolve and inspect

Use the worktree's own environment and retained raw sources:

```sh
uv sync
.venv/bin/python -m build_data.acquire plates --data-dir data --stage normalize
.venv/bin/python -m build_data.plate_country fetch --data-dir data
.venv/bin/python -m build_data.plate_country build --data-dir data
.venv/bin/python -m build_data.plate_country evaluate --data-dir data
.venv/bin/python -m build_data.plate_country status --data-dir data
.venv/bin/python -m build_data.plate_country.report --data-dir data
.venv/bin/python -m build_data.plate_country resolve --data-dir data --plate 'MH-09 S-2112' --country IN
.venv/bin/python -m build_data.plate_country resolve --data-dir data --plate 'MH-09 S-2112'
```

The example is transcribed from a pinned Indian plate photograph in the benchmark.
`fetch` reuses cached files and the shared identified, host-locked client (at least
1.1 seconds between requests to a host). Base pins are supplied by the existing
`plates` acquisition; the new command fetches only additive sources. The default
build is offline. Raw snapshots live under `data/raw/plates_country/`, with
HTTP receipts, and must be retained alongside the accepted `plates` snapshots.
Commons API category responses are pinned by bytes/hash and contain individual
page revision IDs; a later category query is not a historical snapshot. If remote
bytes change, a fresh fetch fails the expected hash rather than accepting new data.

The new manifest commits content-addressed JSON/Parquet artifacts under
`data/normalized/plates_country/`, with base-manifest fingerprint, source licences,
source hashes, policy and implementation hashes, and output hashes. `status` verifies all of these
and the accepted base release. Read active filenames from the manifest, never a
wildcard over superseded releases. Parquet `formats`, `vehicle_priors` and
`coverage` have schema version `plates-country-1`: non-null UTF-8 `country_code`
and non-null UTF-8 `evidence_json`, whose complete nested fields match the bundle.
The bundle's top-level keys are `version`, `policy`, `countries`, `priors`,
`formats` and `codes`. Evaluation is a separately generated report tied to the
manifest hash; the documentation report rejects a stale evaluation.

Validation on `data/plates-country`: 300 tests passed, 7 skipped; whole-worktree
`ruff check`, `ruff format --check` and strict `mypy` passed. Nineteen new synthetic
tests require no network. An offline rebuild reproduced the identical manifest;
all 323 pinned sources verified from cache. Main-checkout code, data and interpreter
were not used by this extension.

<!-- plate-country-measurements:start -->
## Country-inference measurements and format inventory

Generated by `python -m build_data.plate_country.report --data-dir data`.
Before: **151/250** countries with 159 format rows. After: **239/250** with **704** format evidence rows. These counts mean at least one modeled series, not complete coverage.

The benchmark contains **127** distinct documented plates from **33** countries: 99 development examples and **28 held-out examples**. It contains 72 caption/filename transcriptions, 51 visually transcribed photographed plates and 4 published specimens. The latter are not claimed to be issued serials or government-certified specimens.

| Region | All n | All top-1 | All top-3 | Holdout n | Holdout top-1 | Holdout top-3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Overall | 127 | 40.9% | 55.1% | 28 | 46.4% | 60.7% |
| Africa | 18 | 50.0% | 55.6% | 5 | 40.0% | 60.0% |
| Americas | 11 | 9.1% | 9.1% | 0 | — | — |
| Asia | 43 | 48.8% | 72.1% | 9 | 66.7% | 88.9% |
| Europe | 33 | 63.6% | 84.8% | 6 | 83.3% | 100.0% |
| Oceania | 22 | 0.0% | 0.0% | 8 | 0.0% | 0.0% |

Truth appears anywhere in the candidate list for 67.7% overall and 71.4% on holdout. No unhinted result is certified as certain. The absence of an Americas holdout example is a sampling gap, not a zero-accuracy measurement.

| Supplied-country level | All examples | Holdout examples |
| --- | ---: | ---: |
| place | 11 | 4 |
| state | 18 | 5 |
| country | 98 | 19 |

Every supplied-country example retains that country. Geographic levels measure what evidence was available, **not independently checked place accuracy**. Country-only reasons in this sample:

- `no_matching_format`: 41.
- `non_geographic_or_ambiguous_series`: 49.
- `unknown_code_or_unverified_temporal_scope`: 8.

The full scored rows, candidate rankings, image/caption provenance, split assignments and denominators are in `data/normalized/plates_country/evaluation.json`.

### Per-country format coverage

C/H are counts of current/historic **evidence rows**, including duplicate source assertions and non-ordinary series. All coverage remains partial. The bundle records exact regexes, separators, marks, code groups and evidence. No-format territories are not asserted to be non-issuers.

| ISO | Country/territory | C/H | Scripts (digits included) | Sources |
| --- | --- | ---: | --- | --- |
| AD | Andorra | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1363303908) |
| AE | United Arab Emirates | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1365209773) |
| AF | Afghanistan | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1356853566) |
| AG | Antigua & Barbuda | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338001799) |
| AI | Anguilla | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338001793) |
| AL | Albania | 0/1 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1371058793) |
| AM | Armenia | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1371471817) |
| AO | Angola | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338001791) |
| AQ | Antarctica | 0/0 | Gap | Unsourced grammar |
| AR | Argentina | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1367699844) |
| AS | American Samoa | 1/0 | ASCII digits | [1](https://en.wikipedia.org/w/index.php?oldid=1343912298) |
| AT | Austria | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1367179317) |
| AU | Australia | 59/8 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1377988841) |
| AW | Aruba | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338001805) |
| AX | Åland Islands | 1/0 | ASCII digits, Latin | [1](https://de.wikipedia.org/w/index.php?oldid=248707514) |
| AZ | Azerbaijan | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1371307150) |
| BA | Bosnia | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338001871) |
| BB | Barbados | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1367992026) |
| BD | Bangladesh | 1/0 | Bengali, Bengali digits | [1](https://en.wikipedia.org/w/index.php?oldid=1365474120) |
| BE | Belgium | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1369135514) |
| BF | Burkina Faso | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1234450751) |
| BG | Bulgaria | 1/0 | ASCII digits, Cyrillic, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1372353235) |
| BH | Bahrain | 1/0 | ASCII digits | [1](https://en.wikipedia.org/w/index.php?oldid=1338129219) |
| BI | Burundi | 0/0 | Gap | Unsourced grammar |
| BJ | Benin | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338001852) |
| BL | St. Barthélemy | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002779) |
| BM | Bermuda | 1/0 | ASCII digits | [1](https://en.wikipedia.org/w/index.php?oldid=1356256004) |
| BN | Brunei | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338001881) |
| BO | Bolivia | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1341292282) |
| BQ | Caribbean Netherlands | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1345337205) |
| BR | Brazil | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1361898556) |
| BS | Bahamas | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1358279279) |
| BT | Bhutan | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1376978101) |
| BV | Bouvet Island | 0/0 | Gap | Unsourced grammar |
| BW | Botswana | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338001869) |
| BY | Belarus | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1368347962) |
| BZ | Belize | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338001838) |
| CA | Canada | 30/36 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1373784295) |
| CC | Cocos Islands | 0/0 | Gap | Unsourced grammar |
| CD | Congo - Kinshasa | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002018) |
| CF | Central African Republic | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1303069313) |
| CG | Congo - Brazzaville | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338001978) |
| CH | Switzerland | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1368288237) |
| CI | Côte d’Ivoire | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1318022341) |
| CK | Cook Islands | 1/0 | ASCII digits | [1](https://en.wikipedia.org/w/index.php?oldid=1338002003) |
| CL | Chile | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1366530061) |
| CM | Cameroon | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338001926) |
| CN | China | 2/0 | ASCII digits, Han, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1374494974) |
| CO | Colombia | 2/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1373706002) |
| CR | Costa Rica | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002006) |
| CU | Cuba | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1349341809) |
| CV | Cape Verde | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1376832347) |
| CW | Curaçao | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002012) |
| CX | Christmas Island | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1310411286) |
| CY | Cyprus | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1376218876) |
| CZ | Czechia | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1372467542) |
| DE | Germany | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1377669488) |
| DJ | Djibouti | 2/0 | ASCII digits, Arabic, Arabic-Indic digits, Latin | [1](https://uk.wikipedia.org/w/index.php?oldid=36058050) |
| DK | Denmark | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338668056) |
| DM | Dominica | 1/1 | ASCII digits, Latin | [1](https://uk.wikipedia.org/w/index.php?oldid=38199368) |
| DO | Dominican Republic | 1/1 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002026) |
| DZ | Algeria | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1376724844) |
| EC | Ecuador | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002030) |
| EE | Estonia | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002750) |
| EG | Egypt | 2/0 | Arabic, Arabic-Indic digits | [1](https://en.wikipedia.org/w/index.php?oldid=1338002725) |
| EH | Western Sahara | 3/1 | ASCII digits, Latin | [1](https://de.wikipedia.org/w/index.php?oldid=260305379), [2](https://en.wikipedia.org/w/index.php?oldid=1338003287) |
| ER | Eritrea | 1/0 | ASCII digits, Latin | [1](https://fr.wikipedia.org/w/index.php?oldid=222874638) |
| ES | Spain | 1/1 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1363970679) |
| ET | Ethiopia | 0/1 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1376535567) |
| FI | Finland | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1367179902) |
| FJ | Fiji | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1341979193) |
| FK | Falkland Islands | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1345582883) |
| FM | Micronesia | 1/0 | ASCII digits | [1](https://en.wikipedia.org/w/index.php?oldid=1338003034) |
| FO | Faroe Islands | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338668056) |
| FR | France | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1360313366) |
| GA | Gabon | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002796) |
| GB | UK | 2/2 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1370151084), [2](https://en.wikipedia.org/w/index.php?oldid=1375613060) |
| GD | Grenada | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002829) |
| GE | Georgia | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1372335903) |
| GF | French Guiana | 1/0 | ASCII digits, Latin | [1](https://fr.wikipedia.org/w/index.php?oldid=238942028) |
| GG | Guernsey | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1350805077) |
| GH | Ghana | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002819) |
| GI | Gibraltar | 1/1 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1349341906) |
| GL | Greenland | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338668056) |
| GM | Gambia | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002798) |
| GN | Guinea | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1377835056) |
| GP | Guadeloupe | 1/0 | ASCII digits, Latin | [1](https://fr.wikipedia.org/w/index.php?oldid=238942028) |
| GQ | Equatorial Guinea | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002738) |
| GR | Greece | 1/0 | ASCII digits, Greek, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1367180219) |
| GS | South Georgia & South Sandwich Islands | 0/0 | Gap | Unsourced grammar |
| GT | Guatemala | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1347696568) |
| GU | Guam | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1366265234) |
| GW | Guinea-Bissau | 1/0 | ASCII digits, Latin | [1](https://de.wikipedia.org/w/index.php?oldid=264340455) |
| GY | Guyana | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1376645220) |
| HK | Hong Kong | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1374661832) |
| HM | Heard & McDonald Islands | 0/0 | Gap | Unsourced grammar |
| HN | Honduras | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002850) |
| HR | Croatia | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1375714451) |
| HT | Haiti | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002849) |
| HU | Hungary | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1372826697) |
| ID | Indonesia | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1375240023) |
| IE | Ireland | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1375357170) |
| IL | Israel | 1/0 | ASCII digits | [1](https://en.wikipedia.org/w/index.php?oldid=1374923846) |
| IM | Isle of Man | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1352659370) |
| IN | India | 2/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1372866191) |
| IO | British Indian Ocean Territory | 1/0 | ASCII digits, Latin | [1](https://it.wikipedia.org/w/index.php?oldid=151111064) |
| IQ | Iraq | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002866) |
| IR | Iran | 1/0 | Arabic, Persian digits | [1](https://en.wikipedia.org/w/index.php?oldid=1353798607) |
| IS | Iceland | 0/1 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1371704297) |
| IT | Italy | 1/1 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1376348433) |
| JE | Jersey | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1242049100) |
| JM | Jamaica | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002878) |
| JO | Jordan | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002897) |
| JP | Japan | 1/0 | ASCII digits, Han, Hiragana, Katakana, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1375974707) |
| KE | Kenya | 1/1 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1376439213) |
| KG | Kyrgyzstan | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1356365785) |
| KH | Cambodia | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1357532292) |
| KI | Kiribati | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002909) |
| KM | Comoros | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1353226271) |
| KN | St. Kitts & Nevis | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338753711) |
| KP | North Korea | 1/0 | ASCII digits, Hangul | [1](https://en.wikipedia.org/w/index.php?oldid=1376565406) |
| KR | South Korea | 2/0 | ASCII digits, Hangul | [1](https://en.wikipedia.org/w/index.php?oldid=1376656300) |
| KW | Kuwait | 1/0 | ASCII digits | [1](https://en.wikipedia.org/w/index.php?oldid=1366902172) |
| KY | Cayman Islands | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1345582883) |
| KZ | Kazakhstan | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1375818980) |
| LA | Laos | 1/0 | ASCII digits, Lao | [1](https://en.wikipedia.org/w/index.php?oldid=1338002945) |
| LB | Lebanon | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1353201548) |
| LC | St. Lucia | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1376852335) |
| LI | Liechtenstein | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1375193249) |
| LK | Sri Lanka | 1/1 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1377836403) |
| LR | Liberia | 0/0 | Gap | Unsourced grammar |
| LS | Lesotho | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002955) |
| LT | Lithuania | 1/1 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1367983335) |
| LU | Luxembourg | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1367984246) |
| LV | Latvia | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1367304934) |
| LY | Libya | 2/0 | ASCII digits, Arabic, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1349342004) |
| MA | Morocco | 1/0 | ASCII digits, Arabic | [1](https://en.wikipedia.org/w/index.php?oldid=1368833711) |
| MC | Monaco | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1371826222) |
| MD | Moldova | 1/1 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1369300318) |
| ME | Montenegro | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1367985939) |
| MF | St. Martin | 1/0 | ASCII digits, Latin | [1](https://fr.wikipedia.org/w/index.php?oldid=238942028) |
| MG | Madagascar | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1368901238) |
| MH | Marshall Islands | 1/0 | ASCII digits | [1](https://en.wikipedia.org/w/index.php?oldid=1338003012) |
| MK | North Macedonia | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1344572551) |
| ML | Mali | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002998) |
| MM | Myanmar | 2/1 | ASCII digits, Latin, Myanmar, Myanmar digits | [1](https://en.wikipedia.org/w/index.php?oldid=1377004889) |
| MN | Mongolia | 1/0 | ASCII digits, Cyrillic | [1](https://en.wikipedia.org/w/index.php?oldid=1376727365) |
| MO | Macao | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1377063034) |
| MP | Northern Mariana Islands | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1344455877) |
| MQ | Martinique | 1/0 | ASCII digits, Latin | [1](https://fr.wikipedia.org/w/index.php?oldid=238942028) |
| MR | Mauritania | 2/0 | ASCII digits, Arabic, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003015) |
| MS | Montserrat | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1345582883) |
| MT | Malta | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1367984289) |
| MU | Mauritius | 1/0 | ASCII digits, Latin | [1](https://de.wikipedia.org/w/index.php?oldid=223364766) |
| MV | Maldives | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1345469488) |
| MW | Malawi | 0/0 | Gap | Unsourced grammar |
| MX | Mexico | 2/1 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1368484692) |
| MY | Malaysia | 2/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1377349409) |
| MZ | Mozambique | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003047) |
| NA | Namibia | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1353001290) |
| NC | New Caledonia | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002775) |
| NE | Niger | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1374194988) |
| NF | Norfolk Island | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1302829805) |
| NG | Nigeria | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1358193040) |
| NI | Nicaragua | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003071) |
| NL | Netherlands | 6/7 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1377707144) |
| NO | Norway | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1375361487) |
| NP | Nepal | 1/1 | ASCII digits, Devanagari, Devanagari digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003064) |
| NR | Nauru | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003058) |
| NU | Niue | 1/0 | ASCII digits | [1](https://en.wikipedia.org/w/index.php?oldid=1338003086) |
| NZ | New Zealand | 1/1 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1372963488) |
| OM | Oman | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1365425002) |
| PA | Panama | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1375336244) |
| PE | Peru | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1349342190) |
| PF | French Polynesia | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002770) |
| PG | Papua New Guinea | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1375335304) |
| PH | Philippines | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1375973749) |
| PK | Pakistan | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1375579015) |
| PL | Poland | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1376479133) |
| PM | St. Pierre & Miquelon | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1375947292) |
| PN | Pitcairn | 0/0 | Gap | Unsourced grammar |
| PR | Puerto Rico | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1377653126) |
| PS | Palestine | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1374923642) |
| PT | Portugal | 1/1 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1368649490) |
| PW | Palau | 3/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003244) |
| PY | Paraguay | 1/1 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1359377651) |
| QA | Qatar | 1/0 | ASCII digits | [1](https://en.wikipedia.org/w/index.php?oldid=1365424249) |
| RE | Réunion | 1/0 | ASCII digits, Latin | [1](https://fr.wikipedia.org/w/index.php?oldid=238942028) |
| RO | Romania | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1367060445) |
| RS | Serbia | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1371473039) |
| RU | Russia | 1/0 | ASCII digits, Cyrillic, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1362238492) |
| RW | Rwanda | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003284) |
| SA | Saudi Arabia | 2/0 | ASCII digits, Arabic, Arabic-Indic digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1352834674) |
| SB | Solomon Islands | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003337) |
| SC | Seychelles | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003315) |
| SD | Sudan | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003367) |
| SE | Sweden | 1/1 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1366420734) |
| SG | Singapore | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1374924505) |
| SH | St. Helena | 3/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1345582883) |
| SI | Slovenia | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1349122519) |
| SJ | Svalbard & Jan Mayen | 1/0 | ASCII digits, Latin | [1](https://no.wikipedia.org/w/index.php?oldid=25912083) |
| SK | Slovakia | 1/1 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1371504047) |
| SL | Sierra Leone | 2/0 | ASCII digits, Latin | [1](https://de.wikipedia.org/w/index.php?oldid=260758379) |
| SM | San Marino | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1365288456) |
| SN | Senegal | 1/1 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003309) |
| SO | Somalia | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003340) |
| SR | Suriname | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003369) |
| SS | South Sudan | 1/1 | ASCII digits, Latin | [1](https://it.wikipedia.org/w/index.php?oldid=148177462) |
| ST | São Tomé & Príncipe | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003303) |
| SV | El Salvador | 0/1 | ASCII digits, Latin | [1](https://es.wikipedia.org/w/index.php?oldid=175169987) |
| SX | Sint Maarten | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003322) |
| SY | Syria | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1369673122) |
| SZ | Eswatini | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338002752) |
| TC | Turks & Caicos Islands | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1345582883) |
| TD | Chad | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1376836896) |
| TF | French Southern Territories | 1/0 | ASCII digits, Latin | [1](https://fr.wikipedia.org/w/index.php?oldid=238942028) |
| TG | Togo | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003392) |
| TH | Thailand | 1/0 | ASCII digits, Thai | [1](https://en.wikipedia.org/w/index.php?oldid=1365790767) |
| TJ | Tajikistan | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1350953028) |
| TK | Tokelau | 0/0 | Gap | Unsourced grammar |
| TL | Timor-Leste | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1340753182) |
| TM | Turkmenistan | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1376735676) |
| TN | Tunisia | 1/0 | ASCII digits, Arabic | [1](https://en.wikipedia.org/w/index.php?oldid=1372898331) |
| TO | Tonga | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003394) |
| TR | Türkiye | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1359024284) |
| TT | Trinidad & Tobago | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1376191684) |
| TV | Tuvalu | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003435) |
| TW | Taiwan | 1/1 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1367199647) |
| TZ | Tanzania | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003384) |
| UA | Ukraine | 1/0 | ASCII digits, Cyrillic, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1370202866) |
| UG | Uganda | 2/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003439) |
| UM | U.S. Outlying Islands | 0/0 | Gap | Unsourced grammar |
| US | US | 167/110 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1345368469), [2](https://en.wikipedia.org/w/index.php?oldid=1377655506) |
| UY | Uruguay | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1341501926) |
| UZ | Uzbekistan | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1356025945) |
| VA | Vatican City | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003465) |
| VC | St. Vincent & Grenadines | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003294) |
| VE | Venezuela | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003469) |
| VG | British Virgin Islands | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338001878) |
| VI | U.S. Virgin Islands | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1321235066) |
| VN | Vietnam | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1369462169) |
| VU | Vanuatu | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1338003464) |
| WF | Wallis & Futuna | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1359837463) |
| WS | Samoa | 1/0 | ASCII digits | [1](https://en.wikipedia.org/w/index.php?oldid=1338003299) |
| XK | Kosovo | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1368693154) |
| YE | Yemen | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1343643680) |
| YT | Mayotte | 1/0 | ASCII digits, Latin | [1](https://fr.wikipedia.org/w/index.php?oldid=238942028) |
| ZA | South Africa | 2/1 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1374562098) |
| ZM | Zambia | 1/0 | ASCII digits, Latin | [1](https://de.wikipedia.org/w/index.php?oldid=242232989) |
| ZW | Zimbabwe | 1/0 | ASCII digits, Latin | [1](https://en.wikipedia.org/w/index.php?oldid=1340353174) |

### Explicit missing formats and incomplete issuing series

- **AQ Antarctica**: No ordinary issuing format established in fetched reusable sources. Issuer/non-issuer status is unverified; do not infer none or inherit a parent-country serial. Research did not establish a usable format.
- **BI Burundi**: English article gives no standard serial grammar; German/Ukrainian/French article attempts unavailable. Commercial plate guide found but no reuse licence established. Native photo/OCR transcription not generalized into a national grammar.
- **BV Bouvet Island**: No ordinary issuing format established in fetched reusable sources. Issuer/non-issuer status is unverified; do not infer none or inherit a parent-country serial. Research did not establish a usable format.
- **CC Cocos Islands**: English article says current Australian-standard plates since 2000, but its serial table is blank. Italian Australian article does not establish a complete Cocos grammar. Do not inherit every Australian format.
- **DO Dominican Republic**: Only temporary and 1996–2003 truck/SUV rules collected. Current ordinary private series remains a gap; government brochure identified but reuse licence not established.
- **EH Western Sahara**: English/German ordinary digit-count conflict retained. Only SADR issuing series and pre-1976 Spanish example pattern included; Moroccan-administered territorial allocation is not comprehensively mapped. Not a sovereignty inference.
- **GS South Georgia & South Sandwich Islands**: No ordinary issuing format established in fetched reusable sources. Issuer/non-issuer status is unverified; do not infer none or inherit a parent-country serial. Research did not establish a usable format.
- **HM Heard & McDonald Islands**: No ordinary issuing format established in fetched reusable sources. Issuer/non-issuer status is unverified; do not infer none or inherit a parent-country serial. Research did not establish a usable format.
- **LR Liberia**: English article documents A/B/C vehicle-class prefixes but not ordinary serial length or complete syntax. German/Ukrainian articles unavailable. Diplomatic series also lacks a bounded serial length.
- **MW Malawi**: English plate article contains no textual serial grammar; German/Ukrainian/French attempts unavailable. Reuse terms of specialist plate galleries unconfirmed.
- **PN Pitcairn**: No reusable sourced issuing grammar found. Sparse claims about vehicles or absence of plates are insufficient to certify non-issuance.
- **PW Palau**: Ngiwal ordinary, government and diplomatic templates only; most state serial fields are empty. Coverage is not all 16 states.
- **SJ Svalbard & Jan Mayen**: Svalbard ZN five-digit car series only, overlapping Norway. Jan Mayen, motorcycles and historic Russian mining-company series not fully sourced.
- **SL Sierra Leone**: Ordinary serial and diplomatic serial only. Printed office/type field, vanity choices and earlier series are not fully modeled.
- **SV El Salvador**: Numeric private 2011 series only. The official 2021 announcement confirms retained numeric plates and hexadecimal expansion, but the latter is not normalized from a reusable pinned grammar.
- **TK Tokelau**: No reusable sourced issuing grammar found. Sparse claims about vehicles or absence of plates are insufficient to certify non-issuance.
- **UG Uganda**: Digital government, police and prisons rules only; ordinary private and older private formats remain gaps. English article has no ordinary serial grammar, German/Ukrainian attempts unavailable.
- **UM U.S. Outlying Islands**: No ordinary issuing format established in fetched reusable sources. Issuer/non-issuer status is unverified; do not infer none or inherit a parent-country serial. Research did not establish a usable format.
