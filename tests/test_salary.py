import unittest

from pjsk_salary.parser import parse_schedule_workbook
from pjsk_salary.salary import build_default_rates, calculate_salary
from tests.test_parser import make_schedule_workbook


class SalaryTests(unittest.TestCase):
    def test_calculates_day_night_and_partial_hours(self):
        parsed = parse_schedule_workbook(make_schedule_workbook())
        rates = build_default_rates(parsed.records)
        rates.loc[rates["岗位"] == "跑1", ["白班价", "夜班价"]] = [20, 30]
        rates.loc[rates["岗位"] == "推1", ["白班价", "夜班价"]] = [40, 50]

        result = calculate_salary(parsed.records, rates, day_start_hour=8, night_start_hour=20)

        self.assertAlmostEqual(result.total_hours, 5.0)
        self.assertAlmostEqual(result.total_salary, 160.0)
        jiujiu = result.summary[result.summary["姓名"] == "九九"].iloc[0]
        self.assertAlmostEqual(jiujiu["总工时"], 2.0)
        self.assertAlmostEqual(jiujiu["总工资"], 40.0)
        juanjuan = result.summary[result.summary["姓名"] == "卷卷"].iloc[0]
        self.assertAlmostEqual(juanjuan["夜班工时"], 0.5)
        self.assertAlmostEqual(juanjuan["总工资"], 15.0)

    def test_splits_a_slot_that_crosses_shift_boundary(self):
        parsed = parse_schedule_workbook(make_schedule_workbook())
        records = parsed.records.iloc[[0]].copy()
        records.loc[:, "person"] = "跨班人员"
        records.loc[:, "time_slot"] = "7:30-8:30"
        records.loc[:, "start_minutes"] = 7 * 60 + 30
        records.loc[:, "end_minutes"] = 8 * 60 + 30
        records.loc[:, "duration_hours"] = 1.0

        rates = build_default_rates(records, day_rate=20, night_rate=30)
        result = calculate_salary(records, rates, day_start_hour=8, night_start_hour=20)

        row = result.detail.iloc[0]
        self.assertEqual(row["班次"], "跨班")
        self.assertAlmostEqual(row["白班工时"], 0.5)
        self.assertAlmostEqual(row["夜班工时"], 0.5)
        self.assertAlmostEqual(row["工资"], 25.0)


if __name__ == "__main__":
    unittest.main()
