import pytest

from pytest_threadbudget.budget import make_plan


@pytest.mark.parametrize("cpus,workers,expected", [(16, 4, 4), (6, 4, 1), (1, 8, 1), (8, 1, 8)])
def test_auto_allocation(cpus, workers, expected):
    assert make_plan("auto", cpus, workers, None, {}).threads_per_worker == expected


def test_cpu_cap_cannot_expand_allocation():
    assert make_plan("auto", 4, 2, 20, {}).effective_cpus == 4
    assert make_plan("auto", 16, 2, 4, {}).threads_per_worker == 2


@pytest.mark.parametrize(
    "environment",
    [{"OMP_NUM_THREADS": "7"}, {"OPENBLAS_NUM_THREADS": ""}, {"MKL_NUM_THREADS": "2"}],
)
def test_explicit_environment_preserved(environment):
    plan = make_plan("auto", 8, 2, None, environment)
    assert not plan.active
    assert plan.explicit_environment == environment


def test_override_environment_requires_explicit_opt_in():
    assert make_plan("auto", 8, 2, None, {"OMP_NUM_THREADS": "7"}, True).active


@pytest.mark.parametrize("mode", ["0", "-1", "bogus", "1.5", ""])
def test_invalid_modes(mode):
    with pytest.raises(ValueError):
        make_plan(mode, 4, 2, None, {})


@pytest.mark.parametrize("cpus,workers,cap", [(0, 2, None), (4, 0, None), (4, 2, 0)])
def test_invalid_counts(cpus, workers, cap):
    with pytest.raises(ValueError):
        make_plan("auto", cpus, workers, cap, {})


def test_excess_workers_reported():
    assert make_plan("auto", 2, 4, None, {}).allocation_exceeds_budget


def test_fixed_threads_are_explicit_per_worker():
    plan = make_plan("3", 4, 2, None, {})
    assert plan.threads_per_worker == 3
    assert plan.allocation_exceeds_budget


def test_off_is_passive():
    plan = make_plan("off", 8, 2, None, {"OMP_NUM_THREADS": "7"})
    assert not plan.active
    assert plan.threads_per_worker is None
