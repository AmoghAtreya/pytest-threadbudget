"""Run selected upstream release tests; this does not scan GitHub source trees."""

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SUITES = {
    "numpy-svd": (
        "numpy",
        "numpy.linalg.tests.test_linalg",
        "TestSVD",
        "https://github.com/numpy/numpy",
    ),
    "scipy-svd": (
        "scipy",
        "scipy.linalg.tests.test_decomp",
        "TestSVD_GESDD",
        "https://github.com/scipy/scipy",
    ),
    "sklearn-kmeans": (
        "scikit-learn",
        "sklearn.cluster.tests.test_k_means",
        "k_means_1_iteration or k_means_function",
        "https://github.com/scikit-learn/scikit-learn",
    ),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--cpus", type=int)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--suites", choices=SUITES, nargs="+", default=list(SUITES))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = []
    returncodes = []
    for name in args.suites:
        distribution, module, selection, repository = SUITES[name]
        version = importlib.metadata.version(distribution)
        origin = Path(importlib.util.find_spec(module).origin)
        source = {
            "suite": name,
            "distribution": distribution,
            "version": version,
            "repository": repository,
            "module": module,
            "selection": selection,
            "test_file": str(origin),
            "test_file_sha256": hashlib.sha256(origin.read_bytes()).hexdigest(),
            "scope": "Selected tests distributed with an installed upstream release; original assertions and conftest hooks retained.",
        }
        print(f"\n{name}: {distribution} {version}; released upstream test subset", flush=True)
        command = [
            sys.executable,
            "-m",
            "pytest_threadbudget.benchmark",
            "--output",
            str(args.output / name),
            "--workers",
            str(args.workers),
            "--repeats",
            str(args.repeats),
            "--warmups",
            str(args.warmups),
        ]
        if args.cpus:
            command += ["--cpus", str(args.cpus)]
        command += ["--", "--pyargs", module, "-k", selection, "-q"]
        completed = subprocess.run(command)
        source["benchmark_exitcode"] = completed.returncode
        returncodes.append(completed.returncode)
        manifest.append(source)
        (args.output / "sources.json").write_text(json.dumps(manifest, indent=2) + "\n")
    # 2 means correctness may pass but runtime enforcement could not be verified.
    return 1 if any(code not in (0, 2) for code in returncodes) else (2 if 2 in returncodes else 0)


if __name__ == "__main__":
    raise SystemExit(main())
