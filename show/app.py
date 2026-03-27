import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os

# --- 页面全局设置 ---
st.set_page_config(
    page_title="Nice AI - Run",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="expanded"
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


df = load_data()

# --- 主界面 ---
st.title("🏃‍♂️ 周期训练周报")

if df is None:
    st.warning("⚠️ 请设置环境变量 WEEKLY_REPORT_CSV_URL 或使用默认 Google Sheet 的 Weekly Report CSV 链接 (需包含 gid 参数)")
    st.stop()

# --- 数据切片 ---
latest_week = df.iloc[0]
last_4_weeks = df.iloc[1:5]
chart_df = df.sort_values("Week Start", ascending=True)

st.caption("分段浏览：避免像旧版那样一次渲染全部图表导致首屏与交互变慢。")
view = st.radio(
    "视图",
    ["本周概览", "体能与 TSB 图表", "VDOT 与解耦", "原始数据"],
    horizontal=True,
    label_visibility="collapsed",
)


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

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        display_metric(col1, "本周跑量", latest_week["Distance (km)"], "Distance (km)", last_4_weeks, "km")
    with col2:
        display_metric(col2, "Weekly Load", latest_week["Weekly Load"], "Weekly Load", last_4_weeks)
    with col3:
        display_metric(col3, "Fitness (CTL)", latest_week["Fitness (CTL)"], "Fitness (CTL)", last_4_weeks)
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

elif view == "体能与 TSB 图表":
    st.divider()
    c1, c2 = st.columns([2, 1])
    with c1:
        st.subheader("📈 体能管理图表 (PMC)")
        st.caption("蓝色柱=周负荷，紫色线=体能(CTL)")
        st.plotly_chart(build_pmc_figure(chart_df), use_container_width=True)
    with c2:
        st.subheader("⚖️ 身体状态 (TSB) 分布")
        st.caption("TSB > 0 为恢复期，TSB < -20 为疲劳风险区")
        st.plotly_chart(build_tsb_figure(chart_df), use_container_width=True)

elif view == "VDOT 与解耦":
    st.subheader("🚀 效率与能力趋势")
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.plotly_chart(build_vdot_figure(chart_df), use_container_width=True)
    with col_p2:
        st.plotly_chart(build_decouple_figure(chart_df), use_container_width=True)

else:
    st.subheader("📊 历史周报数据")
    display_cols = [
        "Week Start",
        "Week End",
        "Distance (km)",
        "Weekly Load",
        "Fitness (CTL)",
        "Form (TSB)",
        "LSD Decouple",
        "Status",
    ]
    st.dataframe(df[display_cols], use_container_width=True)
