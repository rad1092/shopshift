#!/usr/bin/env python3
"""Reproducible synthetic shop workflow; no customer files or large fixtures.

Run: PYTHONPATH=src python scripts/benchmark_shop.py --operations 240 480 \
         --seconds 3 --output docs/benchmark_shop.json

This is a deliberately bounded release smoke/measurement, not a scalability
claim. The fixture assigns three successive operations to each job in three
production cells, each with two machines and one shared operator. A known
feasible plan is constructed from a 45-minute template (not a competing
scheduling algorithm). Due/release times, lunch, maintenance and half-days are
included. CP-SAT still receives all operations, calendars, dependencies, hints,
and three immutable locks. All returned plans pass a second independent oracle.
"""

from __future__ import annotations

import argparse
import copy
import csv
import importlib.metadata
import json
import platform
import random
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from shopshift.importing import import_operations
from shopshift.model import Operation, Placement, Project, Resource, Scenario, Window
from shopshift.solver import suggest
from shopshift.storage import export_csv, export_html, load_project, save_project
from shopshift.timeutil import format_timestamp
from shopshift.validator import validate


def fixture(count: int, seed: int = 20261008, backlog: bool = False) -> Project:
    if count % 3 or not 3 <= count <= 600:
        raise ValueError("Use a multiple of three between 3 and 600 operations")
    rng = random.Random(seed)
    first = datetime(2026, 10, 5, tzinfo=timezone.utc)
    start = int(first.timestamp())
    end = int((first + timedelta(days=35)).timestamp())
    windows = []
    for day in range(35):
        date = first + timedelta(days=day)
        if date.weekday() < 5:
            windows.extend(Window(int((date + timedelta(hours=a)).timestamp()),
                                  int((date + timedelta(hours=b)).timestamp())) for a, b in ((8, 12), (13, 17)))
    project = Project(name=f"Synthetic {count}-operation shop", horizon_start=start, horizon_end=end)
    project.machines = {f"M{i + 1}": Resource(f"M{i + 1}", copy.deepcopy(windows)) for i in range(6)}
    project.operators = {f"P{i + 1}": Resource(f"P{i + 1}", copy.deepcopy(windows)) for i in range(3)}
    # One operator has Wednesday afternoons off; M4 has Thursday maintenance.
    project.operators["P3"].windows = [w for w in windows if not (
        datetime.fromtimestamp(w.start, timezone.utc).weekday() == 2
        and datetime.fromtimestamp(w.start, timezone.utc).hour == 13)]
    project.machines["M4"].windows = [w for w in windows if not (
        datetime.fromtimestamp(w.start, timezone.utc).weekday() == 3
        and datetime.fromtimestamp(w.start, timezone.utc).hour == 13)]
    slots = [t for w in windows for t in range(w.start, w.end - 45 * 60 + 1, 45 * 60)]
    for cell in range(3):
        cursor = 0
        for job in range(cell, count // 3, 3):
            sequence = []
            for stage in range(3):
                machine = f"M{cell * 2 + stage % 2 + 1}"
                operator = f"P{cell + 1}"
                while cursor < len(slots) and not all(
                    any(w.start <= slots[cursor] and slots[cursor] + 2700 <= w.end for w in resource.windows)
                    for resource in (project.machines[machine], project.operators[operator])
                ):
                    cursor += 1
                if cursor >= len(slots):
                    raise ValueError("Fixture exceeds the bounded five-week template")
                key = f"J{job + 1:03d}-{stage + 1:02d}"
                op = Operation(key, f"J{job + 1:03d}", machine, operator,
                               setup=rng.randint(4, 12) * 60, run=rng.randint(10, 30) * 60,
                               predecessors=[sequence[-1]] if sequence else [],
                               label=("Rough mill", "Drill", "Finish mill")[stage])
                project.operations[key] = op
                project.scenario.placements[key] = Placement(slots[cursor], locked=job < 3 and stage == 0)
                sequence.append(key)
                cursor += 1
            release = start + 8 * 3600 if backlog else project.scenario.placements[sequence[0]].start
            due = project.scenario.placements[sequence[-1]].start + 2700 + rng.randint(-2, 4) * 3600
            for key in sequence:
                project.operations[key].release = release
                project.operations[key].due = due
    return project


def independent_check(project: Project, placements: dict[str, Placement]) -> list[str]:
    """Independent pairwise occupancy oracle, using no production validator."""
    violations = []
    if set(project.operations) != set(placements):
        return ["incomplete placement set"]
    for key, op in project.operations.items():
        start, finish = placements[key].start, placements[key].start + op.setup + op.run
        if start < project.horizon_start or finish > project.horizon_end:
            violations.append(f"{key}: outside horizon")
        if op.release is not None and start < op.release:
            violations.append(f"{key}: before release")
        old = project.scenario.placements.get(key)
        if old and old.locked and placements[key] != old:
            violations.append(f"{key}: changed lock")
        for resource in (project.machines[op.machine], project.operators[op.operator]):
            if not any(w.start <= start and finish <= w.end for w in resource.windows):
                violations.append(f"{key}: calendar hole")
        for predecessor in op.predecessors:
            pred = project.operations[predecessor]
            if placements[predecessor].start + pred.setup + pred.run > start:
                violations.append(f"{key}: precedence")
    items = list(project.operations.values())
    for index, left in enumerate(items):
        for right in items[index + 1:]:
            if left.machine != right.machine and left.operator != right.operator:
                continue
            if (placements[left.id].start < placements[right.id].start + right.setup + right.run
                    and placements[right.id].start < placements[left.id].start + left.setup + left.run):
                violations.append(f"{left.id}/{right.id}: resource overlap")
    return violations


FIELDS = ("id", "job", "machine", "operator", "setup", "run", "predecessors", "release", "due", "label")


def write_export(project: Project, path: Path, changed=False) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for index, op in enumerate(project.operations.values()):
            if changed and index == len(project.operations) - 1:
                continue  # A partial daily export must not imply cancellation.
            row = {field: getattr(op, field) for field in FIELDS}
            row["setup"] = str(op.setup // 60)
            row["run"] = str(op.run // 60 + (1 if changed and index % 20 == 0 else 0))
            row["predecessors"] = ";".join(op.predecessors)
            for field in ("release", "due"):
                row[field] = format_timestamp(row[field], "UTC")
            writer.writerow(row)


def benchmark(count: int, seconds: float, backlog: bool = False) -> dict:
    source = fixture(count, backlog=backlog)
    assert not independent_check(source, source.scenario.placements)
    measures = {}

    def measured(name, action):
        began = time.perf_counter()
        result = action()
        measures[name] = round(time.perf_counter() - began, 6)
        return result

    with tempfile.TemporaryDirectory(prefix="shopshift-benchmark-") as temporary:
        directory = Path(temporary)
        export_path = directory / "erp.csv"
        write_export(source, export_path)
        base = copy.deepcopy(source)
        base.operations = {}
        base.scenario.placements = {}
        initial = measured("initial_csv_import", lambda: import_operations(base, export_path, {key: key for key in FIELDS}))
        project = initial.project
        project.scenario.placements = copy.deepcopy(source.scenario.placements)
        write_export(source, export_path, changed=True)
        refresh = measured("reimport_csv", lambda: import_operations(project, export_path, project.mappings["__last__"]))
        assert refresh.project.scenario.placements == project.scenario.placements
        assert len(refresh.retained) == 1 and len(refresh.project.operations) == count
        project = refresh.project
        input_issues = measured("validate_retained_plan", lambda: validate(project))
        assert not [issue for issue in input_issues if issue.severity == "error"]
        before = project.to_dict()
        result = measured("suggest_total", lambda: suggest(project, time_limit=seconds))
        assert project.to_dict() == before
        candidate_errors = []
        if result.placements:
            candidate_errors = measured("independent_candidate_check", lambda: independent_check(project, result.placements))
            assert not candidate_errors, candidate_errors
            project.scenarios["Suggestion"] = Scenario("Suggestion", result.placements)
            project.active_scenario = "Suggestion"
        path = directory / "plan.shopshift"
        measured("save_project", lambda: save_project(project, path))
        restored = measured("load_project", lambda: load_project(path))
        assert restored.to_dict() == project.to_dict()
        measured("daily_csv_export", lambda: export_csv(project, directory / "day.csv", day="2026-10-05"))
        measured("daily_html_export", lambda: export_html(project, directory / "day.html", day="2026-10-05"))
        return {
            "operations": count, "jobs": count // 3, "machines": 6, "operators": 3,
            "horizon_days": 35, "working_days": 25,
            "manual_locks": sum(placement.locked for placement in source.scenario.placements.values()),
            "release_profile": "entire backlog ready on day one" if backlog else "staggered job releases",
            "source": "authored synthetic three-cell shop; known feasible 45-minute template",
            "reimport_updated": len(refresh.updated), "reimport_retained_omitted": len(refresh.retained),
            "csv_bytes": export_path.stat().st_size, "saved_project_bytes": path.stat().st_size,
            "status": result.status, "candidate_operations": len(result.placements),
            "objective_seconds": result.objective, "best_bound_seconds": result.bound,
            "solver_limit_seconds": seconds, "solver_workers": 1,
            "independent_candidate_errors": candidate_errors,
            "late_operations": sum(issue.code == "late" for issue in result.issues),
            "timings_seconds": measures,
            "feasibility_note": "time_limited with zero candidates is unknown, even though template proves input feasible",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operations", type=int, nargs="+", default=[240, 480])
    parser.add_argument("--seconds", type=float, default=3)
    parser.add_argument("--backlog", action="store_true", help="Make all operations ready on day one")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if not 0 < arguments.seconds <= 5:
        parser.error("Use a solver limit greater than zero and no more than five seconds")
    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": platform.python_version(), "platform": platform.platform(),
        "ortools": importlib.metadata.version("ortools"),
        "notes": "Single sequential run per size; no claims about general shop performance or optimality from a feasible incumbent.",
        "workloads": [benchmark(count, arguments.seconds, arguments.backlog) for count in arguments.operations],
    }
    encoded = json.dumps(report, indent=2) + "\n"
    if arguments.output:
        arguments.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
