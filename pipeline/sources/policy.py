"""Explicit source policy files stay outside the interpolated config tree."""

from typing import Any

import yaml

from pipeline.config.sources import SourceSettings
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.jsonio import sha256_file
from pipeline.runtime.paths import located


def policy_hashes(settings: SourceSettings) -> dict[str, str]:
    return {
        name: sha256_file(located(REPOSITORY, path))
        for name, path in sorted(settings.policies.items())
    }


def read_policies(settings: SourceSettings) -> dict[str, Any]:
    return {
        name: yaml.load(located(REPOSITORY, path).read_bytes(), Loader=yaml.CSafeLoader)
        for name, path in settings.policies.items()
    }
