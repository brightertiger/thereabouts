"""Answer acceptance queries with the installed client, as an application would.

`python probe.py JOB OUTPUT` runs in a child process under a lowered open-file
limit. It imports only the standard library and `thereabouts`, opens the packs
(explicit paths or an installed data directory), optionally verifies each pack
in full, and writes one JSON line per query, then a summary line.
"""

import json
import resource
import sys
import time
from pathlib import Path
from typing import Any

Row = dict[str, Any]


def call(geo: Any, request: Row, evidence: bool) -> Any:
    """The shared-vector request mapping used by every client's conformance runner."""
    kind, values = request["kind"], request["values"]
    options = {
        key: value
        for key, value in request.items()
        if key not in {"kind", "values"} and value is not None
    }
    if kind == "coordinates":
        return geo.reverse(lat=values[0], lon=values[1], evidence=evidence)
    if kind == "h3":
        return geo.from_h3(values[0], evidence=evidence)
    if kind == "ip":
        return geo.ip(values[0], evidence=evidence)
    return getattr(geo, kind)(values[0], evidence=evidence, **options)


def main(argv: list[str]) -> int:
    from thereabouts import Geocoder, _core

    job = json.loads(Path(argv[1]).read_text())
    verified = {}
    started = time.perf_counter()
    for family, path in sorted(job.get("verify", {}).items()):
        verified[family] = _core.verify_pack(path)["family"] == family
    verify_seconds = time.perf_counter() - started
    started = time.perf_counter()
    geo = (
        Geocoder(packs=job["packs"])
        if job.get("packs")
        else Geocoder(data_dir=job["data_dir"])
    )
    open_seconds = time.perf_counter() - started
    latencies = []
    with geo, Path(argv[2]).open("w") as output:
        for query in job["queries"]:
            started = time.perf_counter()
            try:
                line = {
                    "id": query["id"],
                    "result": call(geo, query["request"], query["evidence"]).to_dict(),
                }
            except Exception as error:  # Reported per query; the judge decides.
                line = {"id": query["id"], "error": f"{type(error).__name__}: {error}"}
            latencies.append(time.perf_counter() - started)
            output.write(json.dumps(line, ensure_ascii=False) + "\n")
        latencies.sort()
        summary = {
            "summary": {
                "open_files": resource.getrlimit(resource.RLIMIT_NOFILE)[0],
                "verified": verified,
                "verify_seconds": verify_seconds,
                "open_seconds": open_seconds,
                "queries": len(latencies),
                "p50_ms": 1000 * latencies[len(latencies) // 2] if latencies else None,
                "p99_ms": 1000 * latencies[(99 * len(latencies)) // 100]
                if latencies
                else None,
            }
        }
        output.write(json.dumps(summary) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
