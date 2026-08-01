from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from pjsk_salary import (
    SalaryValidationError,
    ScheduleParseError,
    build_default_rates,
    calculate_salary,
    parse_schedule_workbook,
)
from pjsk_salary.exporter import export_salary_excel, export_summary_csv


st.set_page_config(page_title="PJSK 工资计算器", page_icon="💰", layout="wide")


@st.cache_data(show_spinner=False)
def parse_uploaded_workbook(file_bytes: bytes):
    return parse_schedule_workbook(file_bytes)


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", value).strip(" ._")
    return cleaned or "工资结算"


def display_date_range(records: pd.DataFrame) -> str:
    first_date = records["date"].min().strftime("%Y-%m-%d")
    last_date = records["date"].max().strftime("%Y-%m-%d")
    return first_date if first_date == last_date else f"{first_date} 至 {last_date}"


def reset_rates(state_key: str, editor_key: str, records: pd.DataFrame) -> None:
    st.session_state[state_key] = build_default_rates(records)
    st.session_state.pop(editor_key, None)


st.title("💰 PJSK 工资计算器")
st.caption("上传横向排班 Excel，表内出现的所有人员都会自动参与工资计算。数据只保存在当前浏览器会话中。")

uploaded_file = st.file_uploader(
    "上传排班表",
    type=["xlsx", "xlsm"],
    help="支持日期区块左右并排、首尾日期不完整、半小时和跨午夜时间段。每个工作表视为一个班组。",
)

if uploaded_file is None:
    st.info("请先上传排班表。无需填写结算人员名单，也不需要配置数据库或 Google Sheets。")
    with st.expander("排班表格式说明"):
        st.markdown(
            """
- 日期放在每个区块左上角，右侧依次填写岗位名称。
- 日期下一行开始填写时间段，例如 `15:00-16:00`、`0:00-0:30`。
- 人名直接填在对应的时间段和岗位交叉单元格中。
- 多个日期区块可以左右并排或上下排列；每个工作表会作为一个班组。
"""
        )
    st.stop()

file_bytes = uploaded_file.getvalue()
file_fingerprint = hashlib.sha256(file_bytes).hexdigest()[:16]

try:
    with st.spinner("正在识别排班表……"):
        parsed = parse_uploaded_workbook(file_bytes)
except ScheduleParseError as exc:
    st.error(str(exc))
    st.stop()

records = parsed.records
blocks = parsed.blocks
all_teams = parsed.teams

st.success(
    f"已识别 {len(blocks)} 个日期区块、{records['person'].nunique()} 人、"
    f"{len(records)} 个已填写岗位单元格。"
)
for warning in parsed.warnings:
    st.warning(warning)

with st.sidebar:
    st.header("计算范围")
    selected_teams = st.multiselect(
        "班组（工作表）",
        options=all_teams,
        default=all_teams,
        help="一个 Excel 工作表对应一个班组。",
    )
    st.header("白班 / 夜班")
    day_start_hour = st.selectbox(
        "白班开始",
        options=list(range(24)),
        index=8,
        format_func=lambda hour: f"{hour:02d}:00",
    )
    night_start_hour = st.selectbox(
        "夜班开始",
        options=list(range(24)),
        index=20,
        format_func=lambda hour: f"{hour:02d}:00",
    )
    st.caption("跨越班次边界的时间段会按白班和夜班分别计价。")
    st.divider()
    st.caption("本工具不会上传或持久化保存排班与工资数据。刷新或关闭会话后可直接丢弃。")

if not selected_teams:
    st.warning("请至少选择一个班组。")
    st.stop()

filtered_records = records[records["team"].isin(selected_teams)].copy()
filtered_blocks = blocks[blocks["team"].isin(selected_teams)].copy()

metric_columns = st.columns(4)
metric_columns[0].metric("日期范围", display_date_range(filtered_records))
metric_columns[1].metric("结算人数", int(filtered_records["person"].nunique()))
metric_columns[2].metric("排班工时", f"{filtered_records['duration_hours'].sum():,.1f}")
metric_columns[3].metric("班组", len(selected_teams))

with st.expander("查看解析结果", expanded=False):
    block_display = filtered_blocks.rename(
        columns={
            "team": "班组",
            "date": "日期",
            "roles": "岗位",
            "time_slots": "时间段数量",
            "assignments": "已填写单元格",
            "source_cell": "区块起点",
        }
    )
    st.dataframe(block_display, hide_index=True, use_container_width=True)

st.subheader("1. 设置工价")
st.caption("岗位和班组由排班表自动生成，只需修改白班价和夜班价。工价单位为每小时。")

rates_state_key = f"rates_{file_fingerprint}"
rates_editor_key = f"rates_editor_{file_fingerprint}"
if rates_state_key not in st.session_state:
    st.session_state[rates_state_key] = build_default_rates(records)

reset_column, spacer = st.columns([1, 5])
with reset_column:
    if st.button("重置为 20 / 30", use_container_width=True):
        reset_rates(rates_state_key, rates_editor_key, records)
        st.rerun()

edited_rates = st.data_editor(
    st.session_state[rates_state_key],
    key=rates_editor_key,
    hide_index=True,
    use_container_width=True,
    num_rows="fixed",
    disabled=["班组", "岗位"],
    column_config={
        "班组": st.column_config.TextColumn("班组"),
        "岗位": st.column_config.TextColumn("岗位"),
        "白班价": st.column_config.NumberColumn(
            "白班价（元/小时）", min_value=0.0, step=1.0, format="%.2f"
        ),
        "夜班价": st.column_config.NumberColumn(
            "夜班价（元/小时）", min_value=0.0, step=1.0, format="%.2f"
        ),
    },
)
st.session_state[rates_state_key] = edited_rates

selected_rates = edited_rates[edited_rates["班组"].isin(selected_teams)].copy()

st.subheader("2. 工资结果")
try:
    result = calculate_salary(
        filtered_records,
        selected_rates,
        day_start_hour=day_start_hour,
        night_start_hour=night_start_hour,
    )
except SalaryValidationError as exc:
    st.error(str(exc))
    st.stop()

result_metrics = st.columns(3)
result_metrics[0].metric("结算人数", len(result.summary))
result_metrics[1].metric("总工时", f"{result.total_hours:,.2f}")
result_metrics[2].metric("工资合计", f"¥ {result.total_salary:,.2f}")

summary_tab, detail_tab = st.tabs(["工资汇总", "工资明细"])
with summary_tab:
    summary_config = {
        column: st.column_config.NumberColumn(column, format="%.2f")
        for column in result.summary.columns
        if column not in {"班组", "姓名"}
    }
    st.dataframe(
        result.summary,
        hide_index=True,
        use_container_width=True,
        column_config=summary_config,
    )

with detail_tab:
    st.dataframe(
        result.detail,
        hide_index=True,
        use_container_width=True,
        column_config={
            "日期": st.column_config.DateColumn("日期", format="YYYY-MM-DD"),
            "工时": st.column_config.NumberColumn("工时", format="%.2f"),
            "白班工时": st.column_config.NumberColumn("白班工时", format="%.2f"),
            "夜班工时": st.column_config.NumberColumn("夜班工时", format="%.2f"),
            "白班价": st.column_config.NumberColumn("白班价", format="%.2f"),
            "夜班价": st.column_config.NumberColumn("夜班价", format="%.2f"),
            "工资": st.column_config.NumberColumn("工资", format="%.2f"),
        },
    )

st.subheader("3. 导出结算结果")
event_name = st.text_input("导出文件名", value=Path(uploaded_file.name).stem).strip()
download_name = safe_filename(event_name)

excel_bytes = export_salary_excel(result, selected_rates, filtered_blocks)
csv_bytes = export_summary_csv(result)
excel_column, csv_column = st.columns(2)
with excel_column:
    st.download_button(
        "下载完整 Excel",
        data=excel_bytes,
        file_name=f"{download_name}_工资结算.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        type="primary",
    )
with csv_column:
    st.download_button(
        "下载工资汇总 CSV",
        data=csv_bytes,
        file_name=f"{download_name}_工资汇总.csv",
        mime="text/csv",
        use_container_width=True,
    )

st.caption("Excel 文件包含工资汇总、工资明细、工价设置和解析信息四个工作表。")
