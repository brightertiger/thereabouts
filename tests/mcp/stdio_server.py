"""Run the real command with outbound networking forbidden in the child too."""

import pytest

from tests.network_guard import install
from thereabouts.cli import main

if __name__ == "__main__":
    with pytest.MonkeyPatch.context() as patch:
        install(patch)
        raise SystemExit(main())
