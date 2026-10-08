"""Public I/O contract tests, including interruption and repeated ERP imports."""

from __future__ import annotations

import copy
import csv
import io
import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from shopshift.demo import ERP_MAPPING, demo_project
from shopshift.importing import ImportProblem, import_operations, read_table
from shopshift.model import Operation, Placement, Project, Resource, Window
from shopshift.storage import (
    StorageProblem,
    backup_project,
    export_csv,
    export_html,
    load_project,
    restore_project,
    save_project,
)
from shopshift.timeutil import format_timestamp, parse_timestamp, working_windows
from shopshift.validator import validate

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def blank():
    return Project("Empty", "America/Chicago", parse_timestamp("2026-10-05T00:00", "America/Chicago"),
                   parse_timestamp("2026-10-10T00:00", "America/Chicago"))


def write_csv(tmp_path, rows, headers=("id", "job", "machine", "run"), name="source.csv"):
    path = tmp_path / name
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def test_demo_is_complete_synthetic_valid_and_has_late_work():
    project = demo_project()
    assert len(project.operations) == 21
    issues = validate(project)
    assert not [issue for issue in issues if issue.severity == "error"]
    assert any(issue.code == "late" for issue in issues)


def test_repeated_import_keeps_every_scenario_and_omitted_rows(blank):
    first = import_operations(blank, EXAMPLES / "erp_day1.csv", ERP_MAPPING)
    assert len(first.added) == 21
    assert not blank.operations
    assert first.project.mappings["__last__"]["__duration_unit"] == "minutes"
    assert any("Assumed weekdays" in warning for warning in first.warnings)
    sample = demo_project()
    first.project.scenarios = sample.scenarios
    before = copy.deepcopy(first.project)
    result = import_operations(first.project, EXAMPLES / "erp_day2.csv", ERP_MAPPING)
    assert result.project.scenarios == before.scenarios
    assert result.project.operations["WO-401-20"].duration == 9000
    assert result.project.scenario.placements["WO-401-20"].locked
    assert result.added == ["WO-408-10", "WO-408-20"]
    assert result.updated == ["WO-401-20"]
    assert result.retained == ["WO-401-10"]
    assert first.project == before
    assert result.project.mappings["erp_day2.csv"] == dict(ERP_MAPPING, __duration_unit="minutes")


def test_day_one_fixture_matches_demo(blank):
    imported = import_operations(blank, EXAMPLES / "erp_day1.csv", ERP_MAPPING).project
    assert imported.operations == demo_project().operations


@pytest.mark.parametrize(("value", "unit", "expected"), [("0.5", "minutes", 30), ("0.125", "hours", 450), ("31", "seconds", 31)])
def test_exact_decimal_units(tmp_path, blank, value, unit, expected):
    path = write_csv(tmp_path, [["A", "Job", "Mill", value]])
    result = import_operations(blank, path, {key: key for key in ("id", "job", "machine", "run")}, unit)
    assert result.project.operations["A"].run == expected


@pytest.mark.parametrize("value", ["0.1", "1e2", "NaN", "-1", "0", "2678401", "0.01666666666666666666666666667"])
def test_invalid_or_fractional_seconds_atomic(tmp_path, blank, value):
    path = write_csv(tmp_path, [["A", "Job", "Mill", value]])
    with pytest.raises(ImportProblem):
        import_operations(blank, path, {key: key for key in ("id", "job", "machine", "run")}, "seconds")
    assert not blank.operations and not blank.machines and not blank.mappings


def test_missing_optional_mapping_preserves_manual_details(tmp_path):
    project = demo_project()
    path = write_csv(tmp_path, [["WO-401-20", "WO-401", "MILL-1", "120"]])
    result = import_operations(project, path, {key: key for key in ("id", "job", "machine", "run")})
    operation = result.project.operations["WO-401-20"]
    assert operation.operator == "Alex" and operation.setup == 1800
    assert operation.predecessors == ["WO-401-10"]
    assert operation.due == project.operations[operation.id].due


def test_mapped_blank_clears_optional_cell(tmp_path):
    project = demo_project()
    path = write_csv(tmp_path, [["WO-401-20", "WO-401", "MILL-1", "120", ""]],
                     headers=("id", "job", "machine", "run", "operator"))
    result = import_operations(project, path, {key: key for key in ("id", "job", "machine", "run", "operator")})
    assert result.project.operations["WO-401-20"].operator == ""


def test_corrupt_duplicate_is_atomic():
    project = demo_project()
    original = copy.deepcopy(project)
    with pytest.raises(ImportProblem, match="duplicate operation ID"):
        import_operations(project, EXAMPLES / "corrupt.csv", ERP_MAPPING)
    assert project == original


def test_blank_rows_do_not_shift_reported_source_position(tmp_path, blank):
    path = tmp_path / "blank.csv"
    path.write_text("id,job,machine,run\n\nA,Job,Mill,not-a-number\n", encoding="utf-8")
    with pytest.raises(ImportProblem, match="Row 3"):
        import_operations(blank, path, {key: key for key in ("id", "job", "machine", "run")})


def test_multiline_csv_uses_physical_source_row(tmp_path, blank):
    path = tmp_path / "multiline.csv"
    path.write_text('id,job,machine,run,label\nA,Job,Mill,1,"one\ntwo"\nB,Job,Mill,invalid,three\n')
    with pytest.raises(ImportProblem, match="Row 4"):
        import_operations(blank, path, {key: key for key in ("id", "job", "machine", "run", "label")})


@pytest.mark.parametrize("source", ["id,job,machine,run,\nA,Job,Mill,1,\n", "id,job,machine,run\nA,Job,Mill,1,\n"])
def test_empty_extra_csv_columns_rejected(tmp_path, source):
    path = tmp_path / "extra.csv"
    path.write_text(source)
    with pytest.raises(ImportProblem):
        read_table(path)


@pytest.mark.parametrize("source", ["id,id\nA,B\n", 'id,job,machine,run\n"unterminated', "id,job,machine,run\nA,Job,Mill\n"])
def test_malformed_csv_rejected(tmp_path, source):
    path = tmp_path / "broken.csv"
    path.write_text(source)
    with pytest.raises(ImportProblem):
        read_table(path)


def test_missing_dependency_is_visible_partial_input(tmp_path, blank):
    path = write_csv(tmp_path, [["B", "Job", "Mill", "10", "missing"]], ("id", "job", "machine", "run", "predecessors"))
    result = import_operations(blank, path, {key: key for key in ("id", "job", "machine", "run", "predecessors")})
    assert any("missing" in warning for warning in result.warnings)
    assert any(issue.severity == "error" for issue in validate(result.project))


def test_resource_and_generated_calendar_bounds_precede_allocation(tmp_path, blank):
    path = write_csv(tmp_path, [[f"op-{i}", "Job", f"machine-{i}", "1"] for i in range(2001)])
    mapping = {key: key for key in ("id", "job", "machine", "run")}
    with pytest.raises(ImportProblem, match="2,000"):
        import_operations(blank, path, mapping)
    blank.horizon_end = blank.horizon_start + 365 * 86400
    path = write_csv(tmp_path, [[f"op-{i}", "Job", f"machine-{i}", "1"] for i in range(201)])
    with pytest.raises(ImportProblem, match="100,000"):
        import_operations(blank, path, mapping)
    assert not blank.operations and not blank.machines


def test_xlsx_sparse_trailing_cells_and_dates(tmp_path, blank):
    from datetime import datetime
    path = tmp_path / "export.xlsx"
    workbook = Workbook()
    workbook.active.append(["id", "job", "machine", "run", "release", "label"])
    workbook.active.append(["A", "Job", "Mill", 0.5, datetime(2026, 10, 5, 8)])
    workbook.save(path)
    mapping = {key: key for key in ("id", "job", "machine", "run", "release", "label")}
    result = import_operations(blank, path, mapping)
    assert result.project.operations["A"].run == 30
    assert result.project.operations["A"].label == ""
    assert result.project.operations["A"].release == parse_timestamp("2026-10-05T08:00", blank.timezone)


@pytest.mark.parametrize("bad", ["=SUM(1,2)", "#VALUE!"])
def test_xlsx_formula_or_error_rejected(tmp_path, bad):
    path = tmp_path / "formula.xlsx"
    workbook = Workbook()
    workbook.active.append(["id", "run"])
    workbook.active.append(["A", bad])
    workbook.save(path)
    with pytest.raises(ImportProblem, match="formula or error"):
        read_table(path)


@pytest.mark.parametrize(("value", "message"), [("2026-03-08T02:30", "gap"), ("2026-11-01T01:30", "fold")])
def test_dst_requires_unambiguous_local_time(value, message):
    with pytest.raises(ValueError, match=message):
        parse_timestamp(value, "America/New_York")


def test_explicit_offsets_disambiguate_and_round_trip():
    early = parse_timestamp("2026-11-01T01:30-04:00", "America/New_York")
    later = parse_timestamp("2026-11-01T01:30-05:00", "America/New_York")
    assert later - early == 3600
    assert parse_timestamp(format_timestamp(later, "America/New_York"), "America/New_York") == later
    assert parse_timestamp("2026-10-05T13:00Z", "America/Chicago") == parse_timestamp("2026-10-05T08:00", "America/Chicago")


@pytest.mark.parametrize("value", ["2026-10-05", "10/05/2026 08:00", "2026-10-05T08:00:00.1", "2026-10-05T08:00+01:99", "2026-02-30T08:00"])
def test_dates_never_guess_or_round(value):
    with pytest.raises(ValueError):
        parse_timestamp(value, "UTC")


def test_weekday_lunch_and_overnight_shifts():
    def stamp(text):
        return parse_timestamp(text, "America/Chicago")
    windows = working_windows(stamp("2026-10-05T09:00"), stamp("2026-10-06T09:00"), "America/Chicago")
    assert [(w.start, w.end) for w in windows] == [
        (stamp("2026-10-05T09:00"), stamp("2026-10-05T12:00")),
        (stamp("2026-10-05T13:00"), stamp("2026-10-05T17:00")),
        (stamp("2026-10-06T08:00"), stamp("2026-10-06T09:00")),
    ]
    overnight = working_windows(stamp("2026-10-09T21:00"), stamp("2026-10-10T07:00"), "America/Chicago", 22, 6)
    assert overnight == [Window(stamp("2026-10-09T22:00"), stamp("2026-10-10T06:00"))]


def test_save_reload_previous_backup_and_portable_backup(tmp_path):
    project = demo_project()
    path = tmp_path / "shop.shopshift"
    save_project(project, path)
    project.name = "Changed"
    save_project(project, path)
    assert load_project(path) == project
    assert load_project(str(path) + ".bak").name != project.name
    backup_project(project, tmp_path / "portable.shopshift")
    assert load_project(tmp_path / "portable.shopshift") == project
    assert not list(tmp_path.glob("*.tmp"))


def test_interrupted_replace_retains_original_and_backup(tmp_path, monkeypatch):
    import shopshift.storage as storage
    path = tmp_path / "plan.shopshift"
    project = demo_project()
    save_project(project, path)
    original = path.read_bytes()
    project.name = "After failure"
    real_replace = storage.os.replace

    def fail_destination(source, destination):
        if Path(destination) == path:
            raise OSError("simulated interrupted save")
        return real_replace(source, destination)

    monkeypatch.setattr(storage.os, "replace", fail_destination)
    with pytest.raises(StorageProblem, match="interrupted save"):
        save_project(project, path)
    assert path.read_bytes() == original
    assert Path(str(path) + ".bak").read_bytes() == original
    assert not list(tmp_path.glob(".*.tmp"))


def test_corrupt_file_requires_explicit_restore(tmp_path):
    project = demo_project()
    path = tmp_path / "plan.shopshift"
    backup = tmp_path / "backup.shopshift"
    save_project(project, backup)
    path.write_bytes(b'{"interrupted":')
    with pytest.raises(StorageProblem):
        load_project(path)
    with pytest.raises(StorageProblem, match="corrupt"):
        save_project(project, path)
    restored = restore_project(backup, path)
    assert restored == project == load_project(path)
    assert Path(str(path) + ".corrupt").read_bytes() == b'{"interrupted":'


@pytest.mark.parametrize("change", [lambda d: d.update(version=True), lambda d: d["project"].update(horizon_start=True),
                                   lambda d: d["project"].update(unknown="x"),
                                   lambda d: d["project"]["scenarios"]["Baseline"]["placements"]["WO-401-20"].pop("locked")])
def test_corrupt_schema_is_rejected(tmp_path, change):
    path = tmp_path / "bad.shopshift"
    save_project(demo_project(), path)
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))
    with pytest.raises(StorageProblem):
        load_project(path)


def test_duplicate_json_keys_rejected(tmp_path):
    path = tmp_path / "bad.shopshift"
    path.write_text('{"format":"shopshift","version":1,"version":1,"project":{}}')
    with pytest.raises(StorageProblem, match="Duplicate JSON key"):
        load_project(path)


def test_safe_csv_html_export_and_day_filter(tmp_path):
    project = demo_project()
    project.operations["WO-401-20"].label = '=HYPERLINK("https://invalid") <script>alert(1)</script>'
    csv_path, html_path = tmp_path / "plan.csv", tmp_path / "plan.html"
    export_csv(project, csv_path, day="2026-10-05")
    export_html(project, html_path, day="2026-10-05")
    rows = list(csv.DictReader(io.StringIO(csv_path.read_text(encoding="utf-8-sig"))))
    dangerous = next(row for row in rows if row["operation_id"] == "WO-401-20")
    assert dangerous["label"].startswith("'=")
    assert "late" in dangerous["warnings"]
    assert all("2026-10-05" in row["start"] for row in rows)
    markup = html_path.read_text()
    assert "<script>" not in markup and "&lt;script&gt;" in markup
    assert "DRAFT" in markup and "America/Chicago" in markup and "@media print" in markup


def test_daily_list_includes_overnight_and_unscheduled(tmp_path):
    start = parse_timestamp("2026-10-05T23:30", "UTC")
    project = Project(horizon_start=start, horizon_end=start + 86400)
    project.operations = {"night": Operation("night", "job", "M", run=3600), "waiting": Operation("waiting", "job", "M")}
    project.machines = {"M": Resource("M", [Window(start, start + 86400)])}
    project.scenario.placements = {"night": Placement(start)}
    path = tmp_path / "day.csv"
    export_csv(project, path, day="2026-10-06")
    rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
    assert {row["operation_id"] for row in rows} == {"night", "waiting"}
