"""Publish a release to GitHub Releases: a draft first, published only when complete.

A release ``<tag_prefix><version>`` holds flat assets: each pack archive and its
acceptance report, the dataset's top-level documents, one stored zip per
dataset table (``dataset_zips``), ``dataset-manifest.json``, which tells
``data install dataset`` how to restore ``dataset/<version>/``, and
``index.json``. The index is format 3 with absolute download URLs plus each
asset's id and API URL; it merges every published release's index, so
``releases/latest/download/index.json`` always lists every version.

A run resumes: complete assets already in the draft are verified and kept,
incomplete uploads are deleted, and only missing assets are uploaded. Each
asset is checked by size and SHA-256 digest (downloaded and hashed when GitHub
reports none). A published release is never altered except to add a missing
asset. ``OWNER DECISION`` text blocks a public release; a private publish stops
at the verified draft. A dry run reads only local files.
"""

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pipeline.config.publication import PublicationSettings, service_url
from pipeline.engines.artifacts import read_json
from pipeline.runtime.jsonio import atomic_output, sha256_file
from pipeline.runtime.resources import ResourceGuard

from . import dataset_zips
from .bundle import transport
from .github_api import Client, GithubError
from .publish import Upload, placeholders

TOKEN_ENV = "GITHUB_TOKEN"
INDEX = "index.json"
# Clients refuse a larger release index.
INDEX_LIMIT = 16 * 1024 * 1024
NOTES_LIMIT = 125_000
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
Row = dict[str, Any]


@dataclass(frozen=True)
class Asset:
    name: str
    size: int
    sha256: str
    local: Path


@dataclass(frozen=True)
class Plan:
    version: str
    tag: str
    packs: list[Asset]
    documents: list[Asset]
    zips: list[dataset_zips.TableZip]
    index: Row | None
    notes: str
    unresolved: list[str]

    @property
    def names(self) -> list[str]:
        static = [a.name for a in self.packs + self.documents]
        return [*static, *(z.name for z in self.zips), dataset_zips_manifest(), INDEX]


def dataset_zips_manifest() -> str:
    return str(transport().DATASET_MANIFEST)


def plan(
    entries: list[Upload],
    dataset: Path,
    version: str,
    settings: PublicationSettings,
) -> Plan:
    """Name, size and check every asset from the verified publication inventory."""
    github = settings.github
    packs, documents, members = [], [], []
    index = None
    prefix = f"packs/{version}/"
    for entry in entries:
        if entry.remote == f"{prefix}index.json":
            index = read_json(entry.local)
        elif entry.remote.startswith(f"{prefix}acceptance/"):
            name = "acceptance-" + entry.remote.rpartition("/")[2]
            packs.append(Asset(name, entry.size, entry.sha256, entry.local))
        elif entry.remote.startswith(prefix):
            name = entry.remote.removeprefix(prefix)
            packs.append(Asset(name, entry.size, entry.sha256, entry.local))
        else:
            path = entry.remote.removeprefix(f"dataset/{version}/")
            if "/" in path:
                members.append(dataset_zips.Member(path, entry.size, entry.sha256))
            else:
                documents.append(Asset(path, entry.size, entry.sha256, entry.local))
    zips = dataset_zips.plan(members, github.max_asset_bytes)
    result = Plan(
        version,
        github.tag_prefix + version,
        packs,
        documents,
        zips,
        index,
        notes(dataset, version),
        placeholders(entries),
    )
    names = result.names
    if len(set(names)) != len(names):
        raise ValueError("Release asset names collide: " + ", ".join(sorted(names)))
    if bad := [n for n in names if not NAME.fullmatch(n)]:
        raise ValueError(f"Release asset names must be plain file names: {bad}")
    if len(names) > github.max_assets:
        raise ValueError(
            f"Release needs {len(names)} assets; GitHub allows {github.max_assets}"
        )
    if large := [a.name for a in packs + documents if a.size > github.max_asset_bytes]:
        raise ValueError(f"Release assets over {github.max_asset_bytes} bytes: {large}")
    return result


def notes(dataset: Path, version: str) -> str:
    """Release notes: the dataset's change summary, then its card."""
    parts = [f"Thereabouts dataset {version}."]
    for name in ("CHANGES.md", "DATASET_CARD.md"):
        path = dataset / name
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8").strip())
    text = "\n\n".join(parts) + "\n"
    if len(text) > NOTES_LIMIT:
        cut = "\n\n(Truncated; see CHANGES.md and DATASET_CARD.md in the assets.)\n"
        text = text[: NOTES_LIMIT - len(cut)] + cut
    return text


def public_url(settings: PublicationSettings, tag: str, name: str) -> str:
    web = service_url(settings.github.web_url)
    return f"{web}/{settings.github.repository}/releases/download/{tag}/{quote(name)}"


def locator(settings: PublicationSettings, tag: str, name: str, asset_id: int) -> Row:
    api = service_url(settings.github.api_url)
    repository = settings.github.repository
    return {
        "url": public_url(settings, tag, name),
        "asset_id": asset_id,
        "api_url": f"{api}/repos/{repository}/releases/assets/{asset_id}",
    }


def encode(value: Row) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def dataset_manifest(
    result: Plan,
    settings: PublicationSettings,
    ids: Mapping[str, int],
    digests: Mapping[str, str],
) -> Row:
    archives = [
        {
            "name": item.name,
            "table": item.table,
            "size": item.size,
            "sha256": digests[item.name],
            "unpacked_size": item.unpacked_size,
            "files": [
                {"path": m.path, "size": m.size, "sha256": m.sha256}
                for m in item.members
            ],
            **locator(settings, result.tag, item.name, ids[item.name]),
        }
        for item in result.zips
    ]
    files = [
        {
            "path": doc.name,
            "size": doc.size,
            "sha256": doc.sha256,
            **locator(settings, result.tag, doc.name, ids[doc.name]),
        }
        for doc in result.documents
    ]
    return {
        "format": transport().DATASET_MANIFEST_FORMAT,
        "version": result.version,
        "archives": archives,
        "files": files,
    }


def version_entry(
    result: Plan, settings: PublicationSettings, ids: Mapping[str, int], manifest: Asset
) -> Row:
    packs = {}
    if result.index is not None:
        listed = result.index["datasets"][result.version]["packs"]
        for family, record in sorted(listed.items()):
            name = Path(record["url"]).name
            packs[family] = {
                **record,
                **locator(settings, result.tag, name, ids[name]),
            }
    return {
        "packs": packs,
        "dataset": {
            "size": manifest.size,
            "sha256": manifest.sha256,
            **locator(settings, result.tag, manifest.name, ids[manifest.name]),
        },
    }


def merge(indexes: list[Row], version: str, entry: Row) -> Row:
    """Union of published indexes plus this version; a listed version never changes."""
    form = transport().INDEX_FORMAT
    datasets: Row = {}
    for index in indexes:
        if index.get("format") != form or not isinstance(index.get("datasets"), dict):
            raise ValueError(f"Published release index is not format {form}")
        for listed, value in index["datasets"].items():
            if datasets.setdefault(listed, value) != value:
                raise ValueError(f"Published indexes disagree about {listed}")
    if datasets.setdefault(version, entry) != entry:
        raise ValueError(f"Published index already lists another {version}")
    return {"format": form, "datasets": dict(sorted(datasets.items()))}


def version_key(text: str) -> tuple[tuple[int, int | str], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part) for part in text.split(".")
    )


def summary(result: Plan, settings: PublicationSettings) -> Row:
    """The dry-run plan: every asset, nothing contacted, nothing written."""
    assets = [
        {"name": a.name, "size": a.size, "sha256": a.sha256}
        for a in result.packs + result.documents
    ] + [
        {"name": z.name, "size": z.size, "sha256": None, "files": len(z.members)}
        for z in result.zips
    ]
    return {
        "version": result.version,
        "target": "github",
        "repository": settings.github.repository,
        "tag": result.tag,
        "dry_run": True,
        "draft_only": settings.private,
        "assets": assets,
        "generated": [dataset_zips_manifest(), INDEX],
        "count": len(result.names),
        "bytes": sum(asset["size"] for asset in assets),
        "notes_characters": len(result.notes),
        "unresolved": result.unresolved,
    }


class Publisher:
    """One publication run against one repository and tag."""

    def __init__(
        self,
        result: Plan,
        settings: PublicationSettings,
        client: Client,
        work: Path,
    ) -> None:
        self.plan = result
        self.settings = settings
        self.client = client
        self.work = work
        self.uploaded: list[str] = []
        self.kept: list[str] = []
        self.deleted: list[str] = []

    def release(self) -> Row:
        """The one release for this tag: published, else a draft, else a new draft."""
        found = [r for r in self.client.releases() if r["tag_name"] == self.plan.tag]
        published = [r for r in found if not r["draft"]]
        drafts = [r for r in found if r["draft"]]
        if len(published) > 1 or len(drafts) > 1 or (published and drafts):
            raise ValueError(
                f"Several GitHub releases use {self.plan.tag}; delete the extra drafts"
            )
        if published or drafts:
            return (published or drafts)[0]
        return self.client.create_release(
            {
                "tag_name": self.plan.tag,
                "name": f"Thereabouts {self.plan.version}",
                "body": self.plan.notes,
                "draft": True,
                "prerelease": False,
            }
        )

    def existing(self, release: Row) -> dict[str, Row]:
        """Complete assets by name; drops our own incomplete uploads."""
        planned = set(self.plan.names)
        assets: dict[str, Row] = {}
        for asset in self.client.assets(release["id"]):
            if asset["name"] not in planned:
                raise ValueError(
                    f"Unexpected asset {asset['name']} in {self.plan.tag}; "
                    "remove it on GitHub or choose a new version"
                )
            if asset.get("state") != "uploaded":
                self.client.delete_asset(asset["id"])
                self.deleted.append(asset["name"])
                continue
            assets[asset["name"]] = asset
        return assets

    def matches(self, asset: Row, size: int, sha256: str) -> bool:
        if asset.get("state") != "uploaded" or asset.get("size") != size:
            return False
        digest = asset.get("digest")
        if isinstance(digest, str) and digest.startswith("sha256:"):
            return digest == f"sha256:{sha256}"
        return self.client.download(int(asset["id"])) == (size, sha256)

    def ensure(
        self, release: Row, assets: dict[str, Row], name: str, path: Path, sha256: str
    ) -> int:
        """Keep a matching asset or upload a missing one; a different one is refused."""
        size = path.stat().st_size
        if name in assets:
            if not self.matches(assets[name], size, sha256):
                raise ValueError(
                    f"Conflicting asset {name} in {self.plan.tag}; "
                    "a release never changes once uploaded"
                )
            self.kept.append(name)
            return int(assets[name]["id"])
        if sha256_file(path) != sha256:
            raise ValueError(f"Local release file changed: {name}")
        asset = self.client.upload(int(release["id"]), name, path)
        if not self.matches(asset, size, sha256):
            raise ValueError(f"Uploaded asset differs from the local file: {name}")
        assets[name] = asset
        self.uploaded.append(name)
        return int(asset["id"])

    def generated(self, name: str, value: Row) -> tuple[Path, str]:
        path = self.work / name
        payload = encode(value)
        if not (path.is_file() and path.read_bytes() == payload):
            with atomic_output(path) as temporary:
                temporary.write_bytes(payload)
        return path, sha256_file(path)

    def published_indexes(self, release: Row) -> list[Row]:
        """Every other published release's index, to union into this one."""
        return [
            self.fetch_json(int(asset["id"]))
            for other in self.client.releases()
            if not other["draft"] and other["id"] != release["id"]
            for asset in self.client.assets(int(other["id"]))
            if asset["name"] == INDEX and asset.get("state") == "uploaded"
        ]

    def fetch_json(self, asset_id: int) -> Row:
        value = json.loads(self.client.fetch(asset_id, INDEX_LIMIT))
        if not isinstance(value, dict):
            raise ValueError("A published release index is not a JSON object")
        return value

    def newest(self, release: Row) -> bool:
        prefix = self.settings.github.tag_prefix
        others = [
            r["tag_name"].removeprefix(prefix)
            for r in self.client.releases()
            if not r["draft"]
            and r["id"] != release["id"]
            and r["tag_name"].startswith(prefix)
        ]
        mine = version_key(self.plan.version)
        return all(version_key(other) <= mine for other in others)

    def repairable(self, assets: Mapping[str, Row]) -> None:
        """A published manifest or index names assets by id; a re-upload changes the id.

        So a published release may gain only assets nothing published refers to.
        """
        manifest = dataset_zips_manifest()
        documents = [a.name for a in self.plan.documents]
        tied = {
            INDEX: [
                *(a.name for a in self.plan.packs if a.name.endswith(".tar.zst")),
                manifest,
            ],
            manifest: [*documents, *(z.name for z in self.plan.zips)],
        }
        for generated, names in tied.items():
            lost = sorted(n for n in names if n not in assets)
            if generated in assets and lost:
                raise ValueError(
                    f"Published release {self.plan.tag} lacks {', '.join(lost)}, which "
                    f"its {generated} names by asset id; a published release cannot be "
                    "repaired in place, so publish a new patch version (YYYY.MM.N)"
                )

    def run(self, zips: Mapping[str, dataset_zips.Built]) -> Row:
        release = self.release()
        published = not release["draft"]
        if published and self.plan.unresolved:
            raise ValueError("A published release cannot take OWNER DECISION text")
        assets = self.existing(release)
        if published:
            self.repairable(assets)
        ids: dict[str, int] = {}
        digests: dict[str, str] = {}
        for item in self.plan.packs + self.plan.documents:
            ids[item.name] = self.ensure(
                release, assets, item.name, item.local, item.sha256
            )
        for archive in self.plan.zips:
            path, digests[archive.name] = zips[archive.name]
            ids[archive.name] = self.ensure(
                release, assets, archive.name, path, digests[archive.name]
            )
        name = dataset_zips_manifest()
        path, digest = self.generated(
            name, dataset_manifest(self.plan, self.settings, ids, digests)
        )
        ids[name] = self.ensure(release, assets, name, path, digest)
        manifest = Asset(name, path.stat().st_size, digest, path)
        entry = version_entry(self.plan, self.settings, ids, manifest)
        aggregate = self.index(release, assets, entry, ids)
        state = "published"
        if not published:
            if self.settings.private:
                state = "draft"
            else:
                release = self.client.update_release(
                    int(release["id"]),
                    {
                        "tag_name": self.plan.tag,
                        "draft": False,
                        "make_latest": "true" if self.newest(release) else "false",
                    },
                )
        self.confirm(int(release["id"]), state, ids)
        return {
            "version": self.plan.version,
            "target": "github",
            "repository": self.settings.github.repository,
            "tag": self.plan.tag,
            "release_id": release["id"],
            "dry_run": False,
            "state": state,
            "upload": len(self.uploaded),
            "skip": len(self.kept),
            "deleted_incomplete": self.deleted,
            "aggregate_index": aggregate,
            "unresolved": self.plan.unresolved,
            "files": [{"name": n, "asset_id": ids[n]} for n in self.plan.names],
        }

    def index(
        self, release: Row, assets: dict[str, Row], entry: Row, ids: dict[str, int]
    ) -> str:
        """Keep an uploaded index that lists this version exactly; else union and add.

        Later releases add versions to their own index only, so an uploaded index is
        checked by this version's entry, not byte for byte.
        """
        if INDEX in assets:
            value = self.fetch_json(int(assets[INDEX]["id"]))
            listed = value.get("datasets")
            if (
                value.get("format") != transport().INDEX_FORMAT
                or not isinstance(listed, dict)
                or listed.get(self.plan.version) != entry
            ):
                raise ValueError(
                    f"Conflicting asset {INDEX} in {self.plan.tag}; "
                    "a release never changes once uploaded"
                )
            ids[INDEX] = int(assets[INDEX]["id"])
            self.kept.append(INDEX)
            return "kept"
        indexes = self.published_indexes(release)
        path, digest = self.generated(INDEX, merge(indexes, self.plan.version, entry))
        ids[INDEX] = self.ensure(release, assets, INDEX, path, digest)
        return "updated" if indexes else "created"

    def confirm(self, release_id: int, state: str, ids: Mapping[str, int]) -> None:
        """Re-read the release: its state, tag and exactly the planned assets."""
        release = self.client.release(release_id)
        if (
            release["draft"] != (state == "draft")
            or release["tag_name"] != self.plan.tag
        ):
            raise ValueError(f"GitHub release {self.plan.tag} is not {state}")
        found = {
            a["name"]: int(a["id"])
            for a in self.client.assets(release_id)
            if a.get("state") == "uploaded"
        }
        if found != dict(ids):
            raise ValueError(f"GitHub release {self.plan.tag} lacks planned assets")


def publish(
    entries: list[Upload],
    dataset: Path,
    version: str,
    settings: PublicationSettings,
    *,
    dry_run: bool,
    work: Path,
    guard: ResourceGuard | None = None,
) -> Row:
    """Plan, then (unless a dry run) upload, verify and publish; the token is read
    from the environment only."""
    result = plan(entries, dataset, version, settings)
    if result.unresolved and not settings.private:
        raise ValueError(
            "OWNER DECISION text must be resolved before a public release: "
            + ", ".join(result.unresolved)
            + "; set release.publish.private=true to upload a draft only"
        )
    if dry_run:
        return summary(result, settings)
    token = os.environ.get(TOKEN_ENV, "")
    if not token:
        raise ValueError(f"GitHub publication reads its token from {TOKEN_ENV}")
    client = Client(settings.github, token, settings.read_bytes)
    zips = dataset_zips.build(
        result.zips, dataset, work / "zips", guard, settings.read_bytes
    )
    try:
        return Publisher(result, settings, client, work).run(zips)
    except GithubError as error:
        raise ValueError(
            f"GitHub publication stopped; rerun to resume: {error}"
        ) from error
