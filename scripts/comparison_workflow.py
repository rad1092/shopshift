"""Synthetic repeated ERP-export workflow through public ShopShift APIs.

This is a deterministic functional experiment, not a human usability benchmark.
Temporary CSV/XLSX/projects/exports are deleted after assertions. The retained
JSON report includes timings, outcomes, and hashes only. One solver worker is
enforced by the production API, with a short limit for each suggestion.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import itertools
import json
import platform
import tempfile
import time
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from shopshift.importing import ImportProblem, import_operations
from shopshift.model import Operation, Placement, Project, Resource, Window
from shopshift.solver import suggest
from shopshift.storage import (
    backup_project,
    export_csv,
    export_html,
    load_project,
    restore_project,
    save_project,
)
from shopshift.timeutil import parse_timestamp
from shopshift.validator import validate

MAPPING = {"id": "Route Op ID", "job": "Work Order", "machine": "Work Center",
           "operator": "Crew", "setup": "Setup Min", "run": "Run Min",
           "predecessors": "Previous Op", "release": "Ready At", "due": "Due At",
           "label": "Part / Work"}


def fixture_rows(job_count: int) -> list[dict[str, str]]:
    rows = []
    for job in range(1, job_count + 1):
        for stage, machine, crew, setup, run, description in (
            (10, "SAW-1", "Saw crew", "10", "35.5", "Cut blank"),
            (20, "MILL-1", "Mill crew", "15", "50", "Mill faces and bore"),
            (30, "QA-1", "Inspection", "5", "20", "Inspect drawing dimensions"),
        ):
            rows.append(dict(zip(MAPPING.values(), [
                f"WO{job:04d}-{stage}", f"WO{job:04d}", machine, crew, setup, run,
                f"WO{job:04d}-{stage - 10}" if stage > 10 else "",
                "2026-10-05T08:00-05:00", "2026-10-07T16:00-05:00",
                f"Synthetic spacer {job}: {description}",
            ], strict=True)))
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(MAPPING.values()))
        writer.writeheader()
        writer.writerows(rows)


def oracle(project: Project, placements: dict[str, Placement]) -> dict:
    """Independent pairwise/interval arithmetic; never calls the product validator."""
    assert set(placements) == set(project.operations), "partial result"
    pairs = 0
    precedences = 0
    intervals = []
    for identity, operation in project.operations.items():
        start = placements[identity].start
        end = start + operation.setup + operation.run
        assert project.horizon_start <= start < end <= project.horizon_end
        if operation.release is not None:
            assert start >= operation.release
        for kind, key in (("machines", operation.machine), ("operators", operation.operator)):
            if key:
                resource = getattr(project, kind)[key]
                assert any(window.start <= start and end <= window.end for window in resource.windows), (identity, kind)
        for predecessor in operation.predecessors:
            other = project.operations[predecessor]
            assert placements[predecessor].start + other.setup + other.run <= start
            precedences += 1
        intervals.append((operation, start, end))
    for (left, a, b), (right, c, d) in itertools.combinations(intervals, 2):
        if left.machine == right.machine or (left.operator and left.operator == right.operator):
            pairs += 1
            assert b <= c or d <= a, (left.id, right.id, "overlap")
    return {"valid": True, "operations": len(placements), "resource_pairs": pairs, "precedences": precedences}


def official_instance() -> dict:
    jobs = [[(0, 3), (1, 2), (2, 2)], [(0, 2), (2, 1), (1, 4)], [(1, 4), (2, 3)]]
    project = Project(name="Official toy instance", horizon_start=0, horizon_end=22)
    for machine in range(3):
        project.machines[str(machine)] = Resource(str(machine), [Window(0, 22)])
    for job, tasks in enumerate(jobs):
        for step, (machine, duration) in enumerate(tasks):
            identity = f"{job}-{step}"
            project.operations[identity] = Operation(identity, str(job), str(machine), run=duration,
                                                     predecessors=[f"{job}-{step - 1}"] if step else [])
    result = suggest(project, time_limit=1)
    checked = oracle(project, result.placements)
    makespan = max(placement.start + project.operations[key].duration for key, placement in result.placements.items())
    assert result.status == "optimal" and makespan == 11
    return {"status": result.status, "objective": result.objective, "bound": result.bound,
            "makespan": makespan, "wall_seconds": result.wall_time, "independent_oracle": checked}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--jobs", type=int, default=12)
    args = parser.parse_args()
    if not 4 <= args.jobs <= 16:
        parser.error("Use 4–16 jobs; this is a small bounded comparison, not a scale test")
    report = {"measured_at_utc": datetime.now(timezone.utc).isoformat(),
              "platform": platform.platform(), "python": platform.python_version(),
              "scope": "Synthetic API workflow, no GUI or human time measurement; temporary generated fixtures cleaned up",
              "official_instance_through_product": official_instance(), "timings_seconds": {}}
    timings = report["timings_seconds"]

    def timed(label, callback):
        started = time.perf_counter()
        value = callback()
        timings[label] = time.perf_counter() - started
        return value

    with tempfile.TemporaryDirectory(prefix="shopshift-comparison-") as directory:
        folder = Path(directory)
        day1 = folder / "ERP Monday.csv"
        rows = fixture_rows(args.jobs)
        write_csv(day1, rows)
        project = Project(name="Synthetic contract machine shop", timezone="America/Chicago",
                          horizon_start=parse_timestamp("2026-10-05T00:00", "America/Chicago"),
                          horizon_end=parse_timestamp("2026-10-10T00:00", "America/Chicago"))
        imported = timed("initial_csv_import", lambda: import_operations(project, day1, MAPPING))
        assert not project.operations, "import mutated original project"
        project = imported.project
        first = timed("initial_suggestion", lambda: suggest(project, time_limit=2))
        assert first.status in {"optimal", "feasible"}, asdict(first)
        first_oracle = oracle(project, first.placements)
        project.scenario.placements = copy.deepcopy(first.placements)
        saw_order = sorted((key for key, op in project.operations.items() if op.machine == "SAW-1"),
                           key=lambda key: project.scenario.placements[key].start)
        locked_id, next_id = saw_order[:2]
        project.scenario.placements[locked_id].locked = True
        project.scenarios["Before reimport"] = copy.deepcopy(project.scenario)
        project.scenarios["Before reimport"].name = "Before reimport"
        saved_decisions = {name: scenario.to_dict() for name, scenario in project.scenarios.items()}
        path = folder / "shop.shopshift"
        timed("save_initial", lambda: save_project(project, path))
        project = timed("reopen_initial", lambda: load_project(path))
        assert project.mappings["__last__"] == dict(MAPPING, __duration_unit="minutes")
        assert {name: scenario.to_dict() for name, scenario in project.scenarios.items()} == saved_decisions

        # Extend one locked operation across the next operation by exactly a minute.
        # This creates a known conflict without assuming how CP-SAT ordered jobs.
        updated_duration = project.scenario.placements[next_id].start - project.scenario.placements[locked_id].start + 60
        assert updated_duration > project.operations[locked_id].setup
        for row in rows:
            if row[MAPPING["id"]] == locked_id:
                row[MAPPING["run"]] = str(Decimal(updated_duration - project.operations[locked_id].setup) / 60)
        omitted_id = f"WO{args.jobs:04d}-30"
        rows = [row for row in rows if row[MAPPING["id"]] != omitted_id]
        rows.extend(fixture_rows(args.jobs + 1)[-3:])
        rows.reverse()
        from openpyxl import Workbook
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(list(MAPPING.values()))
        for row in rows:
            worksheet.append([row[column] for column in MAPPING.values()])
        day2 = folder / "ERP Tuesday.xlsx"
        workbook.save(day2)
        workbook.close()
        saved_mapping = project.mappings["__last__"]
        refreshed = timed("reimport_xlsx", lambda: import_operations(
            project, day2, saved_mapping, duration_unit=saved_mapping["__duration_unit"]))
        project = refreshed.project
        assert refreshed.updated == [locked_id]
        assert len(refreshed.added) == 3 and refreshed.retained == [omitted_id]
        assert {name: scenario.to_dict() for name, scenario in project.scenarios.items()} == saved_decisions
        assert project.operations[locked_id].duration == updated_duration
        conflicts = timed("reimport_validation", lambda: validate(project))
        assert any(issue.severity == "error" and locked_id in issue.operation_ids for issue in conflicts)
        prior_snapshot = project.to_dict()
        alternative = copy.deepcopy(project.scenario)
        alternative.name = "Reviewed alternative"
        second = timed("revised_suggestion", lambda: suggest(project, alternative, time_limit=2))
        assert project.to_dict() == prior_snapshot, "suggestion applied without review"
        assert second.status in {"optimal", "feasible"}, asdict(second)
        assert second.placements[locked_id] == project.scenario.placements[locked_id]
        second_oracle = oracle(project, second.placements)
        alternative.placements = second.placements
        moved = sum(project.scenario.placements[key].start != placement.start
                    for key, placement in second.placements.items() if key in project.scenario.placements)
        project.scenarios[alternative.name] = alternative
        project.active_scenario = alternative.name
        assert not [issue for issue in validate(project) if issue.severity == "error"]

        # Both a duplicate-ID CSV and corrupt workbook must reject without mutation.
        duplicate = folder / "duplicate.csv"
        write_csv(duplicate, [rows[0], rows[0]])
        corrupt = folder / "corrupt.xlsx"
        corrupt.write_bytes(b"not an XLSX ZIP archive")
        rejected = []
        for bad in (duplicate, corrupt):
            before = project.to_dict()
            try:
                import_operations(project, bad, saved_mapping)
                raise AssertionError(f"accepted corrupt input {bad.name}")
            except ImportProblem as error:
                rejected.append({"fixture": bad.name, "message": str(error)})
            assert project.to_dict() == before
        csv_plan, html_plan = folder / "daily.csv", folder / "daily.html"
        timed("daily_csv", lambda: export_csv(project, csv_plan, day="2026-10-05"))
        timed("daily_html", lambda: export_html(project, html_plan, day="2026-10-05"))
        assert csv_plan.stat().st_size and html_plan.stat().st_size
        timed("save_revised", lambda: save_project(project, path))
        backup = folder / "backup.shopshift"
        timed("backup", lambda: backup_project(project, backup))
        path.write_bytes(b"interrupted or damaged external file")
        restored = timed("explicit_restore", lambda: restore_project(backup, path))
        assert restored.to_dict() == project.to_dict() == load_project(path).to_dict()
        report.update({
            "fixture": {"day1_rows": args.jobs * 3, "day2_rows": len(rows),
                        "merged_operations": len(project.operations), "machines": len(project.machines),
                        "operators": len(project.operators), "zone": project.timezone,
                        "calendar": "Weekdays 08:00–12:00 / 13:00–17:00, reviewed synthetic assumption",
                        "day1_sha256": hashlib.sha256(day1.read_bytes()).hexdigest()},
            "first_plan": {"status": first.status, "objective": first.objective, "bound": first.bound,
                           "independent_oracle": first_oracle},
            "reimport": {"updated": refreshed.updated, "added": refreshed.added, "retained": refreshed.retained,
                         "warnings": refreshed.warnings, "conflicts": [asdict(issue) for issue in conflicts],
                         "saved_mapping_fields_reused": len(MAPPING),
                         "unchanged_existing_decisions": args.jobs * 3 * 2,
                         "scenarios_checked": 2, "locked_operation": locked_id},
            "reviewed_alternative": {"status": second.status, "objective": second.objective, "bound": second.bound,
                                     "existing_starts_changed_after_explicit_accept": moved,
                                     "locked_start_preserved": True, "independent_oracle": second_oracle},
            "invalid_imports_rejected_atomically": rejected,
            "exports": {"csv_bytes": csv_plan.stat().st_size, "printable_html_bytes": html_plan.stat().st_size},
            "save_reopen_mapping_and_decisions_preserved": True,
            "explicit_backup_restore_roundtrip": True,
        })
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
