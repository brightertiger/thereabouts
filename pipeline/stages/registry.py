"""Validate the declared graph before the runner opens a writable workspace."""

from collections.abc import Sequence
from dataclasses import fields

from pipeline.config import Config
from pipeline.runtime.fingerprints import REPOSITORY, native_versions
from pipeline.runtime.paths import validate_relative

from .contract import Stage
from .retained import RetainedStage


def ordered(stages: Sequence[Stage]) -> list[Stage]:
    by_name = {stage.name: stage for stage in stages}
    if len(by_name) != len(stages) or "" in by_name:
        raise ValueError("Stage names must be nonempty and unique")
    result: list[Stage] = []
    seen: set[str] = set()
    visiting: set[str] = set()

    def visit(name: str) -> None:
        if name not in by_name:
            raise ValueError(f"Unknown stage dependency: {name}")
        if name in visiting:
            raise ValueError(f"Stage dependency cycle at {name}")
        if name in seen:
            return
        visiting.add(name)
        for upstream in by_name[name].needs:
            visit(upstream)
        visiting.remove(name)
        seen.add(name)
        result.append(by_name[name])

    for stage in stages:
        visit(stage.name)
    return result


def registry(config: Config) -> list[Stage]:
    if not config.stages:
        raise ValueError("Configure at least one stage")
    sections = {field.name for field in fields(config)}
    for stage in config.stages:
        if any(name not in sections for name in stage.config):
            raise ValueError(f"Unknown config dependency in {stage.name}")
        for package in stage.packages:
            validate_relative(package)
            if (
                not package.startswith("pipeline/")
                or not (REPOSITORY / package).exists()
            ):
                raise ValueError(f"Missing production code package: {package}")
        native_versions(stage.native, REPOSITORY / "uv.lock")
        if not stage.packages:
            raise ValueError(f"Stage {stage.name} needs an identity package")
    return ordered([RetainedStage(settings) for settings in config.stages])
