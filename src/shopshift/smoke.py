"""Packaged launch check: real Qt widgets plus import/solve/save/export round trip."""
from __future__ import annotations

import copy
import csv
import json
import platform
import time
import traceback
from pathlib import Path


def run_smoke(app, directory: Path) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    checks = []
    started = time.perf_counter()
    window = None
    try:
        from PySide6.QtTest import QTest

        from .demo import demo_project
        from .gui import MainWindow
        from .importing import import_operations
        from .model import Placement
        from .solver import suggest
        from .storage import backup_project, export_csv, export_html, load_project, save_project
        from .validator import validate

        project = demo_project()
        result = suggest(project, time_limit=3.0)
        assert result.status in ("optimal", "feasible"), result
        project.scenario.placements = result.placements
        assert not [issue for issue in validate(project) if issue.severity == "error"]
        checks.append("official solver candidate independently validated")
        identity = next(iter(project.operations))
        operation = project.operations[identity]
        original = project.scenario.placements[identity]
        project.scenario.placements[identity] = Placement(original.start, True)
        incoming = directory / "synthetic-repeat.csv"
        with incoming.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["Operation", "Job", "Machine", "Run"])
            writer.writerow([identity, operation.job, operation.machine, str(operation.run)])
        mapping = {"id": "Operation", "job": "Job", "machine": "Machine", "run": "Run"}
        imported = import_operations(project, incoming, mapping, duration_unit="seconds")
        assert imported.project.scenario.placements[identity] == project.scenario.placements[identity]
        assert imported.project.scenario.placements[identity].locked
        assert len(imported.project.operations) == len(project.operations)
        checks.append("reimport preserves locked start and retains omitted rows")
        project = imported.project
        target = directory / "roundtrip.shopshift"
        save_project(project, target)
        recovered = load_project(target)
        assert recovered.to_dict() == project.to_dict()
        backup = directory / "backup.shopshift"
        backup_project(project, backup)
        assert load_project(backup).to_dict() == project.to_dict()
        checks.append("project save/restart/backup restore round trip")
        export_csv(project, directory / "plan.csv")
        export_html(project, directory / "plan.html")
        assert (directory / "plan.csv").stat().st_size > 50
        assert (directory / "plan.html").stat().st_size > 100
        checks.append("CSV and printable HTML snapshots")
        window = MainWindow(project)
        window.show()
        app.processEvents()
        QTest.qWait(120)
        assert window.isVisible()
        before = window.project.to_dict()
        changed = copy.deepcopy(window.project)
        changed.name = "Smoke edit"
        window.apply_project(changed, "Smoke edit")
        window.undo()
        assert window.project.to_dict() == before
        checks.append("native widget launch and undo")
        app.processEvents()
        assert window.grab().save(str(directory / "screenshot.png"))
        window.set_project(recovered, target)
        window.close()
        app.processEvents()
        report = {"passed": True, "checks": checks, "solver_status": result.status,
                  "platform": platform.platform(), "python": platform.python_version(),
                  "seconds": round(time.perf_counter() - started, 3)}
        (directory / "smoke.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report))
        return 0
    except Exception:  # noqa: BLE001 - smoke boundary must write failure evidence for any error
        report = {"passed": False, "checks": checks, "error": traceback.format_exc(),
                  "platform": platform.platform()}
        (directory / "smoke.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report))
        if window is not None:
            window.hide()
        return 1
