"""Read-only array mappings, structure checks and on-demand text decoding."""

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from pyofflinegeocoder.errors import DamagedPackError

from .manifest import read_manifest
from .schema import ARRAY_DTYPES, LAYERS

Array = NDArray[Any]


class Pack:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.manifest = read_manifest(path)
        self.arrays: dict[str, Array] = {}
        try:
            for name, dtype in ARRAY_DTYPES.items():
                file = path / f"{name}.npy"
                if file.stat().st_size != self.manifest["files"][file.name]["size"]:
                    raise ValueError(f"incorrect file size: {file.name}")
                array = np.load(file, mmap_mode="r", allow_pickle=False)
                if not isinstance(array, np.memmap):
                    array.close()
                    raise ValueError(f"expected an uncompressed NPY array: {file.name}")
                self.arrays[name] = array
                dimensions = 2 if name in ("coordinates", "xyz") else 1
                if array.dtype != dtype or array.ndim != dimensions:
                    raise ValueError(f"invalid dtype or dimensions: {file.name}")
                if array.offset + array.nbytes != file.stat().st_size:
                    raise ValueError(f"invalid array length: {file.name}")
            self._validate_structure()
        except (OSError, ValueError, TypeError, EOFError) as exc:
            self.close()
            raise DamagedPackError(f"Invalid pack arrays: {exc}") from exc

    def _validate_structure(self) -> None:
        self._offsets("text")
        for layer in LAYERS:
            self._offsets(layer, blob=f"{layer}_wkb")
            owners = self.arrays[f"{layer}_owners"]
            if len(owners) + 1 != len(self.arrays[f"{layer}_offsets"]):
                raise ValueError(f"invalid {layer} owner count")
            limit = len(self.arrays["countries" if layer == "country" else "admin1"])
            if layer != "land" and np.any((owners < 0) | (owners >= limit)):
                raise ValueError(f"invalid {layer} owners")
        count = len(self.arrays["places"])
        if self.arrays["coordinates"].shape != (count, 2) or self.arrays[
            "xyz"
        ].shape != (count, 3):
            raise ValueError("invalid settlement coordinate dimensions")
        text_count = len(self.arrays["text_offsets"]) - 1
        for name, fields in (
            ("countries", ("id", "name", "code")),
            ("admin1", ("id", "name", "code")),
            ("places", ("name", "feature", "country", "admin1")),
        ):
            if any(np.any(self.arrays[name][field] >= text_count) for field in fields):
                raise ValueError(f"invalid text references: {name}")
        parents = self.arrays["admin1"]["parent"]
        if np.any((parents < -1) | (parents >= len(self.arrays["countries"]))):
            raise ValueError("invalid parent references")
        if np.any(self.arrays["countries"]["subdivisions"] > 2):
            raise ValueError("invalid subdivision coverage state")

    def _offsets(self, prefix: str, *, blob: str | None = None) -> None:
        offsets = self.arrays[f"{prefix}_offsets"]
        size = len(self.arrays[blob or prefix])
        if not len(offsets) or offsets[0] != 0 or offsets[-1] != size:
            raise ValueError(f"invalid {prefix} offsets")
        if np.any(offsets[1:] < offsets[:-1]):
            raise ValueError(f"nonmonotone {prefix} offsets")

    def text(self, index: int) -> str:
        offsets = self.arrays["text_offsets"]
        start, stop = int(offsets[index]), int(offsets[index + 1])
        try:
            return self.arrays["text"][start:stop].tobytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DamagedPackError("Invalid UTF-8 in text pool") from exc

    def verify(self) -> None:
        try:
            for name, entry in self.manifest["files"].items():
                with (self.path / name).open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                if digest != entry["sha256"]:
                    raise ValueError(f"checksum mismatch: {name}")
            self._validate_structure()
            for index in range(len(self.arrays["text_offsets"]) - 1):
                self.text(index)
        except (OSError, ValueError) as exc:
            raise DamagedPackError(f"Pack verification failed: {exc}") from exc

    def close(self) -> None:
        for array in self.arrays.values():
            # NumPy exposes no public memmap close; no view escapes this package.
            mapping = getattr(array, "_mmap", None)
            if mapping is not None:
                mapping.close()
        self.arrays.clear()
