"""A small complete release (dataset, packs, acceptance, index) for GitHub tests."""

import shutil
from dataclasses import dataclass, replace
from pathlib import Path

from pipeline.config import Config
from pipeline.config.publication import PublicationSettings
from pipeline.release import bundle
from pipeline.release.assemble import assemble
from pipeline.release.publish import Upload, inventory
from pipeline.runtime.jsonio import write_json
from tests.tools.github_fake import FakeGithub

from .fixtures import fixture

PACKS = Path(__file__).parents[2] / "fixtures" / "packs"
FAMILIES = ("core", "phone")


@dataclass
class Built:
    root: Path
    config: Config
    version: str
    dataset: Path
    packs: dict[str, Path]

    def entries(self) -> list[Upload]:
        return inventory(self.dataset, self.packs, self.version)


def build(
    root: Path,
    version: str = "2026.10",
    families: tuple[str, ...] = FAMILIES,
    contact: str | None = None,
) -> Built:
    """The MY fixture dataset plus committed sample packs, archived and indexed."""
    root.mkdir(parents=True, exist_ok=True)
    snapshot, config, guard = fixture(root)
    config.release.version = version
    if contact is not None:
        config.release.contact = contact
    dataset = root / "dataset" / version
    assemble(snapshot, dataset, config, guard, "identity")
    directory = root / "packs" / version
    packs = {}
    for family in families:
        target = directory / family
        shutil.copytree(PACKS / f"{family}-sample", target)
        bundle.archive(target, guard)
        write_json(
            directory / "acceptance" / f"{family}.json",
            {"family": family, "passed": True},
        )
        packs[family] = target
    bundle.index(directory, version, list(families))
    config.release.packs.families = list(families)
    return Built(root, config, version, dataset, packs)


def settings(
    config: Config, fake: FakeGithub, **changes: object
) -> PublicationSettings:
    """GitHub publication against `fake`; `github_*` keys change the GitHub block."""
    github_changes = {
        key.removeprefix("github_"): value
        for key, value in changes.items()
        if key.startswith("github_")
    }
    publish_changes = {k: v for k, v in changes.items() if not k.startswith("github_")}
    github = replace(
        config.release.publish.github,
        repository=fake.repository,
        api_url=fake.api_url,
        upload_url=fake.upload_url,
        web_url=fake.web_url,
        timeout_seconds=30,
        **github_changes,  # type: ignore[arg-type]
    )
    return replace(
        config.release.publish,
        target="github",
        github=github,
        **publish_changes,  # type: ignore[arg-type]
    )
