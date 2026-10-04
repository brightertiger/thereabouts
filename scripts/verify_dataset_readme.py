"""Execute the three Python examples embedded in a generated dataset README."""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    code = re.findall(
        r"```python\n(.*?)\n```", (args.dataset / "README.md").read_text(), re.DOTALL
    )
    if len(code) != 3:
        raise ValueError("Expected exactly three worked read examples")
    environment = {**os.environ, "DATASET": str(args.dataset.absolute())}
    for name, example in zip(("DuckDB", "PyArrow", "pandas"), code, strict=True):
        result = subprocess.run(
            [sys.executable, "-c", example],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"{name}: {result.stdout.strip()}")


if __name__ == "__main__":
    main()
