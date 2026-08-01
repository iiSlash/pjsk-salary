from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, DataReturnMode, GridUpdateMode, JsCode

from pjsk_salary.events import (
    EventPeriod,
    compare_schedule_dates,
    fetch_pjsk_cn_events,
    find_best_event_for_schedule,
    find_current_event,
)
from pjsk_salary.exporter import export_salary_excel, export_summary_csv
from pjsk_salary.parser import ScheduleParseError, parse_schedule_sheets, read_schedule_workbook
from pjsk_salary.salary import SalaryValidationError, build_default_rates, calculate_salary
from pjsk_salary.schedule import (
    START_MINUTES_COLUMN,
    TIME_COLUMN,
    build_daily_grids,
    build_horizontal_grid,
    daily_grids_to_records,
    horizontal_grid_to_daily_grids,
)


st.set_page_config(page_title="PJSK 工资计算器", page_icon="💰", layout="wide")


@st.cache_data(show_spinner=False)
def load_workbook_sheets(file_bytes: bytes) -> dict[str, pd.DataFrame]:
    return read_schedule_workbook(file_bytes)


@st.cache_data(ttl=3600, show_spinner=False)
def load_events() -> tuple[list[EventPeriod], str | None]:
    return fetch_pjsk_cn_events()


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", value).strip(" ._")
    return cleaned or "工资结算"


def display_date_range(records: pd.DataFrame) -> str:
    first_date = records["date"].min().strftime("%Y-%m-%d")
    last_date = records["date"].max().strftime("%Y-%m-%d")
    return first_date if first_date == last_date else f"{first_date} 至 {last_date}"


def display_schedule_date(value: dt.date) -> str:
    weekdays = "一二三四五六日"
    return f"{value:%Y-%m-%d}（周{weekdays[value.weekday()]}）"


def display_event(event: EventPeriod, current: EventPeriod | None) -> str:
    current_marker = "【当前】" if event == current else ""
    return f"{current_marker}{event.name}｜{event.date_label}"


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


def edit_horizontal_schedule(
    date_grids: dict[dt.date, pd.DataFrame],
    *,
    key: str,
    day_start_hour: int,
    night_start_hour: int,
) -> dict[dt.date, pd.DataFrame]:
    frame, date_columns = build_horizontal_grid(date_grids)
    date_options = [
        {
            "field": next(iter(fields)),
            "label": f"{schedule_date:%m-%d} 周{'一二三四五六日'[schedule_date.weekday()]}",
        }
        for schedule_date, fields in date_columns.items()
        if fields
    ]
    date_targets = {option["label"]: option["field"] for option in date_options}
    navigate_on_change = JsCode(
        f"""
        function(params) {{
            if (!params.node.rowPinned || params.colDef.field !== '{TIME_COLUMN}') {{
                return;
            }}
            const targets = {json.dumps(date_targets, ensure_ascii=False)};
            const target = targets[params.newValue];
            if (target) {{
                window.setTimeout(function() {{
                    params.api.ensureColumnVisible(target, 'start');
                }}, 0);
            }}
        }}
        """
    )
    should_return = JsCode(
        """
        function({streamlitRerunEventTriggerName, eventData}) {
            if (streamlitRerunEventTriggerName === 'cellValueChanged'
                    && eventData && eventData.rowPinned === 'top') {
                return false;
            }
            return true;
        }
        """
    )
    date_labels = [option["label"] for option in date_options]
    column_defs = [
        {
            "field": TIME_COLUMN,
            "headerName": "时间",
            "editable": JsCode(
                "function(params) { return Boolean(params.node.rowPinned); }"
            ),
            "pinned": "left",
            "lockPosition": "left",
            "width": 112,
            "minWidth": 112,
            "maxWidth": 112,
            "cellStyle": JsCode(
                """
                function(params) {
                    if (params.node.rowPinned) {
                        return {
                            fontWeight: '600',
                            backgroundColor: '#eaf2f8',
                            cursor: 'pointer'
                        };
                    }
                    return { fontWeight: '600' };
                }
                """
            ),
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": {"values": date_labels},
        }
    ]
    for schedule_date, fields in date_columns.items():
        column_defs.append(
            {
                "headerName": display_schedule_date(schedule_date),
                "marryChildren": True,
                "children": [
                    {
                        "field": field,
                        "headerName": role,
                        "editable": True,
                        "width": 82,
                        "minWidth": 68,
                        "maxWidth": 110,
                    }
                    for field, role in fields.items()
                ],
            }
        )
    column_defs.append({"field": START_MINUTES_COLUMN, "hide": True})

    day_start_minutes = day_start_hour * 60
    night_start_minutes = night_start_hour * 60
    row_style = JsCode(
        f"""
        function(params) {{
            if (params.node.rowPinned) {{
                return {{ backgroundColor: '#f8f9fa' }};
            }}
            const minute = Number(params.data.{START_MINUTES_COLUMN});
            const dayStart = {day_start_minutes};
            const nightStart = {night_start_minutes};
            const isDay = dayStart < nightStart
                ? minute >= dayStart && minute < nightStart
                : minute >= dayStart || minute < nightStart;
            return isDay ? null : {{ backgroundColor: '#f1f3f5' }};
        }}
        """
    )
    grid_options = {
        "columnDefs": column_defs,
        "defaultColDef": {
            "resizable": True,
            "sortable": False,
            "filter": False,
            "suppressMovable": True,
        },
        "getRowStyle": row_style,
        "onCellValueChanged": navigate_on_change,
        "pinnedTopRowData": [
            {TIME_COLUMN: date_labels[0] if date_labels else "定位日期"}
        ],
        "singleClickEdit": True,
        "stopEditingWhenCellsLoseFocus": True,
        "suppressRowClickSelection": True,
        "alwaysShowHorizontalScroll": True,
        "rowHeight": 28,
        "headerHeight": 34,
        "groupHeaderHeight": 34,
    }
    response = AgGrid(
        frame,
        gridOptions=grid_options,
        data_return_mode=DataReturnMode.AS_INPUT,
        update_mode=GridUpdateMode.VALUE_CHANGED,
        allow_unsafe_jscode=True,
        fit_columns_on_grid_load=False,
        height=min(820, 112 + 28 * len(frame)),
        theme="streamlit",
        key=key,
        should_grid_return=should_return,
    )
    edited = pd.DataFrame(response["data"])
    edited = edited.reindex(columns=frame.columns)
    edited[START_MINUTES_COLUMN] = pd.to_numeric(
        edited[START_MINUTES_COLUMN], errors="coerce"
    ).fillna(frame[START_MINUTES_COLUMN]).astype(int)
    return horizontal_grid_to_daily_grids(edited, date_grids, date_columns)


st.title("💰 PJSK 工资计算器")
st.caption("选择活动、核对每日排班、设置工价，然后直接生成可发放的工资表。数据只保存在当前会话中。")

with st.spinner("正在获取简中服活动列表……"):
    events, event_error = load_events()
current_event = find_current_event(events)

if current_event is not None:
    st.info(f"🎵 当前活动：{current_event.name}　｜　{current_event.date_label}")
elif event_error:
    st.warning("暂时无法获取简中服活动列表。排班和工资计算仍可离线使用。")
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
    original_parsed = parse_schedule_sheets(original_sheets)
except ScheduleParseError as exc:
    st.error(str(exc))
    st.stop()

initial_grids, time_step_minutes = build_daily_grids(
    original_parsed.records, original_parsed.blocks
)
schedule_state_key = f"daily_schedule_{file_fingerprint}"
schedule_revision_key = f"daily_schedule_revision_{file_fingerprint}"
if schedule_state_key not in st.session_state:
    st.session_state[schedule_state_key] = initial_grids
    st.session_state[schedule_revision_key] = 0

daily_grids: dict[str, dict[dt.date, pd.DataFrame]] = st.session_state[
    schedule_state_key
]
all_teams = list(daily_grids)

with st.sidebar:
    st.header("计算范围")
    selected_teams = st.multiselect(
        "班组（工作表）",
        options=all_teams,
        default=all_teams,
        help="一个 Excel 工作表对应一个班组。未选中的班组仍可查看，但不会计入工资。",
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
    st.caption("排班表中的浅灰色行是夜班；跨越边界的时段会分别计价。")
    st.divider()
    st.caption("排班和工资不会上传或持久化保存，关闭会话后即可丢弃。")

if not selected_teams:
    st.warning("请至少选择一个班组。")
    st.stop()
if day_start_hour == night_start_hour:
    st.error("白班开始时间不能和夜班开始时间相同。")
    st.stop()

original_start = original_parsed.records["date"].min().date()
original_end = original_parsed.records["date"].max().date()

st.subheader("1. 选择结算活动")
selected_event: EventPeriod | None = None
if events:
    suggested_event = find_best_event_for_schedule(
        events,
        original_start,
        original_end,
        fallback=current_event,
    )
    suggested_index = events.index(suggested_event) if suggested_event in events else 0
    selected_event = st.selectbox(
        "活动",
        options=events,
        index=suggested_index,
        format_func=lambda event: display_event(event, current_event),
        key=f"event_selector_{file_fingerprint}",
        help="会优先选择与排班日期最匹配的活动，也可以手动改成上一期或其他活动。",
    )
    st.caption("当前活动仍会标注出来；活动选择只用于日期校验和导出命名，不改变工资算法。")
else:
    st.warning("活动列表暂不可用，已跳过活动选择与日期校验。")

st.subheader("2. 核对并微调每日排班")
st.caption(
    "一个班组的全部日期会横向排列。时间列固定在左侧；点击或双击表格第一行的日期即可快速定位，直接横向滚动也不会重新加载。"
)

control_columns = st.columns([1, 3])
with control_columns[0]:
    viewed_team = st.selectbox(
        "查看班组",
        options=all_teams,
        key=f"view_team_{file_fingerprint}",
    )
with control_columns[1]:
    st.write("")
    st.write("")
    if st.button("恢复上传时的全部排班", use_container_width=False):
        restored_grids, _ = build_daily_grids(
            original_parsed.records, original_parsed.blocks
        )
        st.session_state[schedule_state_key] = restored_grids
        st.session_state[schedule_revision_key] += 1
        st.rerun()

revision = st.session_state[schedule_revision_key]
grid_key = (
    f"horizontal_grid_v2_{file_fingerprint}_{viewed_team}_"
    f"{revision}_{day_start_hour}_{night_start_hour}"
)
edited_date_grids = edit_horizontal_schedule(
    daily_grids[viewed_team],
    key=grid_key,
    day_start_hour=day_start_hour,
    night_start_hour=night_start_hour,
)
daily_grids[viewed_team] = edited_date_grids
st.session_state[schedule_state_key] = daily_grids

records = daily_grids_to_records(daily_grids, time_step_minutes)
if records.empty:
    st.error("当前排班没有任何人员，无法计算工资。请填写至少一个人员单元格。")
    st.stop()

st.success(
    f"已载入 {sum(len(date_grids) for date_grids in daily_grids.values())} 个单日排班、"
    f"{records['person'].nunique()} 人、{len(records)} 个已填写岗位单元格。"
)

schedule_start = records["date"].min().date()
schedule_end = records["date"].max().date()
event_match: str | None = None
if selected_event is not None:
    event_match = compare_schedule_dates(schedule_start, schedule_end, selected_event)
    if event_match == "match":
        st.success(f"活动校验通过：排班日期完整落在「{selected_event.name}」周期内。")
    elif event_match == "partial":
        st.warning(f"活动校验：排班只有部分日期与「{selected_event.name}」重合，请检查首尾日期。")
    else:
        st.warning(f"活动校验：排班日期不属于「{selected_event.name}」，请切换活动或检查排班日期。")

filtered_records = records[records["team"].isin(selected_teams)].copy()
metric_columns = st.columns(4)
metric_columns[0].metric("日期范围", display_date_range(filtered_records))
metric_columns[1].metric("结算人数", int(filtered_records["person"].nunique()))
metric_columns[2].metric("排班工时", f"{filtered_records['duration_hours'].sum():,.1f}")
metric_columns[3].metric("班组", len(selected_teams))

st.subheader("3. 设置工价")
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

st.subheader("4. 发薪结果")
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

st.subheader("5. 导出结算结果")
default_export_name = selected_event.name if selected_event is not None else Path(uploaded_file.name).stem
event_name = st.text_input("导出文件名", value=default_export_name).strip()
download_name = safe_filename(event_name)
selected_schedule_grids = {
    team: daily_grids[team] for team in selected_teams if team in daily_grids
}

excel_bytes = export_salary_excel(
    result,
    selected_rates,
    schedule_grids=selected_schedule_grids,
    day_start_hour=day_start_hour,
    night_start_hour=night_start_hour,
)
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

st.caption("Excel 包含精简发薪汇总、按日结算明细、工价设置，以及按日期整理的完整排班；夜班行同样使用浅灰色。")
