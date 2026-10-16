# Validation results

Local validation on 2026-10-15: macOS 26.6.2, Apple Silicon arm64, Python 3.11.17,
18 detected logical CPUs. Historical and release validation profiles are separated
below. No established repository adoption or upstream merge is claimed.

## Plugin tests

- pytest 9.1.1, NumPy 2.4.6 / Apple Accelerate: **46 passed, 2 skipped**.
  The two native NumPy enforcement tests explicitly skip because threadpoolctl
  exposes no supported pool for this backend.
- pytest 8.4.2, NumPy 1.26.4 / OpenBLAS: **48 passed**.

Tests include real independent pytest processes and local xdist workers,
environment preservation/override, early and late native imports, in-process
restoration, intentional test failure, worker crash, report-write errors, remote
host rejection, benchmark timeouts, unavailable OS sampling and outcome comparison.
These initial results predated the public CI matrix. The 0.1.1 release checks
below describe the later built-wheel compatibility validation.

## Upstream release subsets

The original assertions and conftest hooks from installed upstream releases were
used. Tests were selected before benchmarking, using the selectors shipped in
`scripts/validate_real_repos.py`. Each mode had one warmup and three measured
runs, in alternating order, using two local workers. Every baseline/plugin run
had identical per-test identities and outcomes within its suite/profile.

Current-release profile (`evidence/current-releases`):

- NumPy **2.4.6**: **19 passed** per run. Median wall time 0.925s baseline and
  0.878s budgeted. Runtime enforcement unverified: Accelerate exposes no supported
  native pools here. No plugin-attributed speedup is reported.
- SciPy **1.17.1**: **62 passed, 1 skipped** per run. Medians 1.086s and 1.091s.
  Same unsupported Accelerate limitation; no plugin-attributed speedup reported.
- scikit-learn **1.9.1**: **7 passed** per run. Medians 1.488s and 1.525s,
  **2.5% slower** with the plugin. OpenMP exposes a supported pool. Both modes
  observed 9 threads because the project already limits threads itself.

That is **88 passing tests and 1 skip across three selected current-release
subsets**, repeated in both modes. It is not full-repository coverage or adoption.

Older OpenBLAS compatibility profile (`evidence/openblas-profile`):

- NumPy **1.26.4**: **17 passed** per run. Medians 1.156s and 1.301s,
  **12.5% slower**. Observed OpenBLAS pool settings changed from 18 to 9.
- SciPy **1.12.0**: **11 passed, 1 skipped** per run. Medians 1.269s and 1.311s,
  **3.3% slower**. Both OpenBLAS libraries were discovered. The project's own
  hooks produced a 4-thread baseline; setting the plugin's environment caused
  those conditional hooks to defer to its 9-thread ceiling. This illustrates a
  real integration tradeoff: project-specific initialization policies can differ
  from a general allocation rule, even when runtime caps preserve tighter limits
  that already exist at the time they are applied.
- scikit-learn **1.4.2**: **7 passed** per run. Medians 1.784s and 1.570s,
  **12.0% faster** in this small sample. Both modes observed 9-thread pools.
  This timing difference does not establish that thread reduction caused it.

These trials are short and include Python startup, worker startup, imports and
collection. Their variability and existing upstream thread controls make them
poor evidence for broad performance claims. Positive differences are preserved
alongside regressions; no statistical significance is claimed. Test-file SHA-256
hashes, package versions, selections and repository URLs are in each profile's
`sources.json`. Raw timings, JUnit outcomes and pool reports are retained.

## Synthetic workload

`evidence/synthetic-openblas` uses our eight NumPy matrix products plus one
conditional enforcement check, four workers, pytest 8.4.2 and NumPy 1.26.4.
There was one warmup and three measured trials per mode:

- All **9 tests passed** with matching outcomes in every run.
- Each worker's supported OpenBLAS setting changed from **18 to 4 threads**.
- Median total wall time changed from **1.875s to 1.689s**, approximately **9.9%
  faster**. The budgeted range was 1.318–1.763s, so the sample is visibly noisy.

This validates the mechanism and benchmark pipeline. It is synthetic evidence,
not an established repository's CI improvement. An earlier synthetic attempt was
discarded after a dependency version changed during its execution. It is excluded
from these results. The runner now checks recorded dependency versions before
and after each trial and invalidates comparisons if they change.

## Statsmodels configuration fix

A later Statsmodels 0.15.0 run exposed a problem with the supplied invocation:
`--pyargs statsmodels.regression.tests.test_regression` loaded its conftest too
late to register `only_slow`. Every trial had 375 setup errors and 2 skips.
Those timings are invalid. The original summary and a compact diagnosis are
preserved in `evidence/statsmodels-configuration-fix/original-failure.json`.

The corrected invocation passes the absolute installed test-file path, so pytest
loads the original conftest before parsing. `scripts/validate_statsmodels.py`
resolves that path and runs both comparisons. The benchmark now stops on the
first failed command, records `invalid_reasons`, and includes Statsmodels and its
main data/formula dependencies in version metadata.

Corrected local trials used four workers, one warmup and three measured runs per
mode, with pytest 8.4.2, Statsmodels 0.15.0, NumPy 1.26.4 and SciPy 1.12.0.
**Every run had 375 passing tests and 2 skips with identical outcomes.**

- Unrestricted baseline: median **8.182s**, range 8.150–8.415s. Plugin: median
  **3.377s**, range 3.203–3.506s. Approximately **58.7% less wall time**.
- Manual `OPENBLAS_NUM_THREADS=1` baseline: median **1.919s**, range 1.872–1.962s.
  Plugin with explicit environment override: median **1.998s**, range
  1.946–2.054s. Approximately **4.1% more wall time**.

The benefit is against unrestricted threading in this selected local workload.
It does not demonstrate superiority to the project's existing manual workaround,
full CI savings, statistical significance, or adoption. The two comparisons have
different initialization environments; compare modes within each comparison.
OS resource sampling was unavailable during the corrected runs and is null.
Raw logs, pool settings, timings and test-file provenance are retained in
`evidence/statsmodels-configuration-fix`.

After this fix the local OpenBLAS environment passed all **51 plugin tests**;
the original 48-test results above describe the initial version.

## Resource measurements

Process-tree OS sampling is blocked by this execution environment's permissions.
Peak-thread and sampled CPU-time fields are therefore **null**, with permission
diagnostics recorded. No OS-thread reduction, CPU-seconds saving, or memory-saving
claim is supported. `num_threads` in a native pool report is a configured runtime
setting, not a measurement of peak live threads or CPU utilization.

## Interpreting benchmark results

For an adoption decision, use longer CPU-heavy tests and compare against the
repository's existing thread policy. Preserve failures,
neutral results and regressions. Only claim upstream CI savings after measuring
an actual CI job. Discuss any proposed integration with maintainers before
claiming adoption or submitting a replacement for their current limiting code.

Relevant primary references:

- https://github.com/pytest-dev/pytest-xdist/issues/1012
- https://pytest-xdist.readthedocs.io/en/stable/how-to.html
- https://github.com/joblib/threadpoolctl
- https://joblib.readthedocs.io/en/stable/generated/joblib.cpu_count.html
- https://docs.pytest.org/en/stable/how-to/writing_plugins.html

## 0.1.1 release validation

Reports produced by 0.1.1 retain all boundary observations rather than only the
final pool snapshot. Historical 0.1.0 reports above retain their original schema
and are not evidence of passing the stricter 0.1.1 verification.

A fresh Statsmodels 0.15.0 regression comparison used four workers, one warmup
and **five measured runs per mode**. All 24 trials across the two comparisons
had **375 passes and 2 skips**, with identical per-test outcomes. Every enabled
trial passed the stricter runtime checks. Raw reports are under
`evidence/release-011-statsmodels`.

- Unrestricted threading: baseline median **8.012s** (7.598–8.566s), plugin
  **3.440s** (3.167–3.671s), approximately **57.1% less wall time**.
- Manual `OPENBLAS_NUM_THREADS=1`: baseline median **2.308s** (2.228–2.418s),
  plugin with explicit override **2.307s** (2.278–2.484s). The approximately
  **0.03%** difference is effectively neutral at this measurement resolution.

These remain short local installed-release subsets, not full CI benchmarks.
They do not support a speed advantage over manual capping. OS resource sampling
remained unavailable. Source hashes in `evidence/source-hashes.json` describe
the 0.1.1 validation code; earlier snapshots are retained separately.

A fresh 0.1.1 OpenBLAS comparison also reran NumPy 1.26.4 (17 passes),
SciPy 1.12.0 (11 passes, 1 skip), and scikit-learn 1.4.2 (7 passes), using
two workers, one warmup and three measured runs per mode. All eight trials per
suite had identical outcomes and passed stricter enforcement verification.
NumPy's median was 4.0% slower, SciPy's 5.0% faster, and scikit-learn's 0.5% faster.
These short differences are not evidence of a general speedup. Raw trials are
in `evidence/release-011-openblas`. The local OpenBLAS plugin suite passed
**54 tests with 2 platform/opt-in skips**.
