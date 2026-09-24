"""
All "when should this fire" input in this app comes from <input
type="datetime-local">, which returns local wall-clock time with no
timezone attached — it is NOT UTC. Every place that used to do
`datetime.fromisoformat(s).replace(tzinfo=timezone.utc)` was silently
treating a 9:00 AM Austin entry as 9:00 AM UTC (4:00/5:00 AM Austin,
depending on DST) — a real bug fixed by routing everything through here
instead.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Chicago")  # Austin


def parse_local(value: str) -> datetime:
    """A <input type="datetime-local"> string, interpreted as Austin time,
    returned as a tz-aware UTC datetime for storage. Explicitly normalized
    to UTC (not just tagged with the Austin offset) to match every other
    datetime stored in this app (_utcnow() etc.) — some DB drivers/backends
    silently drop a non-UTC offset on read-back, so storing a consistent
    UTC representation avoids depending on that."""
    return datetime.fromisoformat(value).replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc)


def to_local(dt: datetime):
    """A tz-aware (or naive-UTC) datetime, converted to Austin time for
    display. Passes through None so it's safe in `{{ x.field|localtime }}`
    even when the field is unset."""
    if dt is None:
        return None
    return dt.astimezone(LOCAL_TZ)
