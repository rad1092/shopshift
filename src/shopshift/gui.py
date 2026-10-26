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

from PySide6.QtCore import QEvent, QLocale, QObject, QPointF, QRectF, Qt, QThread, Signal
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
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from . import i18n
from .i18n import T
from .model import Operation, Placement, Project, Resource, Scenario, Window
from .storage import StorageProblem, validate_project_for_storage
from .timeutil import day_bounds, format_timestamp, parse_timestamp, working_windows
from .validator import validate

TEXT = {
    "new": ("New", "새 프로젝트"), "demo": ("Open demo", "예제 열기"),
    "open": ("Open…", "열기…"), "save": ("Save", "저장"),
    "save_as": ("Save as…", "다른 이름으로 저장…"), "import": ("Import ERP export…", "ERP 파일 가져오기…"),
    "undo": ("Undo", "실행 취소"), "backup": ("Create backup…", "백업 만들기…"),
    "restore": ("Restore backup…", "백업 복원…"), "settings": ("Project and dates…", "프로젝트 및 날짜…"),
    "schedule": ("Schedule", "일정"), "resources": ("Resources and calendars", "자원 및 근무 시간"),
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
    return i18n.duration(seconds)


def _time(value: int | None, project: Project) -> str:
    """A time to read: Mon 10/05 08:00. The project's zone is shown once in the header."""
    return i18n.when(value, project.timezone)


def _iso(value: int | None, project: Project) -> str:
    """A time to edit: full ISO with offset, which parse_timestamp reads back exactly."""
    if value is None:
        return ""
    try:
        return format_timestamp(value, project.timezone)
    except (ValueError, OverflowError, OSError, KeyError):
        return str(value)


def _issues_text(issues) -> str:
    return "\n".join(i18n.issue_line(issue) for issue in issues)


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


_FIELD_NAMES_KO = {"id": "공정 ID", "job": "작업", "machine": "기계", "operator": "작업자", "setup": "준비 시간",
                   "run": "실행 시간", "predecessors": "선행 공정", "release": "작업 가능 시각", "due": "납기", "label": "설명"}


class MappingDialog(QDialog):
    """Explicit mapping with a bounded raw-data preview; never mutates Project."""

    FIELDS = ("id", "job", "machine", "operator", "setup", "run", "predecessors", "release", "due", "label")

    def __init__(self, project: Project, path: str | Path, parent=None):
        super().__init__(parent)
        from .importing import read_table
        self.setWindowTitle(T("Map ERP export columns", "ERP 열 매핑"))
        self.resize(950, 720)
        self.path = Path(path)
        headers, rows = read_table(path)
        saved = project.mappings.get(self.path.name, project.mappings.get("__last__"))
        outer = QVBoxLayout(self)
        outer.addWidget(_label(T(f"{self.path.name} · {len(rows):,} rows · {project.timezone}", f"{self.path.name} · {len(rows):,}행 · {project.timezone}"), "font-weight: 600; font-size: 16px;"))
        outer.addWidget(_label(T("Required: stable operation ID, job, machine and run time. Dates require an ISO timestamp; include an offset for repeated DST times. Optional unmapped fields keep existing values.",
                                 "필수: 공정 ID, 작업, 기계, 실행 시간. 날짜는 ISO 형식(예: 2026-10-05T08:00)이며, 서머타임으로 반복되는 시각에는 오프셋을 붙이세요. 매핑하지 않은 선택 항목은 기존 값을 유지합니다.")))
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
            combo.addItem(T("— Not mapped —", "— 매핑 없음 —"), "")
            for header in headers:
                combo.addItem(header, header)
            # An omitted field in a saved mapping is an intentional decision to
            # retain its existing values. Never auto-map it on repeat imports.
            # Missing saved headers also require an explicit replacement.
            selected = (saved.get(field, "") if saved is not None
                        else next((normalized[a] for a in aliases[field] if a in normalized), ""))
            combo.setCurrentIndex(max(0, combo.findData(selected)))
            required = " *" if field in ("id", "job", "machine", "run") else ""
            form.addRow(T(field, _FIELD_NAMES_KO.get(field, field)) + required, combo)
            self.combos[field] = combo
        self.unit = QComboBox()
        self.unit.setObjectName("durationUnit")
        self.unit.addItems(["seconds", "minutes", "hours"])
        self.unit.setCurrentText((saved or {}).get("__duration_unit", "minutes"))
        form.addRow(T("Setup & run units", "준비·실행 시간 단위"), self.unit)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(fields)
        outer.addWidget(scroll, 2)
        preview = _table(headers, "importPreview")
        for i, row in enumerate(rows[:12]):
            _put_row(preview, i, [row.get(header, "") for header in headers])
        outer.addWidget(_label(T("Source preview · first 12 rows", "원본 미리보기 · 처음 12행")))
        outer.addWidget(preview, 1)
        self.error = _label("", "color:#a33a2a;")
        outer.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(T("Review import", "가져오기 검토"))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    @property
    def mapping(self) -> dict[str, str]:
        return {field: combo.currentData() for field, combo in self.combos.items() if combo.currentData()}

    def _accept(self):
        missing = [key for key in ("id", "job", "machine", "run") if key not in self.mapping]
        if missing:
            self.error.setText(T("Map required columns: ", "필수 열을 매핑하세요: ") + ", ".join(missing))
            return
        mapped = list(self.mapping.values())
        if len(mapped) != len(set(mapped)):
            self.error.setText(T("Each source column can be assigned once.", "원본 열을 중복 지정할 수 없습니다."))
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
        body.setAccessibleName(T("Changes and validation details", "변경 및 검증 내용"))
        layout.addWidget(body)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        apply = buttons.button(QDialogButtonBox.StandardButton.Apply)
        apply.setText(T("Apply", "적용"))
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
        self.setWindowTitle(T(f"Edit {operation_id}", f"{operation_id} 편집"))
        self.resize(630, 300)
        layout = QVBoxLayout(self)
        layout.addWidget(_label(f"{op.job} · {op.machine} · {_duration(op.duration)}", "font-weight:600;"))
        details = _label(f"{T('Description', '설명')}: {op.label or '—'}\n"
                         f"{T('Operator', '작업자')}: {op.operator or '—'}\n"
                         f"{T('Predecessors', '선행 공정')}: {'; '.join(op.predecessors) or '—'}\n"
                         f"{T('Release', '작업 가능 시각')}: {_time(op.release, project)}\n"
                         f"{T('Due', '납기')}: {_time(op.due, project)}")
        details.setObjectName("operationDetails")
        details.setAccessibleName(T("Imported operation details", "가져온 공정 정보"))
        details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                       | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        layout.addWidget(details)
        layout.addWidget(_label(T(f"Times are in {project.timezone}. Enter the start as 2026-10-05T08:00; add an offset such as -05:00 for a repeated daylight-saving hour. Leave it empty to clear the placement.",
                                  f"시간대는 {project.timezone}입니다. 시작을 2026-10-05T08:00 형식으로 입력하세요. 서머타임으로 반복되는 시각에는 -05:00 같은 오프셋을 붙입니다. 비우면 배치를 해제합니다.")))
        form = QFormLayout()
        self.start = QLineEdit(_iso(placement.start, project) if placement else "")
        self.start.setObjectName("placementStart")
        self.start.setPlaceholderText("2026-10-08T08:00:00+09:00")
        form.addRow(T("Start", "시작"), self.start)
        self.locked = QCheckBox(T("Keep this placement fixed during suggestions", "일정 제안 때 이 배치를 고정"))
        self.locked.setObjectName("placementLocked")
        self.locked.setChecked(placement.locked if placement else False)
        form.addRow(T("Lock", "고정"), self.locked)
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
                self.error.setText(T("A locked operation needs a start time.", "고정하려면 시작 시간이 필요합니다."))
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
        self.setWindowTitle(T(f"Calendar · {resource.id}", f"근무 시간 · {resource.id}"))
        self.resize(790, 570)
        layout = QVBoxLayout(self)
        layout.addWidget(_label(f"{resource.id} · {project.timezone}", "font-size:17px;font-weight:600;"))
        layout.addWidget(_label(T("One available interval per line: START / END. Use ISO dates with offsets for DST ambiguity. Gaps mean unavailable; work must fit entirely inside a window. Overnight windows are supported.",
                                  "한 줄에 근무 구간 하나를 시작 / 종료로 입력합니다. 서머타임으로 모호한 시각에는 오프셋을 붙이세요. 빈 구간은 작업 불가 시간이고, 작업은 한 구간 안에 다 들어가야 합니다. 밤샘 구간도 됩니다.")))
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("calendarWindows")
        self.editor.setAccessibleName(T("Available resource windows, one start slash end per line", "근무 구간, 한 줄에 시작 / 종료"))
        self.editor.setPlainText("\n".join(f"{_iso(w.start, project)} / {_iso(w.end, project)}" for w in resource.windows))
        layout.addWidget(self.editor)
        default = QPushButton(T("Replace with weekdays 08–12 and 13–17", "평일 08–12, 13–17로 바꾸기"))
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
            self.editor.setPlainText("\n".join(f"{_iso(w.start, self.project)} / {_iso(w.end, self.project)}" for w in windows))
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
                    raise ValueError(T(f"Line {number}: enter START / END.", f"{number}행: 시작 / 종료를 입력하세요."))
                start, end = (parse_timestamp(part.strip(), self.project.timezone) for part in parts)
                if end <= start:
                    raise ValueError(T(f"Line {number}: end must be after start.", f"{number}행: 종료가 시작보다 뒤여야 합니다."))
                windows.append(Window(start, end))
            windows.sort(key=lambda item: item.start)
            if any(a.end > b.start for a, b in zip(windows, windows[1:])):
                raise ValueError(T("Available windows overlap. Merge or separate them.", "근무 구간이 겹칩니다. 합치거나 나누세요."))
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
        self.setWindowTitle(T("Project & horizon", "프로젝트 및 계획 기간"))
        self.resize(610, 300)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(project.name)
        self.zone = QLineEdit(project.timezone)
        self.begin = QLineEdit(_iso(project.horizon_start, project))
        self.end = QLineEdit(_iso(project.horizon_end, project))
        for label, widget in ((T("Name", "이름"), self.name), (T("IANA timezone", "시간대 (IANA)"), self.zone),
                              (T("Horizon start", "기간 시작"), self.begin), (T("Horizon end", "기간 종료"), self.end)):
            form.addRow(label, widget)
        layout.addLayout(form)
        layout.addWidget(_label(T("Changing the horizon or display zone keeps all existing timestamps and calendars. Review any conflicts afterward.",
                                  "기간이나 시간대를 바꿔도 기존 일정과 근무 시간은 그대로입니다. 바꾼 다음 충돌을 확인하세요.")))
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
                raise ValueError(T("Horizon end must be after its start.", "기간 종료가 시작보다 뒤여야 합니다."))
            if not self.name.text().strip():
                raise ValueError(T("Give the project a name.", "프로젝트 이름을 입력하세요."))
            self.values = (self.name.text().strip(), zone, start, end)
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class _OperationBar(QGraphicsRectItem):
    def __init__(self, timeline: "TimelineView", operation: Operation, placement: Placement, row: int, invalid: bool,
                 late: bool = False):
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
        # Red: a conflict. Orange: finishes after its due time. Gray: locked.
        self.late = late
        self.setBrush(QColor("#aa443c" if invalid else "#d9822b" if late else "#506078" if self.locked else "#187b80"))
        self.setPen(QPen(QColor("#ffffff"), 1))
        overdue = ""
        if late and operation.due is not None:
            overdue = "\n" + T(f"{_duration(placement.start + operation.duration - operation.due)} late", f"납기보다 {_duration(placement.start + operation.duration - operation.due)} 늦음")
        locked = (" · " + T("locked", "고정")) if self.locked else ""
        self.setToolTip(f"{operation.id} · {operation.job}\n{_time(placement.start, timeline.project)} – {_time(placement.start + operation.duration, timeline.project)}"
                        f"\n{_duration(operation.duration)}{locked}{overdue}\n{T('Double-click or Enter to edit', '더블클릭 또는 Enter로 편집')}")
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
        self.setAccessibleName(T("Machine schedule timeline. Use the operations table for keyboard editing.", "기계별 일정 타임라인. 키보드로 편집하려면 공정 표를 쓰세요."))
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMinimumHeight(240)
        self.left, self.top, self.row_height = 150, 52, 53
        self.scale_seconds = 1 / 180
        self.zoom_mode = "overview"
        self.origin = 0
        self.project = None
        self.end = 0
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
        machines = sorted(set(project.machines) | {op.machine for op in project.operations.values()})
        # Show the hours that matter: from the first working window or placement
        # to the last, on whole hours, instead of the full horizon from midnight.
        spans = [(w.start, w.end) for m in machines if m in project.machines for w in project.machines[m].windows]
        spans += [(p.start, p.start + project.operations[k].duration) for k, p in project.scenario.placements.items()
                  if k in project.operations]
        first, last = project.horizon_start, project.horizon_end
        if spans:
            first = max(first, min(a for a, _ in spans) // 3600 * 3600)
            last = min(last, -(-max(b for _, b in spans) // 3600) * 3600)
        if last - first < 3600:
            first, last = project.horizon_start, project.horizon_end
        self.origin = first
        self.end = last
        span = max(3600, last - first)
        # One day remains useful at a glance; long horizons scroll instead of
        # drawing millions of unbounded tick marks.
        self.scale_seconds = {"day": self._working_day_scale(project, spans), "hour": 180 / 3600}.get(
            self.zoom_mode, max(1 / 1200, min(1 / 45, 1350 / span)))
        width = max(900, span * self.scale_seconds)
        invalid = {op_id for issue in issues if issue.severity == "error" for op_id in issue.operation_ids}
        for row, machine in enumerate(machines):
            y = self.top + row * self.row_height
            self.scene().addRect(self.left, y, width, self.row_height, QPen(QColor("#dbe2e5")), QColor("#f0f3f5"))
            text = self.scene().addText(machine)
            text.setDefaultTextColor(QColor("#273b4a"))
            text.setPos(8, y + 14)
            resource = project.machines.get(machine)
            for window in resource.windows if resource else []:
                start, end = max(window.start, self.origin), min(window.end, self.end)
                if end > start:
                    self.scene().addRect(self.left + (start - self.origin) * self.scale_seconds, y + 1,
                                         (end - start) * self.scale_seconds, self.row_height - 2,
                                         QPen(Qt.PenStyle.NoPen), QColor("#ffffff"))
        tick = 3600 if self.zoom_mode in ("day", "hour") or span <= 36 * 3600 else 86400
        tick = max(tick, math.ceil(span / 100) // 3600 * 3600)
        timestamp = self.origin
        while timestamp <= self.end:
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
            late = op.due is not None and placement.start + op.duration > op.due
            bar = _OperationBar(self, op, placement, rows[op.machine], op_id in invalid, late)
            self.scene().addItem(bar)
            self.bars[op_id] = bar
        if not machines:
            self.scene().addText(T("Import an ERP export or open the demo to begin.", "ERP 파일을 가져오거나 예제를 열어 시작하세요.")).setPos(25, 90)
        self.scene().setSceneRect(QRectF(0, 0, self.left + width + 60, max(180, self.top + len(machines) * self.row_height)))
        self.scene().blockSignals(False)

    def _working_day_scale(self, project: Project, spans) -> float:
        """Day detail fits the first working day (08:00–17:00 in the demo) to the visible width."""
        if not spans:
            return 48 / 3600
        try:
            zone = ZoneInfo(project.timezone)
            first = min(a for a, _ in spans)
            day = datetime.fromtimestamp(first, zone).date()
            same_day = [(a, b) for a, b in spans if datetime.fromtimestamp(a, zone).date() == day]
            length = max(b for _, b in same_day) - first
        except (ValueError, OverflowError, OSError, KeyError):
            return 48 / 3600
        length = min(max(length, 4 * 3600), 16 * 3600)
        visible = max(600, self.viewport().width() - self.left - 30)
        return max(48 / 3600, visible / length)

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

    def __init__(self, project: Project, time_limit: float, weights: tuple[int, int] = (1, 1)):
        super().__init__()
        self.project, self.time_limit, self.weights = project, time_limit, weights

    def run(self):
        try:
            from .solver import suggest
            self.result.emit(suggest(self.project, time_limit=self.time_limit,
                                     lateness_weight=self.weights[0], makespan_weight=self.weights[1]))
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
        i18n.set_language("en")
        self.undo_stack: list[tuple[Project, str]] = []
        self._translations = []
        # (setter, English, Korean): every fixed text, re-set when the language changes.
        self._texts: list[tuple] = []
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
        if QLocale.system().language() == QLocale.Language.Korean:
            self.language_box.setCurrentIndex(1)

    @staticmethod
    def blank_project() -> Project:
        now = datetime.now(ZoneInfo("UTC")).replace(hour=0, minute=0, second=0, microsecond=0)
        return Project(name="Untitled shop", timezone="UTC", horizon_start=int(now.timestamp()),
                       horizon_end=int((now + timedelta(days=14)).timestamp()))

    def _tr(self, key: str) -> str:
        return TEXT[key][self.language == "ko"]

    def _bind(self, setter, english: str, korean: str) -> None:
        """Set a fixed text now and again whenever the language changes."""
        setter(T(english, korean))
        self._texts.append((setter, english, korean))

    def _fixed_label(self, english: str, korean: str, style: str = "") -> QLabel:
        label = _label("", style)
        self._bind(label.setText, english, korean)
        return label

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
        file_menu = self.menuBar().addMenu("")
        self._bind(file_menu.setTitle, "File", "파일")
        edit_menu = self.menuBar().addMenu("")
        self._bind(edit_menu.setTitle, "Edit", "편집")
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
        self.language_box.setAccessibleName("Interface language · 인터페이스 언어")
        self.language_box.addItem("English", "en")
        self.language_box.addItem("한국어", "ko")
        self.language_box.currentIndexChanged.connect(self._language_changed)
        toolbar.addWidget(self.language_box)
        help_menu = self.menuBar().addMenu("")
        self._bind(help_menu.setTitle, "Help", "도움말")
        about_action = QAction("", self)
        self._bind(about_action.setText, "About & licenses", "정보 및 라이선스")
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
        self._bind(self.statusBar().showMessage, "Local project · no network · review before committing to production",
                   "로컬 프로젝트 · 네트워크 없음 · 생산 지시 전에 검토하세요")

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
        self._bind(self.scenario_selector.setAccessibleName, "Active scenario", "현재 시나리오")
        self.scenario_selector.currentTextChanged.connect(self.switch_scenario)
        top.addWidget(self.scenario_selector)
        # What the suggestion should care about most; read when Suggest is pressed.
        self.weight_labels = []
        for name, english, korean, tip_en, tip_ko in (
                ("weightDue", "Due dates", "납기", "How much finishing each operation by its due time matters.", "공정을 납기 안에 끝내는 것이 얼마나 중요한지"),
                ("weightFinish", "Finish early", "빨리 끝내기", "How much finishing all work as early as possible matters.", "모든 작업을 최대한 일찍 끝내는 것이 얼마나 중요한지")):
            label = QLabel()
            self._bind(label.setText, english, korean)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setObjectName(name)
            slider.setRange(0, 10)
            slider.setValue(5)
            slider.setPageStep(1)
            slider.setFixedWidth(90)
            self._bind(slider.setToolTip, tip_en, tip_ko)
            self._bind(slider.setAccessibleName, english, korean)
            label.setBuddy(slider)
            top.addWidget(label)
            top.addWidget(slider)
            setattr(self, name, slider)
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
        zoom_label = QLabel()
        self._bind(zoom_label.setText, "Timeline scale", "시간 축")
        zoom_row.addWidget(zoom_label)
        self.timeline_zoom = QComboBox()
        self.timeline_zoom.setObjectName("timelineZoom")
        self._bind(self.timeline_zoom.setAccessibleName, "Timeline zoom level", "시간 축 확대 수준")
        for index, (data, english, korean) in enumerate((("overview", "Overview", "전체"), ("day", "Day detail", "일별"), ("hour", "Hour detail", "시간별"))):
            self.timeline_zoom.addItem("", data)
            self._bind(lambda text, i=index: self.timeline_zoom.setItemText(i, text), english, korean)
        legend = QLabel()
        self._bind(legend.setText, "Bars: teal planned · gray locked · orange late · red conflict", "막대: 청록 배치 · 회색 고정 · 주황 지연 · 빨강 충돌")
        legend.setStyleSheet("color:#526575;font-size:11px;")
        self.timeline_zoom.currentIndexChanged.connect(self._zoom_changed)
        zoom_row.addWidget(self.timeline_zoom)
        zoom_row.addSpacing(16)
        zoom_row.addWidget(legend)
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
        self._bind(self.issues_list.setAccessibleName, "Schedule conflicts and warnings", "일정 충돌과 경고")
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
        layout.addWidget(self._fixed_label("Each operation occupies its assigned machine and optional operator for the entire setup + run duration. Calendar gaps (including lunch) are unavailable. Review default calendars after import.",
                                           "공정은 준비와 실행 시간 내내 기계와 작업자를 점유합니다. 근무 시간 사이의 빈 시간(점심 포함)에는 작업할 수 없습니다. 가져온 다음 기본 근무 시간을 확인하세요."))
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
        layout.addWidget(self._fixed_label("Scenarios share operation definitions and resource calendars. Placements and locks are independent. ERP reimports update every scenario by stable operation ID.",
                                           "시나리오는 공정과 자원 근무 시간을 함께 쓰고, 배치와 고정은 시나리오마다 따로 둡니다. ERP를 다시 가져오면 공정 ID 기준으로 모든 시나리오가 갱신됩니다."))
        buttons = QHBoxLayout()
        buttons.addWidget(self._button("copy", self.copy_scenario_dialog))
        buttons.addStretch()
        compare_label = QLabel()
        self._bind(compare_label.setText, "Compare current with", "비교 대상")
        buttons.addWidget(compare_label)
        self.compare_selector = QComboBox()
        self.compare_selector.setObjectName("compareScenario")
        self._bind(self.compare_selector.setAccessibleName, "Scenario to compare against", "비교할 시나리오")
        self.compare_selector.currentTextChanged.connect(self.refresh_compare)
        buttons.addWidget(self.compare_selector)
        layout.addLayout(buttons)
        self.compare_summary = _label("")
        layout.addWidget(self.compare_summary)
        self.compare_table = _table(["Operation", "Job", "Comparison start", "Current start", "Shift", "Current lateness", "Locked"], "scenarioComparison")
        layout.addWidget(self.compare_table)
        self.tabs.addTab(page, self._tr("scenarios"))

    def _build_daily(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self._fixed_label("Read-only dispatch snapshot for review. Exported files include validation warnings. Confirm the plan before giving production instructions.",
                                           "검토용 읽기 전용 작업 목록입니다. 내보낸 파일에도 검증 경고가 들어갑니다. 생산 지시 전에 계획을 확인하세요."))
        buttons = QHBoxLayout()
        day_label = QLabel()
        self._bind(day_label.setText, "Day", "날짜")
        buttons.addWidget(day_label)
        self.day_filter = QLineEdit()
        self.day_filter.setObjectName("dailyDate")
        self._bind(self.day_filter.setPlaceholderText, "YYYY-MM-DD · empty shows every day", "YYYY-MM-DD · 비우면 전체")
        self._bind(self.day_filter.setAccessibleName, "Date for the daily work list, empty for all dates", "작업 목록 날짜, 비우면 전체")
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
        i18n.set_language(self.language)
        for widget, key in self._translations:
            widget.setText(self._tr(key))
            if isinstance(widget, QWidget):
                widget.setAccessibleName(self._tr(key))
        for i, key in enumerate(("schedule", "resources", "scenarios", "daily")):
            self.tabs.setTabText(i, self._tr(key))
        self.filter.setPlaceholderText(self._tr("search"))
        i18n.set_language(self.language)
        for setter, english, korean in self._texts:
            setter(T(english, korean))
        if self.language == "ko":
            self.operations_table.setHorizontalHeaderLabels(["공정", "작업", "기계", "작업자", "시작", "종료", "준비 + 실행", "납기", "상태"])
            self.resources_table.setHorizontalHeaderLabels(["유형", "자원", "근무 구간", "가용 시간", "첫 시작", "마지막 종료"])
            self.daily_table.setHorizontalHeaderLabels(["기계", "시작", "종료", "작업", "공정", "작업자", "고정", "납기"])
            self.compare_table.setHorizontalHeaderLabels(["공정", "작업", "비교 시작", "현재 시작", "이동", "현재 지연", "고정"])
        else:
            self.operations_table.setHorizontalHeaderLabels(["Operation", "Job", "Machine", "Operator", "Start", "End", "Setup + run", "Due", "State"])
            self.resources_table.setHorizontalHeaderLabels(["Type", "Resource", "Available windows", "Available hours", "First start", "Last end"])
            self.daily_table.setHorizontalHeaderLabels(["Machine", "Start", "End", "Job", "Operation", "Operator", "Lock", "Due"])
            self.compare_table.setHorizontalHeaderLabels(["Operation", "Job", "Comparison start", "Current start", "Shift", "Current lateness", "Locked"])
        self.timeline.setAccessibleName(T("Machine schedule timeline. Use the operations table for keyboard editing.", "기계별 일정 타임라인. 키보드로 편집하려면 공정 표를 쓰세요."))
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

    def _admit_project(self, project: Project) -> bool:
        try:
            validate_project_for_storage(project)
        except StorageProblem as exc:
            self._error(T("Cannot apply change — current project unchanged", "변경을 적용할 수 없음 — 프로젝트는 그대로입니다"), exc)
            return False
        return True

    def set_project(self, project: Project, path: str | Path | None = None) -> bool:
        if not self._admit_project(project):
            return False
        self.project = deepcopy(project)
        self.path = Path(path) if path else None
        self.undo_stack.clear()
        self.dirty = False
        self.filter.clear()
        self.late_only.setChecked(False)
        self.day_filter.clear()
        self.refresh()
        return True

    def apply_project(self, project: Project, description: str) -> bool:
        if not self._admit_project(project):
            return False
        self.undo_stack.append((deepcopy(self.project), description))
        self.undo_stack = self.undo_stack[-50:]
        self.project = deepcopy(project)
        self.dirty = True
        self.refresh()
        self.statusBar().showMessage(description + T(" · Undo available", " · 실행 취소 가능"), 8000)
        return True

    def undo(self):
        if self._solver_thread is not None:
            return
        if self.undo_stack:
            self.project, description = self.undo_stack.pop()
            self.dirty = True
            self.refresh()
            self.statusBar().showMessage(T("Undid: ", "실행 취소: ") + description, 7000)

    def refresh(self):
        self._refreshing = True
        self.setWindowTitle(f"{'● ' if self.dirty else ''}{self.project.name} — ShopShift")
        self.title_label.setText(self.project.name)
        self.subtitle.setText(T("Times in ", "시간대 ") + f"{self.project.timezone}  ·  {_time(self.project.horizon_start, self.project)} → {_time(self.project.horizon_end, self.project)}  ·  "
                              + (str(self.path) if self.path else T("Not saved", "저장되지 않음")))
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
            self.metrics.setText(f"공정 {len(operations)}  ·  배치 {len(placements)}  ·  미배치 {len(set(operations) - set(placements))}  ·  지연 작업 {len(late_jobs)} (공정 {late_count})  ·  고정 {locked_count}  ·  충돌 {len(errors)}")
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
            if late:
                state = T(f"Late {_duration(placement.start + op.duration - op.due)}", f"{_duration(placement.start + op.duration - op.due)} 지연")
            else:
                state = T("Placed", "배치") if placement else T("Unscheduled", "미배치")
            if placement and placement.locked:
                state += " · " + T("Locked", "고정")
            _put_row(self.operations_table, self.operations_table.rowCount(), [op.id, op.job, op.machine, op.operator or "—",
                     _time(placement.start, self.project) if placement else "—", _time(placement.start + op.duration, self.project) if placement else "—",
                     f"{_duration(op.setup)} + {_duration(op.run)}", _time(op.due, self.project), state], op.id)
            if late:
                self.operations_table.item(self.operations_table.rowCount() - 1, 8).setForeground(QColor("#b4561b"))
        self.operations_table.blockSignals(False)
        self.timeline.set_project(self.project, visible, self.current_issues)
        self.issues_list.clear()
        warnings = len(self.current_issues) - len(errors)
        self.issue_heading.setText(T(f"Validation · {len(errors)} conflicts · {warnings} warnings — ", f"검증 · 충돌 {len(errors)} · 경고 {warnings} — ") + self._tr("inspect"))
        if not self.current_issues:
            self.issues_list.addItem(T("No scheduling conflicts detected.", "일정 충돌이 없습니다."))
        for issue in self.current_issues:
            item = QListWidgetItem(i18n.issue_line(issue))
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
            shown = T("Machine", "기계") if kind == "Machine" else T("Operator", "작업자")
            for resource in resources.values():
                windows = resource.windows
                _put_row(self.resources_table, self.resources_table.rowCount(), [shown, resource.id, len(windows),
                         _duration(sum(w.end - w.start for w in windows)), _time(min((w.start for w in windows), default=None), self.project),
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
            if a and b:
                shift = ("+" if b.start >= a.start else "") + _duration(b.start - a.start) if b.start != a.start else "0"
            else:
                shift = T("Placed", "배치") if b else T("Unscheduled", "미배치")
            late = max(0, b.start + op.duration - op.due) if b and op.due is not None else 0
            yes_no = (T("no", "아니요"), T("yes", "예"))
            _put_row(self.compare_table, self.compare_table.rowCount(), [op.id, op.job, _time(a.start, self.project) if a else "—",
                     _time(b.start, self.project) if b else "—", shift, _duration(late) if late else "—",
                     f"{yes_no[bool(a and a.locked)]} → {yes_no[bool(b and b.locked)]}"], op.id)
        self.compare_summary.setText(T(f"{self.project.active_scenario} compared with {name} · {changed} changed placements",
                                       f"{self.project.active_scenario}와(과) {name} 비교 · 바뀐 배치 {changed}개"))

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
                     op.job, op.id, op.operator or "—", T("Yes", "예") if placement.locked else "", _time(op.due, self.project)], op.id)
        for op in self.project.operations.values():
            if op.id not in self.project.scenario.placements:
                _put_row(self.daily_table, self.daily_table.rowCount(), [op.machine, T("Unscheduled", "미배치"), "—",
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
            self.statusBar().showMessage(T("Select an operation first.", "공정을 먼저 선택하세요."), 6000)

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
        self.apply_project(candidate, T(f"Edited placement {op_id}", f"{op_id} 배치 수정"))
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
        self.apply_project(candidate, T(f"Retired completed operation {op_id} from all scenarios", f"완료 공정 {op_id}을(를) 모든 시나리오에서 제거"))

    def retire_selected(self):
        op_id = self.selected_operation()
        if not op_id:
            self.statusBar().showMessage(T("Select an operation first.", "공정을 먼저 선택하세요."), 5000)
            return
        referenced = [op.id for op in self.project.operations.values() if op_id in op.predecessors]
        if referenced:
            self._error(T("Cannot retire a required predecessor", "선행 공정은 제거할 수 없음"),
                        ValueError(T(f"{op_id} is required by: {', '.join(referenced)}. Retire completed downstream operations first, or update dependencies through an ERP import.",
                                     f"{op_id}은(는) 다음 공정의 선행 공정입니다: {', '.join(referenced)}. 뒤 공정을 먼저 제거하거나 ERP 가져오기로 선행 관계를 바꾸세요.")))
            return
        count = sum(op_id in scenario.placements for scenario in self.project.scenarios.values())
        review = ReviewDialog(T("Retire completed operation", "완료 공정 제거"), op_id,
                              T(f"Remove this operation and its {count} placements from all scenarios. Other operations and resource calendars remain.\n\nUndo restores the operation. A later ERP import containing the same ID adds it again.",
                                f"이 공정과 모든 시나리오의 배치 {count}개를 제거합니다. 다른 공정과 근무 시간은 그대로입니다.\n\n실행 취소로 되돌릴 수 있습니다. 나중에 같은 ID가 든 ERP 파일을 가져오면 다시 추가됩니다."), self)
        if review.exec() == QDialog.DialogCode.Accepted:
            self.retire_operation(op_id)

    def switch_scenario(self, name: str):
        if self._refreshing or name not in self.project.scenarios or name == self.project.active_scenario:
            return
        candidate = deepcopy(self.project)
        candidate.active_scenario = name
        self.apply_project(candidate, T(f"Switched to scenario {name}", f"시나리오 {name}(으)로 전환"))

    def copy_scenario(self, name: str):
        name = name.strip()
        if not name or name in self.project.scenarios:
            raise ValueError(T("Use a new, nonempty scenario name.", "새 시나리오 이름을 입력하세요."))
        candidate = deepcopy(self.project)
        candidate.scenarios[name] = Scenario(name, deepcopy(candidate.scenario.placements))
        candidate.active_scenario = name
        self.apply_project(candidate, T(f"Copied scenario to {name}", f"시나리오를 {name}(으)로 복사"))

    def copy_scenario_dialog(self):
        name, accepted = QInputDialog.getText(self, T("Copy scenario", "시나리오 복사"), T("New scenario name", "새 시나리오 이름"))
        if accepted:
            try:
                self.copy_scenario(name)
            except ValueError as exc:
                self._error(T("Cannot copy scenario", "시나리오를 복사할 수 없음"), exc)

    def edit_project(self):
        dialog = ProjectDialog(self.project, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            candidate = deepcopy(self.project)
            candidate.name, candidate.timezone, candidate.horizon_start, candidate.horizon_end = dialog.values
            self.apply_project(candidate, T("Updated project settings", "프로젝트 설정 변경"))

    def _selected_resource(self):
        rows = self.resources_table.selectionModel().selectedRows()
        if not rows:
            self.statusBar().showMessage(T("Select a resource first.", "자원을 먼저 선택하세요."), 5000)
            return None
        value = self.resources_table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        kind, resource_id = value.split(":", 1)
        return kind, resource_id

    def add_resource(self):
        kinds = [T("Machine", "기계"), T("Operator", "작업자")]
        shown, accepted = QInputDialog.getItem(self, T("Resource type", "자원 유형"), T("Type", "유형"), kinds, editable=False)
        if not accepted:
            return
        kind = "Machine" if shown == kinds[0] else "Operator"
        name, accepted = QInputDialog.getText(self, T("Resource ID", "자원 ID"), T("Exact ID used in ERP exports", "ERP 파일에 쓰인 ID 그대로"))
        if not accepted:
            return
        name = name.strip()
        resources = self.project.machines if kind == "Machine" else self.project.operators
        if not name or name in resources:
            self._error(T("Cannot add resource", "자원을 추가할 수 없음"), ValueError(T("Use a new, nonempty resource ID.", "새 자원 ID를 입력하세요.")))
            return
        try:
            resource = Resource(name, working_windows(self.project.horizon_start, self.project.horizon_end, self.project.timezone))
        except (ValueError, OverflowError, OSError, KeyError) as exc:
            self._error(T("Cannot generate resource calendar", "근무 시간을 만들 수 없음"), exc)
            return
        dialog = CalendarDialog(self.project, resource, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            candidate = deepcopy(self.project)
            resource.windows = dialog.windows
            (candidate.machines if kind == "Machine" else candidate.operators)[name] = resource
            self.apply_project(candidate, T(f"Added {kind.lower()} {name}", f"{T('Machine', '기계') if kind == 'Machine' else T('Operator', '작업자')} {name} 추가"))

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
            self.apply_project(candidate, T(f"Updated {resource_id} calendar", f"{resource_id} 근무 시간 변경"))

    def remove_resource(self):
        selected = self._selected_resource()
        if not selected:
            return
        kind, resource_id = selected
        used = [op.id for op in self.project.operations.values() if (op.machine if kind == "Machine" else op.operator) == resource_id]
        if used:
            self._error(T("Resource is in use", "사용 중인 자원"), ValueError(T("Update the ERP export assignment before removing this resource: ", "이 자원을 지우기 전에 ERP 파일의 배정을 바꾸세요: ") + ", ".join(used[:10])))
            return
        candidate = deepcopy(self.project)
        del (candidate.machines if kind == "Machine" else candidate.operators)[resource_id]
        self.apply_project(candidate, T(f"Removed {resource_id}", f"{resource_id} 삭제"))

    def import_from(self, path, mapping, unit="minutes", apply=False):
        from .importing import import_operations
        result = import_operations(self.project, path, mapping, duration_unit=unit)
        if apply:
            self.apply_project(result.project, T(f"Imported {Path(path).name}", f"{Path(path).name} 가져옴"))
        return result

    def import_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, T("Import ERP export", "ERP 파일 가져오기"), "", T("ERP exports (*.csv *.xlsx)", "ERP 파일 (*.csv *.xlsx)"))
        if not path:
            return
        try:
            mapping = MappingDialog(self.project, path, self)
            if mapping.exec() != QDialog.DialogCode.Accepted:
                return
            result = self.import_from(path, mapping.mapping, mapping.unit.currentText())
            issues = validate(result.project)
            summary = T(f"{len(result.added)} added · {len(result.updated)} updated · {len(result.retained)} retained",
                        f"추가 {len(result.added)} · 갱신 {len(result.updated)} · 유지 {len(result.retained)}")
            details = T("All existing placements and locks are retained by operation ID. Omitted operations remain in the project.\n\n",
                        "기존 배치와 고정은 공정 ID 기준으로 모두 유지됩니다. 파일에 없는 공정도 프로젝트에 남습니다.\n\n")
            details += (T("Added: ", "추가: ") + ", ".join(result.added) + T("\nUpdated: ", "\n갱신: ") + ", ".join(result.updated)
                        + T("\nRetained: ", "\n유지: ") + ", ".join(result.retained))
            details += (T("\n\nIMPORT NOTES\n", "\n\n가져오기 참고\n") + "\n".join(result.warnings) + T("\n\nVALIDATION\n", "\n\n검증\n")
                        + (_issues_text(issues) or T("No conflicts.", "충돌 없음.")))
            review = ReviewDialog(T("Review import", "가져오기 검토"), summary, details, self)
            if review.exec() == QDialog.DialogCode.Accepted:
                self.apply_project(result.project, T(f"Imported {Path(path).name}", f"{Path(path).name} 가져옴"))
        except Exception as exc:  # noqa: BLE001 - preserve the live draft and report UI boundary failures.
            self._error(T("Import failed — project unchanged", "가져오기 실패 — 프로젝트는 그대로입니다"), exc)

    def start_suggest(self, _checked=False, *, show_review=True, time_limit=5.0):
        if self._solver_thread is not None:
            return
        if not self.project.operations:
            self.statusBar().showMessage(T("Import operations first.", "먼저 공정을 가져오세요."), 6000)
            return
        self._show_solver_review = show_review
        self._solver_snapshot = deepcopy(self.project)
        self.suggest_button.setEnabled(False)
        self.project_settings_button.setEnabled(False)
        self.tabs.setEnabled(False)
        for action in self.actions.values():
            action.setEnabled(False)
        self.statusBar().showMessage(T("Computing a proposal… The current plan stays unchanged.", "일정 제안을 계산하는 중… 지금 계획은 바뀌지 않습니다."))
        self._solver_thread = QThread(self)
        self._solver_worker = _SolverWorker(self._solver_snapshot, min(30.0, max(0.05, time_limit)), self.suggestion_weights())
        self._solver_worker.moveToThread(self._solver_thread)
        self._solver_thread.started.connect(self._solver_worker.run)
        self._solver_worker.result.connect(self._on_solved)
        self._solver_worker.failed.connect(self._on_solver_failed)
        self._solver_worker.finished.connect(self._solver_thread.quit)
        self._solver_worker.finished.connect(self._solver_worker.deleteLater)
        self._solver_thread.finished.connect(self._solver_done)
        self._solver_thread.start()

    def suggestion_weights(self) -> tuple[int, int]:
        """Lateness and finish-time weights from the sliders; both 0 means equal."""
        weights = (self.weightDue.value(), self.weightFinish.value())
        return weights if any(weights) else (1, 1)

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
        self.statusBar().showMessage(T("Scheduling failed. The current plan is unchanged.", "일정 계산 실패. 지금 계획은 그대로입니다."))
        if self._show_solver_review:
            self._error(T("Scheduling failed", "일정 계산 실패"), RuntimeError(message))

    def _on_solved(self, result):
        self.last_solve_result = result
        self.schedule_ready.emit(result)
        self.statusBar().showMessage(T(f"Proposal: {result.status} · {result.wall_time:.2f}s. Review it before applying.",
                                       f"제안: {result.status} · {result.wall_time:.2f}초. 적용하기 전에 검토하세요."))
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
                changes.append(f"{op_id}: {_time(old.start, self.project) if old else T('Unscheduled', '미배치')} → {_time(placement.start, self.project)}")
        due, finish = self.suggestion_weights()
        details = T(f"Status: {result.status}\nTime: {result.wall_time:.2f}s\nPriorities: due dates {due}, finish early {finish}\n\n",
                    f"상태: {result.status}\n계산 시간: {result.wall_time:.2f}초\n우선순위: 납기 {due}, 빨리 끝내기 {finish}\n\n")
        details += T("The suggestion minimizes lateness past due times and the time the last operation finishes, weighted by the two sliders. Due dates are targets, not hard limits. Optimal means proved best for these priorities; feasible means a complete, checked plan without that proof.\n\n",
                     "제안은 두 슬라이더의 비중대로 납기 지연과 마지막 공정이 끝나는 시각을 줄입니다. 납기는 목표일 뿐 절대 조건이 아닙니다. optimal은 이 우선순위에서 가장 좋다고 증명된 계획, feasible은 증명은 없지만 검증을 통과한 완전한 계획입니다.\n\n")
        details += T("CHANGES\n", "변경\n") + ("\n".join(changes) or T("No placement changes.", "바뀐 배치 없음."))
        details += T("\n\nVALIDATION\n", "\n\n검증\n") + (_issues_text(issues) or T("No conflicts. All operations are placed.", "충돌 없음. 모든 공정이 배치되었습니다."))
        review = ReviewDialog(T("Review scheduling proposal", "일정 제안 검토"),
                              T(f"{result.status.upper()} · {len(result.placements)} / {len(self.project.operations)} operations placed",
                                f"{result.status.upper()} · 공정 {len(self.project.operations)}개 중 {len(result.placements)}개 배치"), details, self, can_apply)
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
        self.apply_project(candidate, T(f"Applied {result.status} scheduling proposal", f"일정 제안({result.status}) 적용"))

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = QMessageBox.warning(self, T("Unsaved changes", "저장되지 않은 변경"), T("Save changes before continuing?", "계속하기 전에 변경 사항을 저장할까요?"),
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
                if self.set_project(candidate):
                    self.dirty = True
                    self.refresh()

    def load_demo(self):
        if self._confirm_discard():
            from .demo import demo_project
            self.set_project(demo_project())
            self.statusBar().showMessage(T("Synthetic demo opened. Save a copy to keep edits.", "예제를 열었습니다. 수정 내용을 남기려면 다른 이름으로 저장하세요."), 9000)

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, T("Open project", "프로젝트 열기"), "", T("ShopShift projects (*.shopshift *.json);;All files (*)", "ShopShift 프로젝트 (*.shopshift *.json);;모든 파일 (*)"))
        if path and self._confirm_discard():
            self.open_path(path)

    def open_path(self, path) -> bool:
        from .storage import load_project
        try:
            project = load_project(path)
            return self.set_project(project, path)
        except Exception as exc:  # noqa: BLE001 - preserve the live draft and report UI boundary failures.
            message = str(exc)
            if Path(str(path) + ".bak").exists():
                message += T("\nA previous-save backup exists. Use File → Restore backup to inspect it.", "\n이전 저장본의 백업이 있습니다. 파일 → 백업 복원으로 확인하세요.")
            self._error(T("Cannot open project — current project unchanged", "프로젝트를 열 수 없음 — 지금 프로젝트는 그대로입니다"), ValueError(message))
            return False

    def save_to(self, path) -> bool:
        from .storage import save_project
        try:
            save_project(self.project, path)
        except Exception as exc:  # noqa: BLE001 - preserve the live draft and report UI boundary failures.
            self._error(T("Save failed — changes are still in memory", "저장 실패 — 변경 내용은 아직 남아 있습니다"), exc)
            return False
        self.path = Path(path)
        self.dirty = False
        self.refresh()
        self.statusBar().showMessage(T(f"Saved {self.path.name}", f"{self.path.name} 저장함"), 6000)
        return True

    def save(self) -> bool:
        return self.save_to(self.path) if self.path else self.save_as()

    def save_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, T("Save project", "프로젝트 저장"), str(self.path or "shop-plan.shopshift"), T("ShopShift project (*.shopshift)", "ShopShift 프로젝트 (*.shopshift)"))
        return self.save_to(path) if path else False

    def backup(self):
        from .storage import backup_project
        path, _ = QFileDialog.getSaveFileName(self, T("Create backup", "백업 만들기"), "shop-plan-backup.shopshift", T("ShopShift backup (*.shopshift)", "ShopShift 백업 (*.shopshift)"))
        if path:
            try:
                backup_project(self.project, path)
                self.statusBar().showMessage(T(f"Backup created: {Path(path).name}", f"백업 만듦: {Path(path).name}"), 6000)
            except Exception as exc:  # noqa: BLE001 - preserve the live draft and report UI boundary failures.
                self._error(T("Backup failed", "백업 실패"), exc)

    def restore(self):
        from .storage import load_project
        path, _ = QFileDialog.getOpenFileName(self, T("Restore backup", "백업 복원"), "", T("Backups (*.shopshift *.bak *.json);;All files (*)", "백업 (*.shopshift *.bak *.json);;모든 파일 (*)"))
        if not path:
            return
        try:
            project = load_project(path)
            review = ReviewDialog(T("Review backup", "백업 검토"), project.name,
                                  T(f"{len(project.operations)} operations · {len(project.scenarios)} scenarios", f"공정 {len(project.operations)} · 시나리오 {len(project.scenarios)}")
                                  + f"\n{project.timezone}\n\n" + (_issues_text(validate(project)) or T("No validation conflicts.", "검증 충돌 없음.")), self)
            if review.exec() == QDialog.DialogCode.Accepted and self._confirm_discard() and self.set_project(project):
                self.dirty = True
                self.refresh()
                self.statusBar().showMessage(T("Backup restored in memory. Save as a project to keep it.", "백업을 불러왔습니다. 남기려면 프로젝트로 저장하세요."), 9000)
        except Exception as exc:  # noqa: BLE001 - preserve the live draft and report UI boundary failures.
            self._error(T("Restore failed — current project unchanged", "복원 실패 — 지금 프로젝트는 그대로입니다"), exc)

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
            path, _ = QFileDialog.getSaveFileName(self, T("Export read-only work list", "읽기 전용 작업 목록 내보내기"), filename, file_filter)
            if path:
                exporter(self.project, path, day=day)
                self.statusBar().showMessage(T(f"Exported {Path(path).name} · includes validation warnings", f"{Path(path).name} 내보냄 · 검증 경고 포함"), 7000)
        except Exception as exc:  # noqa: BLE001 - preserve the live draft and report UI boundary failures.
            self._error(T("Export failed", "내보내기 실패"), exc)

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
            self._error(T("Printing failed — you can also export HTML", "인쇄 실패 — HTML로 내보낼 수도 있습니다"), exc)

    def _error(self, title, error):
        QMessageBox.critical(self, title, str(error))

    def about(self):
        QMessageBox.about(self, T("About ShopShift", "ShopShift 정보"), T(
            "<h2>ShopShift 0.2.0</h2><p>Offline scheduling workbench for one planner. No telemetry, accounts or ERP writes.</p>"
            "<p>ShopShift is MIT licensed. The interface uses <b>Qt / PySide6 under LGPLv3</b>. "
            "Scheduling uses the official Google OR-Tools CP-SAT engine (Apache-2.0).</p>"
            "<p>See the distribution’s <b>THIRD_PARTY_NOTICES</b> and <b>licenses</b> directory for license texts, "
            "corresponding Qt sources and instructions for replacing LGPL libraries.</p>"
            "<p>Plans are decision support. Review constraints and exports before issuing production instructions. "
            "Fixed assignments, nonpreemptive operations, no sequence-dependent setup.</p>",
            "<h2>ShopShift 0.2.0</h2><p>계획 담당자 한 명을 위한 오프라인 일정 작업 도구입니다. 사용 기록 전송, 계정, ERP 쓰기가 없습니다.</p>"
            "<p>ShopShift는 MIT 라이선스입니다. 화면은 <b>Qt / PySide6 (LGPLv3)</b>를, 일정 계산은 Google OR-Tools CP-SAT (Apache-2.0)를 씁니다.</p>"
            "<p>라이선스 원문, Qt 소스, LGPL 라이브러리 교체 방법은 배포본의 <b>THIRD_PARTY_NOTICES</b>와 <b>licenses</b> 폴더에 있습니다.</p>"
            "<p>계획은 결정을 돕는 자료입니다. 생산 지시 전에 제약 조건과 내보낸 파일을 검토하세요. "
            "배정은 고정이고, 공정은 중간에 끊기지 않으며, 순서에 따른 준비 시간은 다루지 않습니다.</p>"))

    def closeEvent(self, event):
        if self._solver_thread is not None:
            self.statusBar().showMessage(T("Wait for the scheduling proposal to finish, then close.", "일정 계산이 끝난 다음 닫으세요."), 10000)
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
