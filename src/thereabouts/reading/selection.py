"""Explicit multi-pack selection, with compatibility checked before use."""

from collections.abc import Mapping, Sequence
from pathlib import Path

from ..client_errors import IncompatibleDataError, InvalidInputError
from ..errors import DataNotInstalledError, GeocoderError
from ..packs.keys import FAMILIES
from ..store import installed_pack
from .pack import Pack

Selection = Mapping[str, str | Path] | Sequence[str]


def require(packs: dict[str, Pack], family: str) -> Pack:
    if family not in packs:
        raise DataNotInstalledError(
            f"Open an explicitly installed {family} pack for this lookup"
        )
    return packs[family]


def open_packs(
    pack: str | Path | None,
    data_dir: str | Path | None,
    selection: Selection | None,
    verify: bool,
    cache_bytes: int,
) -> dict[str, Pack]:
    if pack is not None and (data_dir is not None or selection is not None):
        raise InvalidInputError("Select a pack directory or a pack collection")
    if isinstance(selection, Mapping):
        if data_dir is not None:
            raise InvalidInputError(
                "Explicit pack paths cannot be combined with a data store"
            )
        paths = dict(selection)
    elif pack is not None:
        paths = {"": pack}
    else:
        families = ("reverse",) if selection is None else selection
        if (
            isinstance(families, str)
            or not families
            or any(not isinstance(family, str) for family in families)
            or len(set(families)) != len(families)
        ):
            raise InvalidInputError("Select distinct pack families")
        if any(family not in FAMILIES for family in families):
            raise InvalidInputError("Unknown pack family")
        paths = {family: installed_pack(data_dir, family=family) for family in families}
    if (
        not paths
        or any(family not in FAMILIES for family in paths if pack is None)
        or any(not isinstance(path, (str, Path)) for path in paths.values())
    ):
        raise InvalidInputError("Select known pack families")
    opened: dict[str, Pack] = {}
    try:
        for family, path in paths.items():
            reader = Pack(
                Path(path), verify=verify, cache_bytes=cache_bytes // len(paths)
            )
            actual = reader.manifest["family"]
            if (family and actual != family) or actual in opened:
                reader.close()
                raise IncompatibleDataError(
                    "Selected path has the wrong or a repeated family"
                )
            opened[actual] = reader
        signatures = {
            tuple(
                reader.manifest[key]
                for key in (
                    "catalogue_epoch",
                    "golden_sha256",
                    "policy_sha256",
                    "h3_version",
                )
            )
            for reader in opened.values()
        }
        if len(signatures) != 1:
            raise IncompatibleDataError(
                "Packs must share a catalogue epoch, golden snapshot, "
                "policy and H3 version"
            )
    except (OSError, ValueError, GeocoderError):
        for reader in opened.values():
            reader.close()
        raise
    return opened
