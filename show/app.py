import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
from datetime import date
from html import escape

import training_plan as _training

# --- 页面全局设置 ---
st.set_page_config(
    page_title="Nice AI - Run",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="collapsed"
)

_SHOW_BASE = os.path.dirname(os.path.abspath(__file__))


def _env_int_sec(name: str, default: int, *, minimum: int = 60) -> int:
    raw = os.getenv(name)
    if not raw or not str(raw).strip():
        return default
    try:
        return max(minimum, int(str(raw).strip()))
    except ValueError:
        return default


# 周报 CSV 约每周变一次；拉长 HTTP 缓存减少对 Google 导出链接的请求（图表仍用下方较短 ttl，仅省 CPU）
_WEEKLY_CSV_CACHE_TTL_SEC = _env_int_sec("WEEKLY_REPORT_CSV_CACHE_TTL_SEC", 86400)
_ACTIVITY_CSV_CACHE_TTL_SEC = _env_int_sec("ACTIVITY_ADVICE_CSV_CACHE_TTL_SEC", 300)

def local_css(file_name):
    current_file_path = os.path.abspath(__file__)
    current_dir = os.path.dirname(current_file_path)
    file_path = os.path.join(current_dir, file_name)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)
    except FileNotFoundError:
        st.error(f"❌ 找不到文件: {file_path}")

def load_content(file_name):
    file_path = os.path.join(_SHOW_BASE, file_name)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return ""

# ---------------------------------------------------------
# 页面配置
# ---------------------------------------------------------
local_css("assets/styles.css")

# ---------------------------------------------------------
# 侧边栏导航
# ---------------------------------------------------------
with st.sidebar:
    st.markdown("### 🌐 Navigation")
    st.page_link("https://nice-ai.dev", label="Home Hub", icon="🏠")
    st.page_link("https://blog.nice-ai.dev", label="Tech Blog", icon="📝")
    st.divider()
    st.markdown(load_content("content/sidebar_intro.md"))

# ---------------------------------------------------------
# 主页面内容
# ---------------------------------------------------------
st.markdown(load_content("content/header.md"), unsafe_allow_html=True)
st.write("")

# --- 数据加载 ---
DEFAULT_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQKYBbug9yQhYtejoO-9OMKXYQfA1Ju4ReO2YvYb7kqhWlrczvSrnHCmK_YBc5B6olsbBfUoP2Jbn5b/pub?gid=774375516&single=true&output=csv"
DEFAULT_ACTIVITY_ADVICE_CSV_URL = os.getenv("ACTIVITY_ADVICE_CSV_URL", "")

@st.cache_data(ttl=_WEEKLY_CSV_CACHE_TTL_SEC, show_spinner="正在加载周报 CSV…")
def load_data():
    data_url = os.getenv("WEEKLY_REPORT_CSV_URL", DEFAULT_CSV_URL)
    try:
        df = pd.read_csv(data_url)
        df['Week Start'] = pd.to_datetime(df['Week Start'])
        df['Week End'] = pd.to_datetime(df['Week End'])
        if 'LSD Decouple' in df.columns:
            df['LSD Decouple'] = df['LSD Decouple'].astype(str).str.replace('%', '', regex=False)
            df['LSD Decouple'] = pd.to_numeric(df['LSD Decouple'], errors='coerce').fillna(0)
        numeric_cols = ['Distance (km)', 'Weekly Load', 'Fitness (CTL)', 'Form (TSB)', 'VDOT']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(',', '', regex=False)
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        df = df.sort_values('Week Start', ascending=False).reset_index(drop=True)
        return df
    except Exception as e:
        return None


@st.cache_data(ttl=_ACTIVITY_CSV_CACHE_TTL_SEC, show_spinner="正在加载最近活动点评…")
def load_activity_data():
    data_url = os.getenv("ACTIVITY_ADVICE_CSV_URL", DEFAULT_ACTIVITY_ADVICE_CSV_URL)
    if not data_url:
        return pd.DataFrame()
    try:
        df = pd.read_csv(data_url)
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.sort_values("Date", ascending=False).reset_index(drop=True)
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def build_pmc_figure(chart_df: pd.DataFrame):
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=chart_df["Week Start"],
            y=chart_df["Weekly Load"],
            name="Weekly Load",
            marker_color="rgba(59, 130, 246, 0.5)",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=chart_df["Week Start"],
            y=chart_df["Fitness (CTL)"],
            name="Fitness (CTL)",
            yaxis="y2",
            line=dict(color="#8B5CF6", width=3),
        )
    )
    fig.update_layout(
        yaxis=dict(title="Weekly Load"),
        yaxis2=dict(title="CTL", overlaying="y", side="right"),
        hovermode="x unified",
        legend=dict(orientation="h", y=1.1),
    )
    return fig


@st.cache_data(ttl=300, show_spinner=False)
def build_tsb_figure(chart_df: pd.DataFrame):
    fig_tsb = go.Bar(
        x=chart_df["Week Start"],
        y=chart_df["Form (TSB)"],
        marker_color=chart_df["Form (TSB)"].apply(
            lambda x: "#10B981" if x >= 0 else ("#EF4444" if x < -20 else "#F59E0B")
        ),
    )
    layout_tsb = go.Layout(
        yaxis=dict(title="TSB"),
        shapes=[
            dict(
                type="line",
                x0=chart_df["Week Start"].min(),
                x1=chart_df["Week Start"].max(),
                y0=0,
                y1=0,
                line=dict(color="gray", dash="dash"),
            ),
            dict(
                type="line",
                x0=chart_df["Week Start"].min(),
                x1=chart_df["Week Start"].max(),
                y0=-20,
                y1=-20,
                line=dict(color="red", dash="dot"),
            ),
        ],
    )
    return go.Figure(data=fig_tsb, layout=layout_tsb)


@st.cache_data(ttl=300, show_spinner=False)
def build_vdot_figure(chart_df: pd.DataFrame):
    fig_vdot = px.line(chart_df, x="Week Start", y="VDOT", title="VDOT (跑力) 趋势", markers=True)
    fig_vdot.update_traces(line_color="#EC4899")
    return fig_vdot


@st.cache_data(ttl=300, show_spinner=False)
def build_decouple_figure(chart_df: pd.DataFrame):
    fig_dec = px.area(
        chart_df, x="Week Start", y="LSD Decouple", title="LSD 有氧解耦率 (越低越稳)", markers=True
    )
    fig_dec.add_hline(y=5, line_dash="dash", line_color="red", annotation_text="5% 警戒线")
    return fig_dec


def _fmt_dt(value):
    if pd.isna(value):
        return "-"
    if hasattr(value, "strftime"):
        return value.strftime("%m-%d %H:%M")
    return str(value)


def _render_section_html(title: str, text: str) -> str:
    return (
        f"<div class='advice-section'>"
        f"<div class='advice-section-title'>{escape(title)}</div>"
        f"<div class='advice-section-body'>{escape(text).replace(chr(10), '<br>')}</div>"
        f"</div>"
    )


def render_activity_advice_panel(activity_df: pd.DataFrame):
    st.markdown("#### 🧠 单次活动点评")
    if activity_df.empty:
        st.info("未配置 `ACTIVITY_ADVICE_CSV_URL`，或当前未加载到 Activities CSV。")
        return

    display_cols = ["总评", "配速", "心率", "步频与爬升", "下次训练课"]
    recent = activity_df.head(2)
    for _, row in recent.iterrows():
        header = (
            f"{_fmt_dt(row.get('Date'))} · {row.get('Name', '-')}"
            f" · {row.get('Distance (km)', '-')} km · 配速 {row.get('Avg Pace', '-')}"
        )
        body = "".join(
            _render_section_html(col, str(row.get(col, "") or "暂无"))
            for col in display_cols
        )
        st.markdown(
            (
                "<div class='advice-card'>"
                f"<div class='advice-card-header'>{escape(header)}</div>"
                f"{body}"
                "</div>"
            ),
            unsafe_allow_html=True,
        )


def render_phase_follow_up_panel(latest_week: pd.Series, plan: dict, playbook: dict):
    follow = _training.build_phase_follow_up(latest_week, plan, playbook)
    st.markdown("#### 🧭 训练跟进")
    st.markdown(
        (
            "<div class='follow-card'>"
            f"<div class='follow-phase'>{escape(follow['phase']['name'])}</div>"
            f"<div class='follow-relation'>{escape(follow['relation_text'])}</div>"
            f"<div class='follow-kpis'>"
            f"<span>计划周量 {escape(follow['target_weekly_km'])}</span>"
            f"<span>实际 {escape(str(follow['actual_weekly_km']))} km</span>"
            f"<span>{escape(follow['volume_status'])}</span>"
            "</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    st.caption(f"建议长跑目标：{follow['long_run_target']}")

    if follow["key_items"]:
        st.markdown("**本期关键课**")
        for item in follow["key_items"][:3]:
            st.markdown(f"- `{item['tag']}`：{item['description']}")

    if follow["follow_ups"]:
        st.markdown("**下周跟进建议**")
        for item in follow["follow_ups"]:
            st.markdown(f"- {item}")

    if follow["week_cards"]:
        week_titles = [f"{w['day']} {w['title']}" for w in follow["week_cards"][:4]]
        st.markdown("**典型周节奏**")
        st.caption(" / ".join(week_titles))

    if follow["note"]:
        st.markdown(
            f"<div class='phase-note'>{escape(follow['note'])}</div>",
            unsafe_allow_html=True,
        )


df = load_data()
activity_df = load_activity_data()
plan = _training.load_plan()
playbook = _training.load_phase_playbook()

# --- 主界面 ---
st.title("🏃‍♂️ 周期训练周报")

st.caption("分段浏览：避免像旧版那样一次渲染全部图表导致首屏与交互变慢。")
view = st.radio(
    "视图",
    [
        "夏训计划与执行进度",
        "本周概览",
        "体能与 TSB 图表",
        "VDOT 与解耦",
    ],
    horizontal=True,
    label_visibility="collapsed",
)

# --- 夏训五期（计划 HTML + 周报对齐）---
if view == "夏训计划与执行进度":
    try:
        plan = _training.load_plan()
    except Exception as e:
        st.error(f"无法读取 data/training/plan.json：{e}")
        st.stop()

    st.subheader("📋 夏训五期计划")
    st.caption(
        "机器可读计划见仓库 `data/training/plan.json`；"
        "下方执行进度与「周期训练周报」同源 CSV（Week End 归属当期）。"
    )
    st.markdown(_training.summer_plan_html_fragment(), unsafe_allow_html=True)

    st.divider()
    st.subheader("📊 执行进度（周跑量 vs 计划区间）")
    st.markdown(_training.current_phase_message(date.today(), plan))

    if df is None:
        st.warning(
            "⚠️ 未加载到周报 CSV，无法对比执行进度。"
            "请检查 WEEKLY_REPORT_CSV_URL 或默认导出链接。"
        )
        st.stop()

    try:
        prog = _training.build_progress_dataframe(df, plan)
        if prog.empty:
            st.info(
                "暂无 Week End 落在计划期内的周报行。"
                "若已有数据，请核对 `plan.json` 中日期与 CSV 年份是否一致。"
            )
        else:
            st.dataframe(prog, use_container_width=True, hide_index=True)
        counts = _training.phase_week_counts(df, plan)
        lines = [
            f"- **{ph['name']}**：已有数据 {counts[ph['id']]} 周 / 计划约 {ph.get('weeks_planned', '—')} 周"
            for ph in plan["phases"]
        ]
        st.markdown("**各期周报行数**（Week End 落在该期内）\n\n" + "\n".join(lines))
    except Exception as e:
        st.error(f"生成执行进度表失败：{e}")

    st.stop()

if df is None:
    st.warning("⚠️ 请设置环境变量 WEEKLY_REPORT_CSV_URL 或使用默认 Google Sheet 的 Weekly Report CSV 链接 (需包含 gid 参数)")
    st.stop()

# --- 数据切片 ---
latest_week = df.iloc[0]
last_4_weeks = df.iloc[1:5]
chart_df = df.sort_values("Week Start", ascending=True)
recent_chart_df = chart_df.tail(8)


def display_metric(col, label, value, key_name, dataset, unit="", reverse_color=False):
    avg_4w = dataset[key_name].mean()
    delta = value - avg_4w
    delta_color = "inverse" if reverse_color else "normal"
    col.metric(
        label=label,
        value=f"{value} {unit}",
        delta=f"{delta:.1f} {unit} (vs 4周均值)",
        delta_color=delta_color,
    )


if view == "本周概览":
    st.subheader(
        f"📅 本周概览 ({latest_week['Week Start'].strftime('%m-%d')} ~ {latest_week['Week End'].strftime('%m-%d')})"
    )
    st.caption(f"当前状态: **{latest_week.get('Status', '未知')}**")
    main_col, side_col = st.columns([1.7, 1.05], gap="large")
    with main_col:
        col1, col2, col3 = st.columns(3)
        with col1:
            display_metric(col1, "本周跑量", latest_week["Distance (km)"], "Distance (km)", last_4_weeks, "km")
        with col2:
            display_metric(col2, "Weekly Load", latest_week["Weekly Load"], "Weekly Load", last_4_weeks)
        with col3:
            display_metric(col3, "Fitness (CTL)", latest_week["Fitness (CTL)"], "Fitness (CTL)", last_4_weeks)

        col4, col5 = st.columns(2)
        with col4:
            col4.metric("Form (TSB)", latest_week["Form (TSB)"], delta=None)
        with col5:
            display_metric(
                col5,
                "有氧解耦率",
                latest_week["LSD Decouple"],
                "LSD Decouple",
                last_4_weeks,
                "%",
                reverse_color=True,
            )

        st.markdown("##### 近几周走势")
        st.plotly_chart(build_pmc_figure(recent_chart_df), use_container_width=True)

        st.markdown("##### 最近 4 周摘要")
        summary_cols = ["Week Start", "Week End", "Distance (km)", "Weekly Load", "Form (TSB)", "VDOT"]
        st.dataframe(df.head(4)[summary_cols], use_container_width=True, hide_index=True)

    with side_col:
        render_activity_advice_panel(activity_df)
        st.divider()
        render_phase_follow_up_panel(latest_week, plan, playbook)

elif view == "体能与 TSB 图表":
    chart_col, side_col = st.columns([1.6, 1], gap="large")
    with chart_col:
        st.subheader("📈 体能管理图表 (最近 8 周)")
        st.caption("蓝色柱=周负荷，紫色线=体能(CTL)")
        st.plotly_chart(build_pmc_figure(recent_chart_df), use_container_width=True)

        st.subheader("⚖️ 身体状态 (TSB) 分布（最近 8 周）")
        st.caption("TSB > 0 为恢复期，TSB < -20 为疲劳风险区")
        st.plotly_chart(build_tsb_figure(recent_chart_df), use_container_width=True)
    with side_col:
        render_activity_advice_panel(activity_df)
        st.divider()
        render_phase_follow_up_panel(latest_week, plan, playbook)

elif view == "VDOT 与解耦":
    chart_col, side_col = st.columns([1.6, 1], gap="large")
    with chart_col:
        st.subheader("🚀 效率与能力趋势（最近 8 周）")
        st.plotly_chart(build_vdot_figure(recent_chart_df), use_container_width=True)
        st.plotly_chart(build_decouple_figure(recent_chart_df), use_container_width=True)
    with side_col:
        render_activity_advice_panel(activity_df)
        st.divider()
        render_phase_follow_up_panel(latest_week, plan, playbook)
