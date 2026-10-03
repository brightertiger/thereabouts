"""Run inside a fresh installed wheel environment, without any data dependency."""

import importlib.util
import os
import subprocess
import sysconfig
import tempfile
from pathlib import Path

import thereabouts


def main() -> None:
    assert thereabouts.Geocoder.__module__ == "thereabouts.geocoder"
    for name in ("api", "client", "packs", "reading", "commandline", "installing"):
        assert importlib.util.find_spec(f"thereabouts.{name}") is None, name
    with tempfile.TemporaryDirectory() as directory:
        env = os.environ | {"THEREABOUTS_DATA": directory}
        result = subprocess.run(
            [
                str(
                    Path(sysconfig.get_path("scripts"))
                    / ("thereabouts.exe" if os.name == "nt" else "thereabouts")
                ),
                "--version",
            ],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == "thereabouts 0.1.0", result.stdout
        assert not list(Path(directory).iterdir())
    print("Installed package imports and reports its version without data.")


if __name__ == "__main__":
    main()
