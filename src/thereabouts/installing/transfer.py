"""Stream pinned artifacts to temporary siblings; partial files are never active."""

import hashlib
import os
import tempfile
from http.client import HTTPException
from pathlib import Path
from typing import Any, BinaryIO
from urllib.error import URLError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..packs.errors import CorruptPackError
from ..packs.jsonio import relative_file
from .errors import DownloadError

COPY_BUFFER_BYTES = 1024 * 1024


def validate_url(url: str) -> str:
    parsed = urlsplit(url)
    local_http = parsed.scheme == "http" and parsed.hostname in (
        "127.0.0.1",
        "::1",
        "localhost",
    )
    if (parsed.scheme != "https" and not local_http) or not parsed.hostname:
        raise DownloadError("Use HTTPS (HTTP is allowed only for local testing)")
    if parsed.username or parsed.password or parsed.fragment:
        raise DownloadError("URLs cannot contain credentials or fragments")
    return url


class SecureRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        validate_url(newurl)
        if (
            urlsplit(req.full_url).scheme == "https"
            and urlsplit(newurl).scheme != "https"
        ):
            raise DownloadError("HTTPS redirects cannot downgrade transport")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def copy_checked(stream: BinaryIO, target: Path, size: int, digest: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=target.parent, prefix=".transfer-", delete=False
    ) as output:
        temporary = Path(output.name)
        try:
            remaining = size
            checksum = hashlib.sha256()
            while remaining:
                chunk = stream.read(min(remaining, COPY_BUFFER_BYTES))
                if not chunk:
                    raise DownloadError("Truncated transfer")
                output.write(chunk)
                checksum.update(chunk)
                remaining -= len(chunk)
            if stream.read(1):
                raise DownloadError("Transfer exceeds pinned byte count")
            if checksum.hexdigest() != digest:
                raise CorruptPackError(
                    "Transfer checksum differs from trusted manifest"
                )
            output.flush()
            os.fsync(output.fileno())
            output.close()
            os.replace(temporary, target)
        finally:
            output.close()
            temporary.unlink(missing_ok=True)


def transfer(
    source: str | Path,
    name: str,
    target: Path,
    *,
    size: int,
    digest: str,
    timeout: float,
) -> None:
    if isinstance(source, Path):
        with relative_file(source, name).open("rb") as stream:
            copy_checked(stream, target, size, digest)
        return
    url = source if name == "manifest.json" else urljoin(source, quote(name, safe="/"))
    validate_url(url)
    request = Request(url, headers={"Accept-Encoding": "identity"})
    try:
        with build_opener(SecureRedirects()).open(request, timeout=timeout) as response:
            if response.status != 200:
                raise DownloadError(f"Unexpected HTTP status: {response.status}")
            if response.headers.get("Content-Encoding", "identity") != "identity":
                raise DownloadError("Encoded HTTP payloads are unsupported")
            copy_checked(response, target, size, digest)
    except (URLError, TimeoutError, HTTPException, ConnectionError) as exc:
        raise DownloadError(f"Transfer failed: {exc}") from exc
