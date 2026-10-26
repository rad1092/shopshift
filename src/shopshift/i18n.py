"""Interface language, human-readable times and durations, and issue wording.

The engine keeps integer UTC seconds and English issue messages for files and
logs. Everything a planner reads on screen goes through this module so that
one language setting switches the whole window.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

_LANGUAGE = ["en"]
_WEEKDAYS = {"en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"), "ko": ("월", "화", "수", "목", "금", "토", "일")}


def set_language(language: str) -> None:
    _LANGUAGE[0] = "ko" if language == "ko" else "en"


def language() -> str:
    return _LANGUAGE[0]


def T(english: str, korean: str) -> str:
    """Pick the string for the current interface language."""
    return korean if _LANGUAGE[0] == "ko" else english


def duration(seconds: int | None) -> str:
    """30 min, 2 h 15 min, 1 day 3 h; Korean 30분, 2시간 15분, 1일 3시간."""
    if seconds is None:
        return "—"
    sign = "-" if seconds < 0 else ""
    seconds = abs(int(seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    ko = _LANGUAGE[0] == "ko"
    units = (("일", " day", " days"), ("시간", " h", " h"), ("분", " min", " min"), ("초", " s", " s"))
    parts = []
    for value, (korean, one, many) in zip((days, hours, minutes, secs), units):
        if value and len(parts) < 2:
            parts.append(f"{value}{korean}" if ko else f"{value}{one if value == 1 else many}")
    if not parts:
        return "0분" if ko else "0 min"
    return sign + " ".join(parts)


def when(timestamp: int | None, timezone: str) -> str:
    """A wall-clock time a planner reads at a glance: Mon 10/05 08:00, Korean 10/05 (월) 08:00.

    The zone is shown once in the window, not on every time.
    """
    if timestamp is None:
        return "—"
    try:
        local = datetime.fromtimestamp(timestamp, ZoneInfo(timezone))
    except (ValueError, OverflowError, OSError, KeyError):
        return str(timestamp)
    day = _WEEKDAYS[_LANGUAGE[0]][local.weekday()]
    if _LANGUAGE[0] == "ko":
        return f"{local:%m/%d} ({day}) {local:%H:%M}"
    return f"{day} {local:%m/%d %H:%M}"


def severity(issue) -> str:
    if issue.severity == "error":
        return T("Conflict", "충돌")
    return T("Warning", "경고")


def describe(issue) -> str:
    """Planner-facing wording for scheduling issues; structural ones keep the engine text."""
    code, ids, amount, subject = issue.code, issue.operation_ids, issue.amount, issue.subject
    first = ids[0] if ids else ""
    span = duration(amount) if amount is not None else ""
    if code == "late":
        return T(f"{first}: finishes {span} after its due time", f"{first}: 납기보다 {span} 늦게 끝남")
    if code == "unscheduled":
        return T(f"{first}: not scheduled", f"{first}: 배치되지 않음")
    if code == "before_release":
        return T(f"{first}: starts {span} before it can be released", f"{first}: 작업 가능 시각보다 {span} 일찍 시작")
    if code == "precedence" and len(ids) == 2:
        return T(f"{ids[1]}: starts {span} before {ids[0]} finishes", f"{ids[1]}: 선행 공정 {ids[0]}이(가) 끝나기 {span} 전에 시작")
    if code == "unscheduled_predecessor" and len(ids) == 2:
        return T(f"{ids[0]}: order can't be checked until {ids[1]} is scheduled",
                 f"{ids[0]}: 선행 공정 {ids[1]}을(를) 배치해야 순서를 확인할 수 있음")
    if code in ("machine_overlap", "operator_overlap") and len(ids) == 2:
        kind = T("machine", "기계") if code.startswith("machine") else T("operator", "작업자")
        return T(f"{ids[0]} and {ids[1]} overlap on {kind} {subject} for {span}",
                 f"{ids[0]}와(과) {ids[1]}이(가) {kind} {subject}에서 {span} 겹침")
    if code in ("machine_calendar", "operator_calendar"):
        kind = T("machine", "기계") if code.startswith("machine") else T("operator", "작업자")
        return T(f"{first}: runs outside the working hours of {kind} {subject}",
                 f"{first}: {kind} {subject}의 근무 시간 밖에서 작업함")
    if code == "outside_horizon":
        return T(f"{first}: outside the planning period", f"{first}: 계획 기간 밖에 있음")
    return issue.message


def issue_line(issue) -> str:
    return f"{severity(issue)} · {describe(issue)}"
