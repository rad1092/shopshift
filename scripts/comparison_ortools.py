"""Run a pinned official OR-Tools sample, then independently check its output.

The upstream program is fetched only from a pinned Google commit and verified
before execution. Only CpSolver's resource limits/status capture are wrapped;
the official sample's model, input, and reporting remain unchanged. No source
or wheel download is retained. This is a solver baseline, not a UX benchmark.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import itertools
import json
import platform
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

COMMIT = "551ad10d94835c99e5e1e684500d3db398c0e345"
URL = f"https://raw.githubusercontent.com/google/or-tools/{COMMIT}/ortools/sat/samples/minimal_jobshop_sat.py"
SHA256 = "8294515355a8dc6929994e4ea08b4fee7b276088917c0f9a6b1b08a409e22f1c"
JOBS = [[(0, 3), (1, 2), (2, 2)], [(0, 2), (2, 1), (1, 4)], [(1, 4), (2, 3)]]


def check_output(output: str) -> dict:
    """Pure-Python oracle, independent of CP-SAT and ShopShift's validator."""
    assignments = {}
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("Machine "):
            continue
        machine = int(line.split(":", 1)[0].split()[1])
        tasks = re.findall(r"job_(\d+)_task_(\d+)", line)
        intervals = re.findall(r"\[(\d+),(\d+)\]", lines[index + 1])
        if len(tasks) != len(intervals):
            raise AssertionError("unparseable upstream schedule")
        for task, interval in zip(tasks, intervals, strict=True):
            key = tuple(map(int, task))
            if key in assignments:
                raise AssertionError(f"duplicate operation {key}")
            assignments[key] = (machine, *map(int, interval))
    expected = {(job, task) for job, steps in enumerate(JOBS) for task in range(len(steps))}
    assert set(assignments) == expected, "not all official operations scheduled"
    for (job, task), (machine, start, end) in assignments.items():
        expected_machine, duration = JOBS[job][task]
        assert machine == expected_machine
        assert start >= 0 and end - start == duration
        if task:
            assert start >= assignments[job, task - 1][2], "precedence conflict"
    pairs = 0
    for left, right in itertools.combinations(assignments.values(), 2):
        if left[0] == right[0]:
            pairs += 1
            assert left[2] <= right[1] or right[2] <= left[1], "machine overlap"
    makespan = max(row[2] for row in assignments.values())
    assert makespan == 11, "does not match independently known official toy optimum"
    return {"operation_count": len(assignments), "checked_machine_pairs": pairs,
            "checked_precedences": 5, "makespan": makespan, "valid": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Optional previously downloaded exact upstream file")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    import ortools
    from ortools.sat.python import cp_model

    fetch_start = time.perf_counter()
    if args.source:
        source = args.source.read_bytes()
    else:
        with urllib.request.urlopen(URL, timeout=30) as response:
            source = response.read()
    fetch_seconds = time.perf_counter() - fetch_start
    if hashlib.sha256(source).hexdigest() != SHA256:
        raise RuntimeError("Pinned upstream source integrity mismatch; refusing execution")
    original_solver = cp_model.CpSolver
    solve_results = {}

    class BoundedSolver(original_solver):
        def __init__(self):
            super().__init__()
            self.parameters.num_search_workers = 1
            self.parameters.max_time_in_seconds = 10.0
            self.parameters.random_seed = 0

        def solve(self, model, *positional, **keywords):
            status = super().solve(model, *positional, **keywords)
            solve_results.update(status=self.status_name(status),
                                 solver_wall_seconds=self.wall_time,
                                 objective=self.objective_value,
                                 best_bound=self.best_objective_bound)
            return status

    cp_model.CpSolver = BoundedSolver
    output = io.StringIO()
    execution_start = time.perf_counter()
    try:
        with contextlib.redirect_stdout(output):
            # Exact official source is SHA-256 checked above before this execution.
            exec(compile(source, URL, "exec"), {"__name__": "__main__", "__file__": URL})  # noqa: S102
    finally:
        cp_model.CpSolver = original_solver
    execution_seconds = time.perf_counter() - execution_start
    oracle = check_output(output.getvalue())
    assert solve_results["status"] == "OPTIMAL", "sample did not prove toy optimum"
    report = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(), "machine": platform.machine(),
        "python": platform.python_version(), "ortools": ortools.__version__,
        "upstream_url": URL, "upstream_sha256": SHA256,
        "resource_control": {"workers": 1, "limit_seconds": 10, "random_seed": 0},
        "fetch_seconds": fetch_seconds, "execution_seconds": execution_seconds,
        "solver": solve_results, "independent_oracle": oracle,
        "upstream_stdout": output.getvalue(),
        "scope": "Official 8-operation arithmetic example; no calendars, import UI, retained decisions, or human timing.",
    }
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
