import streamlit as st
import pandas as pd
import datetime
import urllib.request
import json
import io
from streamlit_gsheets import GSheetsConnection

DEFAULT_TEAM_NAMES = {
    "team_1": "队伍A",
    "team_2": "队伍B",
    "team_3": "队伍C",
    "team_4": "队伍D",
    "team_5": "队伍E",
    "team_6": "队伍F",
}

DEFAULT_TEAM_ROLES = {
    "team_1": ["跑1", "s6", "推1", "推2", "推3"],
    "team_2": ["前台", "后勤", "代跑"],
    "team_3": ["打手", "客服", "结算"],
    "team_4": ["跑1", "推1"],
    "team_5": ["客服", "场控"],
    "team_6": ["代跑", "审核"]
}


def make_team_key(i: int):
    return f"team_{i}"


def get_default_team_name(team_key):
    return DEFAULT_TEAM_NAMES.get(team_key, f"队伍{team_key.split('_')[-1]}")


def get_default_roles(team_key):
    return DEFAULT_TEAM_ROLES.get(team_key, ["默认工种"])


def init_team_config():
    if "team_count" not in st.session_state:
        st.session_state.team_count = 6

    if "team_names" not in st.session_state:
        st.session_state.team_names = {}

    if "team_roles" not in st.session_state:
        st.session_state.team_roles = {}

    for i in range(1, st.session_state.team_count + 1):
        team_key = make_team_key(i)
        if team_key not in st.session_state.team_names:
            st.session_state.team_names[team_key] = get_default_team_name(team_key)
        if team_key not in st.session_state.team_roles:
            st.session_state.team_roles[team_key] = get_default_roles(team_key)


def get_team_keys():
    return [make_team_key(i) for i in range(1, st.session_state.team_count + 1)]


def get_team_name(team_key):
    return st.session_state.team_names.get(team_key, get_default_team_name(team_key))


def get_full_save_data():
    save_data = {
        "team_count": st.session_state.get("team_count", 6),
        "team_roles": st.session_state.get("team_roles", {}),
        "team_names": st.session_state.get("team_names", {}),
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


def get_basic_config_data():
    basic_data = {
        "team_count": st.session_state.get("team_count", 6),
        "team_roles": st.session_state.get("team_roles", {}),
        "team_names": st.session_state.get("team_names", {}),
        "days": {}
    }
    for k, v in st.session_state.items():
        if k.startswith("days_"):
            basic_data["days"][k] = v
    return basic_data


def apply_basic_config_data(data):
    st.session_state.team_count = int(data.get("team_count", 6))
    st.session_state.team_names = data.get("team_names", {})
    st.session_state.team_roles = data.get("team_roles", {})

    for i in range(1, st.session_state.team_count + 1):
        team_key = make_team_key(i)
        if team_key not in st.session_state.team_names:
            st.session_state.team_names[team_key] = get_default_team_name(team_key)
        if team_key not in st.session_state.team_roles:
            st.session_state.team_roles[team_key] = get_default_roles(team_key)

    for k, v in data.get("days", {}).items():
        st.session_state[k] = v


def apply_full_save_data(data):
    apply_basic_config_data(data)

    loaded_schedules = {}
    for k, v in data.get("latest_schedules", {}).items():
        loaded_schedules[k] = [
            pd.DataFrame.from_dict(df_dict, orient="index") for df_dict in v
        ]
    st.session_state.latest_schedules = loaded_schedules
    st.session_state.last_view = None


def ensure_sheet_columns(df):
    required_cols = ["save_key", "event_name", "team_key", "team_name", "updated_at", "data_json"]
    if df is None or df.empty:
        return pd.DataFrame(columns=required_cols)
    for col in required_cols:
        if col not in df.columns:
            df[col] = ""
    return df[required_cols]


def make_empty_schedule(team_roles, time_slots):
    return pd.DataFrame("", index=time_slots, columns=team_roles)


def sanitize_filename(text):
    safe = "".join(x for x in str(text) if x.isalnum() or x in " -_")
    return safe.strip() if safe.strip() else "未命名"


def export_schedule_excel(schedule_list, time_slots, team_roles):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        if schedule_list:
            for i, df in enumerate(schedule_list):
                export_df = df.copy()
                export_df.to_excel(writer, sheet_name=f"第{i+1}天")
        else:
            make_empty_schedule(team_roles, time_slots).to_excel(writer, sheet_name="第1天")
    return output.getvalue()


def save_basic_config_to_cloud(conn):
    try:
        cloud_df = conn.read(worksheet="saves", ttl=0)
        cloud_df = ensure_sheet_columns(cloud_df)

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        config_key = "__GLOBAL_CONFIG__"
        data_json = json.dumps(get_basic_config_data(), ensure_ascii=False)

        new_row = pd.DataFrame([{
            "save_key": config_key,
            "event_name": "__CONFIG__",
            "team_key": "__CONFIG__",
            "team_name": "基础设置",
            "updated_at": now_str,
            "data_json": data_json
        }])

        cloud_df = cloud_df[cloud_df["save_key"] != config_key]
        cloud_df = pd.concat([cloud_df, new_row], ignore_index=True)
        conn.update(worksheet="saves", data=cloud_df)
        return True, "基础设置已保存到云端"
    except Exception as e:
        return False, f"基础设置云端保存失败：{e}"


def load_basic_config_from_cloud(conn):
    try:
        cloud_df = conn.read(worksheet="saves", ttl=0)
        cloud_df = ensure_sheet_columns(cloud_df)

        matched = cloud_df[cloud_df["save_key"] == "__GLOBAL_CONFIG__"]
        if matched.empty:
            return False, "云端没有基础设置"

        latest_row = matched.iloc[-1]
        loaded_data = json.loads(latest_row["data_json"])
        apply_basic_config_data(loaded_data)
        return True, "基础设置已从云端恢复"
    except Exception as e:
        return False, f"基础设置云端读取失败：{e}"


if "base_schedules" not in st.session_state:
    st.session_state.base_schedules = {}
if "latest_schedules" not in st.session_state:
    st.session_state.latest_schedules = {}
if "last_view" not in st.session_state:
    st.session_state.last_view = None
if "cloud_config_loaded" not in st.session_state:
    st.session_state.cloud_config_loaded = False

init_team_config()


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

# 首次启动时自动从云端恢复基础设置，解决刷新后队伍名称和数量丢失问题
if conn is not None and not st.session_state.cloud_config_loaded:
    ok, msg = load_basic_config_from_cloud(conn)
    st.session_state.cloud_config_loaded = True

current_dt = datetime.datetime.now()
default_event_idx = 0
for i, row in events_df.iterrows():
    if row["开始日期"] <= current_dt <= row["结束日期"]:
        default_event_idx = int(i)
        break

# ===== 侧边栏最上方先放云端存档按钮 =====
st.sidebar.header("☁️ 云端存档 (Google Sheets)")
cloud_top_container = st.sidebar.container()

# ===== 再放活动与队伍 =====
st.sidebar.header("🗓️ 活动与队伍")
selected_display_name = st.sidebar.selectbox(
    "选择排期活动",
    events_df["显示名称"].tolist(),
    index=default_event_idx,
    key="selected_display_name"
)
event_info = events_df[events_df["显示名称"] == selected_display_name].iloc[0]
selected_event_name = event_info["活动名称"]
default_days = int(event_info["天数"])

current_team_keys = get_team_keys()
if "selected_team_key" not in st.session_state or st.session_state.selected_team_key not in current_team_keys:
    st.session_state.selected_team_key = current_team_keys[0]

selected_team_key = st.sidebar.selectbox(
    "切换队伍",
    current_team_keys,
    format_func=lambda x: get_team_name(x),
    key="selected_team_key"
)
selected_team_name = get_team_name(selected_team_key)

with st.sidebar.expander("✏️ 队伍名称设置", expanded=False):
    new_team_count = st.number_input(
        "队伍数量",
        min_value=1,
        max_value=30,
        value=st.session_state.team_count,
        step=1,
        key="team_count_input"
    )

    old_team_count = st.session_state.team_count
    if int(new_team_count) != int(old_team_count):
        st.session_state.team_count = int(new_team_count)

        for i in range(1, st.session_state.team_count + 1):
            team_key = make_team_key(i)
            if team_key not in st.session_state.team_names:
                st.session_state.team_names[team_key] = get_default_team_name(team_key)
            if team_key not in st.session_state.team_roles:
                st.session_state.team_roles[team_key] = get_default_roles(team_key)

        if conn is not None:
            save_basic_config_to_cloud(conn)

        valid_team_keys = get_team_keys()
        if st.session_state.selected_team_key not in valid_team_keys:
            st.session_state.selected_team_key = valid_team_keys[0]
        st.rerun()

    for team_key in get_team_keys():
        input_key = f"team_name_input_{team_key}"
        default_value = st.session_state.team_names.get(team_key, get_default_team_name(team_key))

        team_name_value = st.text_input(
            f"{team_key} 名称",
            value=default_value,
            key=input_key
        ).strip()

        st.session_state.team_names[team_key] = team_name_value or get_default_team_name(team_key)

    if st.button("💾 保存队伍基础设置到云端", use_container_width=True):
        if conn is None:
            st.warning("云端存储未配置！请检查 Secrets。")
        else:
            ok, msg = save_basic_config_to_cloud(conn)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

current_view = f"{selected_event_name}_{selected_team_key}"
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

if selected_team_key not in st.session_state.team_roles:
    st.session_state.team_roles[selected_team_key] = get_default_roles(selected_team_key)

st.sidebar.header("📝 当前队伍工种")
team_roles_str = ", ".join(st.session_state.team_roles[selected_team_key])
roles_input = st.sidebar.text_input(
    f"{selected_team_name} 工种列表（逗号分隔）",
    value=team_roles_str
)
team_roles = [r.strip() for r in roles_input.split(",") if r.strip()]
if not team_roles:
    team_roles = ["默认工种"]
st.session_state.team_roles[selected_team_key] = team_roles

days_key = f"days_{current_view}"
if days_key not in st.session_state:
    st.session_state[days_key] = default_days

current_days = st.sidebar.number_input(
    f"{selected_team_name} 实际天数",
    min_value=1,
    max_value=30,
    value=st.session_state[days_key]
)
st.session_state[days_key] = current_days

time_slots = [f"{i}:00-{i+1}:00" for i in range(24)]
base_list = st.session_state.base_schedules[current_view]

while len(base_list) < current_days:
    base_list.append(make_empty_schedule(team_roles, time_slots))
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

# ===== 真正把按钮也放到最上面的 container 里 =====
with cloud_top_container:
    if st.button("☁️ 云端读取当前队伍", use_container_width=True):
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
                    apply_full_save_data(loaded_data)

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

    if st.button("☁️ 云端保存当前队伍", use_container_width=True):
        if conn is None:
            st.sidebar.error("云端存储未配置！请检查 Secrets。")
        else:
            try:
                save_basic_config_to_cloud(conn)

                cloud_df = conn.read(worksheet="saves", ttl=0)
                cloud_df = ensure_sheet_columns(cloud_df)

                current_data_json = json.dumps(get_full_save_data(), ensure_ascii=False)
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                new_row = pd.DataFrame([{
                    "save_key": save_key,
                    "event_name": selected_event_name,
                    "team_key": selected_team_key,
                    "team_name": selected_team_name,
                    "updated_at": now_str,
                    "data_json": current_data_json
                }])

                cloud_df = cloud_df[cloud_df["save_key"] != save_key]
                cloud_df = pd.concat([cloud_df, new_row], ignore_index=True)

                conn.update(worksheet="saves", data=cloud_df)
                st.sidebar.success("云端保存成功（含基础设置）")
            except Exception as e:
                st.sidebar.error(f"云端保存失败：{e}")

if st.sidebar.button("⚠️ 清空所有数据", type="primary", width="stretch"):
    for key in [
        "base_schedules", "latest_schedules", "team_roles", "team_names",
        "team_count", "cloud_config_loaded", "selected_team_key"
    ]:
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
            "day": st.number_input(f"{role} 白班价", value=20, key=f"{selected_team_key}_{role}_day"),
            "night": st.number_input(f"{role} 夜班价", value=30, key=f"{selected_team_key}_{role}_night")
        }

st.header(f"📅 【{selected_event_name}】 - {selected_team_name}")
st.caption(f"当前工种：{' / '.join(team_roles)}")

with st.expander("📁 排班表 Excel 导入与导出 (方便本地修改)", expanded=False):
    st.info("💡 现在提供两个导出按钮：一个导出模板/基础表，一个导出当前页面已编辑的最新内容。")
    col_ex1, col_ex2, col_im = st.columns(3)

    with col_ex1:
        template_excel_bytes = export_schedule_excel(
            st.session_state.base_schedules.get(current_view, []),
            time_slots,
            team_roles
        )
        safe_event = sanitize_filename(selected_event_name)
        safe_team = sanitize_filename(selected_team_name)

        st.download_button(
            "📥 下载排班表模板",
            data=template_excel_bytes,
            file_name=f"排班表模板_{safe_event}_{safe_team}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

    with col_ex2:
        current_excel_bytes = export_schedule_excel(
            st.session_state.latest_schedules.get(current_view, []),
            time_slots,
            team_roles
        )
        safe_event = sanitize_filename(selected_event_name)
        safe_team = sanitize_filename(selected_team_name)

        st.download_button(
            "📥 导出当前排班内容",
            data=current_excel_bytes,
            file_name=f"排班表当前内容_{safe_event}_{safe_team}.xlsx",
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
                        clean_df = make_empty_schedule(team_roles, time_slots)

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
        editor_height = int((len(df_for_edit) + 1) * 35 + 6)

        edited_df = st.data_editor(
            df_for_edit,
            key=f"editor_{current_view}_day_{i}",
            width="stretch",
            height=editor_height
        )
        current_edited.append(edited_df)

st.session_state.latest_schedules[current_view] = current_edited

st.header(f"📊 {selected_team_name} 工资汇总")

if st.button(f"🚀 计算【{selected_team_name}】工资", type="primary", width="stretch"):
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

        st.success(f"{selected_team_name} 计算完成！")
        st.dataframe(result_df, width="stretch", height="stretch")

        safe_event = sanitize_filename(selected_event_name)
        safe_team = sanitize_filename(selected_team_name)

        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            result_df.to_excel(writer, index=False, sheet_name="工资汇总")
        excel_bytes = excel_buffer.getvalue()

        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            st.download_button(
                "📥 导出 Excel",
                data=excel_bytes,
                file_name=f"PJSK_{safe_event}_{safe_team}_工资.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        with col_dl2:
            st.download_button(
                "📥 导出 CSV",
                data=result_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"PJSK_{safe_event}_{safe_team}_工资.csv",
                mime="text/csv",
                use_container_width=True
            )