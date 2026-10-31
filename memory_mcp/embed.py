"""Same local embedding model the capture service writes into Neon."""

from __future__ import annotations

import threading

_DIM = 384
_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_lock = threading.Lock()
_embedder = None


def embed(texts: list[str]) -> list[list[float]]:
    global _embedder
    with _lock:
        if _embedder is None:
            from fastembed import TextEmbedding

            _embedder = TextEmbedding(model_name=_MODEL_NAME)
        rows = [vector.tolist() for vector in _embedder.embed(texts)]
    if any(len(row) != _DIM for row in rows):
        raise RuntimeError("embedding size does not match the vector column")
    return rows
