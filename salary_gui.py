import streamlit as st
import pandas as pd
import datetime
import urllib.request
import json
import io
from streamlit_gsheets import GSheetsConnection

DEFAULT_TEAM_ROLES = {
    "队伍A": ["跑1", "s6", "推1", "推2", "推3"],
    "队伍B": ["前台", "后勤", "代跑"],
    "队伍C": ["打手", "客服", "结算"],
    "队伍D": ["跑1", "推1"],
    "队伍E": ["客服", "场控"],
    "队伍F": ["代跑", "审核"]
}


def get_default_roles(team_name):
    return DEFAULT_TEAM_ROLES.get(team_name, ["默认工种"])


def get_save_data():
    save_data = {
        "team_roles": st.session_state.get("team_roles", {}),
        "latest_schedules": {},
        "days": {}
    }
    if "latest_schedules" in st.session_state:
        for k, v in st.session_state.latest_schedules.items():
            save_data["latest_schedules"][k] = [df.to_dict(orient="index") for df in v]
    for k, v in st.session_state.items():
        if k.startswith("days_"):
            save_data["days"][k] = v
    return save_data


def apply_save_data(data):
    st.session_state.team_roles = data.get("team_roles", {})
    loaded_schedules = {}
    for k, v in data.get("latest_schedules", {}).items():
        loaded_schedules[k] = [
            pd.DataFrame.from_dict(df_dict, orient="index") for df_dict in v
        ]
    st.session_state.latest_schedules = loaded_schedules
    st.session_state.last_view = None
    for k, v in data.get("days", {}).items():
        st.session_state[k] = v


def ensure_sheet_columns(df):
    required_cols = ["save_key", "event_name", "team_name", "updated_at", "data_json"]
    if df is None or df.empty:
        return pd.DataFrame(columns=required_cols)
    for col in required_cols:
        if col not in df.columns:
            df[col] = ""
    return df[required_cols]


if "base_schedules" not in st.session_state:
    st.session_state.base_schedules = {}
if "latest_schedules" not in st.session_state:
    st.session_state.latest_schedules = {}
if "last_view" not in st.session_state:
    st.session_state.last_view = None
if "team_roles" not in st.session_state:
    st.session_state.team_roles = {}


@st.cache_data(ttl=43200)
def fetch_pjsk_cn_events():
    urls = [
        "https://ghproxy.net/https://raw.githubusercontent.com/Sekai-World/sekai-master-db-cn-diff/main/events.json",
        "https://raw.gitmirror.com/Sekai-World/sekai-master-db-cn-diff/main/events.json",
        "https://cdn.jsdelivr.net/gh/Sekai-World/sekai-master-db-cn-diff@main/events.json"
    ]
    events_data = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            response = urllib.request.urlopen(req, timeout=5)
            events_data = json.loads(response.read().decode("utf-8"))
            break
        except Exception:
            continue

    if events_data is None:
        now = datetime.datetime.now()
        return pd.DataFrame({
            "活动名称": ["【离线模式】自定义活动"],
            "显示名称": ["【离线模式】自定义活动 (01-01至01-07)"],
            "开始日期": [now],
            "结束日期": [now + datetime.timedelta(days=7)],
            "天数": [8]
        })

    parsed_events = []
    for event in reversed(events_data):
        start_dt = datetime.datetime.fromtimestamp(event["startAt"] / 1000.0)
        end_dt = datetime.datetime.fromtimestamp(event["aggregateAt"] / 1000.0)
        days = (end_dt.date() - start_dt.date()).days + 1
        display_name = f"{event['name']} ({start_dt.strftime('%m-%d')}至{end_dt.strftime('%m-%d')})"
        parsed_events.append({
            "活动名称": event["name"],
            "显示名称": display_name,
            "开始日期": start_dt,
            "结束日期": end_dt,
            "天数": days
        })
    return pd.DataFrame(parsed_events)


events_df = fetch_pjsk_cn_events()

st.set_page_config(page_title="PJSK 多队伍排班系统", layout="wide")
st.title("🎵 PJSK 简中服 - 多队伍动态排班系统")

try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception:
    conn = None

current_dt = datetime.datetime.now()
default_event_idx = 0
for i, row in events_df.iterrows():
    if row["开始日期"] <= current_dt <= row["结束日期"]:
        default_event_idx = int(i)
        break

st.sidebar.header("🗓️ 活动与队伍")
selected_display_name = st.sidebar.selectbox(
    "选择排期活动",
    events_df["显示名称"].tolist(),
    index=default_event_idx
)
event_info = events_df[events_df["显示名称"] == selected_display_name].iloc[0]
selected_event_name = event_info["活动名称"]
default_days = int(event_info["天数"])

teams = ["队伍A", "队伍B", "队伍C", "队伍D", "队伍E", "队伍F"]
selected_team = st.sidebar.selectbox("切换队伍", teams)

current_view = f"{selected_event_name}_{selected_team}"
save_key = current_view

if st.session_state.last_view != current_view:
    st.session_state.last_view = current_view
    if current_view in st.session_state.latest_schedules:
        st.session_state.base_schedules[current_view] = [
            df.copy() for df in st.session_state.latest_schedules[current_view]
        ]
    else:
        st.session_state.base_schedules[current_view] = []
        st.session_state.latest_schedules[current_view] = []

if selected_team not in st.session_state.team_roles:
    st.session_state.team_roles[selected_team] = get_default_roles(selected_team)

st.sidebar.header("📝 当前队伍工种")
team_roles_str = ", ".join(st.session_state.team_roles[selected_team])
roles_input = st.sidebar.text_input(
    f"{selected_team} 工种列表（逗号分隔）",
    value=team_roles_str
)
team_roles = [r.strip() for r in roles_input.split(",") if r.strip()]
if not team_roles:
    team_roles = ["默认工种"]
st.session_state.team_roles[selected_team] = team_roles

days_key = f"days_{current_view}"
if days_key not in st.session_state:
    st.session_state[days_key] = default_days

current_days = st.sidebar.number_input(
    f"{selected_team} 实际天数",
    min_value=1,
    max_value=30,
    value=st.session_state[days_key]
)
st.session_state[days_key] = current_days

base_list = st.session_state.base_schedules[current_view]
time_slots = [f"{i}:00-{i+1}:00" for i in range(24)]

while len(base_list) < current_days:
    base_list.append(pd.DataFrame("", index=time_slots, columns=team_roles))
if len(base_list) > current_days:
    base_list = base_list[:current_days]

for i in range(len(base_list)):
    df = base_list[i]
    if list(df.columns) != team_roles:
        for r in team_roles:
            if r not in df.columns:
                df[r] = ""
        base_list[i] = df[team_roles]

st.session_state.base_schedules[current_view] = base_list

if current_view not in st.session_state.latest_schedules or not st.session_state.latest_schedules[current_view]:
    st.session_state.latest_schedules[current_view] = [
        df.copy() for df in st.session_state.base_schedules[current_view]
    ]

st.sidebar.header("☁️ 云端存档 (Google Sheets)")

if st.sidebar.button("☁️ 云端读取当前队伍", use_container_width=True):
    if conn is None:
        st.sidebar.error("云端存储未配置！请检查 Secrets。")
    else:
        try:
            cloud_df = conn.read(worksheet="saves", ttl=0)
            cloud_df = ensure_sheet_columns(cloud_df)
            matched = cloud_df[cloud_df["save_key"] == save_key]
            if not matched.empty:
                latest_row = matched.iloc[-1]
                loaded_data = json.loads(latest_row["data_json"])
                apply_save_data(loaded_data)

                for i in range(30):
                    ekey = f"editor_{current_view}_day_{i}"
                    if ekey in st.session_state:
                        del st.session_state[ekey]

                st.sidebar.success("云端读档成功，页面即将刷新")
                st.rerun()
            else:
                st.sidebar.warning("云端没有找到该活动和队伍的存档")
        except Exception as e:
            st.sidebar.error(f"云端读档失败：{e}")

if st.sidebar.button("☁️ 云端保存当前队伍", use_container_width=True):
    if conn is None:
        st.sidebar.error("云端存储未配置！请检查 Secrets。")
    else:
        try:
            cloud_df = conn.read(worksheet="saves", ttl=0)
            cloud_df = ensure_sheet_columns(cloud_df)

            current_data_json = json.dumps(get_save_data(), ensure_ascii=False)
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            new_row = pd.DataFrame([{
                "save_key": save_key,
                "event_name": selected_event_name,
                "team_name": selected_team,
                "updated_at": now_str,
                "data_json": current_data_json
            }])

            cloud_df = cloud_df[cloud_df["save_key"] != save_key]
            cloud_df = pd.concat([cloud_df, new_row], ignore_index=True)

            conn.update(worksheet="saves", data=cloud_df)
            st.sidebar.success("云端保存成功")
        except Exception as e:
            st.sidebar.error(f"云端保存失败：{e}")

if st.sidebar.button("⚠️ 清空所有数据", type="primary", width="stretch"):
    for key in ["base_schedules", "latest_schedules", "team_roles"]:
        if key in st.session_state:
            del st.session_state[key]
    st.session_state.last_view = None
    st.rerun()

st.sidebar.header("⏰ 班次时间")
day_start = st.sidebar.number_input("白班开始", min_value=0, max_value=23, value=8)
night_start = st.sidebar.number_input("夜班开始", min_value=0, max_value=23, value=20)

st.sidebar.header("⚙️ 当前队伍工价")
rates = {}
for role in team_roles:
    with st.sidebar.expander(f"[{role}] 工价", expanded=False):
        rates[role] = {
            "day": st.number_input(f"{role} 白班价", value=20, key=f"{selected_team}_{role}_day"),
            "night": st.number_input(f"{role} 夜班价", value=30, key=f"{selected_team}_{role}_night")
        }

st.header(f"📅 【{selected_event_name}】 - {selected_team}")
st.caption(f"当前工种：{' / '.join(team_roles)}")

with st.expander("📁 排班表 Excel 导入与导出 (方便本地修改)", expanded=False):
    st.info("💡 建议先下载当前空表（或已排好的表）作为模板。在 Excel 里修改后，再上传覆盖当前网页内容。")
    col_ex, col_im = st.columns(2)

    with col_ex:
        schedule_excel_buffer = io.BytesIO()
        schedule_source = st.session_state.base_schedules.get(current_view, [])

        with pd.ExcelWriter(schedule_excel_buffer, engine="openpyxl") as writer:
            if schedule_source:
                for i, df in enumerate(schedule_source):
                    export_df = df.copy()
                    export_df.to_excel(writer, sheet_name=f"第{i+1}天")
            else:
                empty_df = pd.DataFrame("", index=time_slots, columns=team_roles)
                empty_df.to_excel(writer, sheet_name="第1天")

        schedule_excel_bytes = schedule_excel_buffer.getvalue()
        safe_filename = "".join(x for x in selected_event_name if x.isalnum() or x in " -_")

        st.download_button(
            "📥 下载排班表模板 (Excel)",
            data=schedule_excel_bytes,
            file_name=f"排班表_{safe_filename}_{selected_team}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

    with col_im:
        uploaded_schedule = st.file_uploader("📂 上传填好的排班表并覆盖", type=["xlsx"])
        if uploaded_schedule is not None:
            if st.button("🚀 确认导入并覆盖", use_container_width=True):
                try:
                    xls = pd.read_excel(uploaded_schedule, sheet_name=None, index_col=0)
                    new_schedules = []

                    for i in range(current_days):
                        sheet_name = f"第{i+1}天"
                        clean_df = pd.DataFrame("", index=time_slots, columns=team_roles)

                        if sheet_name in xls:
                            imported_df = xls[sheet_name].fillna("").astype(str)
                            for t in time_slots:
                                if t in imported_df.index:
                                    for r in team_roles:
                                        if r in imported_df.columns:
                                            clean_df.at[t, r] = imported_df.at[t, r]

                        new_schedules.append(clean_df)

                    st.session_state.base_schedules[current_view] = new_schedules
                    st.session_state.latest_schedules[current_view] = [df.copy() for df in new_schedules]

                    for i in range(current_days):
                        editor_key = f"editor_{current_view}_day_{i}"
                        if editor_key in st.session_state:
                            del st.session_state[editor_key]

                    st.success("导入覆盖成功，页面即将刷新！")
                    st.rerun()
                except Exception as e:
                    st.error(f"导入失败，请检查文件是否被破坏：{e}")

tabs = st.tabs([f"第 {i+1} 天" for i in range(current_days)])
current_edited = []

for i, tab in enumerate(tabs):
    with tab:
        df_for_edit = st.session_state.base_schedules[current_view][i]

        # 让表格尽量完整展开显示，避免内部滚动条
        # 24行排班 + 表头，按每行约35像素计算
        editor_height = int((len(df_for_edit) + 1) * 35 + 6)

        edited_df = st.data_editor(
            df_for_edit,
            key=f"editor_{current_view}_day_{i}",
            width="stretch",
            height=editor_height
        )
        current_edited.append(edited_df)

st.session_state.latest_schedules[current_view] = current_edited

st.header(f"📊 {selected_team} 工资汇总")

if st.button(f"🚀 计算【{selected_team}】工资", type="primary", width="stretch"):
    salary_data = {}

    for df in st.session_state.latest_schedules[current_view]:
        for i, time_slot in enumerate(time_slots):
            is_night_shift = (
                (i < day_start or i >= night_start)
                if day_start < night_start
                else (night_start <= i < day_start)
            )

            for role in team_roles:
                name = df.loc[time_slot, role]
                if pd.isna(name) or str(name).strip() == "":
                    continue

                name = str(name).strip()

                if name not in salary_data:
                    salary_data[name] = {"total_hours": 0, "total_salary": 0}

                salary_data[name]["total_hours"] += 1
                salary_data[name]["total_salary"] += rates[role]["night" if is_night_shift else "day"]

    if salary_data:
        result_df = pd.DataFrame([
            {"姓名": k, "总工时(小时)": v["total_hours"], "总工资(元)": v["total_salary"]}
            for k, v in salary_data.items()
        ]).sort_values(by="总工资(元)", ascending=False).reset_index(drop=True)

        st.success(f"{selected_team} 计算完成！")
        st.dataframe(result_df, width="stretch", height="stretch")

        safe_filename = "".join(x for x in selected_event_name if x.isalnum() or x in " -_")

        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            result_df.to_excel(writer, index=False, sheet_name="工资汇总")
        excel_bytes = excel_buffer.getvalue()

        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            st.download_button(
                "📥 导出 Excel",
                data=excel_bytes,
                file_name=f"PJSK_{safe_filename}_{selected_team}_工资.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        with col_dl2:
            st.download_button(
                "📥 导出 CSV",
                data=result_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"PJSK_{safe_filename}_{selected_team}_工资.csv",
                mime="text/csv",
                use_container_width=True
            )