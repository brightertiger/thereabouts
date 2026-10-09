"""Walk stages in dependency order, logging an interrupted or complete run."""

import fcntl
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pipeline.stages.contract import Context, Stage
from pipeline.stages.registry import ordered

from .execution import Executor
from .jsonio import write_json
from .paths import located


@contextmanager
def exclusive(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Another pipeline writer owns this workspace") from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def run(
    ctx: Context,
    stages: Sequence[Stage],
    *,
    through: str | None = None,
    only: str | None = None,
) -> dict[str, int]:
    if ctx.readonly:
        raise ValueError("Cannot run with a read-only context")
    stages = ordered(stages)
    names = [stage.name for stage in stages]
    if through is not None and only is not None:
        raise ValueError("Use either --through or --only")
    for value in (through, only):
        if value is not None and value not in names:
            raise ValueError(f"Unknown stage: {value}")
    selected = (
        {only} if only else set(names[: names.index(through) + 1] if through else names)
    )
    work = located(ctx.root, ctx.config.paths.work)
    with exclusive(work / "pipeline.lock"):
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        directory = work / "runs" / stamp
        directory.mkdir(parents=True)
        with (directory / "run.log").open("a", buffering=1) as stream:
            lock = threading.Lock()

            def event(message: str) -> None:
                with lock:
                    stream.write(message + "\n")

            with ctx.watch.frozen():
                # Identities are computed here, once, inside the frozen watch.
                executor = Executor(ctx, stages, event)
                complete = False
                previous_log, previous_event = ctx.guard.log, ctx.log
                ctx.guard.log = ctx.log = event
                try:
                    for stage in stages:
                        if stage.name in selected:
                            executor.execute(stage.name, materialize=only is not None)
                    complete = True
                finally:
                    ctx.guard.log, ctx.log = previous_log, previous_event
                    write_json(
                        directory / "summary.json",
                        {
                            "complete": complete,
                            "completed": executor.completed,
                            "skipped": executor.skipped,
                        },
                    )
            return {"completed": executor.completed, "skipped": executor.skipped}
