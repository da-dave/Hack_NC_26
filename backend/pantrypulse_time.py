"""Small, dependency-free date/time parser for PantryPulse's iMessage forms."""
from __future__ import annotations
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")


def parse_day(answer: str) -> date:
    text = answer.strip().lower()
    today = datetime.now(TZ).date()
    if text in ("today", "tonight"):
        return today
    if text in ("tomorrow", "tmrw", "tmr"):
        return today + timedelta(days=1)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d"):
        try:
            result = datetime.strptime(text, fmt).date()
            if fmt == "%m/%d":
                result = result.replace(year=today.year)
                if result < today:
                    result = result.replace(year=today.year + 1)
            return result
        except ValueError:
            continue
    raise ValueError("Please reply TODAY or TOMORROW (or a date like 10/12).")


def _clock(raw: str, assumed: str | None = None) -> int:
    s = re.sub(r"\s+", "", raw.lower().replace(".", ""))
    if s == "noon":
        return 12 * 60
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)?", s)
    if not m:
        raise ValueError("Please use times like 1pm or 1:30pm.")
    h, minutes = int(m.group(1)), int(m.group(2) or 0)
    suffix = m.group(3) or assumed
    if minutes > 59 or (suffix and not 1 <= h <= 12) or (not suffix and not 0 <= h <= 23):
        raise ValueError("Invalid time.")
    if suffix:
        h = (h % 12) + (12 if suffix == "pm" else 0)
    return h * 60 + minutes


def parse_time_window(day: date, answer: str) -> tuple[datetime, datetime]:
    """Accept '1-4pm', '11am-2pm', '12:00-16:00', or '2pm' (one hour)."""
    text = answer.strip().lower().replace("–", "-").replace("—", "-")
    text = re.sub(r"\b(?:between|from)\b", "", text).strip()
    text = re.sub(r"\b(?:and|until|through|to)\b", "-", text)
    if "-" in text:
        parts = [p.strip() for p in text.split("-")]
        if len(parts) != 2 or not all(parts):
            raise ValueError("Reply with a time range like 1-4pm.")
        left, right = parts
        left_suffix = re.search(r"(am|pm)\.?\s*$", left)
        right_suffix = re.search(r"(am|pm)\.?\s*$", right)
        if left_suffix is None and right_suffix is None:
            # 12:00-16:00 works, but '2-4' needs an am/pm to avoid guessing.
            if not (":" in left and ":" in right) and not re.match(r"^(?:1[3-9]|2[0-3])(?::|$)", right):
                raise ValueError("Please add am or pm, e.g. 1-4pm.")
        end = _clock(right)
        if left_suffix is None and right_suffix is not None:
            possible = [_clock(left, "am"), _clock(left, "pm")]
            valid = [n for n in possible if 0 < end - n <= 12 * 60]
            if not valid:
                raise ValueError("The end time must be after the start time.")
            start = max(valid)
        elif right_suffix is None and left_suffix is not None:
            start = _clock(left)
            possible = [_clock(right, "am"), _clock(right, "pm")]
            valid = [n for n in possible if 0 < n - start <= 12 * 60]
            if not valid:
                raise ValueError("The end time must be after the start time.")
            end = min(valid)
        else:
            start = _clock(left)
    else:
        if not re.search(r"(am|pm)\s*$", text):
            raise ValueError("Please include am or pm, e.g. 2pm.")
        start = _clock(text)
        end = start + 60
    if not 0 <= start < end <= 24 * 60:
        raise ValueError("Please give a same-day range (e.g. 1-4pm).")
    a = datetime(day.year, day.month, day.day, start // 60, start % 60, tzinfo=TZ)
    if end == 24 * 60:
        b = a.replace(hour=0, minute=0) + timedelta(days=1)
    else:
        b = datetime(day.year, day.month, day.day, end // 60, end % 60, tzinfo=TZ)
    return a, b
