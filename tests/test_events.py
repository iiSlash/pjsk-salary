import datetime as dt
import unittest

from pjsk_salary.events import (
    CHINA_TIMEZONE,
    EventPeriod,
    compare_schedule_dates,
    find_best_event_for_schedule,
    find_current_event,
    parse_event_periods,
)


class EventTests(unittest.TestCase):
    def test_finds_current_event_and_compares_schedule_dates(self):
        start = dt.datetime(2026, 7, 6, 15, tzinfo=CHINA_TIMEZONE)
        end = dt.datetime(2026, 7, 13, 20, tzinfo=CHINA_TIMEZONE)
        events = parse_event_periods(
            [
                {
                    "name": "测试活动",
                    "startAt": start.timestamp() * 1000,
                    "aggregateAt": end.timestamp() * 1000,
                }
            ]
        )

        current = find_current_event(
            events,
            dt.datetime(2026, 7, 10, 12, tzinfo=CHINA_TIMEZONE),
        )

        self.assertIsNotNone(current)
        self.assertEqual(current.name, "测试活动")
        self.assertEqual(
            compare_schedule_dates(dt.date(2026, 7, 6), dt.date(2026, 7, 13), current),
            "match",
        )
        self.assertEqual(
            compare_schedule_dates(dt.date(2026, 7, 5), dt.date(2026, 7, 7), current),
            "partial",
        )
        self.assertEqual(
            compare_schedule_dates(dt.date(2026, 6, 1), dt.date(2026, 6, 8), current),
            "mismatch",
        )

    def test_selects_previous_event_that_matches_uploaded_schedule(self):
        current = EventPeriod(
            "本期活动",
            dt.datetime(2026, 7, 14, 15, tzinfo=CHINA_TIMEZONE),
            dt.datetime(2026, 7, 21, 20, tzinfo=CHINA_TIMEZONE),
        )
        previous = EventPeriod(
            "上一期活动",
            dt.datetime(2026, 7, 6, 15, tzinfo=CHINA_TIMEZONE),
            dt.datetime(2026, 7, 13, 20, tzinfo=CHINA_TIMEZONE),
        )

        selected = find_best_event_for_schedule(
            [current, previous],
            dt.date(2026, 7, 6),
            dt.date(2026, 7, 13),
            fallback=current,
        )

        self.assertEqual(selected, previous)


if __name__ == "__main__":
    unittest.main()
