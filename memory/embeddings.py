import hashlib
import math


class EmbeddingModel:
    """Small deterministic embedding with no downloaded/pretrained model."""

    def __init__(self, dimensions=512):
        self.dimensions = max(32, int(dimensions))

    def encode(self, text):
        text = str(text or "")
        vector = [0.0] * self.dimensions

        if not text:
            return vector

        normalized = " ".join(text.lower().split())
        features = []

        for token in normalized.split():
            features.append(token)
            features.append("^" + token[:8])
            if len(token) > 1:
                features.extend(
                    token[i:i + 2]
                    for i in range(len(token) - 1)
                )

        for feature in features:
            digest = hashlib.blake2b(
                feature.encode("utf-8", errors="ignore"),
                digest_size=8,
            ).digest()
            index = int.from_bytes(digest, "big") % self.dimensions
            sign = 1.0 if digest[0] & 1 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]

        return vector
