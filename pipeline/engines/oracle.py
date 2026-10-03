"""Array contracts used by refinement and geographic oracles."""

from typing import TypeAlias

import numpy as np
from numpy.typing import NDArray

FloatArray: TypeAlias = NDArray[np.float64]
Labels: TypeAlias = NDArray[np.uint64]
