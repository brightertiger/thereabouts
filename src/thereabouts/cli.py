"""JSON command-line interface. Data transfers require an explicit install command."""

import argparse
import json
import os
import sys
from typing import Any

from .client import Geocoder
from .client_errors import InvalidInputError
from .commandline.parser import parser
from .commandline.rows import rows
from .errors import GeocoderError
from .installing.errors import InstallationError
from .installing.install import install
from .packs.metadata import read_manifest
from .packs.verify import verify
from .results import Resolution
from .store import installed_pack, list_packs


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False))


def _query(
    geo: Geocoder,
    kind: str,
    values: list[str],
    country: str | None = None,
    scheme: str | None = None,
) -> Resolution:
    if kind in ("coordinates", "h3") and (country is not None or scheme is not None):
        raise InvalidInputError("Coordinate and H3 queries do not accept code context")
    if kind == "postal" and scheme is not None:
        raise InvalidInputError("Postal queries do not accept an airport scheme")
    if kind == "postal" and len(values) == 1:
        return geo.postal(values[0], country=country)
    if kind == "airport" and len(values) == 1:
        return geo.airport(values[0], country=country, scheme=scheme)
    if kind == "h3" and len(values) == 1:
        return geo.from_h3(values[0])
    if kind == "coordinates" and len(values) == 2:
        try:
            latitude, longitude = map(float, values)
        except ValueError as exc:
            raise InvalidInputError("Coordinates require two numeric values") from exc
        return geo.reverse(latitude, longitude)
    raise InvalidInputError("Expected one H3 cell or two coordinates")


def _data(args: argparse.Namespace) -> int:
    if args.pack and args.operation != "verify":
        raise InvalidInputError("--pack is only supported for data verify")
    if args.operation == "install":
        path = install(
            args.source,
            manifest_sha256=args.sha256,
            data_dir=args.data_dir,
            manifest_bytes=args.manifest_bytes,
            offline=args.offline,
            timeout=args.timeout,
        )
        emit({"installed": str(path), "manifest_sha256": args.sha256})
    elif args.operation == "list":
        emit(list_packs(args.data_dir))
    else:
        from pathlib import Path

        path = (
            Path(args.pack)
            if args.pack
            else installed_pack(args.data_dir, family=args.family or "reverse")
        )
        value = verify(path) if args.full else read_manifest(path)
        if args.family is not None and value["family"] != args.family:
            raise InvalidInputError("Selected pack has a different family")
        emit(
            {
                "verified": "full" if args.full else "inventory",
                "manifest_sha256": value["manifest_sha256"],
            }
        )
    return 0


def _run(args: argparse.Namespace) -> int:
    if args.command == "data":
        return _data(args)
    if args.command == "mcp":
        try:
            from .mcp_service.server import run
        except ModuleNotFoundError as exc:
            if exc.name != "mcp":
                raise
            raise InvalidInputError(
                "MCP is optional; install thereabouts[mcp] explicitly"
            ) from exc
        run(args.pack, args.data_dir, args.families)
        return 0
    kind = args.kind if args.command in ("resolve", "explain") else args.command
    family = {"postal": "postal", "airport": "airports"}.get(kind, "reverse")
    selection = None if args.pack else [family]
    with Geocoder(args.pack, data_dir=args.data_dir, packs=selection) as geo:
        if args.command == "reverse":
            emit(geo.reverse(args.latitude, args.longitude).to_dict())
        elif args.command in ("postal", "airport"):
            answer = _query(
                geo,
                args.command,
                [args.value],
                args.country,
                getattr(args, "scheme", None),
            )
            emit(answer.to_dict())
        elif args.command == "h3":
            emit(geo.from_h3(args.cell).to_dict())
        elif args.command in ("resolve", "explain"):
            answer = _query(geo, args.kind, args.values, args.country, args.scheme)
            emit(geo.explain(answer) if args.command == "explain" else answer.to_dict())
        elif args.command == "info":
            emit(geo.info())
        elif args.command == "batch":
            source = rows(
                sys.stdin,
                format=args.format,
                kind=args.kind,
                latitude=args.latitude_column,
                longitude=args.longitude_column,
                cell=args.h3_column,
            )
            answers = (
                geo.reverse_many if args.kind == "coordinates" else geo.from_h3_many
            )(
                source,
                errors=args.errors,
                chunk_size=args.chunk_size,
            )
            failed = False
            for answer in answers:
                emit(answer.to_dict())
                failed |= answer.status == "invalid_input"
            return 5 if failed else 0
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = _run(args)
        sys.stdout.flush()
        return result
    except BrokenPipeError:
        # Prevent a second BrokenPipeError during interpreter shutdown.
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
        return 0
    except InvalidInputError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (InstallationError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 4
    except GeocoderError as exc:
        print(str(exc), file=sys.stderr)
        return 3
