import os
from types import SimpleNamespace

import pytest

from pytest_threadbudget.budget import make_plan
from pytest_threadbudget.plugin import State


def state_for_test():
    state = object.__new__(State)
    state.plan = make_plan("2", 8, 2, None, {})
    state.controller_only = False
    return state


def test_budget_never_raises_existing_native_limit(monkeypatch):
    seen = {}

    class Controller:
        def info(self):
            return [{"prefix": "openblas", "num_threads": 1}, {"prefix": "omp", "num_threads": 8}]

        def limit(self, *, limits):
            seen.update(limits)

    monkeypatch.setattr("threadpoolctl.ThreadpoolController", Controller)
    state_for_test().limit_existing_pools()
    assert seen == {"openblas": 1, "omp": 2}


def test_environment_restored_when_runtime_control_raises(monkeypatch):
    state = state_for_test()
    state.saved_environment = {}
    state.closed = False
    state.limiter = None
    monkeypatch.setenv("OMP_NUM_THREADS", "original")

    def fail():
        raise RuntimeError("unsupported runtime")

    state.limit_existing_pools = fail
    with pytest.raises(RuntimeError, match="unsupported runtime"):
        state.start()
    assert os.environ["OMP_NUM_THREADS"] == "original"


def test_runtime_limiter_restored_after_test_exception():
    restored = []
    state = state_for_test()
    state.limit_existing_pools = lambda: SimpleNamespace(
        restore_original_limits=lambda: restored.append(True)
    )
    state.observe = lambda phase: None
    with pytest.raises(RuntimeError):
        with state.boundary():
            raise RuntimeError("test failed")
    assert restored == [True]


def test_cleanup_is_idempotent():
    restored = []
    state = state_for_test()
    state.closed = False
    state.limiter = SimpleNamespace(restore_original_limits=lambda: restored.append(True))
    state.saved_environment = {}
    state.close()
    state.close()
    assert restored == [True]


def test_pool_observations_retain_earlier_violation(monkeypatch):
    state = state_for_test()
    state.mode = "auto"
    state.report_path = None
    state.observed = {}
    state.pool_observations = {}
    pool = {
        "filepath": "test-library",
        "user_api": "blas",
        "internal_api": "openblas",
        "num_threads": 8,
    }
    monkeypatch.setattr("threadpoolctl.threadpool_info", lambda: [dict(pool)])
    state.observe("after_test")
    pool["num_threads"] = 1
    state.observe("session_finish")
    observation = next(iter(state.pool_observations.values()))
    assert observation["max_num_threads"] == 8
    assert observation["min_num_threads"] == 1
    assert observation["ceiling_violations"] == 1
    assert observation["samples"] == 2
