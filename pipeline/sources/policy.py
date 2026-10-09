"""Explicit source policy files stay outside the interpolated config tree."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from pipeline.config.sources import SourceSettings
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.jsonio import sha256_file
from pipeline.runtime.paths import located


def policy_hashes(
    settings: SourceSettings, digest: Callable[[Path], str] = sha256_file
) -> dict[str, str]:
    return {
        name: digest(located(REPOSITORY, path))
        for name, path in sorted(settings.policies.items())
    }


def read_policies(settings: SourceSettings) -> dict[str, Any]:
    return {
        name: yaml.load(located(REPOSITORY, path).read_bytes(), Loader=yaml.CSafeLoader)
        for name, path in settings.policies.items()
    }
