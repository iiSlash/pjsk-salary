import streamlit as st
import pandas as pd
import datetime
import urllib.request
import json
import os
import io

# ================= 0. 存读档与数据分离架构 =================
MANUAL_SAVE_FILE = "pjsk_manual_save.json"

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

# 存档现在保存 latest_schedules (用户最终编辑的结果)
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
    st.session_state.last_view = None # 强制刷新视图
    for k, v in data.get("days", {}).items():
        st.session_state[k] = v

# 初始化三大核心状态：基础数据(不可变)、最新数据(存放输出)、当前视图标记
if "base_schedules" not in st.session_state:
    st.session_state.base_schedules = {}
if "latest_schedules" not in st.session_state:
    st.session_state.latest_schedules = {}
if "last_view" not in st.session_state:
    st.session_state.last_view = None
if "team_roles" not in st.session_state:
    st.session_state.team_roles = {}

# ================= 1. 数据拉取模块 =================
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
        except:
            continue

    if events_data is None:
        now = datetime.datetime.now()
        return pd.DataFrame({
            "活动名称": ["【离线模式】自定义活动"],
            "显示名称": ["【离线模式】自定义活动 (01-01至01-07)"],
            "开始日期": [now], "结束日期": [now + datetime.timedelta(days=7)], "天数": [8]
        })

    parsed_events = []
    for event in reversed(events_data):
        start_dt = datetime.datetime.fromtimestamp(event["startAt"] / 1000.0)
        end_dt = datetime.datetime.fromtimestamp(event["aggregateAt"] / 1000.0)
        days = (end_dt.date() - start_dt.date()).days + 1
        display_name = f"{event['name']} ({start_dt.strftime('%m-%d')}至{end_dt.strftime('%m-%d')})"
        parsed_events.append({
            "活动名称": event["name"], "显示名称": display_name,
            "开始日期": start_dt, "结束日期": end_dt, "天数": days
        })
    return pd.DataFrame(parsed_events)

events_df = fetch_pjsk_cn_events()

# ================= 2. 界面初始化 =================
st.set_page_config(page_title="PJSK 多队伍排班系统", layout="wide")
st.title("🎵 PJSK 简中服 - 多队伍动态排班系统")

current_dt = datetime.datetime.now()
default_event_idx = 0
for i, row in events_df.iterrows():
    if row["开始日期"] <= current_dt <= row["结束日期"]:
        default_event_idx = int(i)
        break

# ================= 3. 侧边栏：存读档 =================
st.sidebar.header("💾 手动存读档")
col1, col2 = st.sidebar.columns(2)
with col1:
    if st.button("💾 保存进度", width="stretch"):
        with open(MANUAL_SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(get_save_data(), f, ensure_ascii=False, indent=2)
        st.sidebar.success("已存档！")
with col2:
    if st.button("📂 读取存档", width="stretch"):
        if os.path.exists(MANUAL_SAVE_FILE):
            with open(MANUAL_SAVE_FILE, "r", encoding="utf-8") as f:
                apply_save_data(json.load(f))
            st.rerun()
        else:
            st.sidebar.error("没有找到存档文件")

if st.sidebar.button("⚠️ 清空所有数据", type="primary", width="stretch"):
    for key in ["base_schedules", "latest_schedules", "team_roles"]:
        if key in st.session_state:
            del st.session_state[key]
    st.session_state.last_view = None
    st.rerun()

# ================= 4. 侧边栏：活动与队伍 =================
st.sidebar.header("🗓️ 活动与队伍")
selected_display_name = st.sidebar.selectbox("选择排期活动", events_df["显示名称"].tolist(), index=default_event_idx)
event_info = events_df[events_df["显示名称"] == selected_display_name].iloc[0]
selected_event_name = event_info["活动名称"]
default_days = int(event_info["天数"])

teams = ["队伍A", "队伍B", "队伍C", "队伍D", "队伍E", "队伍F"]
selected_team = st.sidebar.selectbox("切换队伍", teams)

current_view = f"{selected_event_name}_{selected_team}"

# 【核心防闪烁逻辑】：只有当切换队伍时，才把最新的编辑数据同步为底层数据，否则绝不干涉底层
if st.session_state.last_view != current_view:
    st.session_state.last_view = current_view
    if current_view in st.session_state.latest_schedules:
        # 深拷贝，防止互相污染
        st.session_state.base_schedules[current_view] = [df.copy() for df in st.session_state.latest_schedules[current_view]]
    else:
        st.session_state.base_schedules[current_view] = []
        st.session_state.latest_schedules[current_view] = []

# ================= 5. 工种与天数处理 =================
if selected_team not in st.session_state.team_roles:
    st.session_state.team_roles[selected_team] = get_default_roles(selected_team)

st.sidebar.header("📝 当前队伍工种")
team_roles_str = ", ".join(st.session_state.team_roles[selected_team])
roles_input = st.sidebar.text_input(f"{selected_team} 工种列表（逗号分隔）", value=team_roles_str)
team_roles = [r.strip() for r in roles_input.split(",") if r.strip()]
if not team_roles: team_roles = ["默认工种"]
st.session_state.team_roles[selected_team] = team_roles

days_key = f"days_{current_view}"
if days_key not in st.session_state:
    st.session_state[days_key] = default_days
current_days = st.sidebar.number_input(f"{selected_team} 实际天数", min_value=1, max_value=30, value=st.session_state[days_key])
st.session_state[days_key] = current_days

# 处理天数增加或减少
base_list = st.session_state.base_schedules[current_view]
time_slots = [f"{i}:00-{i+1}:00" for i in range(24)]

while len(base_list) < current_days:
    base_list.append(pd.DataFrame("", index=time_slots, columns=team_roles))
if len(base_list) > current_days:
    base_list = base_list[:current_days]

# 处理工种增删
for i in range(len(base_list)):
    df = base_list[i]
    if list(df.columns) != team_roles:
        for r in team_roles:
            if r not in df.columns:
                df[r] = ""
        base_list[i] = df[team_roles]

st.session_state.base_schedules[current_view] = base_list

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

# ================= 6. 主界面表格展示 =================
st.header(f"📅 【{selected_event_name}】 - {selected_team}")
st.caption(f"当前工种：{' / '.join(team_roles)}")

tabs = st.tabs([f"第 {i+1} 天" for i in range(current_days)])
current_edited = []

for i, tab in enumerate(tabs):
    with tab:
        # 此时读取的是静态的 base 数据，输出统一收集，不再覆盖自身！
        edited_df = st.data_editor(
            st.session_state.base_schedules[current_view][i],
            key=f"editor_{current_view}_day_{i}",
            width="stretch",
            height=900
        )
        current_edited.append(edited_df)

# 把输出统一存到 latest，用于计算和存档
st.session_state.latest_schedules[current_view] = current_edited

# ================= 7. 汇总计算与导出 =================
st.header(f"📊 {selected_team} 工资汇总")
if st.button(f"🚀 计算【{selected_team}】工资", type="primary", width="stretch"):
    salary_data = {}
    
    # 【注意】计算时我们用的是用户刚编辑完的 latest 数据
    for df in st.session_state.latest_schedules[current_view]:
        for i, time_slot in enumerate(time_slots):
            is_night_shift = (
                (i < day_start or i >= night_start)
                if day_start < night_start
                else (night_start <= i < day_start)
            )
            for role in team_roles:
                name = df.loc[time_slot, role]
                if pd.isna(name) or str(name).strip() == "": continue
                name = str(name).strip()
                if name not in salary_data: salary_data[name] = {"total_hours": 0, "total_salary": 0}
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
        
        # 导出 Excel
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            result_df.to_excel(writer, index=False, sheet_name='工资汇总')
        excel_bytes = excel_buffer.getvalue()

        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            st.download_button(
                f"📥 导出 Excel",
                data=excel_bytes,
                file_name=f"PJSK_{safe_filename}_{selected_team}_工资.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        with col_dl2:
            st.download_button(
                f"📥 导出 CSV",
                data=result_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"PJSK_{safe_filename}_{selected_team}_工资.csv",
                mime="text/csv",
                use_container_width=True
            )
