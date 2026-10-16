"""Compare Statsmodels release tests with their conftest loaded before parsing."""

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from pytest_threadbudget.budget import THREAD_ENV


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    args = parser.parse_args()
    if args.workers < 1 or args.repeats < 1 or args.warmups < 0:
        parser.error("workers/repeats must be positive; warmups must be nonnegative")
    try:
        version = importlib.metadata.version("statsmodels")
        importlib.metadata.version("pytest-randomly")
    except importlib.metadata.PackageNotFoundError:
        parser.error("Install statsmodels[test] in this environment first")
    spec = importlib.util.find_spec("statsmodels")
    test_file = Path(spec.origin).parent / "regression/tests/test_regression.py"
    if not test_file.exists():
        parser.error(f"Installed release does not contain {test_file}")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("Choose an empty output directory")
    output.mkdir(parents=True, exist_ok=True)
    source = {
        "distribution": "statsmodels",
        "version": version,
        "repository": "https://github.com/statsmodels/statsmodels",
        "test_file": str(test_file),
        "test_file_sha256": hashlib.sha256(test_file.read_bytes()).hexdigest(),
        "scope": "Installed regression tests; absolute path loads original conftest early",
        "original_native_thread_environment": {
            key: os.environ[key] for key in THREAD_ENV if key in os.environ
        },
    }
    environment = dict(os.environ)
    for key in (*THREAD_ENV, "PYTEST_ADDOPTS"):
        environment.pop(key, None)
    codes = []
    for label, manual in (("default-comparison", False), ("manual-cap-comparison", True)):
        command = [
            sys.executable,
            "-m",
            "pytest_threadbudget.benchmark",
            "--output",
            str(output / label),
            "--workers",
            str(args.workers),
            "--repeats",
            str(args.repeats),
            "--warmups",
            str(args.warmups),
            "--timeout",
            "600",
        ]
        env = dict(environment)
        if manual:
            env["OPENBLAS_NUM_THREADS"] = "1"
            command.append("--override-env")
        command += [
            "--",
            str(test_file),
            "--randomly-seed=42",
            "--randomly-dont-reset-seed",
            "-m",
            "not slow and not high_memory",
            "-q",
        ]
        print(label, flush=True)
        result = subprocess.run(command, env=env)
        codes.append(result.returncode)
        source[label] = {"command": command, "exitcode": result.returncode}
        (output / "source.json").write_text(json.dumps(source, indent=2) + "\n")
        if result.returncode == 1:
            return 1
    return 0 if all(code == 0 for code in codes) else 2


if __name__ == "__main__":
    raise SystemExit(main())
