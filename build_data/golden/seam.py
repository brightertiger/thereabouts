"""Keep date-seam subtrees bounded without assuming a connected H3 footprint."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from build_data.reconcile.lookup import Locator

from .geometry import Floats
from .oracle import Answer, Oracle
from .windows import envelopes


class SeamOracle:
    def __init__(
        self, locator: Locator, paths: dict[str, Path], coordinates: Floats
    ) -> None:
        self.parts = [Oracle(locator, paths, b) for b in envelopes(coordinates)]
        self.answers: list[Answer] = [(None, None, None, None, None)]
        self.codes = {self.answers[0]: 0}

    @property
    def labelled_points(self) -> int:
        return sum(p.labelled_points for p in self.parts)

    def translated(
        self, part: Oracle, labels: NDArray[np.uint64]
    ) -> NDArray[np.uint64]:
        mapping = []
        for answer in part.answers:
            if answer not in self.codes:
                self.codes[answer] = len(self.answers)
                self.answers.append(answer)
            mapping.append(self.codes[answer])
        return np.array(mapping, dtype=np.uint64)[labels]

    def labels(self, coordinates: Floats) -> NDArray[np.uint64]:
        result = np.zeros(len(coordinates), dtype=np.uint64)
        for index, part in enumerate(self.parts):
            selected = coordinates[:, 1] < 0 if index == 0 else coordinates[:, 1] >= 0
            result[selected] = self.translated(part, part.labels(coordinates[selected]))
        return result

    def certify(self, bounds: Floats) -> tuple[NDArray[np.uint64], NDArray[np.bool_]]:
        labels = np.zeros(len(bounds), dtype=np.uint64)
        uniform = np.zeros(len(bounds), dtype=np.bool_)
        for index, part in enumerate(self.parts):
            selected = bounds[:, 2] < 0 if index == 0 else bounds[:, 0] >= 0
            values, accepted = part.certify(bounds[selected])
            labels[selected] = self.translated(part, values)
            uniform[selected] = accepted
        return labels, uniform


def oracle(
    locator: Locator, paths: dict[str, Path], coordinates: Floats
) -> Oracle | SeamOracle:
    bounds = envelopes(coordinates)
    return (
        Oracle(locator, paths, bounds[0])
        if len(bounds) == 1
        else SeamOracle(locator, paths, coordinates)
    )
