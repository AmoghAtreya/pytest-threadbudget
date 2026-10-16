"""Run alternating baseline/budget trials in independent pytest processes."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import signal
import statistics
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path


def read_outcomes(path):
    """Compare individual test identities and statuses, not just pass counts."""
    try:
        tree = ET.parse(path)
    except (OSError, ET.ParseError):
        return None
    result = []
    for case in tree.iter("testcase"):
        status = "passed"
        for candidate in ("error", "failure", "skipped"):
            if case.find(candidate) is not None:
                status = candidate
                break
        result.append((case.get("classname", ""), case.get("name", ""), status))
    return sorted(result)


def runtime_enforcement_verified(diagnostic):
    """Validate every recorded boundary observation, not just the final snapshot."""
    workers = diagnostic.get("workers", [])
    if not workers or diagnostic.get("worker_errors"):
        return False
    for worker in workers:
        if not worker.get("active_in_this_process") or worker.get("exitstatus") != 0:
            return False
        observations = worker.get("pool_observations", [])
        limit = worker.get("plan", {}).get("threads_per_worker")
        if not observations or not isinstance(limit, int) or limit < 1:
            return False
        for observed in observations:
            maximum = observed.get("max_num_threads")
            if (
                not isinstance(maximum, int)
                or maximum < 1
                or maximum > limit
                or observed.get("ceiling_violations", 0)
                or observed.get("unknown_thread_counts", 0)
            ):
                return False
    return True


def terminate_trial(process, parent):
    """Best-effort tree termination; denied child inspection must not block killing the parent."""
    import psutil

    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        try:
            children = parent.children(recursive=True) if parent is not None else []
        except (psutil.Error, OSError):
            children = []
        for child in children:
            try:
                child.kill()
            except (psutil.Error, OSError):
                pass
        try:
            process.kill()
        except ProcessLookupError:
            pass


def run_trial(command, directory, timeout, interval):
    import psutil

    directory.mkdir(parents=True, exist_ok=True)
    cpu_samples = {}
    peak_threads = 0
    resource_sampling_available = True
    sampling_errors = set()
    timed_out = False
    started = time.perf_counter()
    with (directory / "pytest.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name == "posix"
        )
        parent = psutil.Process(process.pid)
        while process.poll() is None:
            if time.perf_counter() - started > timeout:
                timed_out = True
                terminate_trial(process, parent)
                break
            try:
                processes = [parent, *parent.children(recursive=True)]
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as error:
                processes = []
                sampling_errors.add(type(error).__name__)
                if not isinstance(error, psutil.NoSuchProcess):
                    resource_sampling_available = False
            thread_count = 0
            for child in processes:
                try:
                    identity = (child.pid, child.create_time())
                    cpu = child.cpu_times()
                    cpu_samples[identity] = max(cpu_samples.get(identity, 0), cpu.user + cpu.system)
                    thread_count += child.num_threads()
                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                    NotImplementedError,
                    OSError,
                ) as error:
                    sampling_errors.add(type(error).__name__)
                    if not isinstance(error, psutil.NoSuchProcess):
                        resource_sampling_available = False
            peak_threads = max(peak_threads, thread_count)
            time.sleep(interval)
        process.wait()
    return {
        "command": command,
        "exitcode": process.returncode,
        "timed_out": timed_out,
        "wall_seconds": time.perf_counter() - started,
        "sampled_peak_process_tree_threads": peak_threads if resource_sampling_available else None,
        "sampled_cpu_seconds": sum(cpu_samples.values()) if resource_sampling_available else None,
        "sampling_interval_seconds": interval,
        "sampling_notes": sorted(sampling_errors),
    }


def summarize(trials):
    result = {}
    for mode in ("off", "auto"):
        group = [trial for trial in trials if trial["mode"] == mode and not trial["warmup"]]
        result[mode] = {"runs": len(group)}
        for metric in ("wall_seconds", "sampled_peak_process_tree_threads", "sampled_cpu_seconds"):
            values = [trial[metric] for trial in group if trial[metric] is not None]
            result[mode][metric] = {
                "median": statistics.median(values) if values else None,
                "min": min(values) if values else None,
                "max": max(values) if values else None,
                "available_samples": len(values),
            }
    reference = trials[0].get("outcomes") if trials else None
    valid = (
        all(result[mode]["runs"] > 0 for mode in ("off", "auto"))
        and bool(reference)
        and any(case[2] == "passed" for case in reference)
        and all(
            trial["exitcode"] == 0
            and not trial["timed_out"]
            and trial.get("environment_unchanged", True)
            and trial.get("outcomes") == reference
            for trial in trials
        )
    )
    enabled = [trial for trial in trials if trial["mode"] == "auto"]
    enforcement_verified = bool(enabled) and all(
        trial.get("runtime_enforcement_verified", False) for trial in enabled
    )
    result["all_runs_passed_with_identical_outcomes"] = valid
    reasons = []
    for index, trial in enumerate(trials, 1):
        label = f"trial {index} ({trial['mode']}, {'warmup' if trial['warmup'] else 'measured'})"
        if trial["exitcode"] != 0:
            reasons.append(
                f"{label}: pytest exited with code {trial['exitcode']}; inspect pytest.log"
            )
        if trial["timed_out"]:
            reasons.append(f"{label}: timed out")
        if not trial.get("environment_unchanged", True):
            reasons.append(f"{label}: dependency versions changed")
        outcomes = trial.get("outcomes")
        if not outcomes:
            reasons.append(f"{label}: no JUnit test outcomes available")
        elif not any(case[2] == "passed" for case in outcomes):
            reasons.append(
                f"{label}: no passing tests; errors={sum(case[2] == 'error' for case in outcomes)}, "
                f"failures={sum(case[2] == 'failure' for case in outcomes)}, "
                f"skipped={sum(case[2] == 'skipped' for case in outcomes)}"
            )
        if outcomes != reference:
            reasons.append(f"{label}: per-test outcomes differ from the first trial")
    if any(result[mode]["runs"] == 0 for mode in ("off", "auto")):
        reasons.append("No complete measured baseline/plugin comparison is available")
    result["invalid_reasons"] = reasons
    result["runtime_enforcement_verified"] = enforcement_verified
    baseline = result["off"]["wall_seconds"]["median"]
    budgeted = result["auto"]["wall_seconds"]["median"]
    # Positive means faster, negative means slower. Suppress the headline if
    # outcomes differ, a command failed, or no supported pool was controlled.
    result["median_wall_reduction_percent"] = (
        100 * (baseline - budgeted) / baseline if valid and enforcement_verified else None
    )
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--cpus", type=int)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--sample-interval", type=float, default=0.05)
    parser.add_argument(
        "--override-env",
        action="store_true",
        help="Allow plugin mode to override existing native-thread settings; recorded in report",
    )
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        import psutil  # noqa: F401 - validate optional dependencies before spawning

        importlib.metadata.version("pytest-xdist")
    except (ImportError, importlib.metadata.PackageNotFoundError):
        parser.error("Install pytest-threadbudget[benchmark] to run benchmarks")
    if (
        args.workers < 1
        or args.repeats < 1
        or args.warmups < 0
        or args.timeout <= 0
        or args.sample_interval <= 0
        or (args.cpus is not None and args.cpus < 1)
    ):
        parser.error("counts and durations must be positive (warmups may be zero)")
    pytest_args = args.pytest_args[1:] if args.pytest_args[:1] == ["--"] else args.pytest_args
    if not pytest_args:
        parser.error("Supply explicit pytest test paths after --")
    forbidden = ("--threadbudget", "--junit", "--numprocesses", "--tx", "--dist", "--looponfail")
    if any(
        value.startswith(forbidden)
        or value == "-n"
        or (value.startswith("-n") and value[2:].isdigit())
        for value in pytest_args
    ):
        parser.error("Benchmark runner owns worker, threadbudget, distribution and JUnit options")
    # Ambient options could silently turn on budgeting in the baseline or change
    # the workload. Record and reject them instead of publishing a false comparison.
    if os.environ.get("PYTEST_ADDOPTS"):
        parser.error(
            "Unset PYTEST_ADDOPTS for a reproducible comparison; pass options explicitly after --"
        )
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "summary.json").exists():
        parser.error("Output already contains a benchmark; choose a fresh directory")
    versions = {}
    for package in (
        "pytest-threadbudget",
        "pytest",
        "pytest-xdist",
        "threadpoolctl",
        "joblib",
        "numpy",
        "scipy",
        "scikit-learn",
        "statsmodels",
        "pandas",
        "patsy",
        "formulaic",
        "psutil",
    ):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    from .budget import THREAD_ENV

    metadata = {
        "schema_version": 1,
        "cwd": str(Path.cwd()),
        "python": sys.version,
        "platform": platform.platform(),
        "versions": versions,
        "native_thread_environment": {
            key: os.environ[key] for key in THREAD_ENV if key in os.environ
        },
        "workers": args.workers,
        "cpu_cap": args.cpus,
        "override_env": args.override_env,
        "pytest_args": pytest_args,
        "measurement_notes": [
            "Wall time includes pytest startup, collection and worker startup.",
            "Thread peak and CPU time are sampled estimates, not exact accounting.",
            "No cold-cache claim or statistical significance claim is made.",
        ],
    }
    trials = []
    for round_number in range(args.warmups + args.repeats):
        modes = ("off", "auto") if round_number % 2 == 0 else ("auto", "off")
        for mode in modes:
            directory = args.output / f"round-{round_number + 1}-{mode}"
            command = [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "threadbudget",
                "-o",
                "addopts=",
                "-n",
                str(args.workers),
                f"--threadbudget={mode}",
                f"--threadbudget-report={directory / 'threadbudget.json'}",
                f"--junitxml={directory / 'junit.xml'}",
            ]
            if args.cpus is not None:
                command.append(f"--threadbudget-cpus={args.cpus}")
            if args.override_env:
                command.append("--threadbudget-override-env")
            command.extend(pytest_args)
            unchanged_before = all(
                importlib.metadata.version(package) == version
                for package, version in versions.items()
            )
            trial = run_trial(command, directory, args.timeout, args.sample_interval)
            trial.update(
                mode=mode,
                warmup=round_number < args.warmups,
                environment_unchanged=unchanged_before
                and all(
                    importlib.metadata.version(package) == version
                    for package, version in versions.items()
                ),
                outcomes=read_outcomes(directory / "junit.xml"),
            )
            try:
                diagnostic = json.loads((directory / "threadbudget.json").read_text())
                trial["runtime_enforcement_verified"] = runtime_enforcement_verified(diagnostic)
            except (OSError, ValueError, KeyError):
                trial["runtime_enforcement_verified"] = False
            trials.append(trial)
            print(
                f"{'warmup' if trial['warmup'] else 'measured'} {mode}: {trial['wall_seconds']:.3f}s, "
                f"exit {trial['exitcode']}, sampled peak {trial['sampled_peak_process_tree_threads']} threads",
                flush=True,
            )
            (args.output / "runs.json").write_text(
                json.dumps({"metadata": metadata, "trials": trials}, indent=2) + "\n"
            )
            if trial["exitcode"] != 0 or trial["timed_out"]:
                summary = summarize(trials)
                (args.output / "summary.json").write_text(
                    json.dumps({"metadata": metadata, "summary": summary}, indent=2) + "\n"
                )
                print(
                    f"Stopping after a failed trial. Inspect {directory / 'pytest.log'}",
                    file=sys.stderr,
                )
                print(json.dumps(summary, indent=2))
                return 1
    summary = summarize(trials)
    (args.output / "summary.json").write_text(
        json.dumps({"metadata": metadata, "summary": summary}, indent=2) + "\n"
    )
    print(json.dumps(summary, indent=2))
    if not summary["all_runs_passed_with_identical_outcomes"]:
        return 1
    return 0 if summary["runtime_enforcement_verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
