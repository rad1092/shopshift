"""Widget integration checks; run with QT_QPA_PLATFORM=offscreen in headless CI."""
from __future__ import annotations

from copy import deepcopy

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from shopshift.demo import demo_project
from shopshift.gui import (
    CalendarDialog,
    MainWindow,
    MappingDialog,
    PlacementDialog,
    ProjectDialog,
    ReviewDialog,
)
from shopshift.model import Placement, Resource, Window
from shopshift.solver import SolveResult
from shopshift.storage import load_project


@pytest.fixture
def window(qtbot):
    widget = MainWindow(demo_project())
    def cleanup(widget):
        if widget._solver_thread is not None:
            qtbot.waitUntil(lambda: widget._solver_thread is None, timeout=15000)
        widget.dirty = False
    qtbot.addWidget(widget, before_close_func=cleanup)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def test_edit_lock_undo_scenario_and_restart(window, tmp_path):
    identity = "WO-401-10"
    old = deepcopy(window.project.scenario.placements[identity])
    window.select_operation(identity)
    window.toggle_selected_lock()
    assert window.project.scenario.placements[identity].locked
    window.move_operation(identity, old.start + 3600)
    assert window.project.scenario.placements[identity].start == old.start
    window.undo()
    assert window.project.scenario.placements[identity] == old
    window.copy_scenario("Tomorrow")
    window.set_placement(identity, Placement(old.start + 60, True))
    assert window.project.scenarios["Baseline"].placements[identity] == old
    assert window.compare_table.rowCount() == 1
    target = tmp_path / "saved.shopshift"
    assert window.save_to(target)
    assert not window.dirty
    assert load_project(target).to_dict() == window.project.to_dict()
    window.set_project(MainWindow.blank_project())
    assert window.open_path(target)
    assert window.project.active_scenario == "Tomorrow"
    assert window.project.scenario.placements[identity].locked


def test_real_drag_and_keyboard_equivalent(window, qtbot):
    identity = "WO-401-10"
    original = window.project.scenario.placements[identity].start
    window.timeline_zoom.setCurrentIndex(1)
    window.select_operation(identity)
    bar = window.timeline.bars[identity]
    window.timeline.ensureVisible(bar)
    qtbot.wait(20)
    start = window.timeline.mapFromScene(bar.sceneBoundingRect().center())
    end = start + QPoint(48, 0)  # One hour at day-detail scale.
    QTest.mousePress(window.timeline.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window.timeline.viewport(), end, 40)
    QTest.mouseRelease(window.timeline.viewport(), Qt.MouseButton.LeftButton, pos=end)
    qtbot.waitUntil(lambda: window.project.scenario.placements[identity].start != original, timeout=2000)
    assert window.project.scenario.placements[identity].start == original + 3600
    window.undo()
    assert window.project.scenario.placements[identity].start == original
    dialog = PlacementDialog(window.project, identity, window)
    dialog.start.setText("2026-10-05T08:15:00-05:00")
    dialog.locked.setChecked(True)
    dialog._accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    window.set_placement(identity, dialog.result_placement)
    assert window.project.scenario.placements[identity].start == original + 900
    assert window.project.scenario.placements[identity].locked


def test_import_review_cancel_and_repeat_preserves_decisions(window, tmp_path, monkeypatch):
    source = tmp_path / "day2.csv"
    source.write_text("id,job,machine,run\nWO-401-20,WO-401,MILL-1,90\n", encoding="utf-8")
    mapping = {key: key for key in ("id", "job", "machine", "run")}
    before = window.project.to_dict()
    preview = window.import_from(source, mapping)
    assert window.project.to_dict() == before
    assert preview.project.scenario.placements["WO-401-20"] == window.project.scenario.placements["WO-401-20"]
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))
    monkeypatch.setattr(MappingDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(ReviewDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    window.import_dialog()
    assert window.project.to_dict() == before
    monkeypatch.setattr(ReviewDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    window.import_dialog()
    assert window.project.operations["WO-401-20"].run == 5400
    assert window.project.scenario.placements["WO-401-20"].locked
    assert window.project.mappings["__last__"]["run"] == "run"
    window.undo()
    assert window.project.to_dict() == before


def test_bad_import_and_failed_save_keep_live_draft(window, tmp_path, monkeypatch):
    source = tmp_path / "bad.csv"
    source.write_text("id,job,machine,run\nA,Job,MILL-1,not-a-number\n", encoding="utf-8")
    before = window.project.to_dict()
    errors = []
    monkeypatch.setattr(window, "_error", lambda title, exc: errors.append((title, str(exc))))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))
    monkeypatch.setattr(MappingDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    window.import_dialog()
    assert errors and "Import failed" in errors[-1][0]
    assert window.project.to_dict() == before
    window.dirty = True
    def failed_save(*args):
        raise OSError("disk full")
    monkeypatch.setattr("shopshift.storage.save_project", failed_save)
    assert not window.save_to(tmp_path / "cannot-save.shopshift")
    assert window.dirty and window.path is None
    assert "disk full" in errors[-1][1]
    assert window.project.to_dict() == before


def test_save_cancel_and_close_cancel(window, monkeypatch):
    window.dirty = True
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    before = window.project.to_dict()
    window.new_project()
    assert window.project.to_dict() == before
    assert not window.close()
    assert window.isVisible()
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Save)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    assert not window._confirm_discard()
    assert window.dirty


def test_cancel_new_project_settings_keeps_existing_project(window, monkeypatch):
    before = window.project.to_dict()
    monkeypatch.setattr(ProjectDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    window.new_project()
    assert window.project.to_dict() == before


def test_keyboard_activation_opens_one_editor(window, monkeypatch):
    opened = []
    monkeypatch.setattr(window, "edit_operation", lambda op_id: opened.append(op_id))
    window.select_operation("WO-401-10")
    window.operations_table.setFocus()
    QTest.keyClick(window.operations_table, Qt.Key.Key_Return)
    assert opened == ["WO-401-10"]
    opened.clear()
    point = window.operations_table.visualItemRect(window.operations_table.item(0, 0)).center()
    QTest.mouseClick(window.operations_table.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseDClick(window.operations_table.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert opened == ["WO-401-10"]


def test_calendar_gaps_overnight_invalid_and_dst(window):
    dialog = CalendarDialog(window.project, Resource("NIGHT", []), window)
    dialog.editor.setPlainText("2026-10-05T22:00-05:00 / 2026-10-06T02:00-05:00\n2026-10-06T03:00-05:00 / 2026-10-06T06:00-05:00")
    dialog._accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert len(dialog.windows) == 2
    assert dialog.windows[0].end < dialog.windows[1].start
    overlap = CalendarDialog(window.project, Resource("BAD", []), window)
    overlap.editor.setPlainText("2026-10-05T08:00-05:00 / 2026-10-05T12:00-05:00\n2026-10-05T11:00-05:00 / 2026-10-05T13:00-05:00")
    overlap._accept()
    assert "overlap" in overlap.error.text()
    assert overlap.result() != QDialog.DialogCode.Accepted
    placement = PlacementDialog(window.project, "WO-401-10", window)
    placement.start.setText("2026-11-01T01:30")
    placement._accept()
    assert "ambiguous" in placement.error.text()
    placement.start.clear()
    placement.locked.setChecked(True)
    placement._accept()
    assert "needs a start" in placement.error.text()


def test_retirement_blocks_required_predecessors_and_is_undoable(window):
    before = window.project.to_dict()
    with pytest.raises(ValueError, match="predecessor"):
        window.retire_operation("WO-401-10")
    assert window.project.to_dict() == before
    window.retire_operation("WO-401-30")
    assert "WO-401-30" not in window.project.operations
    assert all("WO-401-30" not in scenario.placements for scenario in window.project.scenarios.values())
    window.undo()
    assert window.project.to_dict() == before


def test_independent_validator_rejects_fake_solver_success(window):
    before = window.project.to_dict()
    placements = deepcopy(window.project.scenario.placements)
    placements["WO-402-10"].start = placements["WO-401-10"].start
    result = SolveResult("optimal", placements, [], 0.1, 0, 0)
    with pytest.raises(ValueError, match="Independent validation"):
        window.apply_suggestion(result)
    assert window.project.to_dict() == before
    result.placements = {}
    with pytest.raises(ValueError, match="partial"):
        window.apply_suggestion(result)
    result.status = "time_limited"
    with pytest.raises(ValueError, match="usable complete"):
        window.apply_suggestion(result)
    result.status = "optimal"
    result.placements = deepcopy(window.project.scenario.placements)
    result.placements["WO-401-20"].locked = False
    with pytest.raises(ValueError, match="locked"):
        window.apply_suggestion(result)


def test_solver_worker_keeps_current_plan_until_apply(window, qtbot):
    before = window.project.to_dict()
    with qtbot.waitSignal(window.schedule_ready, timeout=15000) as signal:
        window.start_suggest(show_review=False, time_limit=1.0)
        assert not window.tabs.isEnabled()
        assert not window.project_settings_button.isEnabled()
        assert not window.close()  # Prevent QThread destruction while running.
        assert window.project.to_dict() == before
    qtbot.waitUntil(lambda: window._solver_thread is None, timeout=15000)
    assert window.tabs.isEnabled()
    result = signal.args[0]
    assert result.status in ("feasible", "optimal")
    assert window.project.to_dict() == before
    window.apply_suggestion(result)
    assert window.dirty
    assert not [issue for issue in window.current_issues if issue.severity == "error"]
    window.undo()
    assert window.project.to_dict() == before


def test_korean_filter_late_and_unscheduled_daily(window):
    window.language_box.setCurrentIndex(1)
    assert window.tabs.tabText(0) == "일정"
    assert window.actions["save"].text() == "저장"
    window.filter.setText("WO-401")
    assert window.operations_table.rowCount() == 3
    window.filter.clear()
    window.late_only.setChecked(True)
    assert window.operations_table.rowCount() > 0
    window.set_placement("WO-401-10", None)
    window.day_filter.setText("2026-10-05")
    window.refresh_daily()
    assert any(window.daily_table.item(row, 1).text() == "Unscheduled / 미배치" for row in range(window.daily_table.rowCount()))
    window.day_filter.setText("bad date")
    window.refresh_daily()
    assert window.daily_error.text()
    assert window.daily_table.rowCount() == 0


def test_calendar_default_failure_reports_error_in_dialog(window):
    project = deepcopy(window.project)
    project.horizon_end = project.horizon_start - 1
    dialog = CalendarDialog(project, Resource("M", [Window(1, 2)]), window)
    before = dialog.editor.toPlainText()
    dialog._defaults()
    assert dialog.error.text()
    assert dialog.editor.toPlainText() == before
