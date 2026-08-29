"""
recommendation_math.py
-----------------------
Pure numerical helpers for the WaveCask recommendation engine.
No database or I/O dependencies – safe to import anywhere.
"""
from __future__ import annotations

import numpy as np

EMBEDDING_DIM = 512


def unit_vector(value) -> np.ndarray | None:
    """
    Parse and L2-normalise an embedding from any of the formats that pgvector
    may return (native list, numpy array, or text like '[0.1,0.2,...]').

    Returns None if the value is missing, unparseable, or has a dimension other
    than EMBEDDING_DIM (512).  Never silently pads or truncates.
    """
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip().strip("[]")
        try:
            value = [float(x) for x in stripped.split(",") if x.strip()]
        except ValueError:
            return None
    arr = np.asarray(value, dtype=np.float32)
    if arr.shape != (EMBEDDING_DIM,):
        return None
    norm = float(np.linalg.norm(arr))
    return None if norm <= 1e-8 else arr / norm


def weighted_centroid(
    vectors: list[np.ndarray], weights: list[float]
) -> np.ndarray | None:
    """
    Compute a weighted average of unit vectors and re-normalise the result.
    Returns None when the input list is empty or the resulting vector is
    numerically zero.
    """
    if not vectors:
        return None
    matrix = np.asarray(vectors, dtype=np.float32)
    w = np.asarray(weights, dtype=np.float32)
    w = np.maximum(w, 1e-4)          # guard against all-zero weights
    centroid = np.average(matrix, axis=0, weights=w)
    norm = float(np.linalg.norm(centroid))
    return None if norm <= 1e-8 else centroid / norm


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Dot-product similarity of two pre-normalised unit vectors, clipped to [-1, 1]."""
    return float(np.clip(np.dot(a, b), -1.0, 1.0))
