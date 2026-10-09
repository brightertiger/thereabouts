"""Release and store fixtures use only committed packs and temporary directories."""

import hashlib
import json
import os
import shutil
import subprocess
import sysconfig
from pathlib import Path
from typing import Any

from thereabouts import _core

FIXTURES = Path(__file__).parents[2] / "fixtures"
CONSOLE = Path(sysconfig.get_path("scripts")) / (
    "thereabouts.exe" if os.name == "nt" else "thereabouts"
)


def console(
    root: Path,
    *args: str,
    stdin: str = "",
    source: str | None = None,
    environ: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    for key in (
        "ALL_PROXY",
        "all_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "no_proxy",
    ):
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    if environ:
        env.update(environ)
    if source is not None:
        env["THEREABOUTS_RELEASE_URL"] = source
    return subprocess.run(
        [str(CONSOLE), "--data-dir", str(root), *args],
        input=stdin,
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
        check=False,
    )


def install_fixture(root: Path, source: Path) -> None:
    info = json.loads((source / "manifest.json").read_text())
    relative = Path("packs") / info["family"] / info["data_version"]
    destination = root / relative
    shutil.copytree(source, destination)
    pin_path = root / "active.json"
    pin = (
        json.loads(pin_path.read_text())
        if pin_path.exists()
        else {"data_version": info["data_version"], "packs": {}}
    )
    assert pin["data_version"] == info["data_version"]
    pin["packs"][info["family"]] = {
        "path": relative.as_posix(),
        "manifest_sha256": hashlib.sha256(
            (destination / "manifest.json").read_bytes()
        ).hexdigest(),
    }
    pin_path.write_text(json.dumps(pin))


def release(root: Path, family: str = "phone") -> dict[str, Any]:
    """A format-3 release directory built by the shared Rust archive writer."""
    source = FIXTURES / "packs" / f"{family}-sample"
    manifest = json.loads((source / "manifest.json").read_text())
    root.mkdir(parents=True, exist_ok=True)
    archive = root / f"{family}{_core.ARCHIVE_SUFFIX}"
    created = _core.archive_pack(str(source), str(archive))
    index = {
        "format": _core.INDEX_FORMAT,
        "datasets": {
            manifest["data_version"]: {
                "packs": {
                    family: {
                        "url": archive.name,
                        **created,
                        "format_minor": manifest["format_minor"],
                    }
                }
            }
        },
    }
    (root / "index.json").write_text(json.dumps(index))
    return index
