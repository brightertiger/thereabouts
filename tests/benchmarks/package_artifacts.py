"""Build and smoke-test local release artifacts without publishing anything."""

import argparse
import json
import os
import platform
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Any

from pipeline.runtime.jsonio import sha256_file

ROOT = Path(__file__).resolve().parents[2]


def run(command: list[str], log: Path, cwd: Path = ROOT) -> None:
    with log.open("a") as stream:
        stream.write(json.dumps(command) + "\n")
        stream.flush()
        subprocess.run(
            command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, check=True
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT):
        parser.error("--output must be a new worktree-local directory")
    output.mkdir(parents=True)
    log = output / "build.log"
    # Explicit caches keep all installer/build writes inside this checkout.
    os.environ.update(
        CARGO_HOME=str(ROOT / ".cargo-cache"),
        CARGO_TARGET_DIR=str(ROOT / "core/target"),
        UV_CACHE_DIR=str(ROOT / ".cache/uv"),
        PIP_CACHE_DIR=str(ROOT / ".cache/pip"),
        npm_config_cache=str(ROOT / ".cache/npm"),
        TMPDIR=str(ROOT / ".tmp"),
    )
    run(
        [
            "uv",
            "run",
            "--no-sync",
            "maturin",
            "build",
            "--locked",
            "--release",
            "--out",
            str(output),
        ],
        log,
    )
    run(["uv", "run", "--no-sync", "maturin", "sdist", "--out", str(output)], log)
    sdist = next(output.glob("*.tar.gz"))
    with tarfile.open(sdist) as archive:
        names = archive.getnames()
        assert any(
            name.endswith("clients/python/thereabouts/README.md") for name in names
        )
        assert any(name.endswith("core/thereabouts-cli/Cargo.toml") for name in names)
        assert not any("/thereabouts/reading/" in name for name in names)
    environment = output / "fresh"
    run(["uv", "venv", "--seed", "--python", sys.executable, str(environment)], log)
    python = str(
        environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    wheel = next(output.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        metadata = archive.read(
            next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
        ).decode()
        assert "License-File:" not in metadata
        assert "Thereabouts for Python" in metadata
    run([python, "-m", "pip", "install", str(wheel)], log)
    run([python, str(ROOT / "tests/wheel_smoke.py")], log)
    rebuilt = output / "sdist-wheel"
    run(
        [
            python,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            str(sdist),
            "--wheel-dir",
            str(rebuilt),
        ],
        log,
    )
    run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--force-reinstall",
            "--no-deps",
            str(next(rebuilt.glob("*.whl"))),
        ],
        log,
    )
    run([python, str(ROOT / "tests/wheel_smoke.py")], log)
    run([python, "-m", "pip", "install", "--force-reinstall", "--no-deps", "."], log)
    run([python, str(ROOT / "tests/wheel_smoke.py")], log)
    run(["npm", "pack", "--pack-destination", str(output)], log, ROOT / "clients/node")
    tarball = next(output.glob("*.tgz"))
    consumer = output / "node"
    consumer.mkdir()
    run(["npm", "install", "--ignore-scripts", str(tarball)], log, consumer)
    code = """
import { Geocoder } from "thereabouts";
import assert from "node:assert/strict";
const geo = await Geocoder.open({pack: process.argv[1]});
assert.equal((await geo.reverse({lat:48.8566,lon:2.3522})).country.code, "FR");
await geo.close();
"""
    run(
        [
            "node",
            "--input-type=module",
            "-e",
            code,
            str(ROOT / "tests/fixtures/packs/core-sample"),
        ],
        log,
        consumer,
    )
    run(
        [
            "node",
            str(consumer / "node_modules/thereabouts/bin/thereabouts.js"),
            "--version",
        ],
        log,
        consumer,
    )
    artifacts: dict[str, Any] = {
        p.name: {"bytes": p.stat().st_size, "sha256": sha256_file(p)}
        for p in (wheel, sdist, tarball)
    }
    result = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "artifacts": artifacts,
        "checks": [
            "fresh pip install . no-data import/version",
            "wheel no-data import/version",
            "sdist wheel build and no-data import/version",
            "npm packed library lookup",
            "npm packed bin version",
        ],
        "remote_workflows_executed": False,
        "published": False,
    }
    (
        ROOT / "tests/benchmarks/measurements/CLIENT_PACKAGE_MEASUREMENTS.json"
    ).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
