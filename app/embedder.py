"""Local embeddings via fastembed (ONNX Runtime, CPU, no PyTorch).

If fastembed is not installed the app degrades to keyword-only retrieval
instead of failing — useful for a zero-download run.
"""

from __future__ import annotations

import math
import os
import threading

from .config import EMBED_MODEL, EMBEDDINGS_ENABLED, ROOT

# Windows without Developer Mode cannot create the symlinks the HF cache wants;
# these must be set before fastembed imports huggingface_hub.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

CACHE_DIR = ROOT / "store" / "models"

_model = None
_lock = threading.Lock()
_status = "disabled" if not EMBEDDINGS_ENABLED else "not-loaded"


def status() -> str:
    return _status


def available() -> bool:
    return _load() is not None


def _load():
    global _model, _status
    if not EMBEDDINGS_ENABLED:
        return None
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        try:
            from fastembed import TextEmbedding
        except ImportError:
            _status = "fastembed-not-installed"
            return None
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _model = TextEmbedding(model_name=EMBED_MODEL, cache_dir=str(CACHE_DIR))
            _status = f"loaded:{EMBED_MODEL}"
        except Exception as exc:  # model download / runtime failure
            _status = f"error:{type(exc).__name__}"
            return None
    return _model


def _normalise(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def embed(texts: list[str]) -> list[list[float]] | None:
    """Return unit-length vectors, or None when embeddings are unavailable."""
    model = _load()
    if model is None or not texts:
        return None
    return [_normalise([float(v) for v in vec]) for vec in model.embed(texts)]


def embed_query(text: str) -> list[float] | None:
    # bge models want a retrieval prefix on the query side only.
    prefix = "Represent this sentence for searching relevant passages: "
    vectors = embed([prefix + text if "bge" in EMBED_MODEL.lower() else text])
    return vectors[0] if vectors else None


def cosine(a: list[float], b: list[float]) -> float:
    """Both sides are unit-length, so the dot product is the cosine."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))
