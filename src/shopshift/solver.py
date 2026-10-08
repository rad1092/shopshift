"""Bounded official OR-Tools CP-SAT suggestions, gated by a separate validator.

Objective = sum(max(0, operation_end - operation_due)) + makespan, in seconds
with 1:1 weights. Makespan is final completion minus horizon_start. Due dates
are soft. This is an operation-level objective, not job priorities or a promise
of on-time delivery. No plan is applied by this API.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from .model import Placement, Project, Scenario
from .validator import Issue, validate


@dataclass
class SolveResult:
    status: str
    placements: dict[str, Placement]
    issues: list[Issue]
    wall_time: float
    objective: float | None
    bound: float | None


def _merged(windows: list, low: int, high: int) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for window in windows:
        start, end = max(low, window.start), min(high, window.end)
        if start >= end:
            continue
        if result and start <= result[-1][1]:
            result[-1] = result[-1][0], max(end, result[-1][1])
        else:
            result.append((start, end))
    return result


def _intersection(left: list[tuple[int, int]], right: list[tuple[int, int]]) -> list[tuple[int, int]]:
    result = []
    i = j = 0
    while i < len(left) and j < len(right):
        start, end = max(left[i][0], right[j][0]), min(left[i][1], right[j][1])
        if start < end:
            result.append((start, end))
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return result


def suggest(project: Project, scenario: Scenario | None = None, time_limit: float = 5.0) -> SolveResult:
    """Suggest a complete plan without mutating inputs, using one solver worker.

    ``feasible`` means a validated incumbent, with optimality unproven (usually
    the time limit). ``time_limited`` means no candidate was found before search
    stopped; it never proves infeasibility. ``infeasible`` requires an explicit
    contradiction or CP-SAT proof. Unlocked placements are hints only.
    """
    started = time.monotonic()

    def result(status: str, issues: list[Issue], placements: dict[str, Placement] | None = None,
               objective: float | None = None, bound: float | None = None) -> SolveResult:
        return SolveResult(status, placements or {}, issues, time.monotonic() - started, objective, bound)

    try:
        usable_limit = type(time_limit) in (int, float) and math.isfinite(time_limit) and time_limit > 0
    except OverflowError:
        usable_limit = False
    if not usable_limit:
        return result("invalid", [Issue("invalid_time_limit", "Time limit must be finite and positive.")])
    if not isinstance(project, Project):
        return result("invalid", [Issue("invalid_project", "Expected a Project instance.")])

    # Validate source data independently of existing placements, which can be
    # invalid after an ERP refresh. An empty preview avoids accidental mutation.
    static_issues = validate(project, Scenario("Input validation"))
    errors = [issue for issue in static_issues if issue.severity == "error"]
    if errors:
        return result("invalid", errors)
    if not project.operations:
        return result("invalid", [Issue("no_operations", "Import at least one operation before suggesting a plan.")])
    chosen = scenario if scenario is not None else project.scenario
    if (not isinstance(chosen, Scenario) or not isinstance(chosen.name, str) or not chosen.name.strip()
            or not isinstance(chosen.placements, dict)):
        return result("invalid", [Issue("invalid_scenario", "Selected scenario must have a placement dictionary.")])
    locks: dict[str, Placement] = {}
    for key, placement in chosen.placements.items():
        if not isinstance(placement, Placement) or type(placement.locked) is not bool:
            return result("invalid", [Issue("invalid_placement", f"{key}: invalid placement or lock metadata.", (str(key),))])
        if placement.locked:
            locks[key] = placement
    lock_issues = [issue for issue in validate(project, Scenario("Locked decisions", locks))
                   if issue.severity == "error" and issue.code != "unscheduled_predecessor"]
    if lock_issues:
        malformed = any(issue.code in {"orphan_lock", "invalid_placement"} for issue in lock_issues)
        return result("invalid" if malformed else "infeasible", lock_issues)

    # Lazy import keeps the standalone validator/model usable without OR-Tools.
    from ortools.sat.python import cp_model

    origin = project.horizon_start
    horizon = project.horizon_end - origin
    model = cp_model.CpModel()
    starts, ends, resource_intervals = {}, {}, {}
    cached_calendars = {}
    for kind, resources in (("machine", project.machines), ("operator", project.operators)):
        for key, resource in resources.items():
            cached_calendars[kind, key] = _merged(resource.windows, origin, project.horizon_end)

    for key, operation in project.operations.items():
        windows = cached_calendars["machine", operation.machine]
        if operation.operator:
            windows = _intersection(windows, cached_calendars["operator", operation.operator])
        earliest = max(origin, operation.release if operation.release is not None else origin)
        domain = [[max(start, earliest) - origin, end - operation.duration - origin]
                  for start, end in windows if max(start, earliest) + operation.duration <= end]
        if not domain:
            return result("infeasible", [Issue("no_available_window", f"{key}: no uninterrupted shared machine/operator "
                          f"window fits {operation.duration} seconds after release within the horizon.", (key,))])
        start = model.new_int_var_from_domain(cp_model.Domain.from_intervals(domain), f"start:{key}")
        end = model.new_int_var(0, horizon, f"end:{key}")
        interval = model.new_interval_var(start, operation.duration, end, f"operation:{key}")
        starts[key], ends[key] = start, end
        resource_intervals.setdefault(("machine", operation.machine), []).append(interval)
        if operation.operator:
            resource_intervals.setdefault(("operator", operation.operator), []).append(interval)
        if key in locks:
            model.add(start == locks[key].start - origin)
        else:
            hint = chosen.placements.get(key)
            if (hint is not None and type(hint.start) is int
                    and any(a <= hint.start - origin <= b for a, b in domain)):
                model.add_hint(start, hint.start - origin)

    for intervals in resource_intervals.values():
        model.add_no_overlap(intervals)
    for key, operation in project.operations.items():
        for predecessor in operation.predecessors:
            model.add(starts[key] >= ends[predecessor])
    makespan = model.new_int_var(0, horizon, "makespan_seconds")
    model.add_max_equality(makespan, list(ends.values()))
    tardiness = []
    for key, operation in project.operations.items():
        if operation.due is not None:
            upper = max(0, project.horizon_end - operation.due)
            late = model.new_int_var(0, upper, f"tardiness:{key}")
            model.add_max_equality(late, [0, ends[key] + origin - operation.due])
            tardiness.append(late)
    model.minimize(sum(tardiness) + makespan)
    model_error = model.validate()
    if model_error:
        return result("invalid", [Issue("solver_model_invalid", f"CP-SAT rejected the numeric model: {model_error}")])
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    if status == cp_model.INFEASIBLE:
        return result("infeasible", [Issue("infeasible", "CP-SAT proved that no complete plan fits the current "
                      "resources, calendars, releases, dependencies, horizon and locks. Review these inputs.")])
    if status == cp_model.MODEL_INVALID:
        return result("invalid", [Issue("solver_model_invalid", "CP-SAT rejected the scheduling model.")])
    if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        return result("time_limited", [Issue("time_limit", "Search stopped without a complete candidate; feasibility "
                      "is unknown. Increase the limit or simplify the scenario.", severity="warning")])

    placements = {key: Placement(solver.value(start) + origin, key in locks) for key, start in starts.items()}
    candidate_issues = validate(project, Scenario("Candidate", placements))
    if set(placements) != set(project.operations):
        candidate_issues.append(Issue("incomplete_candidate", "Solver candidate omitted operations."))
    for key, placement in locks.items():
        if placements.get(key) != placement:
            candidate_issues.append(Issue("changed_lock", f"Candidate changed the locked decision for {key}.", (key,)))
    if any(issue.severity == "error" for issue in candidate_issues):
        return result("invalid", [Issue("candidate_rejected", "Independent validation rejected the solver candidate.")]
                      + candidate_issues)
    final_status = "optimal" if status == cp_model.OPTIMAL else "feasible"
    if final_status == "feasible":
        candidate_issues.append(Issue("optimality_unproven", "A complete feasible candidate was found; search stopped "
                                     "without proving optimality, usually at the time limit.", severity="warning"))
    return result(final_status, candidate_issues, placements, solver.objective_value, solver.best_objective_bound)
