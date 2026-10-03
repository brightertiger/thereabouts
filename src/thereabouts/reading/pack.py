"""Lazy mappings and bounded decoded places for one immutable pack."""

from bisect import bisect_right
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..errors import ClosedGeocoderError, DataNotInstalledError
from ..packs.catalogue import Catalogue
from ..packs.errors import CorruptPackError
from ..packs.exact import Exact
from ..packs.jsonio import relative_file
from ..packs.layout import PLACE, PLACES
from ..packs.metadata import read_manifest
from ..packs.spatial import Label, Spatial
from ..packs.verify import verify as verify_pack
from .cache import DEFAULT_CACHE_BYTES, Cache
from .places import Places
from .spatial import SpatialIndex


class Pack:
    def __init__(
        self, root: Path, *, verify: bool, cache_bytes: int = DEFAULT_CACHE_BYTES
    ) -> None:
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
        self.spatials: dict[int, Spatial] = {}
        self.indexes: dict[int, SpatialIndex] = {}
        self.catalogue_maps: dict[int, Catalogue] = {}
        self.cache = Cache(cache_bytes)
        self.places = Places(self, self.cache)
        self.exact_files = [r for r in self.manifest["files"] if r["kind"] == "exact"]
        self.key_starts = [r["first_key"].encode("utf-8") for r in self.exact_files]
        self.exacts: dict[int, Exact] = {}

    def ensure_open(self) -> None:
        if self.closed:
            raise ClosedGeocoderError("Geocoder is closed")

    def info(self) -> dict[str, Any]:
        return deepcopy(self.manifest)

    def spatial_for(self, block: int) -> Spatial | None:
        self.ensure_open()
        index = bisect_right(self.block_starts, block) - 1
        if index < 0 or block > self.cells[index]["last_block"]:
            self._absent_block()
            return None
        shard = self.spatials.get(index)
        if shard is None:
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
            self.spatials[index] = shard
            try:
                self.indexes[index] = SpatialIndex(shard)
            except CorruptPackError:
                self.spatials.pop(index).close()
                raise
        if block not in shard.blocks:
            self._absent_block()
            return None
        return shard

    def index_for(self, block: int) -> SpatialIndex | None:
        if self.spatial_for(block) is None:
            return None
        return self.indexes[bisect_right(self.block_starts, block) - 1]

    def lookup(self, block: int, key: int) -> tuple[bool, tuple[int, Label] | None]:
        index = self.index_for(block)
        return index is not None, None if index is None else index.lookup(block, key)

    def _absent_block(self) -> None:
        if self.manifest["coverage"] == "world":
            raise CorruptPackError("World pack is missing a block")

    def _catalogue_for(self, reference: int) -> tuple[Catalogue, int]:
        self.ensure_open()
        if not 1 <= reference <= self.manifest["place_count"]:
            raise CorruptPackError("Invalid global catalogue reference")
        index = bisect_right(self.place_starts, reference) - 1
        shard = self.catalogue_maps.get(index)
        if shard is None:
            record = self.catalogues[index]
            shard = Catalogue(
                relative_file(self.root, record["path"]), self.manifest["place_count"]
            )
            if shard.sections[PLACES].count != record["count"]:
                shard.close()
                raise CorruptPackError("Catalogue count differs from manifest")
            self.catalogue_maps[index] = shard
        return shard, reference - self.place_starts[index]

    def record(self, reference: int) -> dict[str, Any]:
        shard, local = self._catalogue_for(reference)
        return shard.record(local)

    def identity(self, reference: int) -> str | None:
        if not reference:
            return None
        shard, local = self._catalogue_for(reference)
        fields = PLACE.unpack_from(
            shard.data, shard.sections[PLACES].offset + local * PLACE.size
        )
        identity = shard.text(fields[0])
        if not identity:
            raise CorruptPackError("Missing place identity")
        return identity

    def exact_for(self, key: str) -> Exact | None:
        self.ensure_open()
        encoded = key.encode("utf-8")
        index = bisect_right(self.key_starts, encoded) - 1
        if index < 0 or encoded > self.exact_files[index]["last_key"].encode("utf-8"):
            return None
        if index not in self.exacts:
            record = self.exact_files[index]
            shard = Exact(
                relative_file(self.root, record["path"]), record["max_record_bytes"]
            )
            if (
                shard.count != record["count"]
                or shard.key(0).decode() != record["first_key"]
                or shard.key(shard.count - 1).decode() != record["last_key"]
            ):
                shard.close()
                raise CorruptPackError("Exact-key directory differs from manifest")
            self.exacts[index] = shard
        return self.exacts[index]

    def close(self) -> None:
        self.closed = True
        self.cache.clear()
        for exact in self.exacts.values():
            exact.close()
        self.exacts.clear()
        for index in self.indexes.values():
            index.close()
        self.indexes.clear()
        for shard in self.spatials.values():
            shard.close()
        for catalogue in self.catalogue_maps.values():
            catalogue.close()
        self.spatials.clear()
        self.catalogue_maps.clear()
