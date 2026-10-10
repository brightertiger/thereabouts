"""Accept a pack only after the real reader answers what its dataset requires.

For each family the packs stage opens the new pack in a child process at the
configured open-file limit (`probe.py`), verifies it in full, and answers seeded
queries drawn from the dataset (`samples.py`). Each check must agree on at least
its configured share of applicable samples. The report is deterministic: no
timings, which go to the run log instead.
"""

import json
import math
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from pipeline.config.release import AcceptanceSettings
from pipeline.engines.artifacts import read_json
from pipeline.runtime.jsonio import encode, write_json

from . import probe, samples
from .samples import GEOCODE_LIMIT, Query
from .source import Row

FORMAT = "thereabouts-acceptance-1"
IDS = ("country_id", "state_id", "city_id")
FOUND = {"matched", "ambiguous"}
REFUSED = {"invalid_input", "unsupported_granularity"}
COORDINATE_TOLERANCE = 1e-9


def answers(result: Row) -> list[Row]:
    """The matched result itself, or each ranked candidate."""
    return [result] if result["status"] == "matched" else list(result["candidates"])


def evidence(answer: Row) -> Row:
    return answer.get("evidence") or {}


def reverse(query: Query, result: Row) -> bool | None:
    return all(evidence(result).get(key) == query.expect[key] for key in IDS)


def ocean(query: Query, result: Row) -> bool | None:
    return result["status"] == "not_found" and evidence(result).get("reason") == (
        "no_land"
    )


def named(query: Query, result: Row) -> bool | None:
    if result["status"] in REFUSED:
        # The reader refuses this text as a query, before any lookup.
        return None
    found = {(a.get("city") or {}).get("id") for a in answers(result)}
    if query.expect["city_id"] in found:
        return True
    # More same-named cities than one query returns: not a pack defect.
    return None if len(result["candidates"]) >= GEOCODE_LIMIT else False


def observed(query: Query, result: Row) -> bool | None:
    if result["status"] == "invalid_input" and query.check.startswith("airports"):
        # The writer skips a code its normalization refuses, as the reader does.
        return None
    expected = tuple(query.expect[key] for key in IDS)
    return result["status"] in FOUND and any(
        tuple(evidence(a).get(key) for key in IDS) == expected for a in answers(result)
    )


def phone(query: Query, result: Row) -> bool | None:
    return result["status"] in FOUND and any(
        evidence(a).get("country_id") in query.expect["countries"]
        for a in answers(result)
    )


def plates(query: Query, result: Row) -> bool | None:
    """The country's format matched and read the known code from its code group.

    With a country the reader always answers that country, so the format hit is
    the evidence; whether a code then resolves to a place is plate policy.
    """
    code = folded(query.expect["code"])
    return result["status"] in FOUND and any(
        (a.get("country") or {}).get("code") == query.expect["country"]
        and any(
            source.get("source") == "plate_format"
            and folded(str(source.get("code") or "")) == code
            for source in evidence(a).get("source_ids") or []
        )
        for a in answers(result)
    )


def folded(code: str) -> str:
    return "".join(code.split()).upper()


def difference(actual: Any, expected: Any, path: str = "$") -> str | None:
    """The first differing path; coordinates agree within 1e-9 degrees."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or actual.keys() != expected.keys():
            return path
        for key, value in expected.items():
            if (
                key in {"lat", "lon"}
                and isinstance(value, float)
                and isinstance(actual[key], float)
            ):
                if not math.isclose(
                    actual[key], value, rel_tol=0, abs_tol=COORDINATE_TOLERANCE
                ):
                    return f"{path}.{key}"
            elif found := difference(actual[key], value, f"{path}.{key}"):
                return found
        return None
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return path
        for number, (left, right) in enumerate(zip(actual, expected, strict=True)):
            if found := difference(left, right, f"{path}[{number}]"):
                return found
        return None
    return None if actual == expected else path


def vectors(query: Query, result: Row) -> bool | None:
    return difference(result, query.expect["result"]) is None


JUDGES: dict[str, Callable[[Query, Row], bool | None]] = {
    "reverse": reverse,
    "ocean": ocean,
    "names": named,
    "alternate_names": named,
    "postal": observed,
    "airports_iata": observed,
    "airports_icao": observed,
    "locode": observed,
    "ip_v4": observed,
    "ip_v6": observed,
    "phone": phone,
    "plates": plates,
    "vectors": vectors,
}


def run_probe(
    job: Row, settings: AcceptanceSettings, scratch: Path
) -> tuple[dict[str, Row], Row]:
    """Answer the job in a child process at the configured open-file limit."""
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch, prefix=".probe-") as temporary:
        source, target = Path(temporary) / "job.json", Path(temporary) / "out.ndjson"
        source.write_bytes(encode(job))
        command = shlex.join(
            [sys.executable, "-I", probe.__file__, str(source), str(target)]
        )
        completed = subprocess.run(
            ["/bin/sh", "-c", f"ulimit -n {settings.open_files} && exec {command}"],
            capture_output=True,
            text=True,
            timeout=settings.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            raise ValueError(
                f"Pack probe failed at ulimit -n {settings.open_files}: "
                + completed.stderr.strip()[-2000:]
            )
        lines = [json.loads(line) for line in target.read_text().splitlines()]
    summary = lines.pop()["summary"]
    return {line["id"]: line for line in lines}, summary


def judge(
    queries: Iterable[Query], lines: dict[str, Row], settings: AcceptanceSettings
) -> dict[str, Row]:
    checks: dict[str, Row] = {}
    for query in queries:
        check = checks.setdefault(
            query.check,
            {"samples": 0, "applicable": 0, "agreed": 0, "failures": []},
        )
        check["samples"] += 1
        line = lines.get(query.id, {"error": "no answer"})
        verdict = (
            False
            if "result" not in line
            else JUDGES[query.check](query, line["result"])
        )
        if verdict is None:
            continue
        check["applicable"] += 1
        check["agreed"] += verdict
        if not verdict and len(check["failures"]) < settings.failures_kept:
            check["failures"].append(
                {
                    "id": query.id,
                    "request": query.request,
                    "expect": query.expect,
                    "answer": line.get("result", line.get("error")),
                }
            )
    for name, check in checks.items():
        minimum = settings.minimum[name]
        share = check["agreed"] / check["applicable"] if check["applicable"] else None
        check |= {
            "minimum": minimum,
            "share": share,
            "passed": share is None or share >= minimum,
        }
    return dict(sorted(checks.items()))


def accept(
    dataset: Path,
    packs: Path,
    family: str,
    version: str,
    settings: AcceptanceSettings,
    log: Callable[[str], None] = print,
) -> Path:
    """Probe `packs/<family>`; return its report, or raise naming the failures."""
    queries = samples.queries(dataset, settings, [family])
    selection = {family: str(packs / family)}
    if family != "core":
        # Forward answers are enriched from the release's core catalogue.
        selection["core"] = str(packs / "core")
    job = {
        "packs": selection,
        "verify": {family: str(packs / family)},
        "queries": [query.job() for query in queries],
    }
    lines, summary = run_probe(job, settings, packs)
    log(
        f"acceptance {version}/{family}: verify {summary['verify_seconds']:.1f} s, "
        f"open {summary['open_seconds']:.2f} s, {summary['queries']} queries, "
        f"p50 {summary['p50_ms'] or 0:.2f} ms, p99 {summary['p99_ms'] or 0:.2f} ms "
        f"at ulimit -n {summary['open_files']}"
    )
    manifest = read_json(packs / family / "manifest.json")
    checks = judge(queries, lines, settings)
    report: Row = {
        "format": FORMAT,
        "family": family,
        "version": version,
        "open_files": settings.open_files,
        "seed": settings.seed,
        "pack": {
            "files": len(manifest["files"]) + 1,
            "bytes": sum(record["size"] for record in manifest["files"]),
            "verified": summary["verified"].get(family, False),
        },
        "checks": checks,
    }
    report["passed"] = report["pack"]["verified"] and all(
        check["passed"] for check in checks.values()
    )
    target = packs / "acceptance" / f"{family}.json"
    failed = target.with_suffix(".failed.json")
    if not report["passed"]:
        write_json(failed, report)
        broken = [name for name, check in checks.items() if not check["passed"]]
        raise ValueError(
            f"Pack acceptance failed for {version}/{family}: "
            f"{broken or ['verification']}; see {failed}"
        )
    failed.unlink(missing_ok=True)
    write_json(target, report)
    return target
