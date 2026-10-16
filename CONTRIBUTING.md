# Contributing

Use Python 3.11 or later. Create a virtual environment, then run:

```sh
python -m pip install -e '.[test,release]'
python -m pytest tests -q
ruff check src tests scripts examples
ruff format --check src tests scripts examples
python -m build
python -m twine check --strict dist/*
```

For a behavioral fix, include a regression test reproducing the failure. For
native runtime changes, report Python, OS, pytest, xdist, threadpoolctl, joblib,
and numerical library versions. Do not assume an empty pool list proves a cap.
The opt-in Linux MKL job requires `mkl-service` and `THREADBUDGET_TEST_MKL=1`.

Benchmark reports should include the unmodified baseline, any existing manual
thread caps, raw trial outcomes, repeat count, and slowdowns as well as speedups.
Keep dependency installation separate from measurements. See VALIDATE.md.

CI installs the built wheel on Linux, macOS, and Windows across Python 3.11–3.14,
and checks the minimum dependency profile and the Intel MKL backend on Linux.
