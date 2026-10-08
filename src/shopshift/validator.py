"""Independent schedule validation API; uses only Python's standard library.

An empty error list is not a completeness guarantee: UNSCHEDULED warnings mean
the plan is partial. Due dates are soft; LATE warnings do not make it infeasible.
Resource conflict reporting returns a witness for each conflicting interval,
not every pair, to remain bounded when many imported placements overlap.
"""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .model import MAX_TIMESTAMP, MIN_TIMESTAMP, Operation, Placement, Project, Resource, Scenario, Window


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    operation_ids: tuple[str, ...] = ()
    severity: str = "error"


def _timestamp(value: object) -> bool:
    return type(value) is int and MIN_TIMESTAMP <= value <= MAX_TIMESTAMP


def _identifier(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _covered(start: int, end: int, windows: list[Window]) -> bool:
    """Coverage by the continuous union, including adjacent half-open windows."""
    covered_until = start
    for window in windows:
        if window.end <= covered_until:
            continue
        if window.start > covered_until:
            return False
        covered_until = window.end
        if covered_until >= end:
            return True
    return False


def validate(project: Project, scenario: Scenario | None = None) -> list[Issue]:
    """Return structural errors, conflicts, partial-plan and lateness warnings.

    The selected scenario may be an unattached preview. No values are changed.
    Exact endpoints may touch. An operator is occupied for setup AND run.
    """
    issues: list[Issue] = []

    def report(code: str, message: str, *ids: str, severity: str = "error") -> None:
        issues.append(Issue(code, message, tuple(ids), severity))

    if not isinstance(project, Project):
        return [Issue("invalid_project", "Expected a Project instance.")]
    if not isinstance(project.name, str):
        report("invalid_name", "Project name must be text.")
    try:
        if not isinstance(project.timezone, str):
            raise TypeError("Timezone must be an IANA name")
        ZoneInfo(project.timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        report("invalid_timezone", f"Unknown IANA timezone: {project.timezone!r}.")
    valid_horizon = (_timestamp(project.horizon_start) and _timestamp(project.horizon_end)
                     and project.horizon_start < project.horizon_end)
    if not valid_horizon:
        report("invalid_horizon", "Planning horizon must use integer UTC seconds with start before end.")

    calendars: dict[tuple[str, str], list[Window]] = {}
    resource_ids: dict[str, set[str]] = {"machine": set(), "operator": set()}
    for kind, resources in (("machine", project.machines), ("operator", project.operators)):
        if not isinstance(resources, dict):
            report("invalid_resources", f"{kind.title()} resources must be a dictionary.")
            continue
        for key, resource in resources.items():
            if not _identifier(key) or not isinstance(resource, Resource) or resource.id != key:
                report("invalid_resource", f"{kind.title()} resource key {key!r} must match a nonempty resource ID.")
                continue
            resource_ids[kind].add(key)
            if not isinstance(resource.windows, list):
                report("invalid_calendar", f"{kind.title()} {key!r}: calendar must be a list of windows.")
                continue
            valid_windows = []
            previous: Window | None = None
            for index, window in enumerate(resource.windows):
                if (not isinstance(window, Window) or not _timestamp(window.start) or not _timestamp(window.end)
                        or window.start >= window.end):
                    report("invalid_window", f"{kind.title()} {key!r}: window {index + 1} must have integer start < end.")
                    continue
                if previous is not None and window.start < previous.start:
                    report("calendar_order", f"{kind.title()} {key!r}: availability windows are not chronological.")
                elif previous is not None and window.start < previous.end:
                    report("calendar_overlap", f"{kind.title()} {key!r}: availability windows overlap.")
                previous = window
                valid_windows.append(window)
            calendars[kind, key] = sorted(valid_windows, key=lambda w: w.start)

    if not isinstance(project.operations, dict):
        report("invalid_operations", "Operations must be a dictionary.")
        return issues
    operations: dict[str, Operation] = {}
    duration_valid: set[str] = set()
    predecessor_lists: dict[str, list[str]] = {}
    for key, operation in project.operations.items():
        if not _identifier(key) or not isinstance(operation, Operation) or operation.id != key:
            report("invalid_operation", f"Operation key {key!r} must match a nonempty operation ID.")
            continue
        operations[key] = operation
        if not _identifier(operation.job):
            report("invalid_job", f"{key}: job ID must be nonempty text.", key)
        for kind, resource_id in (("machine", operation.machine), ("operator", operation.operator)):
            if kind == "operator" and resource_id == "":
                continue
            if not _identifier(resource_id):
                report(f"invalid_{kind}", f"{key}: {kind} ID must be nonempty text.", key)
            elif resource_id not in resource_ids[kind]:
                report(f"missing_{kind}", f"{key}: {kind} {resource_id!r} has no availability calendar.", key)
        if (type(operation.setup) is not int or type(operation.run) is not int
                or operation.setup < 0 or operation.run < 0
                or not 0 < operation.setup + operation.run <= MAX_TIMESTAMP):
            report("invalid_duration", f"{key}: setup and run must be nonnegative integer seconds with positive total.", key)
        else:
            duration_valid.add(key)
        if not isinstance(operation.label, str):
            report("invalid_label", f"{key}: label must be text.", key)
        for name, value in (("release", operation.release), ("due", operation.due)):
            if value is not None and not _timestamp(value):
                report(f"invalid_{name}", f"{key}: {name} must be integer UTC seconds or absent.", key)
        if (not isinstance(operation.predecessors, list)
                or any(not _identifier(p) for p in operation.predecessors)):
            report("invalid_predecessors", f"{key}: predecessors must be a list of nonempty operation IDs.", key)
            continue
        predecessor_lists[key] = operation.predecessors
        if len(set(operation.predecessors)) != len(operation.predecessors):
            report("duplicate_predecessor", f"{key}: a predecessor appears more than once.", key)
        for predecessor in operation.predecessors:
            if predecessor not in project.operations:
                report("missing_predecessor", f"{key}: predecessor {predecessor!r} is missing.", key, predecessor)

    # Iterative DFS: long imported dependency chains must not hit recursion limits.
    colors: dict[str, int] = {}
    for origin in operations:
        if colors.get(origin):
            continue
        path = [origin]
        positions = {origin: 0}
        colors[origin] = 1
        stack = [(origin, iter(predecessor_lists.get(origin, [])))]
        while stack:
            current, edges = stack[-1]
            predecessor = next(edges, None)
            if predecessor is None:
                stack.pop()
                colors[current] = 2
                positions.pop(current)
                path.pop()
            elif predecessor in operations and colors.get(predecessor, 0) == 0:
                colors[predecessor] = 1
                positions[predecessor] = len(path)
                path.append(predecessor)
                stack.append((predecessor, iter(predecessor_lists.get(predecessor, []))))
            elif colors.get(predecessor) == 1:
                cycle = path[positions[predecessor]:]
                report("dependency_cycle", "Dependency cycle: " + " → ".join(cycle + [predecessor]), *cycle)

    if not isinstance(project.scenarios, dict) or not isinstance(project.active_scenario, str):
        report("invalid_scenarios", "Scenarios must be a dictionary and active_scenario must be text.")
    elif project.active_scenario not in project.scenarios:
        report("missing_scenario", "Active scenario does not exist.")
    if scenario is None:
        scenario = (project.scenarios.get(project.active_scenario)
                    if isinstance(project.scenarios, dict) and isinstance(project.active_scenario, str) else None)
    if not isinstance(scenario, Scenario) or not _identifier(scenario.name) or not isinstance(scenario.placements, dict):
        report("invalid_scenario", "Selected scenario must have a name and a placement dictionary.")
        return issues

    intervals: dict[str, tuple[int, int]] = {}
    resource_work: dict[tuple[str, str], list[tuple[int, int, str]]] = {}
    for key, placement in scenario.placements.items():
        if key not in operations:
            locked = isinstance(placement, Placement) and placement.locked is True
            report("orphan_lock" if locked else "orphan_placement",
                   f"{'Locked placement' if locked else 'Placement'} references missing operation {key!r}.", str(key))
            continue
        if (not isinstance(placement, Placement) or not _timestamp(placement.start)
                or type(placement.locked) is not bool):
            report("invalid_placement", f"{key}: placement needs integer UTC start and a boolean lock.", key)
            continue
        if key not in duration_valid:
            continue
        operation = operations[key]
        start, end = placement.start, placement.start + operation.duration
        intervals[key] = start, end
        if valid_horizon and (start < project.horizon_start or end > project.horizon_end):
            report("outside_horizon", f"{key}: [{start}, {end}) is outside the planning horizon.", key)
        if _timestamp(operation.release) and start < operation.release:
            report("before_release", f"{key}: starts {operation.release - start} seconds before release.", key)
        if _timestamp(operation.due) and end > operation.due:
            report("late", f"{key}: completes {end - operation.due} seconds after its due time.", key, severity="warning")
        for kind, resource_id in (("machine", operation.machine), ("operator", operation.operator)):
            if not isinstance(resource_id, str) or not resource_id or resource_id not in resource_ids[kind]:
                continue
            resource_work.setdefault((kind, resource_id), []).append((start, end, key))
            if not _covered(start, end, calendars.get((kind, resource_id), [])):
                report(f"{kind}_calendar", f"{key}: [{start}, {end}) crosses unavailable time on {kind} {resource_id!r}.", key)
    for key in operations:
        if key not in scenario.placements:
            report("unscheduled", f"{key}: not scheduled.", key, severity="warning")
        if key not in intervals:
            continue
        for predecessor in predecessor_lists.get(key, []):
            if predecessor not in operations:
                continue
            if predecessor not in intervals:
                report("unscheduled_predecessor", f"{key}: cannot verify precedence until {predecessor!r} is scheduled.",
                       key, predecessor)
            elif intervals[predecessor][1] > intervals[key][0]:
                report("precedence", f"{key}: starts {intervals[predecessor][1] - intervals[key][0]} seconds before "
                       f"predecessor {predecessor!r} finishes.", predecessor, key)

    for (kind, resource_id), work in resource_work.items():
        latest: tuple[int, int, str] | None = None
        for interval in sorted(work):
            if latest is not None and interval[0] < latest[1]:
                report(f"{kind}_overlap", f"{latest[2]} and {interval[2]} overlap on {kind} {resource_id!r} "
                       f"for {min(latest[1], interval[1]) - interval[0]} seconds.", latest[2], interval[2])
            if latest is None or interval[1] > latest[1]:
                latest = interval
    return issues
