"""Reference implementation of the optional numeric reconstruction kernel."""

from ..packs.address import cell_at


def stored_cell(block: int, key: int) -> int:
    return cell_at(block, key)
