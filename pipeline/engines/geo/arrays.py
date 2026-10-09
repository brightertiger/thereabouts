"""Array contracts shared by the point oracles and refinement."""

from typing import TypeAlias

import numpy as np
from numpy.typing import NDArray

FloatArray: TypeAlias = NDArray[np.float64]
IntArray: TypeAlias = NDArray[np.int64]
Labels: TypeAlias = NDArray[np.uint64]
