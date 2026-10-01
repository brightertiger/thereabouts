"""At most two processes and two in-flight blocks; one owner per checkpoint."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

from h3.api import basic_int as h3

from build_data.acquire import Workspace
from build_data.reconcile.common import Row

from .cells import build
from .inputs import Inputs


def one(
    workspace: Workspace, inputs: Inputs, block: Row, implementation: str, verify: bool
) -> Row:
    return build(
        workspace,
        h3.str_to_int(block["root"]),
        inputs,
        block["countries"],
        implementation,
        exhaustive=verify,
        scalar_samples=16 if verify else 0,
    )


def execute(
    workspace: Workspace,
    inputs: Inputs,
    blocks: list[Row],
    implementation: str,
    verify: bool,
    workers: int,
) -> Iterator[tuple[str, Row]]:
    if workers == 1:
        for block in blocks:
            yield block["root"], one(workspace, inputs, block, implementation, verify)
        return
    if workers != 2:
        raise ValueError("Golden permits one or two workers on the 8 GB machine")
    # Workers need canonical partitions and policy, not the acquisition manifests.
    source = Inputs(inputs.countries, inputs.land, inputs.policy, {}, inputs.builder)
    pending_blocks = iter(blocks)
    with ProcessPoolExecutor(max_workers=workers) as executor:
        pending = {}
        for block in pending_blocks:
            pending[
                executor.submit(one, workspace, source, block, implementation, verify)
            ] = block["root"]
            if len(pending) == workers:
                break
        while pending:
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                root = pending.pop(future)
                yield root, future.result()
                next_block = next(pending_blocks, None)
                if next_block is not None:
                    pending[
                        executor.submit(
                            one, workspace, source, next_block, implementation, verify
                        )
                    ] = next_block["root"]
