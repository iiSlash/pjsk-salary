from __future__ import annotations

import io

import pandas as pd
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from .salary import SalaryResult


HEADER_FILL = PatternFill("solid", fgColor="35665C")
HEADER_FONT = Font(color="FFFFFF", bold=True)
TOTAL_FILL = PatternFill("solid", fgColor="E3EFEB")
TOTAL_BORDER = Border(top=Side(style="thin", color="35665C"))


def export_salary_excel(
    result: SalaryResult, rates: pd.DataFrame, blocks: pd.DataFrame
) -> bytes:
    output = io.BytesIO()
    summary = _summary_with_total(result)
    detail = _safe_frame(result.detail)
    rate_export = _safe_frame(rates)
    block_export = blocks.rename(
        columns={
            "team": "班组",
            "date": "日期",
            "roles": "岗位",
            "time_slots": "时间段数量",
            "assignments": "已填写单元格",
            "source_cell": "区块起点",
        }
    )
    block_export = _safe_frame(block_export)

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="工资汇总", index=False)
        detail.to_excel(writer, sheet_name="工资明细", index=False)
        rate_export.to_excel(writer, sheet_name="工价设置", index=False)
        block_export.to_excel(writer, sheet_name="解析信息", index=False)

        for sheet_name, worksheet in writer.sheets.items():
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

            if sheet_name == "解析信息":
                worksheet.column_dimensions["C"].width = 36

            if sheet_name == "工资汇总":
                for cell in worksheet[worksheet.max_row]:
                    cell.fill = TOTAL_FILL
                    cell.font = Font(bold=True)
                    cell.border = TOTAL_BORDER

            if sheet_name in {"工资汇总", "工资明细", "工价设置"}:
                for row in worksheet.iter_rows(min_row=2):
                    for cell in row:
                        if isinstance(cell.value, (int, float)):
                            cell.number_format = "#,##0.00"
            if sheet_name in {"工资明细", "解析信息"}:
                for cell in worksheet["B"]:
                    if hasattr(cell.value, "year"):
                        cell.number_format = "yyyy-mm-dd"

    return output.getvalue()


def export_summary_csv(result: SalaryResult) -> bytes:
    return _summary_with_total(result).to_csv(index=False).encode("utf-8-sig")


def _summary_with_total(result: SalaryResult) -> pd.DataFrame:
    summary = result.summary.copy()
    numeric_columns = summary.select_dtypes(include="number").columns
    total_row: dict[str, object] = {column: "" for column in summary.columns}
    total_row["班组"] = "全部"
    total_row["姓名"] = "合计"
    for column in numeric_columns:
        total_row[column] = round(float(summary[column].sum()), 2)
    summary = pd.concat([summary, pd.DataFrame([total_row])], ignore_index=True)
    return _safe_frame(summary)


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
