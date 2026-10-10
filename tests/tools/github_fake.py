"""A loopback GitHub for publishing and installing releases without github.com.

Four servers on 127.0.0.1 stand in for api.github.com, uploads.github.com, the
github.com download routes and the signed object host behind them. Releases,
drafts, tags, assets (with an optional ``digest``), pagination, private-repository
404s and interrupted uploads and downloads follow GitHub's documented behaviour
closely enough for the publisher and the clients. Every request is logged with
whether it carried an Authorization header, so tests can prove where a token went.
"""

import hashlib
import json
import re
import secrets
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

Row = dict[str, Any]


@dataclass
class Asset:
    id: int
    name: str
    data: bytes
    state: str = "uploaded"


@dataclass
class Release:
    id: int
    tag_name: str
    name: str
    body: str
    draft: bool
    prerelease: bool
    assets: list[Asset] = field(default_factory=list)


@dataclass(frozen=True)
class Request:
    server: str
    method: str
    path: str
    authorized: bool
    range: str | None
    accept: str | None


@dataclass
class FakeGithub:
    repository: str = "brightertiger/thereabouts"
    token: str = "fake-token-0123456789"
    private: bool = True
    # GitHub reports a sha256 digest for assets; older responses carry none.
    digests: bool = True
    # Largest page served, whatever per_page asks for.
    page_size: int = 100
    # Assets embedded in a release object; the rest only through its assets URL.
    embedded_assets: int | None = None
    releases: dict[int, Release] = field(default_factory=dict)
    tags: set[str] = field(default_factory=set)
    latest: int | None = None
    requests: list[Request] = field(default_factory=list)
    # Interrupt the next upload (of `fail_upload_name`, if set) after this many body
    # bytes, leaving a "starter" asset as GitHub does.
    fail_upload_after: int | None = None
    fail_upload_name: str | None = None
    # Cut the next object download after this many bytes.
    cut_download_after: int | None = None
    urls: dict[str, str] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    _ids: Iterator[int] = field(default_factory=lambda: iter(range(1000, 10**9)))

    @property
    def api_url(self) -> str:
        return self.urls["api"]

    @property
    def upload_url(self) -> str:
        return self.urls["uploads"]

    @property
    def web_url(self) -> str:
        return self.urls["web"]

    @property
    def objects_url(self) -> str:
        return self.urls["objects"]

    def release_url(self, tag: str | None = None) -> str:
        """The clients' release base: latest, or one tag."""
        where = f"download/{tag}" if tag else "latest/download"
        return f"{self.web_url}/{self.repository}/releases/{where}/"

    def overrides(self) -> list[str]:
        """Pipeline settings that point the publisher at this fake."""
        prefix = "release.publish.github"
        return [
            f"{prefix}.repository={self.repository}",
            f"{prefix}.api_url={self.api_url}",
            f"{prefix}.upload_url={self.upload_url}",
            f"{prefix}.web_url={self.web_url}",
        ]

    def by_tag(self, tag: str) -> list[Release]:
        return [r for r in self.releases.values() if r.tag_name == tag]

    def published(self, tag: str) -> Release | None:
        return next((r for r in self.by_tag(tag) if not r.draft), None)

    def asset_json(self, release: Release, asset: Asset) -> Row:
        tag = release.tag_name if not release.draft else f"untagged-{release.id}"
        value: Row = {
            "id": asset.id,
            "name": asset.name,
            "label": "",
            "size": len(asset.data),
            "state": asset.state,
            "content_type": "application/octet-stream",
            "url": f"{self.api_url}/repos/{self.repository}/releases/assets/{asset.id}",
            "browser_download_url": (
                f"{self.web_url}/{self.repository}/releases/download/{tag}/"
                + quote(asset.name)
            ),
        }
        if self.digests and asset.state == "uploaded":
            value["digest"] = "sha256:" + hashlib.sha256(asset.data).hexdigest()
        return value

    def release_json(self, release: Release) -> Row:
        base = f"{self.api_url}/repos/{self.repository}/releases/{release.id}"
        uploads = self.upload_url
        assets = [self.asset_json(release, a) for a in release.assets]
        if self.embedded_assets is not None:
            assets = assets[: self.embedded_assets]
        return {
            "id": release.id,
            "tag_name": release.tag_name,
            "name": release.name,
            "body": release.body,
            "draft": release.draft,
            "prerelease": release.prerelease,
            "url": base,
            "assets_url": f"{base}/assets",
            "upload_url": (
                f"{uploads}/repos/{self.repository}/releases/{release.id}"
                "/assets{?name,label}"
            ),
            "html_url": f"{self.web_url}/{self.repository}/releases/tag/"
            + release.tag_name,
            "assets": assets,
        }

    def find_asset(self, asset_id: int) -> tuple[Release, Asset] | None:
        for release in self.releases.values():
            for asset in release.assets:
                if asset.id == asset_id:
                    return release, asset
        return None

    def object_path(self, asset: Asset) -> str:
        return f"/{asset.id}/{quote(asset.name)}?sig={secrets.token_hex(8)}"


class Handler(BaseHTTPRequestHandler):
    fake: FakeGithub
    role: str
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        pass

    def record(self) -> bool:
        authorization = self.headers.get("Authorization")
        self.fake.requests.append(
            Request(
                self.role,
                self.command,
                self.path,
                authorization is not None,
                self.headers.get("Range"),
                self.headers.get("Accept"),
            )
        )
        return authorization in {
            f"Bearer {self.fake.token}",
            f"token {self.fake.token}",
        }

    def send(self, status: int, value: Any = None, **headers: str) -> None:
        body = b"" if value is None else json.dumps(value).encode()
        self.send_response(status)
        if value is not None:
            self.send_header("Content-Type", "application/json")
        for name, text in headers.items():
            self.send_header(name.replace("_", "-"), text)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def missing(self) -> None:
        self.send(404, {"message": "Not Found"})

    def body(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length", "0")))

    def page(self, items: list[Row], query: dict[str, list[str]]) -> None:
        size = min(int(query.get("per_page", ["30"])[0]), self.fake.page_size)
        number = int(query.get("page", ["1"])[0])
        chunk = items[(number - 1) * size : number * size]
        headers = {}
        if number * size < len(items):
            path = urlsplit(self.path).path
            following = f"{path}?per_page={size}&page={number + 1}"
            headers["Link"] = f'<{self.fake.urls[self.role]}{following}>; rel="next"'
        self.send(200, chunk, **headers)

    def do_GET(self) -> None:
        with self.fake.lock:
            authorized = self.record()
            parts = urlsplit(self.path)
            query = parse_qs(parts.query)
            if self.role == "objects":
                self.serve_object(parts.path)
            elif self.role == "web":
                self.web(parts.path, authorized)
            else:
                self.api_get(parts.path, query, authorized)

    def serve_object(self, path: str) -> None:
        match = re.fullmatch(r"/(\d+)/[^/]+", path)
        found = self.fake.find_asset(int(match.group(1))) if match else None
        if found is None:
            self.missing()
            return
        data = found[1].data
        requested = self.headers.get("Range")
        offset = 0
        if requested:
            offset = int(requested.removeprefix("bytes=").removesuffix("-"))
        body = data[offset:]
        self.send_response(206 if requested else 200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        if requested:
            self.send_header(
                "Content-Range", f"bytes {offset}-{len(data) - 1}/{len(data)}"
            )
        self.end_headers()
        if self.fake.cut_download_after is not None:
            body = body[: self.fake.cut_download_after]
            self.fake.cut_download_after = None
            self.wfile.write(body)
            self.wfile.flush()
            self.close_connection = True
            return
        self.wfile.write(body)

    def web(self, path: str, authorized: bool) -> None:
        # github.com serves no private release download to a bearer token.
        del authorized
        prefix = f"/{self.fake.repository}/releases/"
        if self.fake.private or not path.startswith(prefix):
            self.missing()
            return
        rest = path.removeprefix(prefix)
        if rest.startswith("latest/download/"):
            release = (
                self.fake.releases.get(self.fake.latest) if self.fake.latest else None
            )
            if release is None:
                self.missing()
                return
            name = rest.removeprefix("latest/download/")
            location = f"{prefix}download/{release.tag_name}/{name}"
            self.send(302, None, Location=location)
            return
        match = re.fullmatch(r"download/([^/]+)/([^/]+)", rest)
        release = self.fake.published(match.group(1)) if match else None
        asset = (
            next((a for a in release.assets if quote(a.name) == match.group(2)), None)
            if release and match
            else None
        )
        if asset is None:
            self.missing()
            return
        self.send(
            302, None, Location=self.fake.objects_url + self.fake.object_path(asset)
        )

    def visible(self, release: Release, authorized: bool) -> bool:
        return authorized or (not self.fake.private and not release.draft)

    def api_get(self, path: str, query: dict[str, list[str]], authorized: bool) -> None:
        if self.headers.get("Authorization") and not authorized:
            self.send(401, {"message": "Bad credentials"})
            return
        base = f"/repos/{self.fake.repository}/releases"
        if self.fake.private and not authorized:
            self.missing()
            return
        if path == base:
            ordered = sorted(self.fake.releases.values(), key=lambda r: -r.id)
            items = [
                self.fake.release_json(r)
                for r in ordered
                if self.visible(r, authorized)
            ]
            self.page(items, query)
            return
        if path == f"{base}/latest":
            release = (
                self.fake.releases.get(self.fake.latest) if self.fake.latest else None
            )
            if release is None:
                self.missing()
            else:
                self.send(200, self.fake.release_json(release))
            return
        if path.startswith(f"{base}/tags/"):
            release = self.fake.published(path.removeprefix(f"{base}/tags/"))
            if release is None:
                self.missing()
            else:
                self.send(200, self.fake.release_json(release))
            return
        match = re.fullmatch(rf"{base}/assets/(\d+)", path)
        if match:
            found = self.fake.find_asset(int(match.group(1)))
            if found is None or not self.visible(found[0], authorized):
                self.missing()
            elif self.headers.get("Accept") == "application/octet-stream":
                location = self.fake.objects_url + self.fake.object_path(found[1])
                self.send(302, None, Location=location)
            else:
                self.send(200, self.fake.asset_json(*found))
            return
        match = re.fullmatch(rf"{base}/(\d+)(/assets)?", path)
        release = self.fake.releases.get(int(match.group(1))) if match else None
        if match is None or release is None or not self.visible(release, authorized):
            self.missing()
        elif match.group(2):
            self.page([self.fake.asset_json(release, a) for a in release.assets], query)
        else:
            self.send(200, self.fake.release_json(release))

    def do_POST(self) -> None:
        with self.fake.lock:
            authorized = self.record()
            parts = urlsplit(self.path)
            if not authorized:
                self.body()
                self.send(401, {"message": "Requires authentication"})
                return
            base = f"/repos/{self.fake.repository}/releases"
            if self.role == "api" and parts.path == base:
                self.create(json.loads(self.body()))
                return
            match = re.fullmatch(rf"{base}/(\d+)/assets", parts.path)
            release = self.fake.releases.get(int(match.group(1))) if match else None
            if self.role != "uploads" or release is None:
                self.body()
                self.missing()
                return
            self.upload(release, parse_qs(parts.query)["name"][0])

    def create(self, payload: Row) -> None:
        tag = payload["tag_name"]
        if self.fake.published(tag) is not None:
            self.send(
                422,
                {
                    "message": "Validation Failed",
                    "errors": [{"code": "already_exists"}],
                },
            )
            return
        release = Release(
            next(self.fake._ids),
            tag,
            str(payload.get("name") or tag),
            str(payload.get("body") or ""),
            bool(payload.get("draft", False)),
            bool(payload.get("prerelease", False)),
        )
        self.fake.releases[release.id] = release
        if not release.draft:
            self.publish(release, payload.get("make_latest", "true"))
        self.send(201, self.fake.release_json(release))

    def publish(self, release: Release, make_latest: str) -> None:
        self.fake.tags.add(release.tag_name)
        if make_latest == "true" or (
            make_latest == "legacy" and self.fake.latest is None
        ):
            self.fake.latest = release.id

    def upload(self, release: Release, name: str) -> None:
        length = int(self.headers["Content-Length"])
        if any(a.name == name for a in release.assets):
            self.rfile.read(length)
            self.send(
                422,
                {
                    "message": "Validation Failed",
                    "errors": [{"code": "already_exists"}],
                },
            )
            return
        asset = Asset(next(self.fake._ids), name, b"", "starter")
        release.assets.append(asset)
        if self.fake.fail_upload_after is not None and (
            self.fake.fail_upload_name in {None, name}
        ):
            asset.data = self.rfile.read(self.fake.fail_upload_after)
            self.fake.fail_upload_after = None
            self.close_connection = True
            self.connection.shutdown(2)
            return
        asset.data = self.rfile.read(length)
        asset.state = "uploaded"
        self.send(201, self.fake.asset_json(release, asset))

    def do_PATCH(self) -> None:
        with self.fake.lock:
            authorized = self.record()
            payload = json.loads(self.body())
            match = re.fullmatch(
                rf"/repos/{self.fake.repository}/releases/(\d+)", self.path
            )
            release = self.fake.releases.get(int(match.group(1))) if match else None
            if not authorized or release is None or self.role != "api":
                self.missing()
                return
            if "tag_name" in payload:
                release.tag_name = payload["tag_name"]
            for key in ("name", "body", "prerelease"):
                if key in payload:
                    setattr(release, key, payload[key])
            if release.draft and payload.get("draft") is False:
                release.draft = False
                self.publish(release, payload.get("make_latest", "true"))
            self.send(200, self.fake.release_json(release))

    def do_DELETE(self) -> None:
        with self.fake.lock:
            authorized = self.record()
            match = re.fullmatch(
                rf"/repos/{self.fake.repository}/releases/assets/(\d+)", self.path
            )
            found = self.fake.find_asset(int(match.group(1))) if match else None
            if not authorized or found is None or self.role != "api":
                self.missing()
                return
            found[0].assets.remove(found[1])
            self.send(204)


def handler(fake: FakeGithub, role: str) -> type[BaseHTTPRequestHandler]:
    return type(f"{role.title()}Handler", (Handler,), {"fake": fake, "role": role})


@contextmanager
def running(fake: FakeGithub | None = None) -> Iterator[FakeGithub]:
    """Serve `fake` on loopback for the duration of the block."""
    fake = fake or FakeGithub()
    servers = []
    try:
        for role in ("api", "uploads", "web", "objects"):
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler(fake, role))
            server.daemon_threads = True
            fake.urls[role] = f"http://127.0.0.1:{server.server_address[1]}"
            threading.Thread(target=server.serve_forever, daemon=True).start()
            servers.append(server)
        yield fake
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
