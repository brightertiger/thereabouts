"""Extract selected ZIP members atomically without trusting archive paths."""

import shutil
import zipfile
from collections.abc import Callable
from pathlib import Path

from pipeline.runtime.jsonio import atomic_output
from pipeline.runtime.paths import validate_relative
from pipeline.sources.contract import SourceContext


def extract(
    ctx: SourceContext, source: Path, directory: Path, select: Callable[[str], bool]
) -> list[Path]:
    with zipfile.ZipFile(source) as archive:
        members = [
            member
            for member in archive.infolist()
            if not member.is_dir() and select(member.filename)
        ]
        names = [Path(validate_relative(member.filename)).name for member in members]
        if not members or len(names) != len(set(names)):
            raise ValueError("Expected distinct selected archive members")
        reservation = sum(member.file_size for member in members)
        ctx.runtime.guard.admit(reservation)
        written = 0
        try:
            outputs = []
            for member, name in zip(members, names, strict=True):
                target = ctx.ensure(directory / name)
                with atomic_output(target) as temporary:
                    with archive.open(member) as src, temporary.open("wb") as dst:
                        shutil.copyfileobj(src, dst, ctx.settings.limits.read_bytes)
                    if temporary.stat().st_size != member.file_size:
                        raise ValueError(
                            f"Archive member size differs: {member.filename}"
                        )
                written += member.file_size
                outputs.append(target)
            return outputs
        finally:
            ctx.runtime.guard.release(reservation, written_bytes=written)
