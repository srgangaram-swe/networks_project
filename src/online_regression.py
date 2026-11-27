"""Small online ridge models with fixed feature units and delayed updates."""

import math


class OnlineRidge:
    """Recursive least squares, O(D squared) time and memory per update.

    The inverse starts at identity, equivalent to a unit ridge penalty. No
    forgetting or rescaling uses information from a future observation.
    """

    def __init__(self, dimensions):
        if not 1 <= dimensions <= 16:
            raise ValueError("online ridge supports one through sixteen features")
        self.weights = [0.0] * dimensions
        self.inverse = [[float(i == j) for j in range(dimensions)] for i in range(dimensions)]
        self.samples = 0

    def predict(self, features):
        self._validate(features)
        return sum(a * b for a, b in zip(self.weights, features, strict=True))

    def update(self, features, target):
        self._validate(features)
        if not math.isfinite(target):
            raise ValueError("online target must be finite")
        product = [sum(a * b for a, b in zip(row, features, strict=True)) for row in self.inverse]
        divisor = 1 + sum(a * b for a, b in zip(features, product, strict=True))
        gain = [value / divisor for value in product]
        error = target - self.predict(features)
        self.weights = [w + g * error for w, g in zip(self.weights, gain, strict=True)]
        self.inverse = [
            [value - gain[i] * product[j] for j, value in enumerate(row)]
            for i, row in enumerate(self.inverse)
        ]
        self.samples += 1

    def _validate(self, features):
        if len(features) != len(self.weights) or any(not math.isfinite(x) for x in features):
            raise ValueError("online feature dimensions and values must match the model")
