"""One mapping per payload kind; catalogue IDs never escape as public identities."""

from bisect import bisect_right
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..errors import ClosedGeocoderError, DataNotInstalledError
from ..packs.catalogue import Catalogue
from ..packs.errors import CorruptPackError
from ..packs.jsonio import relative_file
from ..packs.layout import PLACES
from ..packs.metadata import read_manifest
from ..packs.spatial import Label, Spatial
from ..packs.verify import verify as verify_pack
from .search import search


class Pack:
    def __init__(self, root: Path, *, verify: bool) -> None:
        if not root.exists():
            raise DataNotInstalledError(f"No pack at {root}; install data explicitly")
        self.closed = False
        self.root = root
        self.manifest = verify_pack(root) if verify else read_manifest(root)
        self.cells = [r for r in self.manifest["files"] if r["kind"] == "cells"]
        self.catalogues = [
            r for r in self.manifest["files"] if r["kind"] == "catalogue"
        ]
        self.block_starts = [r["first_block"] for r in self.cells]
        self.place_starts = [r["first_id"] for r in self.catalogues]
        self.spatial: Spatial | None = None
        self.catalogue: Catalogue | None = None
        self.spatial_index = self.catalogue_index = -1

    def info(self) -> dict[str, Any]:
        return deepcopy(self.manifest)

    def spatial_for(self, block: int) -> Spatial | None:
        if self.closed:
            raise ClosedGeocoderError("Geocoder is closed")
        index = bisect_right(self.block_starts, block) - 1
        if index < 0 or block > self.cells[index]["last_block"]:
            self._absent_block()
            return None
        if self.spatial_index != index:
            if self.spatial is not None:
                self.spatial.close()
                self.spatial = None
            self.spatial_index = -1
            record = self.cells[index]
            shard = Spatial(
                relative_file(self.root, record["path"]), self.manifest["place_count"]
            )
            if (shard.ids[0], shard.ids[-1]) != (
                record["first_block"],
                record["last_block"],
            ):
                shard.close()
                raise CorruptPackError("Spatial directory differs from manifest")
            self.spatial, self.spatial_index = shard, index
        assert self.spatial is not None
        if block not in self.spatial.blocks:
            self._absent_block()
            return None
        return self.spatial

    def _absent_block(self) -> None:
        if self.manifest["coverage"] == "world":
            raise CorruptPackError("World pack is missing a block")

    def lookup_many(
        self,
        block: int,
        keys: list[int],
    ) -> list[tuple[int, Label] | None] | None:
        shard = self.spatial_for(block)
        if shard is None:
            return None
        positions = search(shard, block, keys)
        row = shard.blocks[block]
        stored = shard.keys(row)
        return [
            None if position is None else (stored[position], shard.label(row, position))
            for position in positions
        ]

    def record(self, reference: int) -> dict[str, Any]:
        if self.closed:
            raise ClosedGeocoderError("Geocoder is closed")
        if not 1 <= reference <= self.manifest["place_count"]:
            raise CorruptPackError("Invalid global catalogue reference")
        index = bisect_right(self.place_starts, reference) - 1
        if self.catalogue_index != index:
            if self.catalogue is not None:
                self.catalogue.close()
                self.catalogue = None
            self.catalogue_index = -1
            record = self.catalogues[index]
            shard = Catalogue(
                relative_file(self.root, record["path"]), self.manifest["place_count"]
            )
            if shard.sections[PLACES].count != record["count"]:
                shard.close()
                raise CorruptPackError("Catalogue count differs from manifest")
            self.catalogue, self.catalogue_index = shard, index
        assert self.catalogue is not None
        return self.catalogue.record(reference - self.place_starts[index])

    def identity(self, reference: int) -> str | None:
        if not reference:
            return None
        identity: str = self.record(reference)["place_id"]
        return identity

    def close(self) -> None:
        self.closed = True
        if self.spatial is not None:
            self.spatial.close()
            self.spatial = None
        if self.catalogue is not None:
            self.catalogue.close()
            self.catalogue = None
