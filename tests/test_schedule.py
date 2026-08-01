import datetime as dt
import unittest

from pjsk_salary.parser import parse_schedule_workbook
from pjsk_salary.schedule import (
    START_MINUTES_COLUMN,
    build_daily_grids,
    build_horizontal_grid,
    daily_grids_to_records,
    horizontal_grid_to_daily_grids,
)
from tests.test_parser import make_schedule_workbook


class DailyScheduleTests(unittest.TestCase):
    def test_builds_full_day_grid_and_round_trips_hours(self):
        parsed = parse_schedule_workbook(make_schedule_workbook())

        grids, step_minutes = build_daily_grids(parsed.records, parsed.blocks)

        self.assertEqual(step_minutes, 30)
        first_day = grids["类五"][dt.date(2026, 7, 6)]
        self.assertEqual(len(first_day), 48)
        self.assertEqual(first_day.iloc[0]["时间"], "00:00-00:30")
        self.assertEqual(first_day.iloc[-1]["时间"], "23:30-24:00")
        self.assertEqual(first_day.loc[first_day[START_MINUTES_COLUMN] == 900, "跑1"].iloc[0], "九九")

        round_tripped = daily_grids_to_records(grids, step_minutes)
        self.assertAlmostEqual(
            round_tripped["duration_hours"].sum(),
            parsed.records["duration_hours"].sum(),
        )

    def test_editing_one_person_cell_updates_records(self):
        parsed = parse_schedule_workbook(make_schedule_workbook())
        grids, step_minutes = build_daily_grids(parsed.records, parsed.blocks)
        frame = grids["类五"][dt.date(2026, 7, 6)]
        frame.loc[frame[START_MINUTES_COLUMN] == 900, "跑1"] = "已修改"

        records = daily_grids_to_records(grids, step_minutes)

        edited = records[
            (records["date"] == "2026-07-06")
            & (records["start_minutes"] == 900)
            & (records["role"] == "跑1")
        ]
        self.assertEqual(edited.iloc[0]["person"], "已修改")

    def test_horizontal_grid_places_dates_side_by_side_and_applies_edits(self):
        parsed = parse_schedule_workbook(make_schedule_workbook())
        grids, _ = build_daily_grids(parsed.records, parsed.blocks)
        date_grids = grids["类五"]

        horizontal, date_columns = build_horizontal_grid(date_grids)

        self.assertEqual(len(horizontal), 48)
        self.assertEqual(len(date_columns), len(date_grids))
        first_date = min(date_columns)
        run_field = next(
            field
            for field, role in date_columns[first_date].items()
            if role == "跑1"
        )
        horizontal.loc[
            horizontal[START_MINUTES_COLUMN] == 900,
            run_field,
        ] = "横向修改"

        restored = horizontal_grid_to_daily_grids(
            horizontal,
            date_grids,
            date_columns,
        )
        edited = restored[first_date]
        value = edited.loc[edited[START_MINUTES_COLUMN] == 900, "跑1"].iloc[0]
        self.assertEqual(value, "横向修改")


if __name__ == "__main__":
    unittest.main()
