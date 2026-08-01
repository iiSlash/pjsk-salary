from __future__ import annotations

import io
import re
from typing import Mapping

import pandas as pd
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from .salary import SalaryResult


HEADER_FILL = PatternFill("solid", fgColor="35665C")
HEADER_FONT = Font(color="FFFFFF", bold=True)
TOTAL_FILL = PatternFill("solid", fgColor="E3EFEB")
TOTAL_BORDER = Border(top=Side(style="thin", color="35665C"))
DATE_FILL = PatternFill("solid", fgColor="EAF2F8")
ROLE_FILL = PatternFill("solid", fgColor="F7E6F5")
ASSIGNMENT_FILL = PatternFill("solid", fgColor="EAF5EE")
DATE_TEXT_RE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$|^\d{1,2}月\d{1,2}日$")
TIME_TEXT_RE = re.compile(r"^\d{1,2}:\d{2}\s*[-~～—–至]\s*\d{1,2}:\d{2}$")


def export_salary_excel(
    result: SalaryResult,
    rates: pd.DataFrame,
    schedule_sheets: Mapping[str, pd.DataFrame] | None = None,
) -> bytes:
    output = io.BytesIO()
    summary = _summary_with_total(result)
    detail = _safe_frame(result.daily_detail)
    rate_export = _safe_frame(rates)

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="工资汇总", index=False)
        detail.to_excel(writer, sheet_name="结算明细", index=False)
        rate_export.to_excel(writer, sheet_name="工价设置", index=False)

        used_sheet_names = set(writer.sheets)
        for team, frame in (schedule_sheets or {}).items():
            sheet_name = _schedule_sheet_name(str(team), used_sheet_names)
            _safe_frame(frame).to_excel(
                writer,
                sheet_name=sheet_name,
                index=False,
                header=False,
            )
            used_sheet_names.add(sheet_name)

        for sheet_name, worksheet in writer.sheets.items():
            if sheet_name.startswith("排班-"):
                _format_schedule_sheet(worksheet)
                continue

            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for cell in worksheet[1]:
                cell.fill = HEADER_FILL
                cell.font = HEADER_FONT
                cell.alignment = Alignment(horizontal="center", vertical="center")
            for column_cells in worksheet.columns:
                max_length = max(
                    (len(str(cell.value)) if cell.value is not None else 0)
                    for cell in column_cells
                )
                column_letter = column_cells[0].column_letter
                worksheet.column_dimensions[column_letter].width = min(
                    max(max_length + 2, 10), 28
                )

            if sheet_name == "工资汇总":
                for cell in worksheet[worksheet.max_row]:
                    cell.fill = TOTAL_FILL
                    cell.font = Font(bold=True)
                    cell.border = TOTAL_BORDER

            if sheet_name in {"工资汇总", "结算明细", "工价设置"}:
                for row in worksheet.iter_rows(min_row=2):
                    for cell in row:
                        if isinstance(cell.value, (int, float)):
                            cell.number_format = "#,##0.00"
            for header_cell in worksheet[1]:
                if header_cell.value == "日期":
                    for cell in worksheet.iter_cols(
                        min_col=header_cell.column,
                        max_col=header_cell.column,
                        min_row=2,
                    ):
                        for date_cell in cell:
                            if hasattr(date_cell.value, "year"):
                                date_cell.number_format = "yyyy-mm-dd"

    return output.getvalue()


def export_summary_csv(result: SalaryResult) -> bytes:
    return _summary_with_total(result).to_csv(index=False).encode("utf-8-sig")


def _summary_with_total(result: SalaryResult) -> pd.DataFrame:
    summary = result.payroll_summary.copy()
    numeric_columns = summary.select_dtypes(include="number").columns
    total_row: dict[str, object] = {column: "" for column in summary.columns}
    total_row["班组"] = "全部"
    total_row["姓名"] = "合计"
    for column in numeric_columns:
        total_row[column] = round(float(summary[column].sum()), 2)
    summary = pd.concat([summary, pd.DataFrame([total_row])], ignore_index=True)
    return _safe_frame(summary)


def _schedule_sheet_name(team: str, used_names: set[str]) -> str:
    cleaned = re.sub(r"[\\/*?:\[\]]+", "_", team).strip() or "班组"
    base = f"排班-{cleaned}"[:31]
    candidate = base
    counter = 2
    while candidate in used_names:
        suffix = f"-{counter}"
        candidate = f"{base[: 31 - len(suffix)]}{suffix}"
        counter += 1
    return candidate


def _format_schedule_sheet(worksheet) -> None:
    for column_cells in worksheet.columns:
        max_length = max(
            (len(str(cell.value)) if cell.value is not None else 0)
            for cell in column_cells
        )
        column_letter = column_cells[0].column_letter
        worksheet.column_dimensions[column_letter].width = min(
            max(max_length + 2, 10), 18
        )
        for cell in column_cells:
            cell.alignment = Alignment(horizontal="center", vertical="center")

    for row in worksheet.iter_rows():
        for position, cell in enumerate(row):
            value = cell.value
            is_date = hasattr(value, "year") or (
                isinstance(value, str) and DATE_TEXT_RE.match(value.strip())
            )
            if is_date:
                cell.fill = DATE_FILL
                cell.font = Font(bold=True)
                if hasattr(value, "year"):
                    cell.number_format = "yyyy-mm-dd"
                _fill_following_cells(row, position, ROLE_FILL, bold=True)
                continue

            if isinstance(value, str) and TIME_TEXT_RE.match(value.strip()):
                _fill_following_cells(row, position, ASSIGNMENT_FILL)


def _fill_following_cells(
    row: tuple,
    start_position: int,
    fill: PatternFill,
    bold: bool = False,
) -> None:
    for following_cell in row[start_position + 1 :]:
        if following_cell.value in (None, ""):
            break
        following_cell.fill = fill
        if bold:
            following_cell.font = Font(bold=True)


def _safe_frame(frame: pd.DataFrame) -> pd.DataFrame:
    safe = frame.copy()
    safe.columns = [_safe_text(column) for column in safe.columns]
    for column in safe.select_dtypes(include=["object", "string"]).columns:
        safe[column] = safe[column].map(_safe_text)
    return safe


def _safe_text(value: object) -> object:
    if not isinstance(value, str) or not value:
        return value
    if value[0] in "=+-@":
        return "'" + value
    return value
