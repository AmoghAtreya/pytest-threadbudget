from __future__ import annotations

import json
import os
import platform
import time
import warnings
from contextlib import contextmanager
from pathlib import Path

import pytest

from .budget import THREAD_ENV, make_plan

STATE = pytest.StashKey()


def pytest_addoption(parser):
    group = parser.getgroup("threadbudget", "Native BLAS/OpenMP thread budgets")
    group.addoption(
        "--threadbudget",
        default=None,
        metavar="off|auto|N",
        help="Opt-in native threads per worker; default off",
    )
    group.addoption(
        "--threadbudget-cpus",
        type=int,
        default=None,
        metavar="N",
        help="Cap available CPUs used for budget calculation",
    )
    group.addoption(
        "--threadbudget-override-env",
        action="store_true",
        help="Explicitly override existing native-thread environment settings",
    )
    group.addoption(
        "--threadbudget-report",
        default=None,
        metavar="PATH",
        help="Write aggregate JSON with worker plans and observed pools",
    )
    parser.addini("threadbudget", "off, auto, or positive native thread count", default="off")


class State:
    def __init__(self, config):
        self.config = config
        self.started = time.perf_counter()
        self.worker = hasattr(config, "workerinput")
        self.worker_id = (
            os.environ.get("PYTEST_XDIST_WORKER", "serial") if self.worker else "serial"
        )
        self.report_path = config.getoption("threadbudget_report")
        self.child_reports = []
        self.worker_errors = []
        self.notes = []
        self.observed = {}
        self.pool_observations = {}
        self.limiter = None
        self.saved_environment = {}
        self.closed = False
        self.outcomes = {
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "setup_errors": 0,
            "teardown_errors": 0,
        }
        requested_mode = config.getoption("threadbudget")
        self.mode = requested_mode if requested_mode is not None else config.getini("threadbudget")
        # Validate options even when this process is a controller.
        count = os.environ.get("PYTEST_XDIST_WORKER_COUNT", "1") if self.worker else "1"
        try:
            workers = int(count)
            if self.mode == "off" and self.report_path is None:
                detected = 1  # zero resource probing for a passive installation
            else:
                from joblib import cpu_count

                detected = cpu_count()
            self.plan = make_plan(
                self.mode,
                detected,
                workers,
                config.getoption("threadbudget_cpus"),
                os.environ,
                config.getoption("threadbudget_override_env"),
            )
        except (ValueError, TypeError) as error:
            raise pytest.UsageError(str(error)) from error
        distributed = bool(getattr(config.option, "numprocesses", None)) or bool(
            getattr(config.option, "tx", None)
        )
        self.controller_only = distributed and not self.worker
        if self.controller_only:
            self.worker_id = "controller"
        # Explicit --tx destinations may have independent CPU allocations. The
        # simple local worker-count model cannot safely budget those hosts.
        if (
            self.mode != "off"
            and getattr(config.option, "tx", None)
            and not getattr(config.option, "numprocesses", None)
        ):
            raise pytest.UsageError(
                "threadbudget supports local -n workers; explicit --tx hosts are unsupported"
            )

    @property
    def active(self):
        return self.plan.active and not self.controller_only

    def start(self):
        if not self.active:
            return
        if self.plan.allocation_exceeds_budget:
            warnings.warn(
                "threadbudget: requested worker/thread allocation exceeds the CPU budget; "
                "each worker needs at least one thread",
                pytest.PytestWarning,
                stacklevel=2,
            )
        self.saved_environment = {key: os.environ.get(key) for key in THREAD_ENV}
        for key in THREAD_ENV:
            os.environ[key] = str(self.plan.threads_per_worker)
        # Handles pools imported by conftest files before pytest_configure.
        try:
            self.limiter = self.limit_existing_pools()
        except Exception:
            self.close()
            raise

    def limit_existing_pools(self):
        from threadpoolctl import ThreadpoolController

        controller = ThreadpoolController()
        limits = {}
        for pool in controller.info():
            prefix = pool["prefix"]
            current = pool.get("num_threads")
            if isinstance(current, int) and current > 0:
                # A budget is a ceiling. Never raise a tighter limit established
                # by the project or another tool before this boundary.
                limits[prefix] = min(
                    current,
                    self.plan.threads_per_worker,
                    limits.get(prefix, self.plan.threads_per_worker),
                )
        return controller.limit(limits=limits)

    def observe(self, phase):
        if self.mode == "off" and not self.report_path:
            return
        from threadpoolctl import threadpool_info

        for pool in threadpool_info():
            key = (pool.get("filepath"), pool.get("user_api"), pool.get("internal_api"))
            self.observed[key] = {**pool, "observed_at": phase}
            number = pool.get("num_threads")
            observation = self.pool_observations.setdefault(
                key,
                {
                    "filepath": pool.get("filepath"),
                    "user_api": pool.get("user_api"),
                    "internal_api": pool.get("internal_api"),
                    "samples": 0,
                    "min_num_threads": None,
                    "max_num_threads": None,
                    "ceiling_violations": 0,
                    "unknown_thread_counts": 0,
                },
            )
            observation["samples"] += 1
            if isinstance(number, int) and number > 0:
                observation["min_num_threads"] = min(
                    number, observation["min_num_threads"] or number
                )
                observation["max_num_threads"] = max(
                    number, observation["max_num_threads"] or number
                )
                if self.active and number > self.plan.threads_per_worker:
                    observation["ceiling_violations"] += 1
            else:
                observation["unknown_thread_counts"] += 1

    @contextmanager
    def boundary(self):
        limiter = None
        try:
            if self.active:
                # Re-discover at each test boundary: session-only controllers do
                # not automatically discover subsequently imported libraries.
                limiter = self.limit_existing_pools()
            self.observe("before_test")
            yield
        finally:
            try:
                self.observe("after_test")
            finally:
                if limiter is not None:
                    limiter.restore_original_limits()

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self.limiter is not None:
                self.limiter.restore_original_limits()
        finally:
            for key, value in self.saved_environment.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def payload(self, exitstatus):
        return {
            "worker": self.worker_id,
            "pid": os.getpid(),
            "plan": self.plan.to_dict(),
            "active_in_this_process": self.active,
            "outcomes": self.outcomes,
            "pools": list(self.observed.values()),
            "notes": self.notes,
            "pool_observations": list(self.pool_observations.values()),
            "elapsed_seconds": time.perf_counter() - self.started,
            "exitstatus": int(exitstatus),
        }


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    state = State(config)
    config.stash[STATE] = state
    state.start()


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    state = item.config.stash.get(STATE, None)
    if state is None:
        return (yield)
    with state.boundary():
        return (yield)


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node, error):
    state = node.config.stash[STATE]
    payload = getattr(node, "workeroutput", {}).get("threadbudget")
    if payload is not None:
        state.child_reports.append(payload)
    else:
        state.worker_errors.append(f"{node.gateway.id}: worker produced no threadbudget report")
    if error:
        state.worker_errors.append(f"{node.gateway.id}: {error}")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    state = item.config.stash.get(STATE, None)
    if state is not None:
        if report.when == "call":
            state.outcomes[report.outcome] += 1
        elif report.skipped:
            state.outcomes["skipped"] += 1
        elif report.failed:
            state.outcomes[report.when + "_errors"] += 1
    return report


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    state = session.config.stash.get(STATE, None)
    if state is None:
        return
    try:
        state.observe("session_finish")
    finally:
        state.close()
    payload = state.payload(exitstatus)
    if state.worker:
        session.config.workeroutput["threadbudget"] = payload
    elif state.report_path:
        workers = (
            sorted(state.child_reports, key=lambda report: report["worker"])
            if state.controller_only
            else [payload]
        )
        data = {
            "schema_version": 2,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "requested_mode": state.mode,
            "exitstatus": int(exitstatus),
            "workers": workers,
            "worker_errors": state.worker_errors,
            "scope": "local process BLAS/OpenMP pools; pool observations are not OS thread peaks",
        }
        path = Path(state.report_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
            temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            temporary.replace(path)
        except OSError as error:
            raise pytest.UsageError(f"Cannot write threadbudget report {path}: {error}") from error


def pytest_unconfigure(config):
    state = config.stash.get(STATE, None)
    if state is not None:
        state.close()


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    state = config.stash.get(STATE, None)
    if state is None or (state.mode == "off" and not state.report_path):
        return
    reports = state.child_reports if state.controller_only else [state.payload(exitstatus)]
    terminalreporter.section("threadbudget")
    for report in sorted(reports, key=lambda entry: entry["worker"]):
        plan = report["plan"]
        summary = (
            f"{report['worker']}: {plan['reason']}; {len(report['pools'])} native pools observed"
        )
        if report["active_in_this_process"]:
            summary += f"; {plan['threads_per_worker']} threads/worker, {plan['effective_cpus']} CPUs/{plan['workers']} workers"
        terminalreporter.write_line(summary)
    if reports and not any(report["pools"] for report in reports):
        terminalreporter.write_line(
            "No supported native pools observed; environment hints alone do not verify runtime enforcement."
        )
    for error in state.worker_errors:
        terminalreporter.write_line(error, red=True)
