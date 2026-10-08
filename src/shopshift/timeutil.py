"""Whole-second UTC timestamps with explicit local-time ambiguity checks.

Local date-times are accepted only when they identify one instant in an IANA
zone. Supply an ISO offset for repeated clocks at the end of daylight saving.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .model import MAX_TIMESTAMP, MIN_TIMESTAMP, Window

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?$")
MAX_HORIZON_SECONDS = 366 * 86400


def _epoch_seconds(value: datetime) -> int:
    try:
        result = int(value.timestamp())
    except (OverflowError, OSError) as exc:
        raise ValueError("Timestamp is outside the supported datetime range") from exc
    if not MIN_TIMESTAMP <= result <= MAX_TIMESTAMP:
        raise ValueError("Timestamp is outside the supported UTC range (years 0001–9999)")
    return result


def _zone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError(f"Unknown IANA timezone: {timezone!r}") from exc


def parse_timestamp(value: str, timezone: str) -> int:
    """Parse ISO date-time to epoch seconds; never round or guess a DST fold."""
    zone = _zone(timezone)
    value = str(value).strip()
    if not _ISO.fullmatch(value):
        raise ValueError("Use ISO date and time, e.g. 2026-10-05T08:00 or 2026-11-01T01:30-05:00; whole seconds only")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid date or time: {value}") from exc
    # datetime normalizes malformed offset minutes, so validate before accepting.
    if value[-6:-5] in ("+", "-") and (int(value[-2:]) > 59 or int(value[-5:-3]) > 23):
        raise ValueError(f"Invalid UTC offset: {value[-6:]}")
    if parsed.tzinfo is not None:
        return _epoch_seconds(parsed)
    candidates = set()
    for fold in (0, 1):
        aware = parsed.replace(tzinfo=zone, fold=fold)
        try:
            instant = aware.astimezone(dt_timezone.utc)
            if instant.astimezone(zone).replace(tzinfo=None) == parsed:
                candidates.add(_epoch_seconds(instant))
        except (OverflowError, OSError) as exc:
            raise ValueError("Timestamp is outside the supported datetime range") from exc
    if not candidates:
        raise ValueError(f"Local time does not exist in {timezone} (DST gap): {value}; supply a valid time")
    if len(candidates) > 1:
        raise ValueError(f"Local time is ambiguous in {timezone} (DST fold): {value}; include a UTC offset")
    return candidates.pop()


def format_timestamp(epoch: int, timezone: str) -> str:
    """Return an offset-bearing timestamp suitable for display and reimport."""
    if type(epoch) is not int:
        raise ValueError("Timestamp must be an integer number of seconds")
    if not MIN_TIMESTAMP <= epoch <= MAX_TIMESTAMP:
        raise ValueError("Timestamp is outside the supported UTC range (years 0001–9999)")
    try:
        return datetime.fromtimestamp(epoch, _zone(timezone)).isoformat(timespec="seconds")
    except (OverflowError, OSError) as exc:
        raise ValueError("Timestamp cannot be displayed in this timezone within years 0001–9999") from exc


def day_bounds(day: date | str, timezone: str) -> tuple[int, int]:
    """Return the UTC half-open interval for a local calendar date.

    A repeated midnight uses its earliest occurrence. If midnight falls in a
    forward clock gap, the boundary is the first represented instant after it.
    An entirely skipped date is rejected. Unlike an operation timestamp, a
    calendar date needs no offset to distinguish the two midnight occurrences.
    """
    try:
        selected = date.fromisoformat(day) if isinstance(day, str) else day
        if type(selected) is not date or (isinstance(day, str) and selected.isoformat() != day):
            raise ValueError("Day must be a date or YYYY-MM-DD")
        following = selected + timedelta(days=1)
        zone = _zone(timezone)

        def local(instant: int) -> datetime:
            return datetime.fromtimestamp(instant, zone).replace(tzinfo=None)

        def boundary(value: date) -> int:
            midnight = datetime.combine(value, time())
            candidates = sorted({_epoch_seconds(midnight.replace(tzinfo=zone, fold=fold))
                                 for fold in (0, 1)})
            represented = [instant for instant in candidates if local(instant) == midnight]
            if represented:
                return represented[0]
            # ZoneInfo's two fold choices bracket a forward transition when
            # the wall time is missing. Locate its first second logarithmically
            # rather than scanning an hour (or a skipped 24-hour civil date).
            low, high = candidates[0], candidates[-1]
            if not local(low) < midnight < local(high):
                raise ValueError(f"Cannot resolve calendar boundary {value} in {timezone}")
            while high - low > 1:
                middle = (low + high) // 2
                if local(middle) < midnight:
                    low = middle
                else:
                    high = middle
            return high

        start = boundary(selected)
        if local(start).date() != selected:
            raise ValueError(f"Civil date {selected} does not exist in {timezone}")
        return start, boundary(following)
    except (OverflowError, OSError) as exc:
        raise ValueError("Work-list day boundaries must fit within supported UTC years 0001–9999") from exc


def working_windows(start: int, end: int, timezone: str, start_hour: int = 8, end_hour: int = 17) -> list[Window]:
    """Weekday availability clipped to the horizon, excluding local 12:00–13:00.

An end hour earlier than the start hour creates an overnight shift ending the
next day. Weekday means the shift's starting day. DST-ambiguous boundaries are
rejected; explicit custom UTC windows can express the desired choice instead.
"""
    zone = _zone(timezone)
    if type(start) is not int or type(end) is not int or not 0 < end - start <= MAX_HORIZON_SECONDS:
        raise ValueError("Calendar horizon must be positive and at most 366 days")
    if (type(start_hour) is not int or type(end_hour) is not int
            or not 0 <= start_hour <= 23 or not 0 <= end_hour <= 24 or start_hour == end_hour):
        raise ValueError("Shift hours must be distinct integer hours (start 0–23, end 0–24)")
    first = datetime.fromtimestamp(start, zone).date() - timedelta(days=1)
    last = datetime.fromtimestamp(end, zone).date()
    windows: list[Window] = []
    day = first
    while day <= last:
        if day.weekday() < 5:
            begin = datetime.combine(day, time(start_hour))
            finish = datetime.combine(day, time()) + timedelta(hours=end_hour)
            if finish <= begin:
                finish += timedelta(days=1)
            segments = [(begin, finish)]
            # Exclude each local lunch period intersected by a shift.
            lunch_day = day
            while lunch_day <= finish.date():
                lunch_start = datetime.combine(lunch_day, time(12))
                lunch_end = datetime.combine(lunch_day, time(13))
                pieces = []
                for a, b in segments:
                    if b <= lunch_start or a >= lunch_end:
                        pieces.append((a, b))
                    else:
                        if a < lunch_start:
                            pieces.append((a, lunch_start))
                        if b > lunch_end:
                            pieces.append((lunch_end, b))
                segments = pieces
                lunch_day += timedelta(days=1)
            for begin, finish in segments:
                a = max(start, parse_timestamp(begin.isoformat(), timezone))
                b = min(end, parse_timestamp(finish.isoformat(), timezone))
                if a < b:
                    windows.append(Window(a, b))
        day += timedelta(days=1)
    windows.sort(key=lambda w: w.start)
    # Adjacent windows form continuous availability (e.g. 24-hour weekdays).
    merged: list[Window] = []
    for window in windows:
        if merged and window.start <= merged[-1].end:
            merged[-1] = Window(merged[-1].start, max(merged[-1].end, window.end))
        else:
            merged.append(window)
    return merged
