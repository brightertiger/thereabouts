"""Checkpoint the country identity-link catalogue independently of assignment."""

from __future__ import annotations

from pathlib import Path

from build_data.acquire import Ledger, Workspace, atomic_output
from build_data.acquire.io import fingerprint, sha256_file

from .checkpoints import complete
from .common import Row, check_database, connect
from .matching import link_divisions, prepare_catalog


def catalog(
    workspace: Workspace, root: Path, country: str, inputs: str, policy: Row
) -> Path:
    digest = fingerprint(
        {
            "inputs": inputs,
            "country": country,
            "code": {
                name: sha256_file(Path(__file__).with_name(name))
                for name in ("common.py", "matching.py", "spatial.py")
            },
            "cutoffs": {k: v for k, v in policy.items() if "match_m" in k},
        }
    )
    output = workspace.work / "reconcile" / digest / f"{country}-links.sqlite"
    ledger = Ledger(workspace.ledger_path)
    if not ledger.is_complete("reconcile.links", country, digest):
        with atomic_output(output, check_database) as temp:
            db = connect(temp)
            try:
                prepare_catalog(db, root)
                link_divisions(db, root, policy)
            finally:
                db.close()
        complete(workspace, "reconcile.links", country, digest, [output])
        print(f"links {country}: complete", flush=True)
    return output
