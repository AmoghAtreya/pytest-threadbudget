import importlib.util
import json
import os
import subprocess
import sys

import pytest

from pytest_threadbudget.budget import THREAD_ENV


def run_pytest(tmp_path, source, *arguments, environment=None, conftest=None):
    (tmp_path / "test_case.py").write_text(source)
    if conftest:
        (tmp_path / "conftest.py").write_text(conftest)
    env = dict(os.environ)
    for name in THREAD_ENV:
        env.pop(name, None)
    env.pop("PYTEST_ADDOPTS", None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.update(environment or {})
    # With -c /dev/null, pytest 8.0 needs an explicit conftest boundary to
    # avoid traversing unrelated, potentially protected filesystem ancestors.
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "threadbudget",
        "-p",
        "xdist.plugin",
        "-c",
        os.devnull,
        "--confcutdir",
        str(tmp_path),
        "--rootdir",
        str(tmp_path),
        str(tmp_path / "test_case.py"),
        f"--threadbudget-report={tmp_path / 'report.json'}",
        "-q",
        *arguments,
    ]
    result = subprocess.run(
        command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60
    )
    result.diagnostic = result.stdout + result.stderr
    report = tmp_path / "report.json"
    return result, json.loads(report.read_text()) if report.exists() else None


def test_passive_install_leaves_environment(tmp_path):
    result, report = run_pytest(
        tmp_path,
        'import os\ndef test_env():\n assert os.environ["OMP_NUM_THREADS"] == "7"',
        environment={"OMP_NUM_THREADS": "7"},
    )
    assert result.returncode == 0, result.diagnostic
    assert not report["workers"][0]["active_in_this_process"]


def test_explicit_environment_preserved(tmp_path):
    result, report = run_pytest(
        tmp_path,
        'import os\ndef test_env():\n assert os.environ["OMP_NUM_THREADS"] == "7"',
        "--threadbudget=1",
        environment={"OMP_NUM_THREADS": "7"},
    )
    assert result.returncode == 0, result.diagnostic
    assert "preserved" in report["workers"][0]["plan"]["reason"]


def test_override_environment(tmp_path):
    result, report = run_pytest(
        tmp_path,
        'import os\ndef test_env():\n assert os.environ["OMP_NUM_THREADS"] == "1"',
        "--threadbudget=1",
        "--threadbudget-override-env",
        environment={"OMP_NUM_THREADS": "7"},
    )
    assert result.returncode == 0, result.diagnostic
    assert report["workers"][0]["active_in_this_process"]


@pytest.mark.parametrize("workers", [1, 2])
def test_actual_xdist_workers_get_budget(tmp_path, workers):
    source = """import os
import pytest
@pytest.mark.parametrize("case", range(4))
def test_env(case):
    assert os.environ["OMP_NUM_THREADS"] == "1"
    assert os.environ["OPENBLAS_NUM_THREADS"] == "1"
"""
    result, report = run_pytest(
        tmp_path,
        source,
        "-n",
        str(workers),
        "--threadbudget=auto",
        f"--threadbudget-cpus={workers}",
    )
    assert result.returncode == 0, result.diagnostic
    assert len(report["workers"]) == workers
    assert not report["worker_errors"]
    assert sum(worker["outcomes"]["passed"] for worker in report["workers"]) == 4
    assert all(worker["plan"]["threads_per_worker"] == 1 for worker in report["workers"])


@pytest.mark.parametrize("late", [False, True])
def test_native_enforcement_with_early_and_late_imports(tmp_path, late):
    source = """def test_pool():
    import numpy as np
    import pytest
    from threadpoolctl import threadpool_info
    np.ones((32,32)) @ np.ones((32,32))
    pools = threadpool_info()
    if not pools:
        pytest.skip("No supported native runtime in installed NumPy")
    assert all(pool["num_threads"] == 1 for pool in pools)
"""
    result, report = run_pytest(
        tmp_path, source, "--threadbudget=1", conftest=None if late else "import numpy\n"
    )
    assert result.returncode == 0, result.diagnostic
    outcomes = report["workers"][0]["outcomes"]
    if outcomes["skipped"]:
        pytest.skip("NumPy backend is not controlled by threadpoolctl on this machine")
    assert outcomes["passed"] == 1
    assert report["workers"][0]["pools"]


def test_environment_and_existing_pools_restored_in_process(tmp_path):
    script = """import os, pytest, numpy
from threadpoolctl import threadpool_info
from pytest_threadbudget.budget import THREAD_ENV
for key in THREAD_ENV: os.environ.pop(key, None)
before = {p["filepath"]:p["num_threads"] for p in threadpool_info()}
result = pytest.main(["-p", "threadbudget", "-c", os.devnull, "--confcutdir", %r, "--rootdir", %r, %r, "--threadbudget=1", "-q"])
assert result == 0
assert all(key not in os.environ for key in THREAD_ENV)
after = {p["filepath"]:p["num_threads"] for p in threadpool_info()}
assert before == after, (before,after)
""" % (str(tmp_path), str(tmp_path), str(tmp_path / "test_case.py"))
    (tmp_path / "test_case.py").write_text("def test_pass(): pass\n")
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    env.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_invalid_mode_is_usage_error(tmp_path):
    result, _ = run_pytest(tmp_path, "def test_ok(): pass", "--threadbudget=invalid")
    assert result.returncode == 4
    assert "positive integer" in result.diagnostic


def test_failed_test_retains_failure_and_report(tmp_path):
    result, report = run_pytest(tmp_path, "def test_bad(): assert False", "--threadbudget=1")
    assert result.returncode == 1
    assert report["workers"][0]["outcomes"]["failed"] == 1


def test_worker_crash_is_reported_without_hiding_failure(tmp_path):
    result, report = run_pytest(
        tmp_path,
        "import os\ndef test_crash(): os._exit(3)",
        "-n",
        "1",
        "--max-worker-restart=0",
        "--threadbudget=1",
    )
    assert result.returncode == 1, result.diagnostic
    assert report["worker_errors"]
    assert "INTERNALERROR" not in result.diagnostic


def test_explicit_remote_hosts_are_rejected(tmp_path):
    result, _ = run_pytest(tmp_path, "def test_ok(): pass", "--tx=popen", "--threadbudget=auto")
    assert result.returncode == 4, result.diagnostic
    assert "explicit --tx" in result.diagnostic


def test_report_write_failure_is_visible(tmp_path):
    (tmp_path / "blocked").write_text("not a directory")
    result, _ = run_pytest(
        tmp_path,
        "def test_ok(): pass",
        f"--threadbudget-report={tmp_path / 'blocked' / 'report.json'}",
    )
    assert result.returncode != 0
    assert "Cannot write threadbudget report" in result.diagnostic


def test_cli_overrides_ini_and_serial_execution(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\nthreadbudget = 2\n")
    source = 'import os\ndef test_limit(): assert os.environ["OMP_NUM_THREADS"] == "1"\n'
    result, report = run_pytest(
        tmp_path, source, "-c", str(tmp_path / "pytest.ini"), "--threadbudget=1"
    )
    assert result.returncode == 0, result.diagnostic
    assert report["workers"][0]["worker"] == "serial"
    assert report["workers"][0]["plan"]["threads_per_worker"] == 1


@pytest.mark.skipif(not hasattr(os, "sched_setaffinity"), reason="Requires Linux CPU affinity")
def test_budget_respects_actual_process_affinity(tmp_path):
    test_file = tmp_path / "test_affinity.py"
    test_file.write_text(
        'import os\ndef test_limit(): assert os.environ["OMP_NUM_THREADS"] == "1"\n'
    )
    report_file = tmp_path / "report.json"
    code = """import os, pytest
os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
raise SystemExit(pytest.main(%r))
""" % [
        "-p",
        "threadbudget",
        "-c",
        os.devnull,
        "--confcutdir",
        str(tmp_path),
        "--rootdir",
        str(tmp_path),
        str(test_file),
        "--threadbudget=auto",
        f"--threadbudget-report={report_file}",
        "-q",
    ]
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    for key in (*THREAD_ENV, "PYTEST_ADDOPTS"):
        env.pop(key, None)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(report_file.read_text())
    assert report["workers"][0]["plan"]["detected_cpus"] == 1


@pytest.mark.skipif(os.getenv("THREADBUDGET_TEST_MKL") != "1", reason="Opt-in Linux MKL job")
def test_mkl_backend_is_really_controlled(tmp_path):
    assert importlib.util.find_spec("mkl") is not None, (
        "MKL test requested without mkl-service installed"
    )
    source = """import mkl
from threadpoolctl import threadpool_info
def test_mkl():
    assert mkl.get_max_threads() == 1
    pools = [pool for pool in threadpool_info() if pool["internal_api"] == "mkl"]
    assert pools, "MKL runtime was not detected"
    assert all(pool["num_threads"] == 1 for pool in pools)
"""
    result, report = run_pytest(tmp_path, source, "--threadbudget=1", conftest="import mkl\n")
    assert result.returncode == 0, result.diagnostic
    assert report["workers"][0]["outcomes"]["passed"] == 1
