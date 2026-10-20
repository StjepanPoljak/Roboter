"""Known faces, stored locally as embeddings (128 numbers per sample), never as photos."""

import logging
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)


class FaceDB:
    def __init__(self, path: Path):
        self.path = path
        self.names: list[str] = []
        self.embeddings = np.empty((0, 128), dtype=np.float32)
        if path.exists():
            data = np.load(path)
            self.names = [str(n) for n in data["names"]]
            self.embeddings = data["embeddings"].astype(np.float32)
            log.info("loaded %d face samples for %s", len(self.names), ", ".join(self.people()) or "nobody")

    def people(self) -> list[str]:
        return sorted(set(self.names))

    def add(self, name: str, embedding: np.ndarray) -> None:
        self.names.append(name)
        self.embeddings = np.vstack([self.embeddings, _normalize(embedding)[None, :]])

    def remove(self, name: str) -> int:
        keep = [i for i, n in enumerate(self.names) if n != name]
        removed = len(self.names) - len(keep)
        self.names = [self.names[i] for i in keep]
        self.embeddings = self.embeddings[keep]
        return removed

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # np.savez appends .npz unless the name already ends with it.
        np.savez(self.path, names=np.array(self.names), embeddings=self.embeddings)

    def match(self, embedding: np.ndarray, threshold: float) -> tuple[str | None, float]:
        """Best-matching name by cosine similarity, or None when below the threshold."""
        if not self.names:
            return None, 0.0
        similarities = self.embeddings @ _normalize(embedding)
        best = int(np.argmax(similarities))
        score = float(similarities[best])
        return (self.names[best] if score >= threshold else None), score


def _normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32).flatten()
    return v / (np.linalg.norm(v) + 1e-9)
