# Changelog

## 0.1.1

First public release candidate. Includes opt-in local pytest/xdist budgeting,
conservative environment overrides, runtime pool discovery and restoration,
aggregated JSON diagnostics, and an alternating-order benchmark harness.

Reports use schema version 2 and retain native pool observations across test
boundaries. A final in-budget observation cannot hide an earlier violation.
Timing comparisons require matching successful JUnit outcomes and verified
runtime observations. Statsmodels validation loads the original test file
explicitly so its conftest options are registered before argument parsing.

## 0.1.0

Local prototype and exploratory validation. Historical reports in `evidence/`
were produced with this version; it was not published on PyPI.
