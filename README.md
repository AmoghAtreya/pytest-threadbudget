# pytest-threadbudget

[![tests](https://github.com/AmoghAtreya/pytest-threadbudget/actions/workflows/tests.yml/badge.svg)](https://github.com/AmoghAtreya/pytest-threadbudget/actions/workflows/tests.yml)

Opt-in BLAS/OpenMP thread ceilings for local pytest-xdist workers. Installing the
plugin alone leaves tests unchanged. Python 3.11+, pytest 8–9, pytest-xdist 3.6+.

## Quick start

From this source directory:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test,realrepos]"
python -m pytest tests -q
python -m pytest examples/test_matrix.py -n 2 --threadbudget=auto --threadbudget-report=work/example.json -q
```

The public source is available on [GitHub](https://github.com/AmoghAtreya/pytest-threadbudget).
Until the first PyPI release is verified, install the local checkout or built wheel. Follow [VALIDATE.md](VALIDATE.md) for complete
commands, real upstream test subsets and an optional macOS OpenBLAS profile.
See [RESULTS.md](RESULTS.md) for measured results and their limits.

## What it does

`--threadbudget=auto` computes `max(1, available_cpus // worker_count)` as a
per-native-pool thread ceiling. `joblib.cpu_count()` accounts for supported CPU
affinity and container quota constraints. Optional `--threadbudget-cpus=N` lowers
that allocation budget; it does not set OS affinity or impose a CPU quota.

The plugin sets common native thread environment hints in each worker at
`pytest_configure`, applies runtime caps to supported already-loaded pools, and
rediscovers pools at each test boundary. Runtime caps never raise an existing
tighter limit. JSON reports aggregate plans, observed pool settings, outcomes,
and missing/crashed-worker diagnostics in the controller process. Schema version 2
retains minimum/maximum thread counts and violation counts across all recorded
boundaries; the final snapshot cannot erase an earlier violation.

The implementation builds on [threadpoolctl](https://github.com/joblib/threadpoolctl)
and [joblib](https://joblib.readthedocs.io/en/stable/generated/joblib.cpu_count.html).
The integration is motivated by
[pytest-xdist issue #1012](https://github.com/pytest-dev/pytest-xdist/issues/1012).
It is an independent alpha project with no upstream endorsement or adoption claim.

## Enable it in a project

Install this plugin in the project's test environment, then add:

```toml
[tool.pytest.ini_options]
threadbudget = "auto"
```

Keep the project's normal `-n` configuration. For one run, CLI options override
the INI setting:

```bash
python -m pytest -n 4 --threadbudget=auto
python -m pytest -n 4 --threadbudget=1
python -m pytest -n 4 --threadbudget=off
```

Off is the default. An explicit positive number is a per-worker per-pool ceiling.
If the worker/thread allocation exceeds the CPU budget, the plugin warns; it does
not change xdist's worker count. Serial pytest execution is also supported.

## Explicit settings and cleanup

If **any** of `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`,
`BLIS_NUM_THREADS`, or `VECLIB_MAXIMUM_THREADS` is already defined, the plugin
preserves all existing settings and skips applying its budget. The report states
why. Use `--threadbudget-override-env` to explicitly select a plugin ceiling.
This conservative policy includes empty environment values.

Changed environment values and runtime settings of pools present when budgeting
starts are restored at pytest shutdown, including normal test failure paths.
Per-test runtime contexts are restored after fixture/test teardown. Libraries
first initialized under the plugin's environment retain their initialization
defaults after shutdown; their hypothetical pre-import defaults cannot be
reconstructed. Forced process termination cannot run Python cleanup.

## Boundaries

- Applies to local `-n` workers; explicit `--tx` destinations are rejected when
  budgeting is enabled. CPU allocation across different remote hosts is out of
  scope.
- Apple Accelerate is not controlled by threadpoolctl. Environment hints and an
  empty pool list are not proof of enforcement. Reports say so explicitly.
- Manages supported BLAS/OpenMP APIs, not Numba, PyTorch interop pools, NumExpr,
  GPU kernels, Python executors, subprocess trees, or machine-wide concurrency.
- The number is a ceiling for each supported native pool, not a hard OS limit on
  total live threads or nested parallelism across multiple runtimes. Some native
  APIs apply to the calling thread rather than every Python thread.
- `pytest_configure` runs after initial conftest imports. Their already-loaded
  pools can be limited, but earlier import-time computation is not controlled.
- Libraries loaded inside a test receive environment hints; runtime discovery
  catches them at subsequent boundaries. Tests can deliberately change settings
  inside their own bodies. The plugin is not a sandbox or permanent watchdog.
- Rediscovery and optional reporting add overhead. Existing project limits can
  already solve oversubscription; speedups are workload-dependent.

## Benchmark fairly

```bash
python -m pytest_threadbudget.benchmark --output work/bench-01 --workers 2 --repeats 3 --warmups 1 -- examples/test_matrix.py -q
python scripts/validate_real_repos.py --output work/upstream-01 --workers 2 --repeats 3 --warmups 1
```

The first command is synthetic. The second uses selected original tests from
installed NumPy/SciPy/scikit-learn releases. It does not run complete repositories
or imply adoption. Benchmarks alternate execution order, preserve raw logs,
compare individual JUnit outcomes and keep slowdowns visible. Headline timing
comparisons are suppressed if test outcomes differ or runtime enforcement cannot
be verified. Full details and return codes are in [VALIDATE.md](VALIDATE.md).

## Layout and development

- `src/pytest_threadbudget/budget.py`: pure planning and environment policy.
- `src/pytest_threadbudget/plugin.py`: pytest hooks, lifecycle and reports.
- `src/pytest_threadbudget/benchmark.py`: isolated comparisons and sampling.
- `tests/`: planning, real subprocess/xdist/native-runtime and failure tests.
- `scripts/validate_real_repos.py`: pinned-by-report upstream release selections.
- `scripts/validate_statsmodels.py`: regression tests with early conftest loading.
- `evidence/`: validation metadata, raw reports and logs from this machine.
- `.github/workflows/tests.yml`: built-wheel Linux/macOS/Windows test matrix.

See [CONTRIBUTING.md](CONTRIBUTING.md) for development checks,
[CHANGELOG.md](CHANGELOG.md) for release notes, and [RELEASE.md](RELEASE.md) for
the trusted-publishing procedure. Upstream PRs and adoption are tracked separately
from package publication.
