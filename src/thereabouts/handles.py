"""Own explicitly selected family handles and enforce one dataset version."""

from collections.abc import Mapping
from pathlib import Path

from . import _core
from .errors import ClosedGeocoderError, DataNotInstalledError, IncompatibleDataError
from .store import active_pack


class Handles:
    def __init__(
        self,
        pack: str | Path | None,
        packs: Mapping[str, str | Path] | None,
        data_dir: str | Path | None,
        verify: bool,
    ) -> None:
        if pack is not None and (data_dir is not None or packs is not None):
            raise ValueError("Select pack or data_dir/packs, not both")
        self.paths = dict(packs or {})
        self.data_dir = data_dir
        self.verify = verify
        self.version: str | None = None
        self.readers: dict[str, _core.Geocoder] = {}
        self.closed = False
        if pack is not None:
            info = _core.pack_info(str(pack))
            self.paths[info["family"]] = pack
            self.get(info["family"])
        elif packs:
            # Validate the whole explicit selection even before a family is queried.
            for family, path in self.paths.items():
                self._identity(family, path)
        else:
            for family in ("core", "postal", "airports", "locode", "phone"):
                try:
                    self.get(family)
                except DataNotInstalledError:
                    continue
                break
            else:
                raise DataNotInstalledError("thereabouts data install core")

    def _identity(self, family: str, path: str | Path) -> None:
        info = _core.pack_info(str(path))
        if info["family"] != family:
            raise IncompatibleDataError(f"Requires a {family} pack")
        version: str = info["data_version"]
        if self.version is not None and version != self.version:
            raise IncompatibleDataError("Pack dataset versions must agree")
        self.version = version

    def get(self, family: str) -> _core.Geocoder:
        if self.closed:
            raise ClosedGeocoderError("Geocoder is closed")
        if family not in self.readers:
            path = self.paths.get(family)
            if path is None:
                path = active_pack(self.data_dir, family=family)
            self._identity(family, path)
            self.readers[family] = _core.open(str(path), verify=self.verify)
        return self.readers[family]

    def close(self) -> None:
        for reader in self.readers.values():
            reader.close()
        self.closed = True
