"""A shared byte budget for immutable decoded places and code candidates."""

import sys
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import fields, is_dataclass

DEFAULT_CACHE_BYTES = 32 * 1024 * 1024


def retained_bytes(value: object, seen: set[int] | None = None) -> int:
    """Conservatively charge shared objects once per entry (not across entries)."""
    if seen is None:
        seen = set()
    if id(value) in seen:
        return 0
    seen.add(id(value))
    size = sys.getsizeof(value)
    if is_dataclass(value) and not isinstance(value, type):
        size += sum(retained_bytes(getattr(value, f.name), seen) for f in fields(value))
    elif isinstance(value, Mapping):
        # MappingProxyType doesn't include its backing dictionary in getsizeof.
        size += sys.getsizeof(dict(value))
        size += sum(
            retained_bytes(key, seen) + retained_bytes(item, seen)
            for key, item in value.items()
        )
    elif isinstance(value, tuple):
        size += sum(retained_bytes(item, seen) for item in value)
    return size


class Cache:
    def __init__(self, budget: int) -> None:
        self.budget = budget
        self.entries: OrderedDict[int | str, tuple[object, int]] = OrderedDict()
        self.bytes = 0
        self.hits = self.misses = self.evictions = 0

    def get(self, key: int | str) -> object | None:
        cached = self.entries.get(key)
        if cached is None:
            self.misses += 1
            return None
        self.entries.move_to_end(key)
        self.hits += 1
        return cached[0]

    def put(self, key: int | str, value: object) -> None:
        if not self.budget:
            return
        previous = self.entries.pop(key, None)
        if previous is not None:
            self.bytes -= previous[1]
        size = retained_bytes((key, value, 0))
        self.entries[key] = (value, size)
        self.bytes += size
        while self.entries and self.bytes + sys.getsizeof(self.entries) > self.budget:
            _, (_, removed) = self.entries.popitem(last=False)
            self.bytes -= removed
            self.evictions += 1
        if not self.entries:
            self.entries.clear()

    def info(self) -> dict[str, int]:
        return {
            "budget_bytes": self.budget,
            "entries": len(self.entries),
            "retained_bytes": self.bytes
            + (sys.getsizeof(self.entries) if self.entries else 0),
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
        }

    def clear(self) -> None:
        self.entries.clear()
        self.bytes = 0
