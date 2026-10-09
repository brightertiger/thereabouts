"""Descriptor exhaustion is an environment limit, never reported as corruption."""

import json
from pathlib import Path

from tests.client.cli.helpers import install_fixture
from tests.client.hosts import NODE_CLIENT, node, python

PACK = Path(__file__).parents[2] / "fixtures/packs/core-synthetic"
# Fill the descriptor table before opening anything, as an embedding host might.
EXHAUST = """
import errno, os, resource
soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
resource.setrlimit(resource.RLIMIT_NOFILE, (64, hard))
held = []
try:
    while True:
        held.append(os.open(os.devnull, os.O_RDONLY))
except OSError as error:
    assert error.errno == errno.EMFILE, error
"""


def test_python_open_reports_resource_limit() -> None:
    script = f"""
import sys
from thereabouts import Geocoder, GeocoderError, ResourceLimitError
{EXHAUST}
try:
    Geocoder(sys.argv[1])
except ResourceLimitError as error:
    assert isinstance(error, OSError) and isinstance(error, GeocoderError)
    assert error.code == "resource_limit"
    print(error)
else:
    raise SystemExit("opened without descriptors")
"""
    result = python(script, str(PACK))
    assert result.returncode == 0, result.stderr
    assert "open-file limit" in result.stdout


def test_cli_exit_code_is_distinct_from_integrity(tmp_path: Path) -> None:
    install_fixture(tmp_path, PACK)
    script = f"""
import sys
from thereabouts import _core
{EXHAUST}
sys.exit(_core.run_cli(["thereabouts", "--data-dir", sys.argv[1],
    "reverse", "--lat", "12.97", "--lon", "77.59"]))
"""
    result = python(script, str(tmp_path))
    assert result.returncode == 6, (result.returncode, result.stderr)
    assert "ulimit -n" in result.stderr
    assert "verify --full" not in result.stderr


def test_node_open_reports_resource_limit() -> None:
    runtime = json.dumps((NODE_CLIENT / "runtime/index.js").as_uri())
    loader = json.dumps((NODE_CLIENT / "runtime/wasm.js").as_uri())
    script = f"""
import fs from "node:fs";
const {{ Geocoder, ResourceLimitError }} = await import({runtime});
await (await import({loader})).wasm();  // module bytes are read before exhaustion
const held = [];
try {{ for (;;) held.push(fs.openSync("/dev/null", "r")); }}
catch (e) {{ if (e.code !== "EMFILE") throw e; }}
let outcome = "opened";
try {{
  const geo = await Geocoder.open({{ pack: process.argv[1] }});
  await geo.reverse({{ lat: 12.97, lon: 77.59 }});
}} catch (e) {{
  if (!(e instanceof ResourceLimitError)) throw e;
  outcome = `${{e.exitCode}} ${{e.message}}`;
}}
held.forEach((fd) => fs.closeSync(fd));  // stdout itself needs a descriptor
console.log(outcome);
"""
    result = node(script, str(PACK), open_files=64)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("6 "), result.stdout
    assert "ulimit -n" in result.stdout
