"""
test_recommendation_math.py
---------------------------
Unit tests for the pure-math helpers in recommendation_math.py.

These tests run entirely in-process with no database dependency.
"""
import numpy as np
import pytest

from src.services.recommendation_math import (
    EMBEDDING_DIM,
    cosine_similarity,
    unit_vector,
    weighted_centroid,
)


# ─────────────────────────────────────────────────────────────────────────────
# unit_vector
# ─────────────────────────────────────────────────────────────────────────────

class TestUnitVector:
    def test_rejects_wrong_dimension_small(self):
        assert unit_vector([1.0, 2.0]) is None

    def test_rejects_wrong_dimension_large(self):
        assert unit_vector([0.0] * 1024) is None

    def test_rejects_none(self):
        assert unit_vector(None) is None

    def test_rejects_zero_vector(self):
        assert unit_vector([0.0] * EMBEDDING_DIM) is None

    def test_accepts_list(self):
        vec = [0.0] * EMBEDDING_DIM
        vec[0] = 1.0
        result = unit_vector(vec)
        assert result is not None
        assert result.shape == (EMBEDDING_DIM,)
        assert np.isclose(np.linalg.norm(result), 1.0)

    def test_accepts_numpy_array(self):
        arr = np.ones(EMBEDDING_DIM, dtype=np.float32)
        result = unit_vector(arr)
        assert result is not None
        assert np.isclose(np.linalg.norm(result), 1.0)

    def test_accepts_pgvector_text_format(self):
        vals = [1.0 if i == 0 else 0.0 for i in range(EMBEDDING_DIM)]
        text_repr = "[" + ",".join(map(str, vals)) + "]"
        result = unit_vector(text_repr)
        assert result is not None
        assert np.isclose(np.linalg.norm(result), 1.0)

    def test_output_is_unit_norm_for_arbitrary_input(self):
        rng = np.random.default_rng(42)
        arr = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        result = unit_vector(arr)
        assert result is not None
        assert np.isclose(np.linalg.norm(result), 1.0, atol=1e-6)


# ─────────────────────────────────────────────────────────────────────────────
# weighted_centroid
# ─────────────────────────────────────────────────────────────────────────────

class TestWeightedCentroid:
    def _random_unit(self, seed: int = 0) -> np.ndarray:
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        return v / np.linalg.norm(v)

    def test_returns_none_for_empty_input(self):
        assert weighted_centroid([], []) is None

    def test_output_is_unit_norm_equal_weights(self):
        v1 = self._random_unit(1)
        v2 = self._random_unit(2)
        result = weighted_centroid([v1, v2], [1.0, 1.0])
        assert result is not None
        assert np.isclose(np.linalg.norm(result), 1.0, atol=1e-6)

    def test_output_is_unit_norm_unequal_weights(self):
        v1 = self._random_unit(3)
        v2 = self._random_unit(4)
        result = weighted_centroid([v1, v2], [0.9, 0.1])
        assert result is not None
        assert np.isclose(np.linalg.norm(result), 1.0, atol=1e-6)

    def test_single_vector_returns_itself(self):
        v = self._random_unit(5)
        result = weighted_centroid([v], [1.0])
        assert result is not None
        assert np.allclose(result, v, atol=1e-6)

    def test_high_weight_pulls_centroid_closer(self):
        """Centroid should be closer to the high-weight vector."""
        v1 = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        v1[0] = 1.0                                       # points along dim 0
        v2 = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        v2[1] = 1.0                                       # points along dim 1
        result = weighted_centroid([v1, v2], [10.0, 1.0])
        assert result is not None
        # Should be closer to v1 (larger component on dim 0)
        assert result[0] > result[1]


# ─────────────────────────────────────────────────────────────────────────────
# cosine_similarity
# ─────────────────────────────────────────────────────────────────────────────

class TestCosineSimilarity:
    def test_identical_vectors_return_one(self):
        v = np.ones(EMBEDDING_DIM, dtype=np.float32)
        v /= np.linalg.norm(v)
        assert np.isclose(cosine_similarity(v, v), 1.0)

    def test_orthogonal_vectors_return_zero(self):
        a = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        b = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        a[0] = 1.0
        b[1] = 1.0
        assert np.isclose(cosine_similarity(a, b), 0.0)

    def test_opposite_vectors_return_minus_one(self):
        a = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        b = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        a[0] = 1.0
        b[0] = -1.0
        assert np.isclose(cosine_similarity(a, b), -1.0)
