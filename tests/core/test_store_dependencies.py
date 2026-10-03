"""Core discovery must import without the soon-to-be-removed legacy runtime."""

import subprocess
import sys
from pathlib import Path


def test_core_import_does_not_load_legacy_readers() -> None:
    program = """
import sys
from thereabouts import Geocoder
from thereabouts.store import core_pack
legacy = ("thereabouts.packs", "thereabouts.reading")
assert not any(name.startswith(legacy) for name in sys.modules)
"""
    subprocess.run([sys.executable, "-c", program], check=True)


def test_legacy_pointer_raises_new_error_without_reading_legacy_pack(
    tmp_path: Path,
) -> None:
    import pytest

    from thereabouts import IncompatibleDataError
    from thereabouts.store import core_pack

    pointer = tmp_path / "packs/reverse/current.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_text("{}")
    with pytest.raises(IncompatibleDataError):
        core_pack(tmp_path)


def test_unsafe_core_pointer_has_current_error_code(tmp_path: Path) -> None:
    import pytest

    from thereabouts import CorruptPackError
    from thereabouts.store import core_pack

    outside = tmp_path / "other.json"
    outside.write_text("{}")
    pointer = tmp_path / "packs/core/current.json"
    pointer.parent.mkdir(parents=True)
    pointer.symlink_to(outside)
    with pytest.raises(CorruptPackError) as caught:
        core_pack(tmp_path)
    assert caught.value.code == "corrupt_pack"
