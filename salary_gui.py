from __future__ import annotations

import datetime as dt
import hashlib
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from pjsk_salary.events import (
    EventPeriod,
    compare_schedule_dates,
    fetch_pjsk_cn_events,
    find_current_event,
)
from pjsk_salary.exporter import export_salary_excel, export_summary_csv
from pjsk_salary.parser import (
    ScheduleParseError,
    parse_schedule_sheets,
    read_schedule_workbook,
)
from pjsk_salary.salary import (
    SalaryValidationError,
    build_default_rates,
    calculate_salary,
)


st.set_page_config(page_title="PJSK 工资计算器", page_icon="💰", layout="wide")


@st.cache_data(show_spinner=False)
def load_workbook_sheets(file_bytes: bytes) -> dict[str, pd.DataFrame]:
    return read_schedule_workbook(file_bytes)


@st.cache_data(ttl=3600, show_spinner=False)
def load_current_event() -> tuple[EventPeriod | None, str | None]:
    events, error = fetch_pjsk_cn_events()
    return find_current_event(events), error


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", value).strip(" ._")
    return cleaned or "工资结算"


def display_date_range(records: pd.DataFrame) -> str:
    first_date = records["date"].min().strftime("%Y-%m-%d")
    last_date = records["date"].max().strftime("%Y-%m-%d")
    return first_date if first_date == last_date else f"{first_date} 至 {last_date}"


def excel_column_name(column_index: int) -> str:
    column_number = column_index + 1
    letters = ""
    while column_number:
        column_number, remainder = divmod(column_number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def editor_cell_value(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, (pd.Timestamp, dt.datetime, dt.date)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def make_editable_sheets(
    sheets: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    editable: dict[str, pd.DataFrame] = {}
    for sheet_name, frame in sheets.items():
        editor = frame.apply(lambda column: column.map(editor_cell_value))
        editor.columns = [excel_column_name(index) for index in range(editor.shape[1])]
        editor.index = pd.RangeIndex(1, len(editor) + 1, name="行")
        editable[sheet_name] = editor
    return editable


def reconcile_rates(
    defaults: pd.DataFrame,
    existing: pd.DataFrame | None,
) -> pd.DataFrame:
    if existing is None or not {"班组", "岗位", "白班价", "夜班价"}.issubset(existing):
        return defaults

    previous = existing[["班组", "岗位", "白班价", "夜班价"]].copy()
    merged = defaults.merge(
        previous,
        on=["班组", "岗位"],
        how="left",
        suffixes=("_默认", ""),
    )
    for column in ("白班价", "夜班价"):
        merged[column] = merged[column].fillna(merged[f"{column}_默认"])
    return merged[["班组", "岗位", "白班价", "夜班价"]]


st.title("💰 PJSK 工资计算器")
st.caption("核对排班、微调人员、设置工价，然后直接生成可发放的工资表。数据只保存在当前会话中。")

with st.spinner("正在获取简中服当前活动……"):
    current_event, event_error = load_current_event()

if current_event is not None:
    st.info(f"🎵 当前活动：{current_event.name}　｜　{current_event.date_label}")
elif event_error:
    st.warning("暂时无法获取简中服当前活动。排班和工资计算仍可离线使用。")
else:
    st.info("当前没有识别到正在进行的简中服活动。")

uploaded_file = st.file_uploader(
    "上传排班表",
    type=["xlsx", "xlsm"],
    help="支持日期区块左右并排、首尾日期不完整、半小时和跨午夜时间段。每个工作表视为一个班组。",
)

if uploaded_file is None:
    st.info("请上传排班表。Excel、WPS 和 LibreOffice 保存的 .xlsx 文件均可使用。")
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
    original_sheets = load_workbook_sheets(file_bytes)
except ScheduleParseError as exc:
    st.error(str(exc))
    st.stop()

st.subheader("1. 核对并微调完整排班")
st.caption("下面保留上传表格的完整横向布局。双击单元格即可改人名、岗位或时间，工资会自动重新计算。")

schedule_state_key = f"schedule_sheets_{file_fingerprint}"
schedule_editor_keys = {
    sheet_name: f"schedule_editor_{file_fingerprint}_{index}"
    for index, sheet_name in enumerate(original_sheets)
}
if schedule_state_key not in st.session_state:
    st.session_state[schedule_state_key] = make_editable_sheets(original_sheets)

if st.button("恢复上传时的排班", use_container_width=False):
    st.session_state[schedule_state_key] = make_editable_sheets(original_sheets)
    for editor_key in schedule_editor_keys.values():
        st.session_state.pop(editor_key, None)
    st.rerun()

schedule_sheets: dict[str, pd.DataFrame] = {}
sheet_names = list(original_sheets)
sheet_tabs = st.tabs(sheet_names) if len(sheet_names) > 1 else [st.container()]
for sheet_name, sheet_tab in zip(sheet_names, sheet_tabs):
    with sheet_tab:
        if len(sheet_names) == 1:
            st.caption(f"工作表：{sheet_name}")
        source_frame = st.session_state[schedule_state_key][sheet_name]
        editor_height = min(700, max(280, 35 * (len(source_frame) + 1)))
        schedule_sheets[sheet_name] = st.data_editor(
            source_frame,
            key=schedule_editor_keys[sheet_name],
            height=editor_height,
            use_container_width=True,
            num_rows="fixed",
        )
st.session_state[schedule_state_key] = schedule_sheets

try:
    parsed = parse_schedule_sheets(schedule_sheets)
except ScheduleParseError as exc:
    st.error(f"当前排班无法计算：{exc}")
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

schedule_start = records["date"].min().date()
schedule_end = records["date"].max().date()
event_match: str | None = None
if current_event is not None:
    event_match = compare_schedule_dates(schedule_start, schedule_end, current_event)
    if event_match == "match":
        st.success("活动校验通过：排班日期完整落在当前活动周期内。")
    elif event_match == "partial":
        st.warning("活动校验：排班只有部分日期与当前活动重合，请检查首尾日期。")
    else:
        st.warning("活动校验：排班日期不属于当前活动，请确认是否上传了上一期或下一期排班。")

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
    st.caption("排班和工资不会上传或持久化保存，关闭会话后即可丢弃。")

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

with st.expander("查看识别到的日期区块", expanded=False):
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

st.subheader("2. 设置工价")
st.caption("默认：跑类和 s6 为白班 30 / 夜班 35；推类为白班 20 / 夜班 25。仍可逐项修改。")

default_rates = build_default_rates(records)
role_signature = hashlib.sha256(
    default_rates[["班组", "岗位"]].to_csv(index=False).encode("utf-8")
).hexdigest()[:12]
rates_state_key = f"rates_{file_fingerprint}"
rates_editor_key = f"rates_editor_{file_fingerprint}_{role_signature}"
st.session_state[rates_state_key] = reconcile_rates(
    default_rates,
    st.session_state.get(rates_state_key),
)

if st.button("恢复岗位默认工价", use_container_width=False):
    st.session_state[rates_state_key] = default_rates
    st.session_state.pop(rates_editor_key, None)
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

st.subheader("3. 发薪结果")
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
result_metrics[0].metric("发薪人数", len(result.payroll_summary))
result_metrics[1].metric("总工时", f"{result.total_hours:,.2f}")
result_metrics[2].metric("应发合计", f"¥ {result.total_salary:,.2f}")

summary_tab, detail_tab = st.tabs(["发薪汇总", "按日明细"])
with summary_tab:
    payroll_display = result.payroll_summary.copy()
    if len(selected_teams) == 1:
        payroll_display = payroll_display.drop(columns="班组")
    st.dataframe(
        payroll_display,
        hide_index=True,
        use_container_width=True,
        column_config={
            "总工时": st.column_config.NumberColumn("总工时", format="%.2f"),
            "应发工资": st.column_config.NumberColumn("应发工资", format="¥ %.2f"),
        },
    )

with detail_tab:
    daily_display = result.daily_detail.copy()
    if len(selected_teams) == 1:
        daily_display = daily_display.drop(columns="班组")
    st.dataframe(
        daily_display,
        hide_index=True,
        use_container_width=True,
        column_config={
            "日期": st.column_config.DateColumn("日期", format="YYYY-MM-DD"),
            "白班工时": st.column_config.NumberColumn("白班工时", format="%.2f"),
            "夜班工时": st.column_config.NumberColumn("夜班工时", format="%.2f"),
            "总工时": st.column_config.NumberColumn("总工时", format="%.2f"),
            "应发工资": st.column_config.NumberColumn("应发工资", format="¥ %.2f"),
        },
    )

st.subheader("4. 导出结算结果")
default_export_name = (
    current_event.name
    if current_event is not None and event_match == "match"
    else Path(uploaded_file.name).stem
)
event_name = st.text_input("导出文件名", value=default_export_name).strip()
download_name = safe_filename(event_name)
selected_schedule_sheets = {
    team: schedule_sheets[team] for team in selected_teams if team in schedule_sheets
}

excel_bytes = export_salary_excel(result, selected_rates, selected_schedule_sheets)
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
        "下载发薪汇总 CSV",
        data=csv_bytes,
        file_name=f"{download_name}_发薪汇总.csv",
        mime="text/csv",
        use_container_width=True,
    )

st.caption("Excel 包含精简发薪汇总、按日结算明细、工价设置，以及微调后的完整排班工作表。")
