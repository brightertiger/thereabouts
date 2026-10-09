"""Run each client host in a child process, optionally under a lowered fd limit."""

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
NODE_CLIENT = ROOT / "clients/node"


def _environment() -> dict[str, str]:
    env = dict(os.environ)
    for key in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy"):
        env.pop(key, None)
    for key in ("HTTPS_PROXY", "https_proxy", "no_proxy"):
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    return env


def run(
    argv: list[str], *, open_files: int | None = None, timeout: float = 300
) -> subprocess.CompletedProcess[str]:
    """`ulimit -n` lowers soft and hard limits, so no host can raise its own."""
    command = shlex.join(argv)
    if open_files is not None:
        command = f"ulimit -n {open_files} && exec {command}"
    return subprocess.run(
        ["/bin/sh", "-c", command],
        text=True,
        capture_output=True,
        env=_environment(),
        timeout=timeout,
        check=False,
    )


def python(
    script: str, *args: str, open_files: int | None = None
) -> subprocess.CompletedProcess[str]:
    return run([sys.executable, "-c", script, *args], open_files=open_files)


def console(
    *args: str, open_files: int | None = None
) -> subprocess.CompletedProcess[str]:
    return run([sys.executable, "-m", "thereabouts", *args], open_files=open_files)


def node_available() -> str:
    """Node tests need the built WASM package; CI's Python job does not build it."""
    executable = shutil.which("node")
    if executable is None or not (NODE_CLIENT / "pkg/thereabouts_bg.wasm").exists():
        pytest.skip("Node client WASM package is not built")
    return executable


def node(
    script: str, *args: str, open_files: int | None = None
) -> subprocess.CompletedProcess[str]:
    executable = node_available()
    return run(
        [executable, "--input-type=module", "-e", script, *args],
        open_files=open_files,
    )


def node_console(
    *args: str, open_files: int | None = None
) -> subprocess.CompletedProcess[str]:
    executable = node_available()
    return run(
        [executable, str(NODE_CLIENT / "bin/thereabouts.js"), *args],
        open_files=open_files,
    )
