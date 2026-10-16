# Run it yourself

Use a terminal in this project directory. The project has not been published to
PyPI. Install the local source, including its optional test and upstream-test
dependencies:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test,realrepos]"
python -m pytest tests -q
```

On Windows, activate with `.venv\Scripts\activate` instead. Python 3.11 or newer
is required. The supplied GitHub Actions workflow covers a proposed OS/Python
matrix; only the local combinations documented in RESULTS.md were actually run.

## See a worker report

```bash
mkdir -p work
python -m pytest examples/test_matrix.py -n 2 --threadbudget=1 --threadbudget-report=work/example.json -q
python -m json.tool work/example.json
```

Check that there are two worker entries, `threads_per_worker` is 1, and
`active_in_this_process` is true. If `pools` is nonempty, inspect `num_threads`.
An empty list means runtime control was not verified. New NumPy/SciPy wheels
on Apple Silicon can use Accelerate, which this plugin does not control.

For an assertion against a supported backend on macOS/Linux:

```bash
THREADBUDGET_EXPECT_THREADS=1 python -m pytest examples/test_matrix.py -n 2 --threadbudget=1 -q
```

The assertion explicitly skips if the backend is unsupported. It must not be
reported as successful runtime enforcement in that case.

Existing OMP/BLAS environment settings disable budgeting by default. Inspect the
report's reason. Use `--threadbudget-override-env` only when you intend to override
those settings. The benchmark runner records this choice as `--override-env`.

## Compare real upstream test subsets

```bash
python scripts/validate_real_repos.py --output work/upstream-01 --workers 2 --repeats 3 --warmups 1
```

This runs selected tests distributed with installed releases from:

- NumPy: SVD tests in `numpy.linalg.tests.test_linalg`.
- SciPy: GESDD SVD tests in `scipy.linalg.tests.test_decomp`.
- scikit-learn: selected K-means tests in `sklearn.cluster.tests.test_k_means`.

Each test file's SHA-256, distribution version and repository URL are recorded in
`sources.json`. Original upstream assertions and conftest hooks remain in place.
These are released test subsets, not complete GitHub repository/HEAD test runs.
Their built-in limiting hooks can already prevent oversubscription, so little or
no improvement is a valid result. This script does not patch upstream projects.

Each suite writes:

- `summary.json`: measured medians, ranges and outcome/enforcement checks.
- `runs.json`: commands, warmup flags, timings and per-test outcomes.
- `round-*/pytest.log`, `junit.xml`, `threadbudget.json`: raw evidence.

Exit 0 means all comparisons passed and each worker exposed supported pools
within the requested ceiling. Exit 1 means some run failed, timed out, or changed
test outcomes. Exit 2 means runtime enforcement could not be verified, including
an empty pool list. Inspect each suite even if the aggregate command exits 2.

## A reproducible OpenBLAS profile on this Mac

Keep this in a separate environment. The pinned older releases deliberately use
OpenBLAS wheels on macOS arm64/Python 3.11. They are a compatibility profile, not
evidence about current NumPy/SciPy Accelerate performance.

```bash
python3.11 -m venv .venv-openblas
source .venv-openblas/bin/activate
python -m pip install -e ".[test]" -r requirements-macos-openblas.txt
python -m pytest tests -q
python scripts/validate_real_repos.py --output work/openblas-01 --workers 2 --repeats 3 --warmups 1
```

## Benchmark your own checkout

In a separate environment with the repository's development dependencies and
this plugin installed, run from that repository root. Read its contributor
instructions and choose a meaningful, repeatable, CPU-heavy test selection.

```bash
python -m pytest_threadbudget.benchmark --output work/budget-01 --workers 4 --repeats 5 --warmups 1 -- tests/path_to_selected_tests.py -q
```

Replace the example path with actual tests. Pass the repository's needed options
after `--`. The runner clears configured `addopts` for both modes; `PYTEST_ADDOPTS`
must be unset. It owns worker count, JUnit output and threadbudget options.
Choose a fresh output directory each time. It does not install the target repo,
fetch datasets, set CPU affinity, flush caches, or fix unrelated test failures.

## Statsmodels 0.15.0

In an environment containing `statsmodels[test]`, use the dedicated runner:

```bash
python scripts/validate_statsmodels.py --output work/statsmodels-01 --workers 4 --repeats 3 --warmups 1
```

This compares both unrestricted settings and the project's manual
`OPENBLAS_NUM_THREADS=1` workaround against plugin mode. It clears native-thread
settings and `PYTEST_ADDOPTS` only in its child processes, records the original
native settings, and uses a fixed random seed. It does not install dependencies.

For Statsmodels, pass the installed test file's **absolute path**, rather than
`--pyargs statsmodels.regression.tests.test_regression`. The latter loads its
conftest too late to register options such as `only_slow` during parsing, causing
setup errors. The dedicated script resolves the absolute path automatically.

The benchmark runner now stops at the first failed trial and writes
`invalid_reasons` in the summary. Failed pytest commands are not usable performance
comparisons, even if native pool settings meet their ceilings.

## Synthetic benchmark

```bash
python -m pytest_threadbudget.benchmark --output work/synthetic-01 --workers 4 --repeats 5 --warmups 1 -- examples/test_matrix.py -q
```

This is our NumPy workload, not an upstream benchmark. It can help exercise a
supported BLAS backend but cannot establish project CI impact. Increase workload
size explicitly with `THREADBUDGET_MATRIX_SIZE` if needed.

Wall time includes process startup and collection. Trials alternate mode order,
and warmups are excluded from medians. Process-tree thread counts and CPU times
are sampled estimates. If OS permissions prevent sampling, the metrics are null.
Do not turn null into zero or interpret configured native pool sizes as live OS
thread peaks. Short trials are noisy; no statistical significance is claimed.

## Inspect and build the release

```bash
python -m build
python -m pip install --force-reinstall --no-deps dist/pytest_threadbudget-0.1.0-py3-none-any.whl
python -m pytest --trace-config --collect-only examples/test_matrix.py -q
```

The final command should list `pytest_threadbudget.plugin`. The plugin remains
off unless explicitly enabled. Publishing or submitting upstream PRs is a
separate step after reviewing the evidence.
