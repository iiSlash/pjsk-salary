import datetime as dt
import io
import unittest

from openpyxl import Workbook

from pjsk_salary.parser import ScheduleParseError, parse_schedule_workbook


def make_schedule_workbook() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "类五"

    sheet["A2"] = dt.date(2026, 7, 6)
    sheet["A2"].number_format = 'm"月"d"日"'
    sheet["B2"] = "跑1"
    sheet["C2"] = "推1"
    sheet["A3"] = "15:00-16:00"
    sheet["B3"] = "九九"
    sheet["C3"] = "呐呐"
    sheet["A4"] = "16:00-17:00"
    sheet["B4"] = "九九"
    sheet["C4"] = "新人"

    sheet["H2"] = dt.date(2026, 7, 7)
    sheet["H2"].number_format = 'm"月"d"日"'
    sheet["I2"] = "跑1"
    sheet["J2"] = "推1"
    sheet["H3"] = "0:00-0:30"
    sheet["I3"] = "卷卷"
    sheet["J3"] = "景"

    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


class ParserTests(unittest.TestCase):
    def test_parses_side_by_side_partial_blocks(self):
        parsed = parse_schedule_workbook(make_schedule_workbook())

        self.assertEqual(parsed.teams, ["类五"])
        self.assertEqual(len(parsed.blocks), 2)
        self.assertEqual(len(parsed.records), 6)
        self.assertEqual(set(parsed.records["role"]), {"跑1", "推1"})
        self.assertEqual(set(parsed.records["person"]), {"九九", "呐呐", "新人", "卷卷", "景"})
        half_hour = parsed.records[parsed.records["time_slot"] == "0:00-0:30"]
        self.assertTrue((half_hour["duration_hours"] == 0.5).all())

    def test_rejects_workbook_without_schedule(self):
        workbook = Workbook()
        output = io.BytesIO()
        workbook.save(output)
        with self.assertRaises(ScheduleParseError):
            parse_schedule_workbook(output.getvalue())


if __name__ == "__main__":
    unittest.main()
