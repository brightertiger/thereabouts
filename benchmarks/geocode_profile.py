"""Sample a symbol-bearing Rust query loop; keep attribution separate from timings."""

import json
import platform
import subprocess
from pathlib import Path

from benchmarks.core_read_path import ROOT


def main() -> None:
    subprocess.run(
        [
            "cargo",
            "rustc",
            "--release",
            "-p",
            "thereabouts-core",
            "--example",
            "geocode_profile",
            "--",
            "-C",
            "strip=none",
        ],
        cwd=ROOT / "core",
        check=True,
    )
    path = ROOT / ".tmp/geocode-profile.txt"
    with subprocess.Popen(
        [str(ROOT / "core/target/release/examples/geocode_profile")],
        stdout=subprocess.PIPE,
        text=True,
    ) as process:
        if platform.system() == "Darwin":
            subprocess.run(
                ["sample", str(process.pid), "3", "-file", str(path)], check=True
            )
        stdout, _ = process.communicate()
        if process.returncode:
            raise RuntimeError("Profiling loop failed")
    normalization = int(stdout.strip().split("=")[1])
    data_path = ROOT / "docs/measurements/CLIENT_CORE_MEASUREMENTS.json"
    data = json.loads(data_path.read_text())
    data["geocode_profile"] = {
        "normalization_ns_per_call": normalization,
        "normalization_calls": 100000,
        "normalization_input": "Utrecht",
        "cpu_workload": ["Utrecht (NL)", "Springfield", "Utrechx (NL)"],
        "cpu_sample": str(path.relative_to(ROOT)),
    }
    data_path.write_text(json.dumps(data, indent=2) + "\n")
    # Preserve reproducible native attribution, without machine-specific binary paths.
    if path.exists():
        lines = path.read_text().splitlines()
        symbols = [line.strip() for line in lines if "thereabouts_core" in line]
        report = Path("docs/measurements/geocode-profile.txt")
        (ROOT / report).write_text("\n".join(symbols) + "\n")
    print(json.dumps(data["geocode_profile"], indent=2))


if __name__ == "__main__":
    main()
