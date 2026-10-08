"""Versioned local projects, atomic backups, and safe read-only work lists."""

from __future__ import annotations

import csv
import html
import io
import json
import os
import tempfile
from pathlib import Path

from .model import Project
from .timeutil import day_bounds, format_timestamp

FORMAT_VERSION = 1
MAX_PROJECT_BYTES = 20 * 1024 * 1024


class StorageProblem(ValueError):
    """A project could not be read or safely replaced."""


def _bounded(payload: object, depth: int = 0) -> None:
    if depth > 12:
        raise StorageProblem("Project nesting exceeds the supported schema")
    if isinstance(payload, dict):
        if len(payload) > 10_000:
            raise StorageProblem("Project object exceeds 10,000 entries")
        for key, value in payload.items():
            _bounded(key, depth + 1)
            _bounded(value, depth + 1)
    elif isinstance(payload, list):
        if len(payload) > 10_000:
            raise StorageProblem("Project array exceeds 10,000 entries")
        for value in payload:
            _bounded(value, depth + 1)
    elif isinstance(payload, str) and len(payload) > 4096:
        raise StorageProblem("Project text value exceeds 4,096 characters")


def _checked_project(payload: object) -> Project:
    _bounded(payload)
    try:
        project = Project.from_dict(payload)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise StorageProblem(f"Invalid project schema: {exc}") from exc
    if len(project.scenarios) > 100:
        raise StorageProblem("Project exceeds 100 scenarios")
    if len(project.machines) + len(project.operators) > 2000:
        raise StorageProblem("Project exceeds 2,000 resources")
    if sum(len(resource.windows) for resource in (*project.machines.values(), *project.operators.values())) > 100_000:
        raise StorageProblem("Project exceeds 100,000 availability windows")
    return project


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise StorageProblem(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _decode(data: bytes) -> Project:
    if len(data) > MAX_PROJECT_BYTES:
        raise StorageProblem("Project exceeds 20 MiB")
    try:
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates,
                             parse_constant=lambda value: (_ for _ in ()).throw(StorageProblem(f"Invalid JSON {value}")))
        if not isinstance(payload, dict) or set(payload) != {"format", "version", "project"}:
            raise StorageProblem("Expected a ShopShift project file with format, version, and project fields")
        if payload["format"] != "shopshift" or type(payload["version"]) is not int or payload["version"] != FORMAT_VERSION:
            raise StorageProblem("Unsupported project format/version")
        return _checked_project(payload["project"])
    except StorageProblem:
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise StorageProblem(f"Corrupt project file: {exc}") from exc


def _encode(project: Project) -> bytes:
    try:
        payload = project.to_dict()
        _checked_project(payload)
        encoded = (json.dumps({"format": "shopshift", "version": FORMAT_VERSION, "project": payload},
                              ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
    except StorageProblem:
        raise
    except (ValueError, TypeError, AttributeError, RecursionError) as exc:
        raise StorageProblem(f"Invalid project: {exc}") from exc
    if len(encoded) > MAX_PROJECT_BYTES:
        raise StorageProblem("Project exceeds 20 MiB")
    return encoded


def _fsync_directory(directory: Path) -> None:
    # Windows has no portable directory fsync; file flushing + replace still
    # avoids partial JSON, but sudden power-loss guarantees depend on the FS.
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, content: bytes) -> None:
    if path.is_symlink():
        raise StorageProblem(f"Refusing to replace a symbolic link: {path.name}")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def load_project(path) -> Project:
    """Load exactly the selected file; recovery never silently hides corruption.

To recover, explicitly select ``path + '.bak'`` using this same function, then
save under a new name, or call restore_project to replace a damaged file.
"""
    path = Path(path)
    try:
        if path.stat().st_size > MAX_PROJECT_BYTES:
            raise StorageProblem("Project exceeds 20 MiB")
        return _decode(path.read_bytes())
    except (OSError, StorageProblem) as exc:
        recovery = f" A previous version is available at {path.name}.bak; open it explicitly to recover." if Path(str(path) + ".bak").is_file() else ""
        raise StorageProblem(f"Could not open {path.name}: {exc}.{recovery}") from exc


def save_project(project: Project, path) -> None:
    """Persist atomically, keeping the previous valid bytes at ``path + '.bak'``.

The original stays in place if writing the backup or new file fails before its
atomic replacement. This is a single-planner format, without multiwriter locks.
"""
    path = Path(path)
    encoded = _encode(project)
    try:
        if path.is_symlink():
            raise StorageProblem("Choose a regular project file, not a symbolic link")
        if path.exists():
            if path.stat().st_size > MAX_PROJECT_BYTES:
                raise StorageProblem("Existing file exceeds 20 MiB; save under a new name")
            previous = path.read_bytes()
            try:
                _decode(previous)
            except StorageProblem as exc:
                raise StorageProblem("Existing file is corrupt. Preserve it and save under a new name, "
                                     "or explicitly restore a valid backup") from exc
            _atomic_write(Path(str(path) + ".bak"), previous)
        _atomic_write(path, encoded)
    except OSError as exc:
        raise StorageProblem(f"Could not save {path.name}: {exc}") from exc


def backup_project(project: Project, path) -> None:
    """Write a portable full project backup, using the same atomic safeguards."""
    save_project(project, path)


def restore_project(backup_path, destination_path) -> Project:
    """Explicitly restore a selected valid backup, preserving damaged bytes.

An existing corrupt destination is copied to ``.corrupt`` before replacement.
An existing .corrupt file is not overwritten; use a new destination in that case.
"""
    backup_path, destination_path = Path(backup_path), Path(destination_path)
    restored = load_project(backup_path)
    encoded = _encode(restored)
    try:
        if destination_path.exists():
            if destination_path.stat().st_size > MAX_PROJECT_BYTES:
                raise StorageProblem("Damaged destination exceeds 20 MiB; restore under a new name")
            previous = destination_path.read_bytes()
            try:
                _decode(previous)
            except StorageProblem:
                corrupt_path = Path(str(destination_path) + ".corrupt")
                if corrupt_path.exists():
                    raise StorageProblem("A .corrupt recovery copy already exists; restore under a new name")
                _atomic_write(corrupt_path, previous)
                _atomic_write(destination_path, encoded)
                return restored
        save_project(restored, destination_path)
        return restored
    except OSError as exc:
        raise StorageProblem(f"Could not restore {destination_path.name}: {exc}") from exc


def _day_range(day, timezone: str) -> tuple[int, int] | None:
    if day is None:
        return None
    try:
        return day_bounds(day, timezone)
    except ValueError as exc:
        raise StorageProblem(f"Invalid work-list day: {exc}") from exc


def _plan(project: Project, day=None):
    from .validator import validate
    issues = validate(project)
    selected = _day_range(day, project.timezone)
    headers = ["operation_id", "job", "label", "machine", "operator", "start", "end", "setup_seconds",
               "run_seconds", "due", "late_seconds", "locked", "status", "warnings"]
    rows = []
    placements = project.scenario.placements
    for operation in sorted(project.operations.values(), key=lambda op: (placements[op.id].start if op.id in placements else float("inf"), op.machine, op.id)):
        placement = placements.get(operation.id)
        end = placement.start + operation.duration if placement else None
        # Include overnight intersections, and keep unscheduled work visible.
        if selected and placement and not (placement.start < selected[1] and end > selected[0]):
            continue
        related = [f"{issue.severity.upper()} {issue.code}: {issue.message}" for issue in issues
                   if not issue.operation_ids or operation.id in issue.operation_ids]
        late = max(0, end - operation.due) if end is not None and operation.due is not None else ""
        rows.append([operation.id, operation.job, operation.label, operation.machine, operation.operator,
                     format_timestamp(placement.start, project.timezone) if placement else "",
                     format_timestamp(end, project.timezone) if end is not None else "",
                     operation.setup, operation.run,
                     format_timestamp(operation.due, project.timezone) if operation.due is not None else "",
                     late, "yes" if placement and placement.locked else "no",
                     "UNSCHEDULED" if placement is None else "LATE" if late else "SCHEDULED",
                     " | ".join(related)])
    return headers, rows, issues


def _safe_csv(value: object) -> str:
    text = str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def export_csv(project: Project, path, day=None) -> None:
    """Export a read-only work list, escaping spreadsheet formula prefixes.

This work-list format is not an ERP round-trip export. Unscheduled operations
remain visible for every day. Validation issues appear in each applicable row.
"""
    headers, rows, issues = _plan(project, day)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, quoting=csv.QUOTE_ALL)
    writer.writerow([*headers, "plan", "timezone", "scenario", "selected_day"])
    for row in rows:
        writer.writerow([_safe_csv(value) for value in [*row, "DRAFT — review before production", project.timezone,
                                                       project.active_scenario, str(day or "all")]])
    # Even an empty work list should carry diagnostics.
    if not rows and issues:
        warning_row = [""] * len(headers)
        warning_row[-1] = " | ".join(f"{issue.code}: {issue.message}" for issue in issues)
        writer.writerow([_safe_csv(value) for value in [*warning_row, "DRAFT — no operations", project.timezone,
                                                       project.active_scenario, str(day or "all")]])
    try:
        _atomic_write(Path(path), stream.getvalue().encode("utf-8-sig"))
    except OSError as exc:
        raise StorageProblem(f"Could not export CSV: {exc}") from exc


def export_html(project: Project, path, day=None) -> None:
    """Write a self-contained printable snapshot; all user text is HTML escaped."""
    headers, rows, issues = _plan(project, day)
    def esc(value):
        return html.escape(str(value), quote=True)
    issue_markup = "".join(f"<li>{esc(issue.severity.upper())} {esc(issue.code)}: {esc(issue.message)}</li>" for issue in issues)
    body = "".join("<tr>" + "".join(f"<td>{esc(value)}</td>" for value in row) + "</tr>" for row in rows)
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>{esc(project.name)} — work list</title>
<style>body{{font:13px system-ui,sans-serif;margin:24px;color:#18212b}}h1{{font-size:23px}}
table{{border-collapse:collapse;width:100%;font-size:11px}}th,td{{border:1px solid #bbc5cc;padding:6px;text-align:left;vertical-align:top;overflow-wrap:anywhere}}
th{{background:#eef3f5}}.notice{{padding:12px;background:#fff3d4;border:1px solid #a5781f}}
@media print{{@page{{size:landscape;margin:10mm}}body{{margin:0}}thead{{display:table-header-group}}tr{{break-inside:avoid}}}}</style></head>
<body><h1>{esc(project.name)}</h1><p class="notice">DRAFT — planner review required before production. Read-only snapshot; it does not update an ERP or commit work.</p>
<p>Scenario: {esc(project.active_scenario)} · Timezone: {esc(project.timezone)} · Day: {esc(day or 'All scheduled days')}. Unscheduled operations remain visible.</p>
<h2>Validation and warnings</h2><ul>{issue_markup or '<li>No validation issues detected.</li>'}</ul>
<table><thead><tr>{''.join(f'<th>{esc(header)}</th>' for header in headers)}</tr></thead><tbody>{body}</tbody></table>
<p>Times include UTC offsets. Setup and run values are whole seconds. Generated locally by ShopShift.</p></body></html>
"""
    try:
        _atomic_write(Path(path), document.encode("utf-8"))
    except OSError as exc:
        raise StorageProblem(f"Could not export HTML: {exc}") from exc
