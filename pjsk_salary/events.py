from __future__ import annotations

import datetime as dt
import json
import urllib.request
from dataclasses import dataclass
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo


CHINA_TIMEZONE = ZoneInfo("Asia/Shanghai")
EVENT_URLS = (
    "https://raw.githubusercontent.com/"
    "Sekai-World/sekai-master-db-cn-diff/main/events.json",
    "https://cdn.jsdelivr.net/gh/"
    "Sekai-World/sekai-master-db-cn-diff@main/events.json",
    "https://ghproxy.net/https://raw.githubusercontent.com/"
    "Sekai-World/sekai-master-db-cn-diff/main/events.json",
)


@dataclass(frozen=True)
class EventPeriod:
    name: str
    start: dt.datetime
    end: dt.datetime

    @property
    def date_label(self) -> str:
        return f"{self.start:%Y-%m-%d} 至 {self.end:%Y-%m-%d}"


def fetch_pjsk_cn_events(
    urls: Sequence[str] = EVENT_URLS,
) -> tuple[list[EventPeriod], str | None]:
    """Fetch CN event periods from the public master-data mirrors."""

    errors: list[str] = []
    for url in urls:
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "pjsk-salary/1.0"},
            )
            with urllib.request.urlopen(request, timeout=6) as response:
                payload = json.loads(response.read().decode("utf-8"))
            events = parse_event_periods(payload)
            if events:
                return events, None
            errors.append(f"{url}: 没有有效活动")
        except Exception as exc:  # network and mirror errors are non-fatal
            errors.append(f"{url}: {exc}")

    return [], "；".join(errors)


def parse_event_periods(payload: Iterable[dict[str, object]]) -> list[EventPeriod]:
    events: list[EventPeriod] = []
    for item in payload:
        try:
            name = str(item["name"]).strip()
            start_at = float(item["startAt"])
            end_at = float(item["aggregateAt"])
        except (KeyError, TypeError, ValueError):
            continue
        if not name or end_at < start_at:
            continue

        start = dt.datetime.fromtimestamp(start_at / 1000, tz=dt.timezone.utc)
        end = dt.datetime.fromtimestamp(end_at / 1000, tz=dt.timezone.utc)
        events.append(
            EventPeriod(
                name=name,
                start=start.astimezone(CHINA_TIMEZONE),
                end=end.astimezone(CHINA_TIMEZONE),
            )
        )
    return sorted(events, key=lambda event: event.start, reverse=True)


def find_current_event(
    events: Iterable[EventPeriod],
    now: dt.datetime | None = None,
) -> EventPeriod | None:
    current_time = now or dt.datetime.now(CHINA_TIMEZONE)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=CHINA_TIMEZONE)
    candidates = [event for event in events if event.start <= current_time <= event.end]
    return max(candidates, key=lambda event: event.start, default=None)


def compare_schedule_dates(
    schedule_start: dt.date,
    schedule_end: dt.date,
    event: EventPeriod,
) -> str:
    """Return match, partial, or mismatch for a schedule and event date range."""

    event_start = event.start.date()
    event_end = event.end.date()
    if event_start <= schedule_start and schedule_end <= event_end:
        return "match"
    if schedule_start <= event_end and event_start <= schedule_end:
        return "partial"
    return "mismatch"
