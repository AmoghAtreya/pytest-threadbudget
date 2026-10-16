import json
import os
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

from pytest_threadbudget.benchmark import (
    main,
    read_outcomes,
    run_trial,
    runtime_enforcement_verified,
    summarize,
)


def trial(mode, seconds, outcomes=None, **extra):
    return {
        "mode": mode,
        "warmup": False,
        "exitcode": 0,
        "timed_out": False,
        "wall_seconds": seconds,
        "sampled_peak_process_tree_threads": 8,
        "sampled_cpu_seconds": 1,
        "runtime_enforcement_verified": mode == "auto",
        "outcomes": outcomes if outcomes is not None else [("case", "test", "passed")],
        **extra,
    }


def test_summary_uses_median_and_reports_slowdowns():
    report = summarize(
        [
            trial("off", 10),
            trial("off", 11),
            trial("off", 100),
            trial("auto", 15),
            trial("auto", 16),
            trial("auto", 17),
        ]
    )
    assert report["off"]["wall_seconds"]["median"] == 11
    assert report["median_wall_reduction_percent"] < 0


def test_no_speed_claim_on_different_outcomes():
    report = summarize(
        [trial("off", 10), trial("auto", 1, outcomes=[("case", "different", "passed")])]
    )
    assert not report["all_runs_passed_with_identical_outcomes"]
    assert report["median_wall_reduction_percent"] is None


def test_no_speed_claim_without_runtime_enforcement():
    report = summarize([trial("off", 10), trial("auto", 1, runtime_enforcement_verified=False)])
    assert report["median_wall_reduction_percent"] is None


def test_earlier_pool_violation_cannot_be_hidden_by_final_snapshot():
    report = {
        "workers": [
            {
                "active_in_this_process": True,
                "exitstatus": 0,
                "plan": {"threads_per_worker": 2},
                "pools": [{"num_threads": 2}],
                "pool_observations": [{"max_num_threads": 8, "ceiling_violations": 1}],
            }
        ],
        "worker_errors": [],
    }
    assert not runtime_enforcement_verified(report)
    report["workers"][0]["pool_observations"] = [{"max_num_threads": 2, "ceiling_violations": 0}]
    assert runtime_enforcement_verified(report)
    report["workers"][0]["pool_observations"][0]["unknown_thread_counts"] = 1
    assert not runtime_enforcement_verified(report)


def test_timeout_invalidates_benchmark():
    report = summarize([trial("off", 10), trial("auto", 1, timed_out=True)])
    assert not report["all_runs_passed_with_identical_outcomes"]


def test_setup_errors_are_explained_and_timing_is_invalid():
    errors = [("c", "test", "error")]
    report = summarize(
        [
            trial("off", 1, outcomes=errors, exitcode=1),
            trial("auto", 2, outcomes=errors, exitcode=1),
        ]
    )
    assert not report["all_runs_passed_with_identical_outcomes"]
    assert any("errors=1" in reason for reason in report["invalid_reasons"])
    assert report["median_wall_reduction_percent"] is None


def test_runner_stops_after_first_failed_warmup(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    calls = []

    def fake_trial(command, directory, timeout, interval):
        calls.append(command)
        directory.mkdir(parents=True)
        (directory / "junit.xml").write_text(
            '<testsuite><testcase classname="c" name="test"><error>setup failed</error></testcase></testsuite>'
        )
        return {
            "exitcode": 1,
            "timed_out": False,
            "wall_seconds": 0.1,
            "sampled_peak_process_tree_threads": None,
            "sampled_cpu_seconds": None,
        }

    monkeypatch.setattr("pytest_threadbudget.benchmark.run_trial", fake_trial)
    output = tmp_path / "audit"
    assert main(["--output", str(output), "--repeats", "3", "--", "test_case.py"]) == 1
    assert len(calls) == 1
    report = json.loads((output / "summary.json").read_text())["summary"]
    assert report["invalid_reasons"]
    assert report["off"]["wall_seconds"]["median"] is None
    assert report["median_wall_reduction_percent"] is None


def test_statsmodels_runner_uses_absolute_path_and_isolated_environment(tmp_path, monkeypatch):
    package = tmp_path / "package"
    test_file = package / "regression/tests/test_regression.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_placeholder(): pass\n")
    monkeypatch.setattr("importlib.metadata.version", lambda name: "test-version")
    monkeypatch.setattr(
        "importlib.util.find_spec",
        lambda name: SimpleNamespace(origin=str(package / "__init__.py")),
    )
    monkeypatch.setenv("OMP_NUM_THREADS", "7")
    calls = []

    def capture(command, *, env):
        calls.append((command, env))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("subprocess.run", capture)
    script = Path(__file__).resolve().parents[1] / "scripts/validate_statsmodels.py"
    monkeypatch.setattr(sys, "argv", [str(script), "--output", str(tmp_path / "results")])
    namespace = runpy.run_path(str(script))
    assert namespace["main"]() == 0
    assert len(calls) == 2
    for command, env in calls:
        assert str(test_file) in command
        assert "--pyargs" not in command
        assert "OMP_NUM_THREADS" not in env
    assert "OPENBLAS_NUM_THREADS" not in calls[0][1]
    assert calls[1][1]["OPENBLAS_NUM_THREADS"] == "1"
    assert os.environ["OMP_NUM_THREADS"] == "7"


def test_unavailable_resource_metrics_are_null():
    report = summarize(
        [
            trial("off", 10, sampled_peak_process_tree_threads=None, sampled_cpu_seconds=None),
            trial("auto", 5, sampled_peak_process_tree_threads=None, sampled_cpu_seconds=None),
        ]
    )
    assert report["auto"]["sampled_cpu_seconds"]["median"] is None
    assert report["median_wall_reduction_percent"] == 50


def test_all_skipped_is_not_a_valid_benchmark():
    report = summarize(
        [
            trial("off", 10, outcomes=[("c", "t", "skipped")]),
            trial("auto", 5, outcomes=[("c", "t", "skipped")]),
        ]
    )
    assert not report["all_runs_passed_with_identical_outcomes"]


def test_dependency_changes_invalidate_comparison():
    report = summarize([trial("off", 10), trial("auto", 5, environment_unchanged=False)])
    assert not report["all_runs_passed_with_identical_outcomes"]
    assert report["median_wall_reduction_percent"] is None


def test_warmup_excluded_from_median():
    report = summarize(
        [
            trial("off", 100, warmup=True),
            trial("auto", 100, warmup=True),
            trial("off", 10),
            trial("auto", 5),
        ]
    )
    assert report["median_wall_reduction_percent"] == 50


def test_junit_compares_each_test_identity(tmp_path):
    path = tmp_path / "test.xml"
    path.write_text(
        '<testsuites><testsuite><testcase classname="c" name="a"/><testcase classname="c" name="b"><failure/></testcase></testsuite></testsuites>'
    )
    assert read_outcomes(path) == [("c", "a", "passed"), ("c", "b", "failure")]


def test_sampling_permission_failure_does_not_abort_trial(tmp_path, monkeypatch):
    import subprocess

    import psutil

    polls = iter([None, 0])

    class Process:
        pid = 123
        returncode = 0

        def poll(self):
            return next(polls)

        def wait(self):
            return 0

    class Parent:
        def children(self, **kwargs):
            raise PermissionError("sampling blocked")

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(psutil, "Process", lambda pid: Parent())
    report = run_trial(["unused"], tmp_path / "trial", 10, 0.001)
    assert report["exitcode"] == 0
    assert report["sampled_cpu_seconds"] is None
    assert report["sampled_peak_process_tree_threads"] is None
    assert "PermissionError" in report["sampling_notes"]


def test_timeout_terminates_our_trial_process(tmp_path):
    report = run_trial(
        [sys.executable, "-c", "import time; time.sleep(10)"], tmp_path / "timeout", 0.2, 0.02
    )
    assert report["timed_out"]
    assert report["exitcode"] != 0
    assert report["wall_seconds"] < 5
