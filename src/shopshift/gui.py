"""Native, offline scheduling workbench.

The widgets deliberately call the same import, storage and validation APIs as the
headless application. No widget owns a second scheduling or persistence model.
"""
from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPalette, QPen, QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .model import Operation, Placement, Project, Resource, Scenario, Window
from .timeutil import day_bounds, format_timestamp, parse_timestamp, working_windows
from .validator import validate

TEXT = {
    "new": ("New", "새 프로젝트"), "demo": ("Open demo", "예제 열기"),
    "open": ("Open…", "열기…"), "save": ("Save", "저장"),
    "save_as": ("Save as…", "다른 이름으로 저장…"), "import": ("Import ERP export…", "ERP 파일 가져오기…"),
    "undo": ("Undo", "실행 취소"), "backup": ("Create backup…", "백업 만들기…"),
    "restore": ("Restore backup…", "백업 복원…"), "settings": ("Project & dates…", "프로젝트 및 날짜…"),
    "schedule": ("Schedule", "일정"), "resources": ("Resources & calendars", "자원 및 근무 시간"),
    "scenarios": ("Scenarios", "시나리오"), "daily": ("Daily work lists", "일일 작업 목록"),
    "suggest": ("Suggest schedule…", "일정 제안…"), "edit": ("Edit start / lock…", "시작 시간 / 고정 편집…"),
    "lock": ("Toggle lock", "고정 전환"), "unschedule": ("Clear placement", "배치 해제"),
    "retire": ("Retire operation…", "완료 공정 제거…"),
    "late": ("Late jobs only", "지연 작업만"), "add_resource": ("Add resource…", "자원 추가…"),
    "edit_calendar": ("Edit calendar…", "근무 시간 편집…"), "remove_resource": ("Remove resource", "자원 삭제"),
    "copy": ("Copy current scenario…", "현재 시나리오 복사…"),
    "csv": ("Export CSV…", "CSV 내보내기…"), "html": ("Export printable HTML…", "인쇄용 HTML 내보내기…"),
    "print": ("Print…", "인쇄…"), "refresh": ("Update list", "목록 갱신"),
    "search": ("Filter by job, operation or machine", "작업, 공정 또는 기계 검색"),
    "inspect": ("Select a conflict to inspect its operation. Unscheduled work is never hidden.",
                "충돌을 선택하면 해당 공정으로 이동합니다. 미배치 작업도 표시됩니다."),
    "timeline_help": ("Drag an unlocked bar to change its start (1-minute steps). Double-click or press Enter to edit exactly. Ctrl/Cmd+Z undoes a change.",
                      "고정되지 않은 막대를 끌어 시작 시간을 1분 단위로 변경합니다. 더블클릭 또는 Enter로 정확히 편집합니다. Ctrl/Cmd+Z로 취소합니다."),
}


def _label(text: str, style: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if style:
        label.setStyleSheet(style)
    return label


def _table(headers: list[str], name: str) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setObjectName(name)
    table.setAccessibleName(name)
    table.setHorizontalHeaderLabels(headers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().hide()
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def _put_row(table: QTableWidget, row: int, values: list[str], key: str = "") -> None:
    table.insertRow(row)
    for column, value in enumerate(values):
        item = QTableWidgetItem(str(value))
        item.setToolTip(str(value))
        if column == 0:
            item.setData(Qt.ItemDataRole.UserRole, key)
        table.setItem(row, column, item)


def _duration(seconds: int) -> str:
    return f"{seconds / 60:g} min"


def _time(value: int | None, project: Project) -> str:
    if value is None:
        return "—"
    try:
        return format_timestamp(value, project.timezone)
    except (ValueError, OverflowError, OSError, KeyError):
        return str(value)


def _issues_text(issues) -> str:
    return "\n".join(f"{issue.severity.upper()} · {issue.code}: {issue.message}" for issue in issues)


def _configure_appearance() -> None:
    """Keep the app's authored light timeline and text legible in every OS theme."""
    app = QApplication.instance()
    app.setStyle("Fusion")
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#f7f9fb", QPalette.ColorRole.WindowText: "#172b3a",
        QPalette.ColorRole.Base: "#ffffff", QPalette.ColorRole.AlternateBase: "#f0f4f7",
        QPalette.ColorRole.Text: "#172b3a", QPalette.ColorRole.Button: "#e8edf2",
        QPalette.ColorRole.ButtonText: "#172b3a", QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.ToolTipBase: "#ffffdc", QPalette.ColorRole.ToolTipText: "#172b3a",
        QPalette.ColorRole.Highlight: "#187b80", QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.PlaceholderText: "#657586", QPalette.ColorRole.Link: "#12696e",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#657586"))
    app.setPalette(palette)


class MappingDialog(QDialog):
    """Explicit mapping with a bounded raw-data preview; never mutates Project."""

    FIELDS = ("id", "job", "machine", "operator", "setup", "run", "predecessors", "release", "due", "label")

    def __init__(self, project: Project, path: str | Path, parent=None):
        super().__init__(parent)
        from .importing import read_table
        self.setWindowTitle("Map ERP export columns / ERP 열 매핑")
        self.resize(950, 720)
        self.path = Path(path)
        headers, rows = read_table(path)
        saved = project.mappings.get(self.path.name, project.mappings.get("__last__"))
        outer = QVBoxLayout(self)
        outer.addWidget(_label(f"{self.path.name} · {len(rows):,} rows · {project.timezone}", "font-weight: 600; font-size: 16px;"))
        outer.addWidget(_label("Required: stable operation ID, job, machine and run time. Dates require an ISO timestamp; include an offset for repeated DST times. Optional unmapped fields keep existing values. / 필수: 공정 ID, 작업, 기계, 실행 시간. 날짜는 ISO 형식입니다."))
        fields = QWidget()
        form = QFormLayout(fields)
        self.combos: dict[str, QComboBox] = {}
        normalized = {h.casefold().replace(" ", "_"): h for h in headers}
        aliases = {
            "id": ("id", "operation_id", "op_id"), "job": ("job", "job_id", "work_order"),
            "machine": ("machine", "machine_id", "work_center"), "operator": ("operator", "operator_id"),
            "run": ("run", "run_minutes", "run_time", "duration"), "setup": ("setup", "setup_minutes", "setup_time"),
            "predecessors": ("predecessors", "depends_on"), "release": ("release", "release_date"),
            "due": ("due", "due_date"), "label": ("label", "description"),
        }
        for field in self.FIELDS:
            combo = QComboBox()
            combo.setObjectName(f"mapping_{field}")
            combo.addItem("— Not mapped / 매핑 없음 —", "")
            for header in headers:
                combo.addItem(header, header)
            # An omitted field in a saved mapping is an intentional decision to
            # retain its existing values. Never auto-map it on repeat imports.
            # Missing saved headers also require an explicit replacement.
            selected = (saved.get(field, "") if saved is not None
                        else next((normalized[a] for a in aliases[field] if a in normalized), ""))
            combo.setCurrentIndex(max(0, combo.findData(selected)))
            required = " *" if field in ("id", "job", "machine", "run") else ""
            form.addRow(field + required, combo)
            self.combos[field] = combo
        self.unit = QComboBox()
        self.unit.setObjectName("durationUnit")
        self.unit.addItems(["seconds", "minutes", "hours"])
        self.unit.setCurrentText((saved or {}).get("__duration_unit", "minutes"))
        form.addRow("Setup & run units / 시간 단위", self.unit)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(fields)
        outer.addWidget(scroll, 2)
        preview = _table(headers, "importPreview")
        for i, row in enumerate(rows[:12]):
            _put_row(preview, i, [row.get(header, "") for header in headers])
        outer.addWidget(_label("Source preview · first 12 rows / 원본 미리보기"))
        outer.addWidget(preview, 1)
        self.error = _label("", "color:#a33a2a;")
        outer.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Review import / 가져오기 검토")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    @property
    def mapping(self) -> dict[str, str]:
        return {field: combo.currentData() for field, combo in self.combos.items() if combo.currentData()}

    def _accept(self):
        missing = [key for key in ("id", "job", "machine", "run") if key not in self.mapping]
        if missing:
            self.error.setText("Map required columns: " + ", ".join(missing))
            return
        mapped = list(self.mapping.values())
        if len(mapped) != len(set(mapped)):
            self.error.setText("Each source column can be assigned once. / 원본 열을 중복 지정할 수 없습니다.")
            return
        self.accept()


class ReviewDialog(QDialog):
    def __init__(self, title: str, summary: str, details: str, parent=None, can_apply: bool = True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 540)
        layout = QVBoxLayout(self)
        layout.addWidget(_label(summary, "font-size:16px;font-weight:600;"))
        body = QPlainTextEdit(details)
        body.setReadOnly(True)
        body.setObjectName("reviewDetails")
        body.setAccessibleName("Changes and validation details")
        layout.addWidget(body)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        apply = buttons.button(QDialogButtonBox.StandardButton.Apply)
        apply.setText("Apply / 적용")
        apply.setEnabled(can_apply)
        apply.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class PlacementDialog(QDialog):
    def __init__(self, project: Project, operation_id: str, parent=None):
        super().__init__(parent)
        self.project = project
        self.operation_id = operation_id
        self.result_placement: Placement | None = None
        op = project.operations[operation_id]
        placement = project.scenario.placements.get(operation_id)
        self.setWindowTitle(f"Edit {operation_id} / 공정 편집")
        self.resize(630, 300)
        layout = QVBoxLayout(self)
        layout.addWidget(_label(f"{op.job} · {op.machine} · {_duration(op.duration)}", "font-weight:600;"))
        details = _label(f"Description / 설명: {op.label or '—'}\n"
                         f"Operator / 작업자: {op.operator or '—'}\n"
                         f"Predecessors / 선행 공정: {'; '.join(op.predecessors) or '—'}\n"
                         f"Release / 작업 가능 시각: {_time(op.release, project)}\n"
                         f"Due / 납기: {_time(op.due, project)}")
        details.setObjectName("operationDetails")
        details.setAccessibleName("Imported operation details / 가져온 공정 정보")
        details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                       | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        layout.addWidget(details)
        layout.addWidget(_label(f"Display zone: {project.timezone}. ISO timestamp with offset is safest. Leave start empty to clear placement. / 시작 시간이 없으면 배치를 해제합니다."))
        form = QFormLayout()
        self.start = QLineEdit(_time(placement.start, project) if placement else "")
        self.start.setObjectName("placementStart")
        self.start.setPlaceholderText("2026-10-08T08:00:00+09:00")
        form.addRow("Start / 시작", self.start)
        self.locked = QCheckBox("Keep this placement fixed during suggestions / 일정 제안 시 고정")
        self.locked.setObjectName("placementLocked")
        self.locked.setChecked(placement.locked if placement else False)
        form.addRow("Lock / 고정", self.locked)
        layout.addLayout(form)
        self.error = _label("", "color:#a33a2a;")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        value = self.start.text().strip()
        if not value:
            if self.locked.isChecked():
                self.error.setText("A locked operation needs a start time. / 고정하려면 시작 시간이 필요합니다.")
                return
            self.result_placement = None
        else:
            try:
                self.result_placement = Placement(parse_timestamp(value, self.project.timezone), self.locked.isChecked())
            except (ValueError, TypeError, OverflowError) as exc:
                self.error.setText(str(exc))
                return
        self.accept()


class CalendarDialog(QDialog):
    def __init__(self, project: Project, resource: Resource, parent=None):
        super().__init__(parent)
        self.project = project
        self.resource = resource
        self.windows: list[Window] = []
        self.setWindowTitle(f"Calendar · {resource.id}")
        self.resize(790, 570)
        layout = QVBoxLayout(self)
        layout.addWidget(_label(f"{resource.id} · {project.timezone}", "font-size:17px;font-weight:600;"))
        layout.addWidget(_label("One available interval per line: START / END. Use ISO dates with offsets for DST ambiguity. Gaps mean unavailable; work must fit entirely inside a window. Overnight windows are supported. / 한 줄에 시작 / 종료를 입력합니다. 빈 구간은 작업 불가 시간입니다."))
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("calendarWindows")
        self.editor.setAccessibleName("Available resource windows, one start slash end per line")
        self.editor.setPlainText("\n".join(f"{_time(w.start, project)} / {_time(w.end, project)}" for w in resource.windows))
        layout.addWidget(self.editor)
        default = QPushButton("Replace with weekdays 08–12 / 13–17 / 평일 기본 근무")
        default.clicked.connect(self._defaults)
        layout.addWidget(default)
        self.error = _label("", "color:#a33a2a;")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _defaults(self):
        try:
            windows = working_windows(self.project.horizon_start, self.project.horizon_end, self.project.timezone)
            self.editor.setPlainText("\n".join(f"{_time(w.start, self.project)} / {_time(w.end, self.project)}" for w in windows))
            self.error.clear()
        except (ValueError, OverflowError, OSError, KeyError) as exc:
            self.error.setText(str(exc))

    def _accept(self):
        windows = []
        try:
            for number, line in enumerate(self.editor.toPlainText().splitlines(), 1):
                if not line.strip():
                    continue
                parts = line.split("/")
                if len(parts) != 2:
                    raise ValueError(f"Line {number}: enter START / END.")
                start, end = (parse_timestamp(part.strip(), self.project.timezone) for part in parts)
                if end <= start:
                    raise ValueError(f"Line {number}: end must be after start.")
                windows.append(Window(start, end))
            windows.sort(key=lambda item: item.start)
            if any(a.end > b.start for a, b in zip(windows, windows[1:])):
                raise ValueError("Available windows overlap. Merge or separate them.")
        except (ValueError, TypeError, OverflowError) as exc:
            self.error.setText(str(exc))
            return
        self.windows = windows
        self.accept()


class ProjectDialog(QDialog):
    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project
        self.values = None
        self.setWindowTitle("Project & horizon / 프로젝트 및 계획 기간")
        self.resize(610, 300)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(project.name)
        self.zone = QLineEdit(project.timezone)
        self.begin = QLineEdit(_time(project.horizon_start, project))
        self.end = QLineEdit(_time(project.horizon_end, project))
        for label, widget in (("Name / 이름", self.name), ("IANA timezone / 시간대", self.zone),
                              ("Horizon start / 기간 시작", self.begin), ("Horizon end / 기간 종료", self.end)):
            form.addRow(label, widget)
        layout.addLayout(form)
        layout.addWidget(_label("Changing the horizon or display zone keeps all existing timestamps and calendars. Review any conflicts afterward. / 기존 일정과 자원 근무 시간은 유지됩니다."))
        self.error = _label("", "color:#a33a2a;")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        try:
            zone = self.zone.text().strip()
            ZoneInfo(zone)
            start, end = parse_timestamp(self.begin.text(), zone), parse_timestamp(self.end.text(), zone)
            if end <= start:
                raise ValueError("Horizon end must be after its start.")
            if not self.name.text().strip():
                raise ValueError("Give the project a name.")
            self.values = (self.name.text().strip(), zone, start, end)
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class _OperationBar(QGraphicsRectItem):
    def __init__(self, timeline: "TimelineView", operation: Operation, placement: Placement, row: int, invalid: bool):
        width = max(7.0, operation.duration * timeline.scale_seconds)
        super().__init__(0, 0, width, 28)
        self.timeline = timeline
        self.operation_id = operation.id
        self.old_start = placement.start
        self.locked = placement.locked
        self.row_y = timeline.top + row * timeline.row_height + 12
        self.setPos(timeline.left + (placement.start - timeline.origin) * timeline.scale_seconds, self.row_y)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, not self.locked)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.CursorShape.ArrowCursor if self.locked else Qt.CursorShape.OpenHandCursor)
        self.setBrush(QColor("#aa443c" if invalid else "#506078" if self.locked else "#187b80"))
        self.setPen(QPen(QColor("#ffffff"), 1))
        self.setToolTip(f"{operation.id} · {operation.job}\n{_time(placement.start, timeline.project)}\n{_duration(operation.duration)}{' · LOCKED' if self.locked else ''}\nDouble-click / Enter to edit")
        self.label = QGraphicsSimpleTextItem(("🔒 " if self.locked else "") + operation.id, self)
        self.label.setBrush(QColor("white"))
        self.label.setPos(5, 5)
        self.label.setVisible(width > 45)
        self.label.setFlag(QGraphicsSimpleTextItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemClipsChildrenToShape, True)

    def itemChange(self, change, value):
        if change == QGraphicsRectItem.GraphicsItemChange.ItemPositionChange and self.scene():
            return QPointF(value.x(), self.row_y)
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.locked:
            return
        original_x = self.timeline.left + (self.old_start - self.timeline.origin) * self.timeline.scale_seconds
        delta = round((self.x() - original_x) / self.timeline.scale_seconds / 60) * 60
        start = self.old_start + delta
        if start != self.old_start:
            self.timeline.moved.emit(self.operation_id, start)
        else:
            self.setPos(original_x, self.row_y)

    def mouseDoubleClickEvent(self, event):
        self.timeline.edit_requested.emit(self.operation_id)
        event.accept()


class TimelineView(QGraphicsView):
    # Qt's `int` signal type is signed 32-bit. Python integers preserve UTC
    # timestamps outside 1901–2038 throughout the model's supported range.
    moved = Signal(str, object)
    edit_requested = Signal(str)
    operation_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("scheduleTimeline")
        self.setAccessibleName("Machine schedule timeline. Use the operations table for keyboard editing.")
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMinimumHeight(240)
        self.left, self.top, self.row_height = 150, 52, 53
        self.scale_seconds = 1 / 180
        self.zoom_mode = "overview"
        self.origin = 0
        self.project = None
        self.bars: dict[str, _OperationBar] = {}
        self.scene().selectionChanged.connect(self._selection)

    def _selection(self):
        for item in self.scene().selectedItems():
            if isinstance(item, _OperationBar):
                self.operation_selected.emit(item.operation_id)
                break

    def set_project(self, project: Project, visible_ids: set[str] | None = None, issues=()):
        self.project = project
        self.scene().blockSignals(True)
        self.scene().clear()
        self.bars = {}
        self.origin = project.horizon_start
        span = max(3600, project.horizon_end - project.horizon_start)
        # One day remains useful at a glance; long horizons scroll instead of
        # drawing millions of unbounded tick marks.
        self.scale_seconds = {"day": 48 / 3600, "hour": 180 / 3600}.get(
            self.zoom_mode, max(1 / 1200, min(1 / 45, 1350 / span)))
        width = max(900, span * self.scale_seconds)
        machines = sorted(set(project.machines) | {op.machine for op in project.operations.values()})
        invalid = {op_id for issue in issues if issue.severity == "error" for op_id in issue.operation_ids}
        for row, machine in enumerate(machines):
            y = self.top + row * self.row_height
            self.scene().addRect(self.left, y, width, self.row_height, QPen(QColor("#dbe2e5")), QColor("#f0f3f5"))
            text = self.scene().addText(machine)
            text.setDefaultTextColor(QColor("#273b4a"))
            text.setPos(8, y + 14)
            resource = project.machines.get(machine)
            for window in resource.windows if resource else []:
                start, end = max(window.start, self.origin), min(window.end, project.horizon_end)
                if end > start:
                    self.scene().addRect(self.left + (start - self.origin) * self.scale_seconds, y + 1,
                                         (end - start) * self.scale_seconds, self.row_height - 2,
                                         QPen(Qt.PenStyle.NoPen), QColor("#ffffff"))
        tick = 3600 if self.zoom_mode in ("day", "hour") or span <= 36 * 3600 else 86400
        tick = max(tick, math.ceil(span / 100) // 3600 * 3600)
        timestamp = self.origin
        while timestamp <= project.horizon_end:
            x = self.left + (timestamp - self.origin) * self.scale_seconds
            self.scene().addLine(x, self.top - 4, x, self.top + len(machines) * self.row_height, QPen(QColor("#d9e3e8")))
            try:
                label = datetime.fromtimestamp(timestamp, ZoneInfo(project.timezone)).strftime("%m-%d\n%H:%M")
            except (ValueError, OverflowError, OSError, KeyError):
                label = str(timestamp)
            text = self.scene().addText(label)
            text.setDefaultTextColor(QColor("#526577"))
            text.setPos(x + 3, 4)
            timestamp += tick
        rows = {machine: row for row, machine in enumerate(machines)}
        for op_id, placement in project.scenario.placements.items():
            op = project.operations.get(op_id)
            if op is None or (visible_ids is not None and op_id not in visible_ids):
                continue
            bar = _OperationBar(self, op, placement, rows[op.machine], op_id in invalid)
            self.scene().addItem(bar)
            self.bars[op_id] = bar
        if not machines:
            self.scene().addText("Import an ERP export or open the demo to begin. / ERP 파일을 가져오거나 예제를 여세요.").setPos(25, 90)
        self.scene().setSceneRect(QRectF(0, 0, self.left + width + 60, max(180, self.top + len(machines) * self.row_height)))
        self.scene().blockSignals(False)

    def select_operation(self, op_id: str):
        self.scene().blockSignals(True)
        self.scene().clearSelection()
        if op_id in self.bars:
            self.bars[op_id].setSelected(True)
            self.ensureVisible(self.bars[op_id])
        self.scene().blockSignals(False)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            selected = [item for item in self.scene().selectedItems() if isinstance(item, _OperationBar)]
            if selected:
                self.edit_requested.emit(selected[0].operation_id)
                return
        super().keyPressEvent(event)


class _SolverWorker(QObject):
    result = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, project: Project, time_limit: float):
        super().__init__()
        self.project, self.time_limit = project, time_limit

    def run(self):
        try:
            from .solver import suggest
            self.result.emit(suggest(self.project, time_limit=self.time_limit))
        except Exception as exc:  # noqa: BLE001 - report numerical engine failures at the UI boundary.
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    """Single planner editor. Changes are snapshots, allowing one-step undo."""

    schedule_ready = Signal(object)

    def __init__(self, project: Project | None = None):
        super().__init__()
        _configure_appearance()
        self.project = project or self.blank_project()
        self.path: Path | None = None
        self.dirty = False
        self.language = "en"
        self.undo_stack: list[tuple[Project, str]] = []
        self._translations = []
        self._refreshing = False
        self._solver_thread: QThread | None = None
        self._solver_worker = None
        self.last_solve_result = None
        self.resize(1320, 920)
        self.setMinimumSize(850, 620)
        self.setObjectName("shopshiftMainWindow")
        self.setStyleSheet("QToolBar{spacing:7px;padding:7px;} QTableWidget{gridline-color:#dde3e7;} QHeaderView::section{padding:7px;font-weight:600;} QTabWidget::pane{border:1px solid #d6dfe3;} QPushButton{padding:6px 10px;} QLineEdit,QComboBox{padding:5px;} QStatusBar{padding:3px;}")
        self.actions = {}
        self._build_actions()
        self._build_main()
        self.refresh()

    @staticmethod
    def blank_project() -> Project:
        now = datetime.now(ZoneInfo("UTC")).replace(hour=0, minute=0, second=0, microsecond=0)
        return Project(name="Untitled shop", timezone="UTC", horizon_start=int(now.timestamp()),
                       horizon_end=int((now + timedelta(days=14)).timestamp()))

    def _tr(self, key: str) -> str:
        return TEXT[key][self.language == "ko"]

    def _button(self, key: str, callback, name: str = "") -> QPushButton:
        button = QPushButton(self._tr(key))
        button.setObjectName(name or key + "Button")
        button.setAccessibleName(button.text())
        button.clicked.connect(callback)
        self._translations.append((button, key))
        return button

    def _build_actions(self):
        toolbar = QToolBar("Project actions")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        file_menu = self.menuBar().addMenu("File / 파일")
        edit_menu = self.menuBar().addMenu("Edit / 편집")
        definitions = [
            ("new", self.new_project, QKeySequence.StandardKey.New),
            ("demo", self.load_demo, None), ("open", self.open_project, QKeySequence.StandardKey.Open),
            ("save", self.save, QKeySequence.StandardKey.Save),
            ("save_as", self.save_as, QKeySequence.StandardKey.SaveAs),
            ("import", self.import_dialog, "Ctrl+I"), ("backup", self.backup, None),
            ("restore", self.restore, None), ("undo", self.undo, QKeySequence.StandardKey.Undo),
            ("settings", self.edit_project, None),
        ]
        for key, callback, shortcut in definitions:
            action = QAction(self._tr(key), self)
            action.setObjectName(key + "Action")
            action.triggered.connect(callback)
            if shortcut:
                action.setShortcut(shortcut)
            (edit_menu if key in ("undo", "settings") else file_menu).addAction(action)
            if key in ("new", "demo", "open", "save", "import", "undo"):
                toolbar.addAction(action)
            self._translations.append((action, key))
            self.actions[key] = action
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().Policy.Expanding, spacer.sizePolicy().Policy.Preferred)
        toolbar.addWidget(spacer)
        self.language_box = QComboBox()
        self.language_box.setObjectName("languageSelector")
        self.language_box.setMinimumWidth(110)
        self.language_box.setAccessibleName("Interface language / 인터페이스 언어")
        self.language_box.addItem("English", "en")
        self.language_box.addItem("한국어", "ko")
        self.language_box.currentIndexChanged.connect(self._language_changed)
        toolbar.addWidget(self.language_box)
        help_menu = self.menuBar().addMenu("Help / 도움말")
        about_action = QAction("About & licenses / 정보 및 라이선스", self)
        about_action.triggered.connect(self.about)
        help_menu.addAction(about_action)

    def _build_main(self):
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 12, 16, 12)
        header = QHBoxLayout()
        self.title_label = _label("", "font-size:24px;font-weight:700;color:#174952;")
        header.addWidget(self.title_label, 1)
        self.project_settings_button = self._button("settings", self.edit_project)
        header.addWidget(self.project_settings_button)
        layout.addLayout(header)
        self.subtitle = _label("", "color:#526575;")
        layout.addWidget(self.subtitle)
        self.metrics = _label("", "font-size:14px;font-weight:600;padding:10px;background:#e8f2f1;color:#174952;border-radius:5px;")
        self.metrics.setObjectName("scheduleMetrics")
        layout.addWidget(self.metrics)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("workbenchTabs")
        layout.addWidget(self.tabs, 1)
        self._build_schedule()
        self._build_resources()
        self._build_scenarios()
        self._build_daily()
        self.setCentralWidget(central)
        self.statusBar().showMessage("Local project · no network · review before committing to production / 오프라인 단일 계획자")

    def _build_schedule(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        top = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setObjectName("operationFilter")
        self.filter.setPlaceholderText(self._tr("search"))
        self.filter.setAccessibleName(self._tr("search"))
        self.filter.textChanged.connect(self.refresh_schedule)
        top.addWidget(self.filter, 1)
        self.late_only = QCheckBox(self._tr("late"))
        self.late_only.setObjectName("lateOnly")
        self.late_only.toggled.connect(self.refresh_schedule)
        self._translations.append((self.late_only, "late"))
        top.addWidget(self.late_only)
        self.scenario_selector = QComboBox()
        self.scenario_selector.setObjectName("activeScenario")
        self.scenario_selector.setAccessibleName("Active scenario / 현재 시나리오")
        self.scenario_selector.currentTextChanged.connect(self.switch_scenario)
        top.addWidget(self.scenario_selector)
        self.suggest_button = self._button("suggest", self.start_suggest)
        top.addWidget(self.suggest_button)
        layout.addLayout(top)
        buttons = QHBoxLayout()
        for key, callback in (("edit", self.edit_selected), ("lock", self.toggle_selected_lock),
                              ("unschedule", self.clear_selected), ("retire", self.retire_selected)):
            buttons.addWidget(self._button(key, callback))
        buttons.addStretch()
        layout.addLayout(buttons)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.operations_table = _table(["Operation", "Job", "Machine", "Operator", "Start", "End", "Setup + run", "Due", "State"], "operationsTable")
        self.operations_table.itemSelectionChanged.connect(self._table_selection)
        self.operations_table.itemActivated.connect(self.edit_selected)
        self.operations_table.installEventFilter(self)
        splitter.addWidget(self.operations_table)
        timeline_widget = QWidget()
        timeline_layout = QVBoxLayout(timeline_widget)
        timeline_layout.setContentsMargins(0, 0, 0, 0)
        self.timeline_help = _label(self._tr("timeline_help"), "color:#526575;font-size:11px;")
        self._translations.append((self.timeline_help, "timeline_help"))
        timeline_layout.addWidget(self.timeline_help)
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(QLabel("Timeline scale / 시간 축"))
        self.timeline_zoom = QComboBox()
        self.timeline_zoom.setObjectName("timelineZoom")
        self.timeline_zoom.setAccessibleName("Timeline zoom level / 시간 축 확대 수준")
        self.timeline_zoom.addItem("Overview / 전체", "overview")
        self.timeline_zoom.addItem("Day detail / 일별", "day")
        self.timeline_zoom.addItem("Hour detail / 시간별", "hour")
        self.timeline_zoom.currentIndexChanged.connect(self._zoom_changed)
        zoom_row.addWidget(self.timeline_zoom)
        zoom_row.addStretch()
        timeline_layout.addLayout(zoom_row)
        self.timeline = TimelineView()
        self.timeline.moved.connect(self.move_operation, Qt.ConnectionType.QueuedConnection)
        self.timeline.edit_requested.connect(self.edit_operation)
        self.timeline.operation_selected.connect(self.select_operation)
        timeline_layout.addWidget(self.timeline)
        splitter.addWidget(timeline_widget)
        issue_widget = QWidget()
        issue_layout = QVBoxLayout(issue_widget)
        issue_layout.setContentsMargins(0, 0, 0, 0)
        self.issue_heading = _label("")
        issue_layout.addWidget(self.issue_heading)
        self.issues_list = QListWidget()
        self.issues_list.setObjectName("conflictList")
        self.issues_list.setAccessibleName("Schedule conflicts and warnings / 일정 충돌과 경고")
        self.issues_list.itemClicked.connect(self._issue_selected)
        self.issues_list.itemActivated.connect(self._issue_selected)
        issue_layout.addWidget(self.issues_list)
        splitter.addWidget(issue_widget)
        splitter.setSizes([270, 340, 150])
        layout.addWidget(splitter)
        self.tabs.addTab(page, self._tr("schedule"))

    def _zoom_changed(self):
        self.timeline.zoom_mode = self.timeline_zoom.currentData()
        self.refresh_schedule()

    def _build_resources(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_label("Each operation occupies its assigned machine and optional operator for the entire setup + run duration. Calendar gaps (including lunch) are unavailable. Review default calendars after import. / 공정은 준비 및 실행 시간 동안 기계와 작업자를 점유합니다. 가져오기 후 기본 근무 시간을 확인하세요."))
        buttons = QHBoxLayout()
        for key, callback in (("add_resource", self.add_resource), ("edit_calendar", self.edit_calendar), ("remove_resource", self.remove_resource)):
            buttons.addWidget(self._button(key, callback))
        buttons.addStretch()
        layout.addLayout(buttons)
        self.resources_table = _table(["Type", "Resource", "Available windows", "Available hours", "First start", "Last end"], "resourcesTable")
        self.resources_table.itemActivated.connect(self.edit_calendar)
        self.resources_table.installEventFilter(self)
        layout.addWidget(self.resources_table)
        self.tabs.addTab(page, self._tr("resources"))

    def _build_scenarios(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_label("Scenarios share operation definitions and resource calendars. Placements and locks are independent. ERP reimports update every scenario by stable operation ID. / 시나리오는 공정과 자원을 공유하며 배치와 고정은 별도로 유지됩니다."))
        buttons = QHBoxLayout()
        buttons.addWidget(self._button("copy", self.copy_scenario_dialog))
        buttons.addStretch()
        buttons.addWidget(QLabel("Compare current with / 비교 대상"))
        self.compare_selector = QComboBox()
        self.compare_selector.setObjectName("compareScenario")
        self.compare_selector.setAccessibleName("Scenario to compare against")
        self.compare_selector.currentTextChanged.connect(self.refresh_compare)
        buttons.addWidget(self.compare_selector)
        layout.addLayout(buttons)
        self.compare_summary = _label("")
        layout.addWidget(self.compare_summary)
        self.compare_table = _table(["Operation", "Job", "Comparison start", "Current start", "Shift", "Current lateness", "Lock change"], "scenarioComparison")
        layout.addWidget(self.compare_table)
        self.tabs.addTab(page, self._tr("scenarios"))

    def _build_daily(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_label("Read-only dispatch snapshot for review. Exported files include validation warnings. Confirm the plan before giving production instructions. / 검토용 읽기 전용 작업 목록입니다. 내보낸 파일에도 검증 경고가 포함됩니다."))
        buttons = QHBoxLayout()
        buttons.addWidget(QLabel("Local day / 현지 날짜"))
        self.day_filter = QLineEdit()
        self.day_filter.setObjectName("dailyDate")
        self.day_filter.setPlaceholderText("YYYY-MM-DD · empty = all / 비우면 전체")
        self.day_filter.setAccessibleName("Local date for daily work list, empty for all dates")
        self.day_filter.returnPressed.connect(self.refresh_daily)
        buttons.addWidget(self.day_filter, 1)
        for key, callback in (("refresh", self.refresh_daily), ("csv", self.export_csv_dialog), ("html", self.export_html_dialog), ("print", self.print_plan)):
            buttons.addWidget(self._button(key, callback))
        layout.addLayout(buttons)
        self.daily_error = _label("", "color:#a33a2a;")
        layout.addWidget(self.daily_error)
        self.daily_table = _table(["Machine", "Start", "End", "Job", "Operation", "Operator", "Lock", "Due"], "dailyWorkList")
        layout.addWidget(self.daily_table)
        self.tabs.addTab(page, self._tr("daily"))

    def _language_changed(self):
        self.language = self.language_box.currentData()
        for widget, key in self._translations:
            widget.setText(self._tr(key))
            if isinstance(widget, QWidget):
                widget.setAccessibleName(self._tr(key))
        for i, key in enumerate(("schedule", "resources", "scenarios", "daily")):
            self.tabs.setTabText(i, self._tr(key))
        self.filter.setPlaceholderText(self._tr("search"))
        if self.language == "ko":
            self.operations_table.setHorizontalHeaderLabels(["공정", "작업", "기계", "작업자", "시작", "종료", "준비 + 실행", "납기", "상태"])
            self.resources_table.setHorizontalHeaderLabels(["유형", "자원", "근무 구간", "가용 시간", "첫 시작", "마지막 종료"])
            self.daily_table.setHorizontalHeaderLabels(["기계", "시작", "종료", "작업", "공정", "작업자", "고정", "납기"])
        else:
            self.operations_table.setHorizontalHeaderLabels(["Operation", "Job", "Machine", "Operator", "Start", "End", "Setup + run", "Due", "State"])
            self.resources_table.setHorizontalHeaderLabels(["Type", "Resource", "Available windows", "Available hours", "First start", "Last end"])
            self.daily_table.setHorizontalHeaderLabels(["Machine", "Start", "End", "Job", "Operation", "Operator", "Lock", "Due"])
        self.refresh()

    def eventFilter(self, watched, event):
        # Native table activation keys differ by platform. Provide one explicit
        # Return/Enter path and consume it so it cannot open a second dialog.
        tables = (getattr(self, "operations_table", None), getattr(self, "resources_table", None))
        if watched in tables and event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            item = watched.currentItem()
            if item is not None:
                watched.itemActivated.emit(item)
            return True
        return super().eventFilter(watched, event)

    def set_project(self, project: Project, path: str | Path | None = None):
        self.project = deepcopy(project)
        self.path = Path(path) if path else None
        self.undo_stack.clear()
        self.dirty = False
        self.filter.clear()
        self.late_only.setChecked(False)
        self.day_filter.clear()
        self.refresh()

    def apply_project(self, project: Project, description: str):
        self.undo_stack.append((deepcopy(self.project), description))
        self.undo_stack = self.undo_stack[-50:]
        self.project = deepcopy(project)
        self.dirty = True
        self.refresh()
        self.statusBar().showMessage(description + " · Undo available / 실행 취소 가능", 8000)

    def undo(self):
        if self._solver_thread is not None:
            return
        if self.undo_stack:
            self.project, description = self.undo_stack.pop()
            self.dirty = True
            self.refresh()
            self.statusBar().showMessage("Undid: " + description, 7000)

    def refresh(self):
        self._refreshing = True
        self.setWindowTitle(f"{'● ' if self.dirty else ''}{self.project.name} — ShopShift")
        self.title_label.setText(self.project.name)
        self.subtitle.setText(f"{self.project.timezone}  ·  {_time(self.project.horizon_start, self.project)} → {_time(self.project.horizon_end, self.project)}  ·  {str(self.path) if self.path else 'Not saved / 저장되지 않음'}")
        self.actions["undo"].setEnabled(bool(self.undo_stack) and self._solver_thread is None)
        comparison = self.compare_selector.currentText()
        for box in (self.scenario_selector, self.compare_selector):
            box.blockSignals(True)
            box.clear()
            box.addItems(list(self.project.scenarios))
            box.blockSignals(False)
        self.scenario_selector.setCurrentText(self.project.active_scenario)
        self.compare_selector.setCurrentText(comparison if comparison in self.project.scenarios else next(iter(self.project.scenarios)))
        self._refreshing = False
        self.current_issues = validate(self.project)
        self.refresh_schedule()
        self.refresh_resources()
        self.refresh_compare()
        self.refresh_daily()

    def refresh_schedule(self, *_):
        if self._refreshing:
            return
        selected = self.selected_operation()
        operations = self.project.operations
        placements = self.project.scenario.placements
        query = self.filter.text().casefold().strip()
        errors = [issue for issue in self.current_issues if issue.severity == "error"]
        late_operations = {op_id for op_id, p in placements.items() if op_id in operations
                           and operations[op_id].due is not None
                           and p.start + operations[op_id].duration > operations[op_id].due}
        late_jobs = {operations[op_id].job for op_id in late_operations}
        late_count = len(late_operations)
        locked_count = sum(p.locked for p in placements.values())
        if self.language == "ko":
            self.metrics.setText(f"공정 {len(operations)}  ·  배치 {len(placements)}  ·  미배치 {len(set(operations) - set(placements))}  ·  지연 작업 {len(late_jobs)} (공정 {late_count})  ·  고정 {locked_count}  ·  오류 {len(errors)}")
        else:
            self.metrics.setText(f"{len(operations)} operations  ·  {len(placements)} placed  ·  {len(set(operations) - set(placements))} unscheduled  ·  {len(late_jobs)} late jobs ({late_count} operations)  ·  {locked_count} locked  ·  {len(errors)} conflicts")
        self.operations_table.blockSignals(True)
        self.operations_table.setRowCount(0)
        visible = set()
        for op in operations.values():
            placement = placements.get(op.id)
            late = placement is not None and op.due is not None and placement.start + op.duration > op.due
            if query and query not in " ".join((op.id, op.job, op.machine, op.operator, op.label)).casefold():
                continue
            if self.late_only.isChecked() and op.job not in late_jobs:
                continue
            visible.add(op.id)
            state = ("지연" if self.language == "ko" else "Late") if late else ("배치" if self.language == "ko" else "Placed") if placement else ("미배치" if self.language == "ko" else "Unscheduled")
            if placement and placement.locked:
                state += " · " + ("고정" if self.language == "ko" else "Locked")
            _put_row(self.operations_table, self.operations_table.rowCount(), [op.id, op.job, op.machine, op.operator or "—",
                     _time(placement.start, self.project) if placement else "—", _time(placement.start + op.duration, self.project) if placement else "—",
                     f"{op.setup / 60:g} + {op.run / 60:g} min", _time(op.due, self.project), state], op.id)
        self.operations_table.blockSignals(False)
        self.timeline.set_project(self.project, visible, self.current_issues)
        self.issues_list.clear()
        self.issue_heading.setText(f"{'검증' if self.language == 'ko' else 'Validation'} · {len(errors)} errors · {len(self.current_issues) - len(errors)} warnings — {self._tr('inspect')}")
        if not self.current_issues:
            self.issues_list.addItem("No scheduling conflicts detected. / 일정 충돌이 발견되지 않았습니다.")
        for issue in self.current_issues:
            item = QListWidgetItem(f"{issue.severity.upper()} · {issue.code} · {issue.message}")
            item.setData(Qt.ItemDataRole.UserRole, issue.operation_ids)
            item.setToolTip(issue.message)
            if issue.severity == "error":
                item.setForeground(QColor("#a43930"))
            self.issues_list.addItem(item)
        if selected in visible:
            self.select_operation(selected)

    def refresh_resources(self):
        self.resources_table.setRowCount(0)
        for kind, resources in (("Machine", self.project.machines), ("Operator", self.project.operators)):
            for resource in resources.values():
                windows = resource.windows
                _put_row(self.resources_table, self.resources_table.rowCount(), [kind, resource.id, len(windows),
                         f"{sum(w.end - w.start for w in windows) / 3600:g}", _time(min((w.start for w in windows), default=None), self.project),
                         _time(max((w.end for w in windows), default=None), self.project)], kind + ":" + resource.id)

    def refresh_compare(self, *_):
        if self._refreshing:
            return
        name = self.compare_selector.currentText()
        if name not in self.project.scenarios:
            return
        reference = self.project.scenarios[name].placements
        current = self.project.scenario.placements
        self.compare_table.setRowCount(0)
        changed = 0
        for op in self.project.operations.values():
            a, b = reference.get(op.id), current.get(op.id)
            if (a.start if a else None, a.locked if a else False) == (b.start if b else None, b.locked if b else False):
                continue
            changed += 1
            shift = f"{(b.start - a.start) / 60:+g} min" if a and b else "Placed" if b else "Unscheduled"
            late = max(0, b.start + op.duration - op.due) if b and op.due is not None else 0
            _put_row(self.compare_table, self.compare_table.rowCount(), [op.id, op.job, _time(a.start, self.project) if a else "—",
                     _time(b.start, self.project) if b else "—", shift, _duration(late), f"{bool(a and a.locked)} → {bool(b and b.locked)}"], op.id)
        self.compare_summary.setText(f"{self.project.active_scenario} compared with {name} · {changed} changed placements / 변경된 배치 {changed}개")

    def _daily_bounds(self) -> tuple[int, int] | None:
        text = self.day_filter.text().strip()
        if not text:
            return None
        return day_bounds(text, self.project.timezone)

    def refresh_daily(self, *_):
        self.daily_table.setRowCount(0)
        try:
            bounds = self._daily_bounds()
        except (ValueError, OverflowError, OSError, KeyError) as exc:
            self.daily_error.setText(str(exc))
            return
        self.daily_error.clear()
        rows = sorted(self.project.scenario.placements.items(), key=lambda pair: (self.project.operations[pair[0]].machine if pair[0] in self.project.operations else "", pair[1].start))
        for op_id, placement in rows:
            op = self.project.operations.get(op_id)
            if not op:
                continue
            end = placement.start + op.duration
            if bounds and not (placement.start < bounds[1] and end > bounds[0]):
                continue
            _put_row(self.daily_table, self.daily_table.rowCount(), [op.machine, _time(placement.start, self.project), _time(end, self.project),
                     op.job, op.id, op.operator or "—", "Yes" if placement.locked else "", _time(op.due, self.project)], op.id)
        for op in self.project.operations.values():
            if op.id not in self.project.scenario.placements:
                _put_row(self.daily_table, self.daily_table.rowCount(), [op.machine, "Unscheduled / 미배치", "—",
                         op.job, op.id, op.operator or "—", "", _time(op.due, self.project)], op.id)

    def selected_operation(self) -> str | None:
        rows = self.operations_table.selectionModel().selectedRows()
        return self.operations_table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole) if rows else None

    def select_operation(self, op_id: str):
        for row in range(self.operations_table.rowCount()):
            if self.operations_table.item(row, 0).data(Qt.ItemDataRole.UserRole) == op_id:
                self.operations_table.blockSignals(True)
                self.operations_table.setCurrentCell(row, 0)
                self.operations_table.selectRow(row)
                self.operations_table.scrollToItem(self.operations_table.item(row, 0))
                self.operations_table.blockSignals(False)
                self.timeline.select_operation(op_id)
                return

    def _table_selection(self):
        op_id = self.selected_operation()
        if op_id:
            self.timeline.select_operation(op_id)

    def _issue_selected(self, item):
        ids = item.data(Qt.ItemDataRole.UserRole)
        if ids:
            self.filter.clear()
            self.late_only.setChecked(False)
            self.select_operation(ids[0])

    def edit_selected(self, *_):
        op_id = self.selected_operation()
        if op_id:
            self.edit_operation(op_id)
        else:
            self.statusBar().showMessage("Select an operation first. / 공정을 먼저 선택하세요.", 6000)

    def edit_operation(self, op_id: str):
        if self._solver_thread is not None or op_id not in self.project.operations:
            return
        dialog = PlacementDialog(self.project, op_id, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_placement(op_id, dialog.result_placement)

    def set_placement(self, op_id: str, placement: Placement | None):
        if op_id not in self.project.operations:
            raise ValueError(f"Unknown operation: {op_id}")
        candidate = deepcopy(self.project)
        if placement is None:
            candidate.scenario.placements.pop(op_id, None)
        else:
            candidate.scenario.placements[op_id] = deepcopy(placement)
        self.apply_project(candidate, f"Edited placement {op_id}")
        self.select_operation(op_id)

    def move_operation(self, op_id: str, start: int):
        old = self.project.scenario.placements.get(op_id)
        if self._solver_thread is not None or (old and old.locked):
            self.refresh_schedule()
            return
        self.set_placement(op_id, Placement(start, False))

    def toggle_selected_lock(self):
        op_id = self.selected_operation()
        if not op_id:
            return
        old = self.project.scenario.placements.get(op_id)
        if old:
            self.set_placement(op_id, Placement(old.start, not old.locked))
        else:
            self.edit_operation(op_id)

    def clear_selected(self):
        op_id = self.selected_operation()
        if op_id:
            self.set_placement(op_id, None)

    def retire_operation(self, op_id: str):
        if op_id not in self.project.operations:
            raise ValueError(f"Unknown operation: {op_id}")
        referenced = [op.id for op in self.project.operations.values() if op_id in op.predecessors]
        if referenced:
            raise ValueError(f"{op_id} is a predecessor of {', '.join(referenced)}. Retire finished downstream operations first, or update those dependencies in the next ERP import.")
        candidate = deepcopy(self.project)
        del candidate.operations[op_id]
        for scenario in candidate.scenarios.values():
            scenario.placements.pop(op_id, None)
        self.apply_project(candidate, f"Retired completed operation {op_id} from all scenarios")

    def retire_selected(self):
        op_id = self.selected_operation()
        if not op_id:
            self.statusBar().showMessage("Select an operation first. / 공정을 먼저 선택하세요.", 5000)
            return
        referenced = [op.id for op in self.project.operations.values() if op_id in op.predecessors]
        if referenced:
            self._error("Cannot retire a required predecessor / 선행 공정 제거 불가",
                        ValueError(f"{op_id} is required by: {', '.join(referenced)}. Retire completed downstream operations first, or update dependencies through an ERP import."))
            return
        count = sum(op_id in scenario.placements for scenario in self.project.scenarios.values())
        review = ReviewDialog("Retire completed operation / 완료 공정 제거", op_id,
                              f"Remove this operation and its {count} placements from all scenarios. Other operations and resource calendars remain.\n\nUndo restores the operation. A later ERP import containing the same ID adds it again.\n\n공정 및 모든 시나리오의 배치를 제거합니다. 실행 취소로 복원할 수 있습니다.", self)
        if review.exec() == QDialog.DialogCode.Accepted:
            self.retire_operation(op_id)

    def switch_scenario(self, name: str):
        if self._refreshing or name not in self.project.scenarios or name == self.project.active_scenario:
            return
        candidate = deepcopy(self.project)
        candidate.active_scenario = name
        self.apply_project(candidate, f"Switched to scenario {name}")

    def copy_scenario(self, name: str):
        name = name.strip()
        if not name or name in self.project.scenarios:
            raise ValueError("Use a new, nonempty scenario name.")
        candidate = deepcopy(self.project)
        candidate.scenarios[name] = Scenario(name, deepcopy(candidate.scenario.placements))
        candidate.active_scenario = name
        self.apply_project(candidate, f"Copied scenario to {name}")

    def copy_scenario_dialog(self):
        name, accepted = QInputDialog.getText(self, "Copy scenario / 시나리오 복사", "New scenario name / 새 이름")
        if accepted:
            try:
                self.copy_scenario(name)
            except ValueError as exc:
                self._error("Cannot copy scenario", exc)

    def edit_project(self):
        dialog = ProjectDialog(self.project, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            candidate = deepcopy(self.project)
            candidate.name, candidate.timezone, candidate.horizon_start, candidate.horizon_end = dialog.values
            self.apply_project(candidate, "Updated project settings")

    def _selected_resource(self):
        rows = self.resources_table.selectionModel().selectedRows()
        if not rows:
            self.statusBar().showMessage("Select a resource first. / 자원을 먼저 선택하세요.", 5000)
            return None
        value = self.resources_table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        kind, resource_id = value.split(":", 1)
        return kind, resource_id

    def add_resource(self):
        kind, accepted = QInputDialog.getItem(self, "Resource type / 자원 유형", "Type", ["Machine", "Operator"], editable=False)
        if not accepted:
            return
        name, accepted = QInputDialog.getText(self, "Resource ID / 자원 ID", "Exact ID used in ERP exports / ERP 파일의 정확한 ID")
        if not accepted:
            return
        name = name.strip()
        resources = self.project.machines if kind == "Machine" else self.project.operators
        if not name or name in resources:
            self._error("Cannot add resource", ValueError("Use a new, nonempty resource ID."))
            return
        try:
            resource = Resource(name, working_windows(self.project.horizon_start, self.project.horizon_end, self.project.timezone))
        except (ValueError, OverflowError, OSError, KeyError) as exc:
            self._error("Cannot generate resource calendar", exc)
            return
        dialog = CalendarDialog(self.project, resource, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            candidate = deepcopy(self.project)
            resource.windows = dialog.windows
            (candidate.machines if kind == "Machine" else candidate.operators)[name] = resource
            self.apply_project(candidate, f"Added {kind.lower()} {name}")

    def edit_calendar(self, *_):
        selected = self._selected_resource()
        if not selected:
            return
        kind, resource_id = selected
        resources = self.project.machines if kind == "Machine" else self.project.operators
        dialog = CalendarDialog(self.project, resources[resource_id], self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            candidate = deepcopy(self.project)
            (candidate.machines if kind == "Machine" else candidate.operators)[resource_id].windows = dialog.windows
            self.apply_project(candidate, f"Updated {resource_id} calendar")

    def remove_resource(self):
        selected = self._selected_resource()
        if not selected:
            return
        kind, resource_id = selected
        used = [op.id for op in self.project.operations.values() if (op.machine if kind == "Machine" else op.operator) == resource_id]
        if used:
            self._error("Resource is in use", ValueError("Update the ERP export assignment before removing this resource: " + ", ".join(used[:10])))
            return
        candidate = deepcopy(self.project)
        del (candidate.machines if kind == "Machine" else candidate.operators)[resource_id]
        self.apply_project(candidate, f"Removed {resource_id}")

    def import_from(self, path, mapping, unit="minutes", apply=False):
        from .importing import import_operations
        result = import_operations(self.project, path, mapping, duration_unit=unit)
        if apply:
            self.apply_project(result.project, f"Imported {Path(path).name}")
        return result

    def import_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import ERP export / ERP 파일 가져오기", "", "ERP exports (*.csv *.xlsx)")
        if not path:
            return
        try:
            mapping = MappingDialog(self.project, path, self)
            if mapping.exec() != QDialog.DialogCode.Accepted:
                return
            result = self.import_from(path, mapping.mapping, mapping.unit.currentText())
            issues = validate(result.project)
            summary = f"{len(result.added)} added · {len(result.updated)} updated · {len(result.retained)} retained"
            details = "All existing placements and locks are retained by operation ID. Omitted operations remain in the project.\n\n"
            details += "Added: " + ", ".join(result.added) + "\nUpdated: " + ", ".join(result.updated) + "\nRetained: " + ", ".join(result.retained)
            details += "\n\nIMPORT NOTES\n" + "\n".join(result.warnings) + "\n\nVALIDATION\n" + (_issues_text(issues) or "No conflicts.")
            review = ReviewDialog("Review import / 가져오기 검토", summary, details, self)
            if review.exec() == QDialog.DialogCode.Accepted:
                self.apply_project(result.project, f"Imported {Path(path).name}")
        except Exception as exc:  # noqa: BLE001 - preserve the live draft and report UI boundary failures.
            self._error("Import failed — project unchanged / 가져오기 실패", exc)

    def start_suggest(self, _checked=False, *, show_review=True, time_limit=5.0):
        if self._solver_thread is not None:
            return
        if not self.project.operations:
            self.statusBar().showMessage("Import operations first. / 먼저 공정을 가져오세요.", 6000)
            return
        self._show_solver_review = show_review
        self._solver_snapshot = deepcopy(self.project)
        self.suggest_button.setEnabled(False)
        self.project_settings_button.setEnabled(False)
        self.tabs.setEnabled(False)
        for action in self.actions.values():
            action.setEnabled(False)
        self.statusBar().showMessage("Computing a proposal with one solver worker… The current plan stays unchanged. / 일정 제안 계산 중…")
        self._solver_thread = QThread(self)
        self._solver_worker = _SolverWorker(self._solver_snapshot, min(30.0, max(0.05, time_limit)))
        self._solver_worker.moveToThread(self._solver_thread)
        self._solver_thread.started.connect(self._solver_worker.run)
        self._solver_worker.result.connect(self._on_solved)
        self._solver_worker.failed.connect(self._on_solver_failed)
        self._solver_worker.finished.connect(self._solver_thread.quit)
        self._solver_worker.finished.connect(self._solver_worker.deleteLater)
        self._solver_thread.finished.connect(self._solver_done)
        self._solver_thread.start()

    def _solver_done(self):
        thread = self._solver_thread
        self._solver_thread = None
        self._solver_worker = None
        if thread:
            thread.deleteLater()
        self.tabs.setEnabled(True)
        self.suggest_button.setEnabled(True)
        self.project_settings_button.setEnabled(True)
        for action in self.actions.values():
            action.setEnabled(True)
        self.actions["undo"].setEnabled(bool(self.undo_stack))

    def _on_solver_failed(self, message):
        self.statusBar().showMessage("Scheduling failed. The current plan is unchanged.")
        if self._show_solver_review:
            self._error("Scheduling failed", RuntimeError(message))

    def _on_solved(self, result):
        self.last_solve_result = result
        self.schedule_ready.emit(result)
        self.statusBar().showMessage(f"Proposal: {result.status} · {result.wall_time:.2f}s. Review required before applying.")
        if not self._show_solver_review:
            return
        candidate = deepcopy(self._solver_snapshot)
        candidate.scenario.placements = deepcopy(result.placements)
        issues = validate(candidate) if result.placements else result.issues
        all_placed = set(candidate.operations) == set(result.placements)
        can_apply = result.status in ("optimal", "feasible") and all_placed and not any(issue.severity == "error" for issue in issues)
        changes = []
        for op_id, placement in result.placements.items():
            old = self.project.scenario.placements.get(op_id)
            if old is None or old.start != placement.start:
                changes.append(f"{op_id}: {_time(old.start, self.project) if old else 'Unscheduled'} → {_time(placement.start, self.project)}")
        details = f"Status: {result.status}\nWall time: {result.wall_time:.3f}s\nObjective: {result.objective}\nBest bound: {result.bound}\n\n"
        details += "Objective: sum of per-operation tardiness + makespan, in seconds with equal weights. Due dates are soft targets. Optimal means proved best for this objective. Feasible is a complete validated plan without proof of optimality. Time-limited means no candidate was found before the limit; feasibility remains unknown.\n\n"
        details += "CHANGES\n" + ("\n".join(changes) or "No placement changes.")
        details += "\n\nVALIDATION\n" + (_issues_text(issues) or "No conflicts. All operations are placed.")
        review = ReviewDialog("Review scheduling proposal / 일정 제안 검토", f"{result.status.upper()} · {len(result.placements)} / {len(self.project.operations)} operations placed", details, self, can_apply)
        if review.exec() == QDialog.DialogCode.Accepted:
            self.apply_suggestion(result)

    def apply_suggestion(self, result):
        """A second boundary check: engine success alone cannot authorize apply."""
        if result.status not in ("optimal", "feasible"):
            raise ValueError("The solver did not return a usable complete proposal.")
        if set(result.placements) != set(self.project.operations):
            raise ValueError("A partial proposal cannot replace the current schedule.")
        candidate = deepcopy(self.project)
        for op_id, old in self.project.scenario.placements.items():
            if old.locked and result.placements.get(op_id) != old:
                raise ValueError(f"Proposal changed locked operation {op_id}.")
        candidate.scenario.placements = deepcopy(result.placements)
        issues = validate(candidate)
        if any(issue.severity == "error" for issue in issues):
            raise ValueError("Independent validation rejected the proposal:\n" + _issues_text(issues))
        self.apply_project(candidate, f"Applied {result.status} scheduling proposal")

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = QMessageBox.warning(self, "Unsaved changes / 저장되지 않은 변경", "Save changes before continuing? / 계속하기 전에 변경 사항을 저장할까요?",
                                     QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                     QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    def new_project(self):
        if self._confirm_discard():
            candidate = self.blank_project()
            dialog = ProjectDialog(candidate, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                candidate.name, candidate.timezone, candidate.horizon_start, candidate.horizon_end = dialog.values
                self.set_project(candidate)
                self.dirty = True
                self.refresh()

    def load_demo(self):
        if self._confirm_discard():
            from .demo import demo_project
            self.set_project(demo_project())
            self.statusBar().showMessage("Synthetic demo opened. Save a copy to keep edits. / 합성 예제입니다.", 9000)

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open project / 프로젝트 열기", "", "ShopShift projects (*.shopshift *.json);;All files (*)")
        if path and self._confirm_discard():
            self.open_path(path)

    def open_path(self, path) -> bool:
        from .storage import load_project
        try:
            project = load_project(path)
            self.set_project(project, path)
            return True
        except Exception as exc:  # noqa: BLE001 - preserve the live draft and report UI boundary failures.
            message = str(exc)
            if Path(str(path) + ".bak").exists():
                message += "\nA previous-save backup exists. Use File → Restore backup to inspect it."
            self._error("Cannot open project — current project unchanged", ValueError(message))
            return False

    def save_to(self, path) -> bool:
        from .storage import save_project
        try:
            save_project(self.project, path)
        except Exception as exc:  # noqa: BLE001 - preserve the live draft and report UI boundary failures.
            self._error("Save failed — changes are still in memory / 저장 실패", exc)
            return False
        self.path = Path(path)
        self.dirty = False
        self.refresh()
        self.statusBar().showMessage(f"Saved {self.path.name}", 6000)
        return True

    def save(self) -> bool:
        return self.save_to(self.path) if self.path else self.save_as()

    def save_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "Save project / 프로젝트 저장", str(self.path or "shop-plan.shopshift"), "ShopShift project (*.shopshift)")
        return self.save_to(path) if path else False

    def backup(self):
        from .storage import backup_project
        path, _ = QFileDialog.getSaveFileName(self, "Create backup / 백업 만들기", "shop-plan-backup.shopshift", "ShopShift backup (*.shopshift)")
        if path:
            try:
                backup_project(self.project, path)
                self.statusBar().showMessage(f"Backup created: {Path(path).name}", 6000)
            except Exception as exc:  # noqa: BLE001 - preserve the live draft and report UI boundary failures.
                self._error("Backup failed", exc)

    def restore(self):
        from .storage import load_project
        path, _ = QFileDialog.getOpenFileName(self, "Restore backup / 백업 복원", "", "Backups (*.shopshift *.bak *.json);;All files (*)")
        if not path:
            return
        try:
            project = load_project(path)
            review = ReviewDialog("Review backup / 백업 검토", project.name,
                                  f"{len(project.operations)} operations · {len(project.scenarios)} scenarios\n{project.timezone}\n\n" + (_issues_text(validate(project)) or "No validation conflicts."), self)
            if review.exec() == QDialog.DialogCode.Accepted and self._confirm_discard():
                self.set_project(project)
                self.dirty = True
                self.refresh()
                self.statusBar().showMessage("Backup restored in memory. Save as a project to keep it. / 복원 후 저장하세요.", 9000)
        except Exception as exc:  # noqa: BLE001 - preserve the live draft and report UI boundary failures.
            self._error("Restore failed — current project unchanged", exc)

    def _export_day(self):
        self._daily_bounds()  # Validate before opening a destination dialog.
        return self.day_filter.text().strip() or None

    def export_csv_dialog(self):
        from .storage import export_csv
        self._export(export_csv, "CSV (*.csv)", "work-list.csv")

    def export_html_dialog(self):
        from .storage import export_html
        self._export(export_html, "HTML (*.html)", "work-list.html")

    def _export(self, exporter, file_filter, filename):
        try:
            day = self._export_day()
            path, _ = QFileDialog.getSaveFileName(self, "Export read-only work list / 읽기 전용 작업 목록 내보내기", filename, file_filter)
            if path:
                exporter(self.project, path, day=day)
                self.statusBar().showMessage(f"Exported {Path(path).name} · includes validation warnings", 7000)
        except Exception as exc:  # noqa: BLE001 - preserve the live draft and report UI boundary failures.
            self._error("Export failed", exc)

    def print_plan(self):
        from tempfile import TemporaryDirectory

        from .storage import export_html
        try:
            from PySide6.QtPrintSupport import QPrintDialog, QPrinter
            day = self._export_day()
            with TemporaryDirectory(prefix="shopshift-print-") as directory:
                path = Path(directory) / "plan.html"
                export_html(self.project, path, day=day)
                document = QTextDocument(self)
                document.setHtml(path.read_text(encoding="utf-8"))
                printer = QPrinter(QPrinter.PrinterMode.HighResolution)
                dialog = QPrintDialog(printer, self)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    document.print_(printer)
        except Exception as exc:  # noqa: BLE001 - preserve the live draft and report UI boundary failures.
            self._error("Printing failed — you can also export HTML", exc)

    def _error(self, title, error):
        QMessageBox.critical(self, title, str(error))

    def about(self):
        QMessageBox.about(self, "About ShopShift / ShopShift 정보",
                          "<h2>ShopShift 0.1.0</h2><p>Offline scheduling workbench for one planner. No telemetry, accounts or ERP writes.</p>"
                          "<p>ShopShift is MIT licensed. The interface uses <b>Qt / PySide6 under LGPLv3</b>. "
                          "Scheduling uses the official Google OR-Tools CP-SAT engine (Apache-2.0).</p>"
                          "<p>See the distribution’s <b>THIRD_PARTY_NOTICES</b> and <b>licenses</b> directory for license texts, "
                          "corresponding Qt sources and instructions for replacing LGPL libraries.</p>"
                          "<p>Plans are decision support. Review constraints and exports before issuing production instructions. "
                          "Fixed assignments, nonpreemptive operations, no sequence-dependent setup.</p>"
                          "<p>단일 계획자를 위한 오프라인 일정 작업 도구입니다. 생산 지시 전 제약 조건과 결과를 검토하세요.</p>")

    def closeEvent(self, event):
        if self._solver_thread is not None:
            self.statusBar().showMessage("Wait for the bounded scheduling proposal to finish, then close. / 일정 계산이 끝난 후 닫아주세요.", 10000)
            event.ignore()
            return
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()


def run_gui() -> int:
    """Convenience entry point; CLI packaging may construct MainWindow directly."""
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("ShopShift")
    window = MainWindow()
    window.show()
    return app.exec()
