"""Subset predicates preserve table schemas and the original cell decisions."""

from dataclasses import dataclass
from typing import cast

import pyarrow as pa
import pyarrow.compute as pc
from h3.api import basic_int as h3

from pipeline.config.release import ReleaseSettings
from pipeline.config.schema import H3
from thereabouts.format import H3_DIGIT_BITS, H3_MAX_RESOLUTION

from .source import TableFile

H3_RESOLUTION_SHIFT = 52
H3_RESOLUTION_MASK = H3_MAX_RESOLUTION << H3_RESOLUTION_SHIFT
UINT64_MASK = (1 << 64) - 1


@dataclass(frozen=True)
class Selection:
    countries: tuple[str, ...]
    blocks: tuple[str, ...]
    grid: H3

    @classmethod
    def from_settings(cls, settings: ReleaseSettings, grid: H3) -> "Selection":
        if settings.countries and not settings.blocks:
            raise ValueError("A country subset must name its spatial blocks explicitly")
        return cls(tuple(settings.countries), tuple(settings.blocks), grid)

    def includes(self, record: TableFile) -> bool:
        if self.countries and record.country and record.country not in self.countries:
            return False
        return not (
            self.blocks and record.kind == "cells" and record.block not in self.blocks
        )

    def spatial(self, batch: pa.RecordBatch) -> pa.BooleanArray:
        keys = batch.column("h3_uint64")
        resolution = batch.column("h3_resolution")
        block_resolution = self.grid.block_resolution
        trailing = (1 << (H3_DIGIT_BITS * (H3_MAX_RESOLUTION - block_resolution))) - 1
        mask = UINT64_MASK ^ (H3_RESOLUTION_MASK | trailing)
        parents = pc.bit_wise_or(
            pc.bit_wise_and(keys, pa.scalar(mask, type=pa.uint64())),
            pa.scalar(
                (block_resolution << H3_RESOLUTION_SHIFT) | trailing, type=pa.uint64()
            ),
        )
        roots = [int(block, 16) for block in self.blocks]
        fine = pc.and_(
            pc.greater_equal(resolution, pa.scalar(block_resolution)),
            pc.is_in(parents, value_set=pa.array(roots, type=pa.uint64())),
        )
        ancestors = {
            h3.cell_to_parent(root, level)
            for root in roots
            for level in range(block_resolution)
        }
        coarse = pc.is_in(keys, value_set=pa.array(sorted(ancestors), type=pa.uint64()))
        return cast(
            pa.BooleanArray, pc.fill_null(pc.or_(fine, coarse), pa.scalar(False))
        )

    def filter(self, kind: str, batch: pa.RecordBatch) -> pa.RecordBatch:
        mask: pa.BooleanArray | None = None
        names = batch.schema.names
        if self.countries:
            candidates = pa.array(self.countries, type=pa.string())
            field = (
                "country_code"
                if "country_code" in names
                else "territory"
                if "territory" in names
                else None
            )
            if field:
                mask = pc.is_in(batch.column(field), value_set=candidates)
            elif "country_codes" in names:
                values = batch.column("country_codes").to_pylist()
                selected = set(self.countries)
                mask = pa.array(
                    [
                        bool(
                            selected.intersection(
                                value.split(",")
                                if isinstance(value, str)
                                else value or []
                            )
                        )
                        for value in values
                    ]
                )
            elif kind == "cells":
                mask = pc.is_in(
                    batch.column("country_id"),
                    value_set=pa.array(["country:" + cc for cc in self.countries]),
                )
        if self.blocks and "h3_uint64" in names and kind != "zone_tables":
            spatial = self.spatial(batch)
            # Unlocated observations still belong to a selected country's tables.
            if kind not in {"cells", "timezone_cells"}:
                spatial = pc.or_(spatial, pc.is_null(batch.column("h3_uint64")))
            mask = spatial if mask is None else pc.and_(mask, spatial)
        return (
            batch
            if mask is None
            else batch.filter(
                cast(pa.BooleanArray, pc.fill_null(mask, pa.scalar(False)))
            )
        )
