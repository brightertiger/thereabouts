"""The world end-to-end test (spec §9, steps 2 to 7) over a staged release.

`run(Settings)` serves `<release>/packs` over loopback HTTP (or uses a given
URL), installs every family through the Python console, the Node client and
the CLI at `ulimit -n 256`, then checks seeded reverse and forward samples, the
120 city points, plate examples, the world-safe vectors through each client,
cross-client JSON equality, the MCP server and every skill example. Each step
is recorded with its evidence; a failure never hides the later steps.
`markdown()` renders the report. The checks are the packs-stage acceptance
judges (`pipeline/release/acceptance.py`), with a different default seed.
"""

import asyncio
import csv
import functools
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from pipeline.config import load
from pipeline.config.release import AcceptanceSettings
from pipeline.release import acceptance, samples
from pipeline.release.samples import Query
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.jsonio import encode
from tests.client.cli.test_vectors import USAGE_CASES, arguments
from tests.skill import examples

Row = dict[str, Any]
FAMILIES = ("core", "postal", "airports", "locode", "phone", "ip", "plates")
NODE = REPOSITORY / "clients/node"
SKILL = REPOSITORY / "skills/thereabouts"
DOCUMENTS = [SKILL / "SKILL.md", SKILL / "references/query-recipes.md"]
TOOLS = {"coordinates": "reverse", "h3": "h3"}


@dataclass
class Settings:
    release: Path
    work: Path
    version: str | None = None
    url: str | None = None
    families: tuple[str, ...] = FAMILIES
    open_files: int = 256
    seed: int = 20261011
    land_cells: int = 10000
    ocean_points: int = 1000
    names: int = 1000
    forward_rows: int = 500
    cross_client: int = 1000
    city_points: Path | None = REPOSITORY / "eval/city_points/points.csv"
    plate_examples: Path | None = None
    timeout: int = 7200


@dataclass
class Step:
    name: str
    status: str = "pass"
    seconds: float = 0.0
    details: Row = field(default_factory=dict)
    error: str | None = None


@dataclass
class Report:
    settings: Settings
    version: str = ""
    base: str = ""
    steps: list[Step] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(step.status != "fail" for step in self.steps)

    def step(self, name: str) -> Step:
        return next(step for step in self.steps if step.name == name)


@contextmanager
def step(report: Report, name: str) -> Iterator[Step]:
    """Record a step; an exception fails it without stopping the run."""
    record = Step(name)
    report.steps.append(record)
    started = time.perf_counter()
    try:
        yield record
    except Exception as error:  # Reported in the step; later steps still run.
        record.status = "fail"
        record.error = f"{type(error).__name__}: {error}"
        record.details["traceback"] = traceback.format_exc(limit=4)
    finally:
        record.seconds = time.perf_counter() - started


def environment(base: str) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key.lower() not in {"all_proxy", "http_proxy", "https_proxy", "no_proxy"}
    }
    return env | {"NO_PROXY": "*", "THEREABOUTS_RELEASE_URL": base}


def command(
    argv: list[str], settings: Settings, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """`ulimit -n` lowers soft and hard limits, so no client can raise its own."""
    shell = f"ulimit -n {settings.open_files} && exec {shlex.join(argv)}"
    return subprocess.run(
        ["/bin/sh", "-c", shell],
        capture_output=True,
        text=True,
        env=env,
        timeout=settings.timeout,
        check=False,
    )


def checked(completed: subprocess.CompletedProcess[str]) -> Row:
    if completed.returncode != 0:
        raise AssertionError(
            f"exit {completed.returncode}: {completed.stderr.strip()[-1500:]}"
        )
    value = json.loads(completed.stdout) if completed.stdout.strip() else {}
    return value if isinstance(value, dict) else {"value": value}


def node() -> str | None:
    executable = shutil.which("node")
    if executable is None or not (NODE / "pkg/thereabouts_bg.wasm").exists():
        return None
    return executable


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return None


@contextmanager
def served(settings: Settings) -> Iterator[str]:
    """`python -m http.server` over the release's packs/, on loopback."""
    if settings.url:
        yield settings.url.rstrip("/") + "/"
        return
    handler = functools.partial(Quiet, directory=str(settings.release / "packs"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


def install(
    report: Report, name: str, argv: list[str], store: Path, env: dict[str, str]
) -> None:
    settings = report.settings
    with step(report, name) as record:
        started = time.perf_counter()
        installed = checked(
            command(
                [
                    *argv,
                    *("--data-dir", str(store), "--json", "data", "install"),
                    *settings.families,
                    "--yes",
                ],
                settings,
                env,
            )
        )
        record.details["install_seconds"] = time.perf_counter() - started
        started = time.perf_counter()
        verified = checked(
            command(
                [*argv, "--data-dir", str(store), "--json", "data", "verify", "--full"],
                settings,
                env,
            )
        )
        record.details["verify_seconds"] = time.perf_counter() - started
        update = checked(
            command(
                [
                    *argv,
                    "--data-dir",
                    str(store),
                    "--json",
                    "data",
                    "update",
                    "--check",
                ],
                settings,
                env,
            )
        )
        record.details |= {"active": installed, "verified": verified, "update": update}
        assert verified.get("verified") == "full", verified
        assert verified.get("packs") == len(settings.families), verified
        # The aggregate index lists this version and nothing newer.
        assert update.get("available_version") == report.version, update
        assert update.get("update_available") is False, update


def sizes(report: Report, store: Path, index: Row) -> None:
    with step(report, "sizes") as record:
        rows = []
        for family in report.settings.families:
            entry = index["datasets"][report.version]["packs"][family]
            installed = store / "packs" / family / report.version
            files = [p for p in installed.rglob("*") if p.is_file()]
            rows.append(
                {
                    "family": family,
                    "compressed": entry["size"],
                    "unpacked": entry["unpacked_size"],
                    "files": len(files),
                }
            )
        record.details["packs"] = rows


def probe_job(store: Path, queries: list[Query]) -> Row:
    return {"data_dir": str(store), "queries": [q.job() for q in queries]}


def run_node(
    settings: Settings, executable: str, job: Row, env: dict[str, str]
) -> tuple[dict[str, Row], Row]:
    settings.work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=settings.work, prefix=".node-") as temporary:
        source, target = Path(temporary) / "job.json", Path(temporary) / "out.ndjson"
        source.write_bytes(encode(job))
        script = str(Path(__file__).with_name("node_queries.mjs"))
        checked(command([executable, script, str(source), str(target)], settings, env))
        lines = [json.loads(line) for line in target.read_text().splitlines()]
    summary = lines.pop()["summary"]
    return {line["id"]: line for line in lines}, summary


def judged(
    report: Report,
    name: str,
    queries: list[Query],
    lines: dict[str, Row],
    accept: AcceptanceSettings,
) -> None:
    with step(report, name) as record:
        checks = acceptance.judge(queries, lines, accept)
        record.details["checks"] = checks
        failed = [check for check, value in checks.items() if not value["passed"]]
        assert not failed, f"checks below their minimum: {failed}"


def city_points(report: Report, store: Path, accept: AcceptanceSettings) -> None:
    settings = report.settings
    with step(report, "city-points") as record:
        if settings.city_points is None or not settings.city_points.is_file():
            record.status = "skip"
            record.details["reason"] = "no city points file"
            return
        with settings.city_points.open(newline="") as stream:
            points = list(csv.DictReader(stream))
        queries = [
            Query(
                f"city-{row['id']}",
                "city_points",
                "core",
                {
                    "kind": "coordinates",
                    "values": [float(row["latitude"]), float(row["longitude"])],
                },
                row,
            )
            for row in points
        ]
        lines, _ = acceptance.run_probe(
            probe_job(store, queries), accept, settings.work
        )
        totals: Counter[str] = Counter()
        correct: Counter[str] = Counter()
        misses = []
        for query in queries:
            row = query.expect
            city = (lines[query.id].get("result") or {}).get("city") or {}
            accepted = {row["expected_name"], *row["accepted_names"].split("|")}
            right = city.get(
                "id"
            ) == f"city:geonames:{row['expected_geonames_id']}" or (
                bool({city.get("name"), city.get("name_en")} & accepted)
            )
            for key in (row["split"], f"{row['split']}/{row['group']}"):
                totals[key] += 1
                correct[key] += right
            if not right:
                misses.append(
                    {
                        "id": row["id"],
                        "expected": row["expected_name"],
                        "found": city.get("name"),
                    }
                )
        record.details = {
            "correct": dict(sorted(correct.items())),
            "total": dict(sorted(totals.items())),
            "misses": misses,
        }


def plate_examples(report: Report, store: Path, accept: AcceptanceSettings) -> None:
    settings = report.settings
    with step(report, "plate-examples") as record:
        if settings.plate_examples is None:
            record.status = "skip"
            record.details["reason"] = (
                "the plate_country evaluation sources are not pinned; pass "
                "THEREABOUTS_E2E_PLATE_EXAMPLES (a JSON list of country_code, plate)"
            )
            return
        rows = json.loads(settings.plate_examples.read_text())
        queries = [
            Query(
                f"plate-{n:04d}",
                "plate_examples",
                "plates",
                {"kind": "plate", "values": [row["plate"]]},
                row,
                evidence=False,
            )
            for n, row in enumerate(rows)
        ]
        lines, _ = acceptance.run_probe(
            probe_job(store, queries), accept, settings.work
        )
        top1 = top3 = 0
        for query in queries:
            result = lines[query.id].get("result") or {}
            ranked = (
                [result]
                if result.get("status") == "matched"
                else result.get("candidates", [])
            )
            codes = [(answer.get("country") or {}).get("code") for answer in ranked]
            top1 += codes[:1] == [query.expect["country_code"]]
            top3 += query.expect["country_code"] in codes[:3]
        record.details = {"examples": len(queries), "top1": top1, "top3": top3}


def console(
    report: Report, store: Path, queries: list[Query], env: dict[str, str]
) -> dict[str, Row]:
    """Vector requests through the CLI (the Rust command tree via Python)."""
    lines: dict[str, Row] = {}
    for query in queries:
        case = query.id.removeprefix("vectors-")
        args = arguments(query.request)
        if any("\0" in arg for arg in args):
            continue  # OS argv cannot carry NUL; the libraries assert these.
        completed = command(
            [
                sys.executable,
                "-m",
                "thereabouts",
                "--data-dir",
                str(store),
                "--json",
                *args,
            ],
            report.settings,
            env,
        )
        usage = case in USAGE_CASES or (
            query.request["kind"] == "postal" and not query.request.get("country")
        )
        if usage:
            # The grammar refuses these before the core: exit 2, no result.
            ok = completed.returncode == 2 and not completed.stdout.strip()
            lines[query.id] = (
                {"result": query.expect["result"]}
                if ok
                else {"error": completed.stderr}
            )
            continue
        lines[query.id] = (
            {"result": json.loads(completed.stdout)}
            if completed.returncode in {0, 2} and completed.stdout.strip()
            else {"error": completed.stderr}
        )
    return lines


def tool(query: Query) -> str:
    kind = str(query.request["kind"])
    return TOOLS.get(kind) or kind


def tool_arguments(query: Query, schema: Row) -> Row:
    """A sample request as the MCP tool of the same verb takes it."""
    values = query.request["values"]
    if query.request["kind"] == "coordinates":
        return {"lat": values[0], "lon": values[1]}
    properties = schema.get("properties", {})
    value = next(iter(schema.get("required") or properties))
    options = {
        key: item
        for key, item in query.request.items()
        if key in properties and key not in {"kind", "values"} and item is not None
    }
    return {value: values[0], **options}


def text(result: Any) -> str:
    """The single text body of a read resource."""
    (content,) = result.contents
    return str(content.text)


async def mcp_session(report: Report, store: Path, queries: list[Query]) -> None:
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    settings = report.settings
    dataset = settings.release / "dataset" / report.version
    shell = shlex.join(
        [sys.executable, "-m", "thereabouts", "--data-dir", str(store), "mcp"]
    )
    server = StdioServerParameters(
        command="/bin/sh",
        args=["-c", f"ulimit -n {settings.open_files} && exec {shell}"],
        env=environment(report.base),
    )
    async with Client(server) as client:
        with step(report, "mcp") as record:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            resources = sorted(
                str(r.uri) for r in (await client.list_resources()).resources
            )
            document = await client.read_resource("thereabouts://dictionary")
            markdown = await client.read_resource("thereabouts://dictionary/markdown")
            record.details |= {"tools": sorted(tools), "resources": resources}
            # The installed core pack's dictionary, not the packaged copy.
            assert text(document) == (dataset / "data_dictionary.json").read_text()
            assert text(markdown) == (dataset / "DATA_DICTIONARY.md").read_text()
            calls = {}
            first: dict[str, Query] = {}
            if reverse := next((q for q in queries if q.check == "reverse"), None):
                first["h3"] = replace(
                    reverse, request={"kind": "h3", "values": [reverse.expect["cell"]]}
                )
            for query in queries:
                first.setdefault(tool(query), query)
            for name, definition in sorted(tools.items()):
                if name == "describe":
                    arguments_ = {"table": "cells"}
                else:
                    if name not in first:
                        raise AssertionError(f"no sample request for tool {name}")
                    schema = definition.input_schema or {}
                    arguments_ = tool_arguments(first[name], schema)
                result = await client.call_tool(name, arguments_)
                assert not result.is_error, f"{name} {arguments_}: {result.content}"
                content = result.structured_content or {}
                calls[name] = {"arguments": arguments_, "status": content.get("status")}
            record.details["calls"] = calls

        with step(report, "skill") as record:

            async def call_tool(name: str, arguments_: Row) -> Row:
                result = await client.call_tool(name, arguments_)
                assert not result.is_error, f"{name} {arguments_}: {result.content}"
                return dict(result.structured_content or {})

            ran = await examples.run_documents(
                DOCUMENTS, call_tool, str(dataset), verify=False
            )
            record.details["examples"] = ran


def run(settings: Settings) -> Report:
    report = Report(settings)
    settings.work.mkdir(parents=True, exist_ok=True)
    with served(settings) as base:
        report.base = base
        with urllib.request.urlopen(base + "index.json") as response:
            index = json.loads(response.read())
        report.version = settings.version or max(
            index["datasets"], key=lambda v: [int(p) for p in v.split(".")]
        )
        env = environment(base)
        python_store, node_store = settings.work / "python", settings.work / "node"
        python = [sys.executable, "-m", "thereabouts"]
        install(report, "install-python", python, python_store, env)
        executable = node()
        if executable is None:
            report.steps.append(
                Step(
                    "install-node",
                    "skip",
                    details={"reason": "Node client WASM is not built"},
                )
            )
        else:
            install(
                report,
                "install-node",
                [executable, str(NODE / "bin/thereabouts.js")],
                node_store,
                env,
            )
        sizes(report, python_store, index)
        accept = replace(
            load().release.acceptance,
            seed=settings.seed,
            open_files=settings.open_files,
            land_cells=settings.land_cells,
            ocean_points=settings.ocean_points,
            names=settings.names,
            forward_rows=settings.forward_rows,
            timeout_seconds=settings.timeout,
        )
        dataset = settings.release / "dataset" / report.version
        queries = samples.queries(dataset, accept, settings.families)
        lines: dict[str, Row] = {}
        with step(report, "python-queries") as record:
            lines, summary = acceptance.run_probe(
                probe_job(python_store, queries), accept, settings.work
            )
            record.details = {"queries": len(queries), **summary}
        sampled = [q for q in queries if q.check != "vectors"]
        vectors = [q for q in queries if q.check == "vectors"]
        judged(report, "reverse-and-forward", sampled, lines, accept)
        city_points(report, python_store, accept)
        plate_examples(report, python_store, accept)
        with step(report, "vectors") as record:
            clients = {
                "python": {q.id: lines.get(q.id, {"error": "missing"}) for q in vectors}
            }
            if executable is not None:
                clients["node"] = run_node(
                    settings, executable, probe_job(node_store, vectors), env
                )[0]
            clients["cli"] = console(report, python_store, vectors, env)
            for client, answers in clients.items():
                # The CLI cannot carry NUL in argv; it answers the rest.
                asked = [q for q in vectors if q.id in answers]
                record.details[client] = acceptance.judge(asked, answers, accept).get(
                    "vectors", {}
                )
            failed = [c for c in clients if not record.details[c].get("passed", True)]
            assert not failed, f"vectors disagree in: {failed}"
        with step(report, "cross-client") as record:
            if executable is None:
                record.status = "skip"
                record.details["reason"] = "Node client WASM is not built"
            else:
                stride = max(1, len(sampled) // max(1, settings.cross_client))
                chosen = sampled[::stride][: settings.cross_client]
                node_lines, summary = run_node(
                    settings, executable, probe_job(node_store, chosen), env
                )
                different = [
                    {"id": q.id, "path": found}
                    for q in chosen
                    if (
                        found := acceptance.difference(
                            node_lines[q.id].get("result"), lines[q.id].get("result")
                        )
                    )
                ]
                record.details = {
                    "queries": len(chosen),
                    "identical": len(chosen) - len(different),
                    "node": summary,
                    "different": different[:20],
                }
                assert not different, f"{len(different)} answers differ"
        try:
            asyncio.run(mcp_session(report, python_store, sampled))
        except Exception as error:  # A server that cannot start fails both steps.
            for name in ("mcp", "skill"):
                if not any(s.name == name for s in report.steps):
                    report.steps.append(
                        Step(name, "fail", error=f"{type(error).__name__}: {error}")
                    )
    return report


def table(header: list[str], rows: list[list[Any]]) -> list[str]:
    numeric = [
        all(isinstance(row[i], int | float) for row in rows) for i in range(len(header))
    ]
    return [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---:" if n else "---" for n in numeric) + " |",
        *("| " + " | ".join(cell(value) for value in row) + " |" for row in rows),
    ]


def cell(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value).replace("|", "\\|").replace("\n", " ")[:200]


def markdown(report: Report) -> str:
    settings = report.settings
    found = {item.name: item for item in report.steps}
    lines = [
        f"# Thereabouts end-to-end test: {report.version}",
        "",
        f"Result: **{'pass' if report.passed else 'FAIL'}**. Release "
        f"`{settings.release}` served at `{report.base}`; every client ran at "
        f"`ulimit -n {settings.open_files}`; sample seed {settings.seed}.",
        "",
        *table(
            ["Step", "Status", "Seconds", "Notes"],
            [
                [
                    i.name,
                    i.status,
                    round(i.seconds, 1),
                    i.error or i.details.get("reason", ""),
                ]
                for i in report.steps
            ],
        ),
    ]
    if "sizes" in found and "packs" in found["sizes"].details:
        lines += ["", "## Sizes", ""]
        lines += table(
            ["Family", "Compressed bytes", "Unpacked bytes", "Installed files"],
            [
                [p["family"], p["compressed"], p["unpacked"], p["files"]]
                for p in found["sizes"].details["packs"]
            ],
        )
    lines += ["", "## Timings", ""]
    for name in ("install-python", "install-node"):
        if name in found and found[name].status == "pass":
            d = found[name].details
            lines.append(
                f"- {name}: install {d['install_seconds']:.1f} s, "
                f"`data verify --full` {d['verify_seconds']:.1f} s"
            )
    for label, item, key in (
        ("Python", found.get("python-queries"), None),
        ("Node", found.get("cross-client"), "node"),
    ):
        if item is None or item.status != "pass":
            continue
        d = item.details[key] if key else item.details
        lines.append(
            f"- {label}: open {d['open_seconds']:.2f} s; {d['queries']} queries, "
            f"p50 {d['p50_ms']:.3f} ms, p99 {d['p99_ms']:.3f} ms"
        )
    checks = found.get("reverse-and-forward")
    if checks is not None and "checks" in checks.details:
        lines += ["", "## Reverse and forward checks", ""]
        lines += table(
            ["Check", "Samples", "Applicable", "Agreed", "Share", "Minimum"],
            [
                [
                    name,
                    c["samples"],
                    c["applicable"],
                    c["agreed"],
                    "n/a" if c["share"] is None else c["share"],
                    float(c["minimum"]),
                ]
                for name, c in checks.details["checks"].items()
            ],
        )
        for name, c in checks.details["checks"].items():
            for failure in c["failures"][:5]:
                lines.append(f"- {name} `{failure['id']}`: {cell(json.dumps(failure))}")
    points = found.get("city-points")
    if points is not None and "total" in points.details:
        d = points.details
        lines += ["", "## City points (reported, not gated)", ""]
        lines += table(
            ["Split / group", "Correct", "Total"],
            [
                [key, d["correct"].get(key, 0), total]
                for key, total in d["total"].items()
            ],
        )
        misses = ", ".join(f"{m['id']} → {m['found']}" for m in d["misses"][:60])
        lines += ["", f"Misses (expected city not returned): {misses or 'none'}."]
    plates = found.get("plate-examples")
    if plates is not None and plates.status == "pass":
        d = plates.details
        lines += [
            "",
            "## Plate examples",
            "",
            f"{d['top1']} of {d['examples']} top-1, {d['top3']} top-3.",
        ]
    vectors = found.get("vectors")
    if vectors is not None:
        lines += ["", "## World-safe vectors by client", ""]
        lines += table(
            ["Client", "Applicable", "Agreed"],
            [
                [client, value.get("applicable", 0), value.get("agreed", 0)]
                for client, value in vectors.details.items()
                if isinstance(value, dict) and "applicable" in value
            ],
        )
    cross = found.get("cross-client")
    if cross is not None and "queries" in cross.details:
        d = cross.details
        lines += [
            "",
            "## Cross-client JSON",
            "",
            f"{d['identical']} of {d['queries']} Python and Node answers are "
            "identical (coordinates within 1e-9 degrees).",
        ]
        lines += [f"- `{x['id']}` differs at `{x['path']}`" for x in d["different"]]
    mcp = found.get("mcp")
    if mcp is not None and "calls" in mcp.details:
        d = mcp.details
        lines += [
            "",
            "## MCP",
            "",
            f"Tools: {', '.join(d['tools'])}. Resources: "
            f"{', '.join(d['resources'])}; the dictionary is the installed core "
            "pack's.",
            "",
        ]
        lines += table(
            ["Tool", "Arguments", "Status"],
            [
                [n, json.dumps(c["arguments"]), c["status"]]
                for n, c in d["calls"].items()
            ],
        )
    skill = found.get("skill")
    if skill is not None and skill.status == "pass":
        lines += [
            "",
            "## Skill",
            "",
            f"{skill.details['examples']} examples from SKILL.md and "
            "query-recipes.md ran: MCP through the stdio server, SQL with DuckDB "
            "over the staged dataset.",
        ]
    for item in report.steps:
        if item.status == "fail" and "traceback" in item.details:
            lines += [
                "",
                f"## Failure: {item.name}",
                "",
                "```text",
                item.details["traceback"].strip(),
                "```",
            ]
    return "\n".join(lines) + "\n"
