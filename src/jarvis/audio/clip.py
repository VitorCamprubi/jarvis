"""A piece of mono audio in memory."""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

Samples = npt.NDArray[np.float32]


# eq=False: comparing numpy arrays with == is element-wise, not a boolean.
@dataclass(frozen=True, eq=False)
class AudioClip:
    samples: Samples  # mono, float32 in [-1, 1]
    sample_rate: int

    @property
    def duration_s(self) -> float:
        return len(self.samples) / self.sample_rate
