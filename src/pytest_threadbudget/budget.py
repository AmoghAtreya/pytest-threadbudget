from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

# These control common BLAS/OpenMP runtimes. This plugin does not claim to
# manage NumExpr, Numba, PyTorch interop pools, Python executors or GPU threads.
THREAD_ENV = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "BLIS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)


@dataclass(frozen=True)
class Plan:
    mode: str
    detected_cpus: int
    effective_cpus: int
    workers: int
    threads_per_worker: int | None
    active: bool
    reason: str
    explicit_environment: dict[str, str]
    allocation_exceeds_budget: bool

    def to_dict(self):
        return asdict(self)


def make_plan(
    mode: str,
    detected_cpus: int,
    workers: int,
    cpu_cap: int | None,
    environment: Mapping[str, str],
    override_environment: bool = False,
) -> Plan:
    if detected_cpus < 1 or workers < 1 or (cpu_cap is not None and cpu_cap < 1):
        raise ValueError("CPU counts, CPU caps, and worker counts must be positive")
    detected_cpus = int(detected_cpus)
    cpus = min(detected_cpus, cpu_cap) if cpu_cap is not None else detected_cpus
    explicit = {key: environment[key] for key in THREAD_ENV if key in environment}
    if mode == "off":
        return Plan(mode, detected_cpus, cpus, workers, None, False, "disabled", explicit, False)
    if mode == "auto":
        threads = max(1, cpus // workers)
    else:
        try:
            threads = int(mode)
        except (ValueError, TypeError) as error:
            raise ValueError("threadbudget must be off, auto, or a positive integer") from error
        if threads < 1:
            raise ValueError("threadbudget must be off, auto, or a positive integer")
    active = not explicit or override_environment
    return Plan(
        mode,
        detected_cpus,
        cpus,
        workers,
        threads,
        active,
        "enabled"
        if active
        else "explicit environment preserved (use --threadbudget-override-env to opt in)",
        explicit,
        active and workers * threads > cpus,
    )
