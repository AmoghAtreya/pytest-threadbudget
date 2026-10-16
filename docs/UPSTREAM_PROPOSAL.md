# Upstream integration proposal (draft; not sent)

Target: pytest-xdist documentation or plugin references. Start from the existing
native oversubscription discussion at
https://github.com/pytest-dev/pytest-xdist/issues/1012 and read current maintainer
feedback before submitting. Do not open duplicate issues to advertise the tool.

## Proposed message

I built an opt-in plugin that divides the detected CPU allocation across local
xdist workers and applies a per-pool ceiling through threadpoolctl. It preserves
existing thread environment settings unless explicitly overridden, discovers
late imports at test boundaries, and restores settings on normal shutdown.

The plugin and reproducible validation are at
https://github.com/AmoghAtreya/pytest-threadbudget. It is independent of xdist and
has no adoption claim. Would a short reference in the relevant documentation be
useful, or would you prefer it remain an external project?

For projects already using `OPENBLAS_NUM_THREADS=1`, the plugin is not a proven
performance improvement. My selected Statsmodels regression subset was faster
than unrestricted threading, while the manual one-thread baseline was faster
than the plugin in the initial local comparison. Its purpose is configurable
allocation and diagnostics. It is not a hard process-wide thread quota.

## Before sending

- Link the verified PyPI release and green CI run.
- Link specific raw results with exact library/OS versions and repeat counts.
- Read the current target issue and contribution guidance.
- Submit only the smallest integration maintainers consider useful.
- Ask the project owner before sending this message or posting a PR.

A documentation reference is not evidence that the repository uses the plugin.
Count adoption only when the project's own maintained configuration installs and
enables it. Count an upstream merge only after the PR is actually merged.
