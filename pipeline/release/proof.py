"""Upload only what the pipeline itself built, checked and accepted.

`release upload` can publish any local directory. It first requires the
workspace ledger to hold completed `dataset` and `packs` units whose recorded
outputs are exactly the bytes about to be published: the dataset manifest
(which pins every dataset file), each archive with its acceptance report, and
the version index. A completed unit means its gates passed.
"""

from pathlib import Path

from pipeline.config import Config
from pipeline.runtime.jsonio import sha256_file
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.paths import located
from pipeline.runtime.records import Completion


def verify(root: Path, config: Config, version: str) -> None:
    path = located(root, config.paths.ledger)
    if not path.is_file():
        raise ValueError(f"Release upload found no pipeline ledger at {path}")
    dataset = located(root, config.paths.dataset) / version
    packs = located(root, config.paths.packs) / version
    families = config.release.packs.families
    expected = {
        ("dataset", version): [dataset / "manifest.json"],
        **{
            ("packs", f"{version}/{family}"): [
                packs / f"{family}.tar.zst",
                packs / "acceptance" / f"{family}.json",
            ]
            for family in families
        },
        **({("packs", f"{version}/index"): [packs / "index.json"]} if families else {}),
    }
    with Ledger(root, path) as ledger:
        for (stage, unit), files in expected.items():
            record = ledger.get(stage, unit)
            if record is None:
                raise ValueError(
                    f"Release upload needs proof: no completed {stage}/{unit} "
                    "in the ledger"
                )
            for file in files:
                if not recorded(root, record, file):
                    raise ValueError(
                        f"Release upload needs proof: {stage}/{unit} differs from "
                        f"its ledger record at {file.name}"
                    )


def recorded(root: Path, record: Completion, path: Path) -> bool:
    for output in record.outputs:
        if located(root, output.path) == path:
            return (
                path.is_file()
                and path.stat().st_size == output.size
                and sha256_file(path) == output.sha256
            )
    return False
