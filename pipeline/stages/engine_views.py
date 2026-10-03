"""Lazily load country selectors with a bounded per-unit cache."""

from collections import OrderedDict
from collections.abc import Iterator, Mapping

from pipeline.engines.cities.engine import Engine
from pipeline.engines.cities.urban import Urban
from pipeline.engines.reconcile.common import Row

from . import cities
from .contract import Context


class Engines(Mapping[str, Engine]):
    def __init__(
        self,
        ctx: Context,
        codes: list[str],
        policy: Row,
        centres: Urban,
        *,
        land: bool = True,
    ) -> None:
        self.ctx, self.codes, self.policy, self.centres = ctx, codes, policy, centres
        self.land = land
        self.cache: OrderedDict[str, Engine] = OrderedDict()

    def __iter__(self) -> Iterator[str]:
        return iter(self.codes)

    def __len__(self) -> int:
        return len(self.codes)

    def __getitem__(self, code: str) -> Engine:
        if code not in self.codes:
            raise KeyError(code)
        if code in self.cache:
            self.cache.move_to_end(code)
        else:
            while len(self.cache) >= self.ctx.config.engines.limits.city_cache_entries:
                self.cache.popitem(last=False)
            self.cache[code] = cities.engine(
                self.ctx, code, self.policy, self.centres, land=self.land
            )
        return self.cache[code]
