"""Render client status from recorded measurements and offline conformance checks."""

import argparse
import json
import re
from pathlib import Path
from typing import Any

from benchmarks.core_read_path import ROOT
from tests.conformance import core_legacy, forward_legacy
from tools.check_sample_source import check as check_source


def section(text: str, name: str) -> str:
    """Retain the tables produced by the corresponding benchmark scripts."""
    start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    return text[text.index(start) : text.index(end) + len(end)]


def legacy_table() -> tuple[str, dict[str, dict[str, int]]]:
    """Run assertions against original expectations before reporting counts."""
    results = {
        "reverse": core_legacy.check(),
        "postal": forward_legacy.check("postal"),
        "airports": forward_legacy.check("airports"),
    }
    lines = ["| Legacy family | Requests | Asserted mapping |", "| --- | ---: | --- |"]
    for family, counts in results.items():
        mapping = ", ".join(f"{n} {k}" for k, n in counts.items())
        lines.append(f"| {family} | {sum(counts.values())} | {mapping} |")
    return "\n".join(lines), results


def validation(path: Path) -> dict[str, Any]:
    """Read a completed full-gate log; the final mypy line must be present."""
    text = path.read_text()
    python = re.search(r"(\d+) passed, (\d+) skipped in", text)
    types = re.search(r"Success: no issues found in (\d+) source files", text)
    node = re.search(r"# tests (\d+)", text)
    if python is None or types is None or node is None:
        raise ValueError("A completed full-gate log is required")
    return {
        "rust_tests": sum(
            int(n) for n in re.findall(r"test result: ok\. (\d+) passed;", text)
        ),
        "pytest_passed": int(python[1]),
        "pytest_skipped": int(python[2]),
        "mypy_files": int(types[1]),
        "node_tests": int(node[1]),
        "gates": [
            "cargo fmt --check",
            "cargo clippy --all-targets --all-features -- -D warnings",
            "cargo test",
            "cargo check -p thereabouts-core --target wasm32-unknown-unknown",
            "cargo check -p thereabouts-cli-core --target wasm32-unknown-unknown",
            "uv run pytest",
            "uv run ruff check",
            "uv run ruff format --check",
            "uv run mypy",
            "node --test (with offline guard)",
            "npm run check",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-log", type=Path, required=True)
    args = parser.parse_args()
    core_path = ROOT / "docs/CLIENT_CORE_MEASUREMENTS.json"
    core = json.loads(core_path.read_text())
    forward = json.loads((ROOT / "docs/CLIENT_FORWARD_MEASUREMENTS.json").read_text())
    status = ROOT / "docs/CLIENT_STATUS.md"
    old = status.read_text()
    legacy, mappings = legacy_table()
    gates = validation(args.gate_log)
    independent = check_source()
    from tests.cli.test_vectors import BUNDLES, USAGE_CASES

    cases = [
        case
        for name in BUNDLES
        for case in json.loads(
            (ROOT / f"tests/fixtures/{name}-vectors.json").read_text()
        )["cases"]
    ]
    nul = sum(
        any(isinstance(v, str) and "\0" in v for v in c["request"]["values"])
        for c in cases
    )
    typed = sum(
        c["request"]["kind"] != "coordinates"
        and not isinstance(c["request"]["values"][0], str)
        for c in cases
    )
    cli_counts = {
        "current_total": len(cases),
        "console": len(cases) - nul - typed,
        "nul_binding": nul,
        "typed_api": typed,
        "grammar_usage": len(USAGE_CASES),
        "legacy_console": 18,
        "legacy_typed_api": 1,
    }
    cli = core["cli_startup"]
    core["qualification"] = {
        "legacy_mappings": mappings,
        "independent_reverse": independent,
        "validation": gates,
        "cli_conformance": cli_counts,
    }
    core_path.write_text(json.dumps(core, indent=2) + "\n")
    fixture = forward["fixture_packs"]
    plate = core["result_contract_rework"]["vectors"]["plates-vectors.json"]
    exports = core["world_exports"]
    machine = core["machine"]
    current = []
    for name in ("cache_hot", "random"):
        value = core[name]
        current.append(
            f"| {name} | {value['scalar_median_us']:.3f} / "
            f"{value['scalar_p99_us']:.3f} | "
            f"{value['reverse_columns_points_per_second']:,.0f} |"
        )
    extract = json.loads((ROOT / "tests/fixtures/core-source-extract.json").read_text())
    reverse_vectors = json.loads(
        (ROOT / "tests/fixtures/core-sample-vectors.json").read_text()
    )
    spans = core.get("single_shard", {})
    span_rows = "\n".join(
        f"| {phase} | {v['scalar_median_us']:.3f} | {v['scalar_p99_us']:.3f} | "
        f"{v['single_shard_spans']['hot_text_max_bytes']:,} | "
        f"{v['single_shard_spans']['hot_offsets_max_bytes']:,} |"
        for phase, v in spans.items()
        if phase in {"before", "after"}
    )
    world = core.get("world_scale", {})
    world_rows = "\n".join(
        f"| {verb} | {phase} | {v[verb]['scalar_median_us']:.3f} | "
        f"{v[verb]['scalar_p99_us']:.3f} | "
        f"{v[verb]['batch_points_per_second']:,.0f} |"
        for verb in ("ip", "names_exact", "names_random", "names_fuzzy_common_grams")
        for phase, v in world.items()
        if phase in {"before", "after"}
    )
    text = f"""# Thereabouts client status

The Rust runtime and Python reverse/forward API are implemented. This report
is generated by `python -m benchmarks.client_status --gate-log <full-gate-log>`
from the measurement scripts and offline legacy assertions. Package 3 is
implemented: the native command tree, data store and Python-hosted MCP service.
The wire contract is [PACK_FORMAT.md](PACK_FORMAT.md); [CLI.md](CLI.md) is the
normative command grammar for this runtime and the later Node implementation.

## Package 3

The native thereabouts-cli crate uses clap and injectable IO. The three
executable lines in Python cli.py call _core.run_cli; matching, argument policy,
table/JSON/NDJSON/CSV output and streaming reverse batches remain in Rust.
All nine lookup verbs are explicit. Data commands install, list, verify, remove,
path and update --check share discovery with Python. Info reports installed
identities; mcp starts the optional current server without protocol banners.

Install uses a format-2 release index, ureq with rustls, exact Range validation,
bounded ustar extraction, SHA-256, an OS lock and atomic dataset activation.
The packs/<family>/<dataset-version> layout and active.json pin one release.
Old per-family pointers remain discoverable. Platform paths are compared
against platformdirs. Nothing downloads implicitly; test transfers use local
directories and loopback HTTP. Registry dependency fetches were authorized
separately and do not fetch pipeline data.

Batch rows preserve input columns and prefix result fields with thereabouts_.
Bad rows continue and exit 5. JSON output streams one results object; CSV from
NDJSON spools rows to disk to determine its input header with bounded schema
memory. Disk exhaustion is exit 2; no product free-space floor applies.
NO_COLOR is honored by plain tables.

The optional MCP server returns the same JSON for all nine verbs. The original
CLI and MCP implementations remain under commandline/application.py and
mcp_service/catalogue_server.py, with their existing behavioral assertions.
They are deliberately retained for package 5.

Console conformance covers {cli_counts["console"]} current vectors; five NUL
cases use the same embedded runner because OS argv cannot contain NUL. One
integer-type case remains a typed API assertion. Six invalid grammar cases
assert usage exit 2. The original 19 forward cases retain their old assertions:
18 execute the console; the integer-type rejection stays at the typed boundary.
The legacy expectations are never regenerated; current forward snapshots reflect
optional core enrichment. Native IO tests exercise every
command, output modes, failures, prompts and field selection. HTTP tests cover
interruption/resume, ignored ranges, bad checksums, activation failure,
concurrent locking and the absence of implicit network access.

CLI process start to first flushed reverse result on the sample pack:
**{cli["first_result_median_ms"]:.3f} ms median,
{cli["first_result_p99_ms"]:.3f} ms p99** across {cli["iterations"]} fresh process
launches after {cli["warmup_launches"]} warmups. File caches are warm; Python
imports and pack opening are included. The initial launch took
{cli["first_launch_ms"]:.3f} ms. These numbers come from
python -m benchmarks.cli_startup. The full per-launch series is in the JSON.

## CLI review fixes after package 3

A1-A4 separate the agent disk rule from product admission (twice archive bytes
plus 64 MiB), replace the global HTTP timer with connection/header deadlines
and per-read stall limits, render bounded aligned place rows, and preserve CSV
input order followed by public or selected result order. Candidates are indented;
evidence remains structured output. Unicode display width determines padding.

A5-A9 refuse version changes that omit an active family, provide path-specific
repair commands and missing-file errors, stop locally at the unpublished release
placeholder, explain help forms, delegate Python directory selection to Rust,
use standard-library file locks, honor environment proxies and HTTPS-only
redirects, diagnose non-CSV/non-JSON input, expose MCP LOCODE country, and give
invalid coordinates a range hint. Five synthetic reverse results gain that hint;
legacy expectations and real reverse vectors are unchanged. Loopback TLS tests
verify a trusted redirect and reject a downgrade; no public endpoint is contacted.

A10 moves batch parsing, rendering, field selection and exit mapping into the
wasm-clean thereabouts-cli-core crate. Hosts own streams and temporary storage.
Its wasm target is checked alongside the reader. A11 refreshes this report and
CLI startup from scripts. The retained Node reader passes {gates["node_tests"]}
Node 22 tests and npm type checks pending replacement in package 4.

## Format follow-ups after package 3

Forward packs now pin the core catalogue's dataset version, digest and ordinal
count. They contain no duplicated catalogue. Explicit or installed matching core
supplies canonical city detail and its timezone. Standalone forward packs retain
source points and pooled country/subdivision names and codes, with city detail
and timezone null. A different core catalogue is incompatible, including at
store activation. Core fixtures include the forward extracts' geographic closure;
the reverse spatial coverage is unchanged. The writer accepts core_pack explicitly.
The shared core sample uses {core["shared_catalogue"]["core_sample_bytes"]:,} bytes.
It is larger than the original reverse-only sample because the independent
forward source checks now resolve their full place closure through that one core.

Catalogue strings are now contiguous per record, with evidence last. A miss is
three bounded positioned reads: 80 bytes, at most 112 offset bytes and at most
65,536 string bytes. Full verification also checks record ownership of every
string reference. Core now requires manifest minor 2; older core packs must be rebuilt.
The 25,000-place, single-shard workload uses 2,000 distinct random queries and
fresh decoded caches, with warm filesystem caches (explicitly preloaded now);
timings include Python.

| Single shard | Median µs | p99 µs | Max hot strings B | Max offsets B |
| --- | ---: | ---: | ---: | ---: |
{span_rows}

These measurements come from benchmarks.single_shard_read_path; both the synthetic
and real-sample physical spans are retained in CLIENT_CORE_MEASUREMENTS.json.

Forward tables now share a lazy 512 MiB decoded-block LRU per opened pack.
IP starts use contiguous 24-byte rows. IO and decompression remain outside the
cache lock. Fuzzy search derives length/first-trigram buckets and has pack-wide
budgets of 2,048 keys, 16,384 posting visits and 256 projected rows. Exact and
prefix are exhaustive; larger fuzzy searches can omit otherwise eligible cities,
and population ranks the admitted set. Hard geography filters still apply.

| Synthetic workload | Reader | Median µs | p99 µs | Batch rows/s |
| --- | --- | ---: | ---: | ---: |
{world_rows}

The world-scale script uses 7.8M synthetic intervals with gaps and one million
distinct name keys across 34 shards. It explicitly preloads file bytes, then opens
fresh decoded caches. Initial block misses are included. It measures search
scale, not world accuracy or compressibility. Historical unconditioned filesystem
runs are retained as history in the JSON. Process peak RSS was
{world.get("before", {}).get("process_peak_rss_bytes", 0):,} bytes before and
{world.get("after", {}).get("process_peak_rss_bytes", 0):,} bytes after.

## What changed in the package-2 rework

Forward packs use format 2.2: bounded LZ4 column blocks, dictionary IDs, FST
keys, implicit IP ends with gap rows, pooled strings and separate cold evidence.
Numeric columns can use lossless scaling, deltas and byte alignment; string
blocks choose direct, prefix or suffix coding. Detail strings share the name
pool, and airport keys reuse the base source assertion unless evidence differs.
Older forward minors 0 and 1 are rejected.

The final audit tightened size tests to count **all compressed blocks,
including evidence**. The earlier query-only check was insufficient. Expanded
samples exercise multiple full blocks; independent source extracts are gzip
JSON and remain available offline. No observations were discarded to meet the
gate. Before/after sample row counts differ and are retained in the JSON.

Catalogue misses use one record read, one contiguous offsets read and one text
read; evidence is fetched only on request. Exact geocode reuses its first FST
lookup. Fuzzy search uses bounded counters, cached trigram cardinalities and
bit-parallel edit distance; the later R4 work bounds its admitted candidate set.
Plate matching
prefilters with RegexSet before ordered capture extraction and scoring.

Ambiguity retains all shared flat fields across the complete candidate set,
before limits. Unlinked postal candidates inherit the source-key country with
`country_from_key` evidence. One inferred plate country is matched with its
ranking basis; several remain ambiguous. The unhinted UNKNOWN placeholder is
not_found. The plate contract changed {plate["changed_cases"]} shared vectors.
Source coordinates are now asserted by both legacy forward test runners.

## Python API

Top-level exports are Geocoder, reverse, Result and the coded error classes.
Results are frozen dataclasses. Queries do not download data.

```python
from pathlib import Path
from thereabouts import Geocoder

root = Path("tests/fixtures/packs")
with Geocoder(packs={{
    "core": root / "core-sample",
    "postal": root / "postal-sample",
    "airports": root / "airports-sample",
    "ip": root / "ip-sample",
}}) as geo:
    city = geo.geocode("Paris", country="FR")
    postal = geo.postal("75001", country="FR", evidence=True)
    airport = geo.airport("CDG")
    batch = geo.ip_columns(addresses=["8.8.8.8"])
```

Use reverse(lat=, lon=), from_h3(cell), reverse_many and reverse_columns for
reverse lookup. Forward verbs are postal(code, country=), airport(code, scheme=,
country=), locode(code, country=), phone(number), ip(address), plate(serial,
country=, series=) and geocode(name, country=, subdivision=, limit=,
prefer="population", scope="cities"). All accept evidence. Each forward verb
also has a columns method. Geocode finds towns and cities; street addresses
return unsupported_granularity, and code-shaped input names the appropriate
verb in its hint. Exact English spellings report alternate_name; prefix
completion and typo fallback report fuzzy.

Column batches release the GIL and fill fixed-width buffers while iterating.
Strings use int32 codes and categories; nullable numerics have _valid masks.
Forward candidate_offsets index flattened candidate columns. Reverse batches
omit candidates; all batches omit evidence.

Select paths explicitly or use data_dir, THEREABOUTS_DATA, then platform user
data. Existing packs/<family>/v-<version>/<digest>/ layouts and current.json
remain discoverable. Families open lazily and must share a dataset version.
Missing data raises the exact `thereabouts data install <family>` command;
the native installer is explicit through the data install command. Invalid
requests and misses are result
statuses; missing, incompatible, corrupt or closed data raise coded exceptions.
State fields come from subdivisions by code, with published place fields as
the fallback only when the table has no row.

## Writer dataset layout support

The writer accepts legacy per-block cell files and manifest-declared coalesced
resolution-1 groups, one Parquet row group per resolution-3 block. Spatial emission
selects only that block's row group. Tests cover multiple row groups, empty blocks,
byte-identical pack artifacts across layouts, malformed routing and input changes
before publication. Whole-file checksums run before first consumption and before
publication, without a repeated full hash for every block. No real dataset export
was performed for this change. PACK_FORMAT.md specifies the input contract.

## Inputs, samples and admission

The workspace separates thereabouts-core, thereabouts-writer, thereabouts-py
and the native-only thereabouts-cli library.
Core builds for wasm without Arrow, Parquet or SQLite. Writer ingestion uses
typed Arrow columns, bounded scans and SQLite staging. Required inputs and
counts are verified; missing tables require explicit fixture omissions. Changed
inputs cannot overwrite an existing output. Staging checks its output parent
and retains the disk floor. Full hashes and cold sections are checked with
verify=True or verify_pack; normal opening validates directories and loads
payloads on demand. Decoded-block caches are bounded per table, with separate
byte-bounded place and observation caches. Name indexes and plate rules are
resident. Open files must remain immutable.

Builders under tools select BE/NL/LU/FR/TR/IN/US where available. Postal uses
the first 1,024 distinct codes per country, airports/LOCODE 512, and IP 512
intervals per country/version, plus named examples and all observations for
selected keys. Manifests record this policy, source digests and dataset version.
The Google IPv6 interval is a documented CA/Montreal exception. INBOM is
included. Golden has no literal 9122 phone row: all six published Mumbai child
prefixes are retained instead. Kidarakulam/Karakulam supplies a real differing
English-name vector. The reverse sample retains its original geographic subset.

Forward/name packs total {fixture["total_bytes"]:,} bytes; compressed source
extracts use {fixture["source_extract_bytes"]:,} bytes. Packs, extracts and shared
vectors total {fixture["packs_extracts_vectors_bytes"]:,} bytes, below the fixture
budget. Builders are idempotent for the recorded inputs and writer revision.

## Conformance and validation

{legacy}

The original expectations are unchanged. Reverse explicitly maps miss reasons
and allows the coarse-cell acceptance and canonical display-name changes.
Forward allows the IATA/ICAO default remap for case 52, the canonical display
name, and case 29's source-key country fallback. Source identity, geography,
and source points remain asserted. Shared vectors assert candidate ordering.
Shared ambiguous context is checked in addition to each original candidate.

There are {len(reverse_vectors["cases"])} real reverse vectors and
{len(extract["queries"])} independent committed reverse source checks. The forward
table below lists real vector counts; synthetic vectors additionally cover
legacy codes, shared calling codes and alternate names. Pytest requires no real
data. Node execution awaits its binding package.

The full gate passed: {gates["rust_tests"]} Rust tests; {gates["pytest_passed"]}
pytest passed and {gates["pytest_skipped"]} skipped; strict mypy checked
{gates["mypy_files"]} files. Rustfmt, Clippy with all targets/features, Ruff check,
Ruff format and the wasm target check passed. Legacy reader and pipeline tests
remain included. Skipped tests are reported separately from passing checks.

## Measurements

Machine: {machine["chip"]}, {machine["memory_bytes"]:,} memory bytes,
Python {machine["python"]}; platform details are in the JSON. Numbers below are
script output, not hand-entered estimates. Reverse open time is
{core["open_seconds"] * 1000:.3f} ms; RSS delta is
{core["open_rss_delta_bytes"]:,} bytes.

| Reverse workload | Median / p99 µs | Batch points/s |
| --- | ---: | ---: |
{chr(10).join(current)}

{section(old, "forward-measurements")}

Random workloads visit all published sample keys, plus seeded repetitions.
Misses and default airport scheme searches are separate JSON workloads.
Postal/airport batches group required country/scheme options. Plate sample
batches cover code/country assertions; all-rule inference is measured below.

{section(old, "forward-format")}

The old column counts full legacy data shards. Current query/all columns count
compressed payloads; all includes evidence but excludes FST/container framing
and supporting tables. The enforced ceilings apply to all compressed blocks.
World estimates scale complete data artifacts, including evidence and FSTs.
IP/postal add historical measured world metadata only; their catalogue is now
shared with core and excluded. Other estimates add sample metadata. These remain
estimates, not measurements of new world exports. Estimates exclude manifests,
notices and unmeasured supporting-table growth. The geocode figure is a name-index
component estimate with sample catalogue/metadata, not a world spatial-core size.

{section(old, "world-exports")}

These are the two authorised world exports, made with writer 0.3.1 before the
final numeric/string refinements. They are measurements of that recorded
revision, not final-codec world measurements. Exact manifests are retained under
docs/measurements; both outputs were deleted. No second world export was run.
Postal's measured catalogue alone uses
{exports["postal"]["storage"]["catalogue_bytes"]:,} bytes in that historical export.
Current writer 0.4.0 forward packs omit that catalogue
entirely; the current estimates above use the new sample data bytes per row.
IPv6 low words are preserved; the measured export contains
{exports["ip"]["ipv6_nonzero_low64"]:,} nonzero low-word rows.

{section(old, "catalogue-reads")}

{section(old, "forward-scale")}

The historical package-2 scale run covered
{core["forward_scale"]["after"]["intervals"]:,} intervals
with gaps and {core["forward_scale"]["after"]["name_keys"]:,} name keys. Its uncapped
fuzzy profile is retained in
docs/measurements/geocode-profile.txt; it predates the million-key R4 measurements.

{section(old, "plates-rules")}

The all-rule benchmark retains original rule order and scoring. Its optimization
before/after pair has an identical evidence-inclusive digest; the final run also
includes the intended plate-status changes. It measures rule-count scaling with
sample code assertions and no vehicle priors.

## Reproduction, remaining work and boundaries

Run benchmarks.core_read_path with --output docs/CLIENT_CORE_MEASUREMENTS.json,
single_shard_read_path --record after, multishard_read_path --record after
--series catalogue_read_rework, forward_read_path for every family,
forward_sizes --check, shared_catalogue, cli_startup and
plates_world_rules --record final. Run the Rust forward_scale example into
.tmp/forward-scale before benchmarks.forward_scale --record after.
These scripts preload file bytes without populating decoded caches; earlier
filesystem-cache conditions remain labelled in measurement history.
No real world export is part of this refresh. Final scratch is removed after
the gate and status generation.
The retained historical measurements include the old reader and earlier rework
stages; workload and sample changes are explicit.

The real names table is pending; the tested alternate-name input can extend the
same index. Plate samples use read-only normalized/plates plus committed rules
because the requested plate-country release and vehicle priors were absent.
The pipeline's plates table will replace that adapter. Phone city/state output
needs pipeline prefix-to-place links: current real rows link only to countries;
Mumbai description evidence does not manufacture a city identity.

The final codec has not been world-exported. Other family world sizes are
estimates. Linux, Windows, other Python versions and the new Node binding were not run.
Node/WASM host integration is package 4; legacy Python cleanup is package 5.
The shared CLI policy is ready; the Node host and cleanup are still pending.
The default release URL is a placeholder; no public
release service or real-network data download was exercised. HTTPS uses rustls
certificate verification but live public-endpoint behavior was not tested.
Linux/Windows runtime behavior was not run. Legacy modules remain importable.

Only this worktree and normal shared Git metadata were written. The real data
tree was read-only; build_data source was unchanged. Export outputs were deleted.
Disk limits were respected. Nothing was pushed, published or uploaded.
Package-3 registry fetches were limited to authorized development dependencies;
all data transfer tests used loopback HTTP or local directories.
"""
    status.write_text(text)
    print(json.dumps(core["qualification"], indent=2))


if __name__ == "__main__":
    main()
