from __future__ import annotations

import datetime as dt
import io
import re
from dataclasses import dataclass
from typing import BinaryIO

import pandas as pd


RECORD_COLUMNS = [
    "team",
    "date",
    "time_slot",
    "start_minutes",
    "end_minutes",
    "duration_hours",
    "role",
    "person",
    "source_cell",
]

BLOCK_COLUMNS = [
    "team",
    "date",
    "roles",
    "time_slots",
    "assignments",
    "source_cell",
]

_TIME_SLOT_RE = re.compile(
    r"^\s*(\d{1,2})\s*:\s*(\d{2})\s*-\s*(\d{1,2})\s*:\s*(\d{2})\s*$"
)
_DATE_PATTERNS = (
    re.compile(r"^(\d{4})[./-](\d{1,2})[./-](\d{1,2})$"),
    re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日?$"),
)
_SHORT_DATE_PATTERNS = (
    re.compile(r"^(\d{1,2})[./-](\d{1,2})$"),
    re.compile(r"^(\d{1,2})月(\d{1,2})日?$"),
)


class ScheduleParseError(ValueError):
    """Raised when an uploaded workbook does not contain a recognizable schedule."""


@dataclass(frozen=True)
class ParsedWorkbook:
    records: pd.DataFrame
    blocks: pd.DataFrame
    warnings: tuple[str, ...] = ()

    @property
    def teams(self) -> list[str]:
        return self.records["team"].drop_duplicates().tolist()


def parse_schedule_workbook(source: bytes | bytearray | BinaryIO) -> ParsedWorkbook:
    """Parse horizontal date/time/role blocks from every worksheet in an xlsx file."""

    stream: BinaryIO
    if isinstance(source, (bytes, bytearray)):
        stream = io.BytesIO(source)
    else:
        stream = source

    try:
        sheets = pd.read_excel(stream, sheet_name=None, header=None, engine="openpyxl")
    except Exception as exc:  # openpyxl exposes several low-level exceptions
        raise ScheduleParseError(f"无法读取 Excel 文件：{exc}") from exc

    records: list[dict[str, object]] = []
    blocks: list[dict[str, object]] = []
    warnings: list[str] = []

    for sheet_name, frame in sheets.items():
        sheet_records, sheet_blocks, sheet_warnings = _parse_sheet(str(sheet_name), frame)
        records.extend(sheet_records)
        blocks.extend(sheet_blocks)
        warnings.extend(sheet_warnings)

    if not blocks:
        raise ScheduleParseError(
            "没有识别到排班区块。日期应位于区块左上角，右侧是岗位，下一行开始是“0:00-1:00”格式的时间段。"
        )
    if not records:
        raise ScheduleParseError("识别到了排班结构，但没有找到任何已填写的人员姓名。")

    record_df = pd.DataFrame.from_records(records, columns=RECORD_COLUMNS)
    block_df = pd.DataFrame.from_records(blocks, columns=BLOCK_COLUMNS)
    record_df["date"] = pd.to_datetime(record_df["date"])
    block_df["date"] = pd.to_datetime(block_df["date"])
    return ParsedWorkbook(record_df, block_df, tuple(warnings))


def _parse_sheet(
    sheet_name: str, frame: pd.DataFrame
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str]]:
    records: list[dict[str, object]] = []
    blocks: list[dict[str, object]] = []
    warnings: list[str] = []
    seen_blocks: set[tuple[int, int]] = set()

    for row_index in range(frame.shape[0]):
        for col_index in range(frame.shape[1]):
            schedule_date = _coerce_date(frame.iat[row_index, col_index])
            if schedule_date is None or row_index + 1 >= frame.shape[0]:
                continue

            roles = _read_roles(frame, row_index, col_index)
            first_slot = _parse_time_slot(frame.iat[row_index + 1, col_index])
            if not roles or first_slot is None:
                continue
            if (row_index, col_index) in seen_blocks:
                continue
            seen_blocks.add((row_index, col_index))

            block_records: list[dict[str, object]] = []
            time_slot_count = 0
            for data_row in range(row_index + 1, min(frame.shape[0], row_index + 97)):
                parsed_slot = _parse_time_slot(frame.iat[data_row, col_index])
                if parsed_slot is None:
                    break
                time_slot_count += 1
                start_minutes, end_minutes, duration_hours, time_slot = parsed_slot

                for role_col, role in roles:
                    person = _clean_text(frame.iat[data_row, role_col])
                    if not person:
                        continue
                    block_records.append(
                        {
                            "team": sheet_name,
                            "date": schedule_date,
                            "time_slot": time_slot,
                            "start_minutes": start_minutes,
                            "end_minutes": end_minutes,
                            "duration_hours": duration_hours,
                            "role": role,
                            "person": person,
                            "source_cell": _cell_address(data_row, role_col),
                        }
                    )

            role_names = [item[1] for item in roles]
            duplicate_roles = {
                role for role in role_names if role_names.count(role) > 1
            }
            if duplicate_roles:
                block_address = _cell_address(row_index, col_index)
                warnings.append(
                    f"{sheet_name}!{block_address} 的岗位名称重复："
                    f"{', '.join(sorted(duplicate_roles))}。"
                )

            records.extend(block_records)
            blocks.append(
                {
                    "team": sheet_name,
                    "date": schedule_date,
                    "roles": "、".join(role for _, role in roles),
                    "time_slots": time_slot_count,
                    "assignments": len(block_records),
                    "source_cell": _cell_address(row_index, col_index),
                }
            )

    return records, blocks, warnings


def _read_roles(frame: pd.DataFrame, row_index: int, date_col: int) -> list[tuple[int, str]]:
    roles: list[tuple[int, str]] = []
    for col_index in range(date_col + 1, min(frame.shape[1], date_col + 31)):
        value = frame.iat[row_index, col_index]
        role = _clean_text(value)
        if not role or _coerce_date(value) is not None or _parse_time_slot(value) is not None:
            break
        roles.append((col_index, role))
    return roles


def _parse_time_slot(value: object) -> tuple[int, int, float, str] | None:
    text = _clean_text(value)
    if not text:
        return None
    normalized = (
        text.replace("：", ":")
        .replace("～", "-")
        .replace("~", "-")
        .replace("—", "-")
        .replace("–", "-")
        .replace("至", "-")
    )
    match = _TIME_SLOT_RE.match(normalized)
    if not match:
        return None

    start_hour, start_minute, end_hour, end_minute = map(int, match.groups())
    if start_hour > 23 or start_minute > 59 or end_hour > 24 or end_minute > 59:
        return None
    if end_hour == 24 and end_minute != 0:
        return None

    start = start_hour * 60 + start_minute
    end = end_hour * 60 + end_minute
    if end <= start:
        end += 24 * 60
    duration = (end - start) / 60
    if duration <= 0 or duration > 24:
        return None
    return start, end, duration, f"{start_hour}:{start_minute:02d}-{end_hour}:{end_minute:02d}"


def _coerce_date(value: object) -> dt.date | None:
    if _is_blank(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, (int, float)) and 20_000 <= float(value) <= 80_000:
        return (dt.datetime(1899, 12, 30) + dt.timedelta(days=float(value))).date()

    text = str(value).strip()
    for pattern in _DATE_PATTERNS:
        match = pattern.match(text)
        if match:
            try:
                return dt.date(*map(int, match.groups()))
            except ValueError:
                return None
    for pattern in _SHORT_DATE_PATTERNS:
        match = pattern.match(text)
        if match:
            try:
                return dt.date(dt.date.today().year, *map(int, match.groups()))
            except ValueError:
                return None
    return None


def _clean_text(value: object) -> str:
    if _is_blank(value):
        return ""
    return str(value).strip()


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _cell_address(row_index: int, col_index: int) -> str:
    column_number = col_index + 1
    letters = ""
    while column_number:
        column_number, remainder = divmod(column_number - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row_index + 1}"
