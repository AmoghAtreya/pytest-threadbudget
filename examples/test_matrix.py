"""Synthetic workload. Useful for enforcement checks, not upstream impact claims."""

import os

import numpy as np
import pytest
from threadpoolctl import threadpool_info


@pytest.mark.parametrize("seed", range(8))
def test_matrix_product(seed):
    rng = np.random.default_rng(seed)
    size = int(os.environ.get("THREADBUDGET_MATRIX_SIZE", "768"))
    matrix = rng.standard_normal((size, size))
    result = matrix @ matrix.T
    assert np.isfinite(result).all()
    np.testing.assert_allclose(np.diag(result), np.sum(matrix * matrix, axis=1), rtol=1e-10)


def test_budget_is_visible_when_requested():
    expected = os.environ.get("THREADBUDGET_EXPECT_THREADS")
    if expected is None:
        return
    pools = threadpool_info()
    if not pools:
        pytest.skip("No threadpoolctl-supported native runtime loaded on this platform")
    assert all(pool["num_threads"] <= int(expected) for pool in pools)
