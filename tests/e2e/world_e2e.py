"""The world end-to-end test over a staged release (spec §9, steps 2 to 7).

Excluded from the default run (marker `world`). `scripts/vm/e2e.sh` runs it:

    THEREABOUTS_E2E_RELEASE=<staging root with dataset/ and packs/>
    THEREABOUTS_E2E_URL=<HTTP base of packs/; default: serve the release locally>
    THEREABOUTS_E2E_VERSION=<version; default: newest in packs/index.json>
    THEREABOUTS_E2E_WORK=<scratch for stores>  THEREABOUTS_E2E_REPORT=<report.md>
    THEREABOUTS_E2E_LAND / _OCEAN / _NAMES / _FORWARD / _CROSS (sample sizes)
    THEREABOUTS_E2E_PLATE_EXAMPLES=<JSON list of {country_code, plate}>
"""

import os
from pathlib import Path

import pytest

from . import driver

ENV = "THEREABOUTS_E2E_"


def setting(name: str, default: int) -> int:
    return int(os.environ.get(ENV + name, default))


@pytest.mark.world
def test_world_release_end_to_end(tmp_path: Path) -> None:
    release = os.environ.get(ENV + "RELEASE")
    if not release:
        pytest.skip("Set THEREABOUTS_E2E_RELEASE to a staged release directory")
    examples = os.environ.get(ENV + "PLATE_EXAMPLES")
    settings = driver.Settings(
        release=Path(release),
        work=Path(os.environ.get(ENV + "WORK", tmp_path / "work")),
        version=os.environ.get(ENV + "VERSION") or None,
        url=os.environ.get(ENV + "URL") or None,
        land_cells=setting("LAND", 10000),
        ocean_points=setting("OCEAN", 1000),
        names=setting("NAMES", 1000),
        forward_rows=setting("FORWARD", 500),
        cross_client=setting("CROSS", 1000),
        plate_examples=Path(examples) if examples else None,
    )
    report = driver.run(settings)
    target = Path(os.environ.get(ENV + "REPORT", tmp_path / "world-e2e.md"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(driver.markdown(report))
    failed = {step.name: step.error for step in report.steps if step.status == "fail"}
    assert report.passed, f"see {target}: {failed}"
