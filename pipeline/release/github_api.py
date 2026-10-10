"""A small GitHub REST client for release publication, on the standard library.

Every URL is built from the configured API and upload origins; the token is
sent only to those two. Redirects are followed by hand, at most five, never from
HTTPS to plain HTTP, and the token is dropped as soon as the origin changes
(asset downloads redirect to an object host). Errors name the request and
GitHub's message but never the token.
"""

import hashlib
import http.client
import json
import ssl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import quote, urljoin, urlsplit

from pipeline.config.publication import GithubSettings, loopback, service_url

API_VERSION = "2022-11-28"
JSON = "application/vnd.github+json"
BINARY = "application/octet-stream"
MAX_JSON_BYTES = 64 << 20
MAX_PAGES = 100
MAX_REDIRECTS = 5
REDIRECTS = {301, 302, 303, 307, 308}
Row = dict[str, Any]


class GithubError(ValueError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def origin(url: str) -> tuple[str, str, int]:
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return parts.scheme, (parts.hostname or "").lower(), port


def safe_hop(current: str, target: str) -> None:
    """HTTPS anywhere; plain HTTP only from loopback HTTP to loopback (tests)."""
    now, then = urlsplit(current), urlsplit(target)
    if then.username is None and then.password is None and then.hostname:
        if then.scheme == "https":
            return
        if then.scheme == "http" and now.scheme == "http" and loopback(then.hostname):
            return
    raise GithubError(f"Refusing a redirect to {then.scheme}://{then.hostname}")


def next_page(link: str | None) -> str | None:
    for part in (link or "").split(","):
        target, _, relation = part.partition(";")
        if relation.strip() == 'rel="next"':
            return target.strip().removeprefix("<").removesuffix(">")
    return None


class Client:
    def __init__(
        self, settings: GithubSettings, token: str, read_bytes: int = 1 << 20
    ) -> None:
        if not token:
            raise GithubError("GitHub publication needs a token in GITHUB_TOKEN")
        self.api = service_url(settings.api_url, "GitHub API URL")
        self.uploads = service_url(settings.upload_url, "GitHub upload URL")
        self.repository = settings.repository
        self.timeout = settings.timeout_seconds
        self.read_bytes = read_bytes
        self._token = token
        self.trusted = {origin(self.api), origin(self.uploads)}

    def __repr__(self) -> str:
        return f"Client({self.api}, {self.repository})"

    @property
    def releases_url(self) -> str:
        return f"{self.api}/repos/{self.repository}/releases"

    @contextmanager
    def opened(
        self,
        method: str,
        url: str,
        *,
        body: bytes | BinaryIO | None = None,
        length: int = 0,
        accept: str = JSON,
        content_type: str = "application/json",
    ) -> Iterator[http.client.HTTPResponse]:
        """One request; GET follows redirects. Yields the final, unread response."""
        for _ in range(MAX_REDIRECTS + 1):
            parts = urlsplit(url)
            connection: http.client.HTTPConnection
            if parts.scheme == "https":
                connection = http.client.HTTPSConnection(
                    parts.hostname or "",
                    parts.port,
                    timeout=self.timeout,
                    blocksize=self.read_bytes,
                    context=ssl.create_default_context(),
                )
            else:
                connection = http.client.HTTPConnection(
                    parts.hostname or "",
                    parts.port,
                    timeout=self.timeout,
                    blocksize=self.read_bytes,
                )
            headers = {
                "Accept": accept,
                "User-Agent": "thereabouts-release",
                "X-GitHub-Api-Version": API_VERSION,
            }
            if origin(url) in self.trusted:
                headers["Authorization"] = f"Bearer {self._token}"
            if body is not None:
                headers["Content-Type"] = content_type
                headers["Content-Length"] = str(length)
            target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
            try:
                connection.request(method, target, body=body, headers=headers)
                response = connection.getresponse()
            except (OSError, http.client.HTTPException) as error:
                connection.close()
                raise GithubError(
                    f"GitHub {method} {parts.path} was interrupted: {error}"
                ) from error
            if method == "GET" and response.status in REDIRECTS:
                location = response.getheader("Location")
                response.read()
                connection.close()
                if not location:
                    raise GithubError(f"GitHub redirect without a location: {url}")
                following = urljoin(url, location)
                safe_hop(url, following)
                url = following
                continue
            try:
                yield response
            finally:
                response.close()
                connection.close()
            return
        raise GithubError(f"Too many redirects from GitHub: {url}")

    def failure(
        self, method: str, url: str, response: http.client.HTTPResponse, data: bytes
    ) -> GithubError:
        try:
            message = str(json.loads(data).get("message", ""))[:300]
        except (ValueError, AttributeError):
            message = ""
        if response.getheader("x-ratelimit-remaining") == "0":
            reset = response.getheader("x-ratelimit-reset")
            message += f" (rate limit exhausted until {reset})"
        path = urlsplit(url).path
        return GithubError(
            f"GitHub {method} {path} returned {response.status}: {message}",
            response.status,
        )

    def json(
        self,
        method: str,
        url: str,
        payload: Row | None = None,
        ok: tuple[int, ...] = (200,),
    ) -> Any:
        body = None if payload is None else json.dumps(payload).encode()
        with self.opened(method, url, body=body, length=len(body or b"")) as response:
            data = response.read(MAX_JSON_BYTES + 1)
            if response.status not in ok:
                raise self.failure(method, url, response, data)
        if len(data) > MAX_JSON_BYTES:
            raise GithubError(f"GitHub response too large: {urlsplit(url).path}")
        return json.loads(data) if data else None

    def paginate(self, url: str) -> list[Row]:
        items: list[Row] = []
        for _ in range(MAX_PAGES):
            with self.opened("GET", url) as response:
                data = response.read(MAX_JSON_BYTES + 1)
                if response.status != 200:
                    raise self.failure("GET", url, response, data)
                following = next_page(response.getheader("Link"))
            page = json.loads(data)
            if not isinstance(page, list):
                raise GithubError(f"GitHub list response is not a list: {url}")
            items += page
            if following is None:
                return items
            if origin(following) != origin(self.api):
                raise GithubError("GitHub pagination left the API origin")
            url = following
        raise GithubError(f"GitHub list exceeds {MAX_PAGES} pages: {url}")

    def releases(self) -> list[Row]:
        """Every release, drafts included (which needs push access)."""
        return self.paginate(f"{self.releases_url}?per_page=100")

    def create_release(self, payload: Row) -> Row:
        return dict(self.json("POST", self.releases_url, payload, ok=(201,)))

    def update_release(self, release_id: int, payload: Row) -> Row:
        return dict(self.json("PATCH", f"{self.releases_url}/{release_id}", payload))

    def release(self, release_id: int) -> Row:
        return dict(self.json("GET", f"{self.releases_url}/{release_id}"))

    def assets(self, release_id: int) -> list[Row]:
        return self.paginate(f"{self.releases_url}/{release_id}/assets?per_page=100")

    def upload(self, release_id: int, name: str, path: Path) -> Row:
        url = (
            f"{self.uploads}/repos/{self.repository}/releases/{release_id}"
            f"/assets?name={quote(name)}"
        )
        size = path.stat().st_size
        with (
            path.open("rb") as stream,
            self.opened(
                "POST", url, body=stream, length=size, content_type=BINARY
            ) as response,
        ):
            data = response.read(MAX_JSON_BYTES + 1)
            if response.status != 201:
                raise self.failure("POST", url, response, data)
        return dict(json.loads(data))

    def delete_asset(self, asset_id: int) -> None:
        self.json("DELETE", f"{self.releases_url}/assets/{asset_id}", ok=(204,))

    def download(self, asset_id: int) -> tuple[int, str]:
        """Stream an asset through its object-host redirect; returns size, SHA-256."""
        url = f"{self.releases_url}/assets/{asset_id}"
        digest = hashlib.sha256()
        count = 0
        with self.opened("GET", url, accept=BINARY) as response:
            if response.status != 200:
                raise self.failure("GET", url, response, response.read(1 << 16))
            while chunk := response.read(self.read_bytes):
                digest.update(chunk)
                count += len(chunk)
        return count, digest.hexdigest()
