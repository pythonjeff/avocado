"""Centralized timestamp and date parsing utilities."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def parse_timestamp(s: str | None, tz: timezone = timezone.utc) -> datetime:
    """
    Parse common timestamp formats into a timezone-aware datetime.

    Supports:
    - ISO8601: "2026-01-17T12:00:00+00:00" or "2026-01-17T12:00:00Z"
    - Date only: "2026-01-17" (interpreted as midnight in specified tz)
    - Common formats: "2026-01-17 12:00:00"
    - Excel serial dates: 46031 (if > 20000, assumes 1900 date system)
    - US date formats: "01/17/2026", "1/17/26"

    Returns:
    - datetime in UTC (or specified tz)

    Raises:
    - ValueError if format is not recognized
    """
    if s is None:
        raise ValueError("timestamp is None")
    
    s = str(s).strip()
    if not s:
        raise ValueError("timestamp is empty")

    # Excel serial date (common in .xlsx XML).
    try:
        f = float(s)
        if f > 20000:
            # Excel 1900 date system: day 0 is 1899-12-30
            base = datetime(1899, 12, 30, tzinfo=tz)
            dt = base + timedelta(days=float(s))
            return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    except (ValueError, TypeError):
        pass

    # Normalize Z suffix
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    # Fast-path: ISO8601
    if "T" in s or "+" in s or s.count("-") >= 2:
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass

    # Date only (YYYY-MM-DD)
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    # Common: "YYYY-MM-DD HH:MM:SS"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=tz)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue

    # US date formats: MM/DD/YYYY, MM/DD/YY
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=tz)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue

    raise ValueError(f"unsupported timestamp format: {s!r}")


def utc_now_iso() -> str:
    """Return current UTC timestamp as ISO8601 string."""
    return datetime.now(timezone.utc).isoformat()
