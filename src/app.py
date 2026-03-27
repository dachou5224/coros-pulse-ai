import os

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import gspread
from oauth2client.service_account import ServiceAccountCredentials


def _env_int_sec(name: str, default: int, *, minimum: int = 60) -> int:
    raw = os.getenv(name)
    if not raw or not str(raw).strip():
        return default
    try:
        return max(minimum, int(str(raw).strip()))
    except ValueError:
        return default


# 周报在 Sheet 侧约每周更新一次；默认 24h 缓存可显著减少 gspread / Sheets API 往返（可用环境变量缩短）
_PULSE_WEEKLY_CACHE_TTL_SEC = _env_int_sec("PULSE_WEEKLY_CACHE_TTL_SEC", 86400)

# --- 📱 页面配置 (移动端优化) ---
st.set_page_config(
    page_title="Coros Pulse",
    page_icon="🏃‍♂️",
    layout="centered", # 手机端使用 centered 布局视觉更聚焦
    initial_sidebar_state="collapsed" # 默认收起侧边栏
)

# --- 🎨 自定义 CSS (美化界面) ---
st.markdown("""
    <style>
    /* 隐藏 Streamlit 默认的菜单和页脚 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* 调整指标卡片的样式 */
    [data-testid="stMetricValue"] {
        font-size: 24px !important;
        font-weight: 700 !important;
    }
    
    /* 调整 Tab 字体 */
    button[data-baseweb="tab"] > div[data-testid="stMarkdownContainer"] > p {
        font-size: 16px;
        font-weight: bold;
    }
    
    /* 给图表加个圆角边框 */
    .js-plotly-plot {
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1); 
    }
    </style>
    """, unsafe_allow_html=True)

# --- 1. 数据加载函数 (保持不变) ---
@st.cache_data(ttl=_PULSE_WEEKLY_CACHE_TTL_SEC, show_spinner="正在从 Google Sheet 拉取周报…")
def load_data():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = {
            "type": st.secrets["gcp_service_account"]["type"],
            "project_id": st.secrets["gcp_service_account"]["project_id"],
            "private_key_id": st.secrets["gcp_service_account"]["private_key_id"],
            "private_key": st.secrets["gcp_service_account"]["private_key"],
            "client_email": st.secrets["gcp_service_account"]["client_email"],
            "client_id": st.secrets["gcp_service_account"]["client_id"],
            "auth_uri": st.secrets["gcp_service_account"]["auth_uri"],
            "token_uri": st.secrets["gcp_service_account"]["token_uri"],
            "auth_provider_x509_cert_url": st.secrets["gcp_service_account"]["auth_provider_x509_cert_url"],
            "client_x509_cert_url": st.secrets["gcp_service_account"]["client_x509_cert_url"]
        }
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("Coros_Running_Data")
        report_ws = sheet.worksheet("Weekly_Report")
        report_df = pd.DataFrame(report_ws.get_all_records())
        
        # 数据类型清洗
        cols_to_num = ['VDOT', 'Fitness (CTL)', 'Form (TSB)', 'Distance (km)', 'Weekly Load']
        for col in cols_to_num:
            if col in report_df.columns:
                report_df[col] = pd.to_numeric(report_df[col], errors='coerce')
        
        return report_df
    except Exception as e:
        return pd.DataFrame()


@st.cache_data(ttl=_PULSE_WEEKLY_CACHE_TTL_SEC, show_spinner=False)
def build_pulse_trend_figure(report_df: pd.DataFrame):
    """与主表数据绑定缓存，避免每次交互都重建 Plotly。"""
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=report_df["Week End"],
            y=report_df["Form (TSB)"],
            name="状态(TSB)",
            fill="tozeroy",
            line=dict(color="rgba(255, 99, 71, 0.5)", width=0),
            fillcolor="rgba(255, 99, 71, 0.2)",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=report_df["Week End"],
            y=report_df["Fitness (CTL)"],
            name="体能(CTL)",
            line=dict(color="#1f77b4", width=3),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=report_df["Week End"],
            y=report_df["VDOT"],
            name="跑力(VDOT)",
            line=dict(color="#2ca02c", width=2, dash="dot"),
            yaxis="y2",
        )
    )
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        height=350,
        yaxis=dict(showgrid=True, gridcolor="rgba(0,0,0,0.05)"),
        yaxis2=dict(overlaying="y", side="right", showgrid=False),
        legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# --- 加载数据 ---
df = load_data()

if df.empty:
    st.warning("⏳ 数据正在同步中，请稍后再来...")
    st.stop()

# --- 顶部欢迎语 ---
latest = df.iloc[-1]
prev = df.iloc[-2] if len(df) > 1 else latest

st.markdown(f"### 👋 Hi, Runner!")
st.caption(f"📅 数据更新至: {latest['Week End']}")

# --- 📱 主要布局：radio 单页渲染（st.tabs 会每次重跑执行所有 tab，拖慢首屏与交互） ---
st.caption("切换栏目时只渲染当前页，减轻加载与滚动卡顿。")
nav = st.radio(
    "栏目",
    ["📊 核心看板", "📝 历史数据", "📖 指标百科"],
    horizontal=True,
    label_visibility="collapsed",
)

if nav == "📊 核心看板":
    col1, col2 = st.columns(2)
    with col1:
        st.metric(
            "🚀 跑力 (VDOT)",
            f"{latest['VDOT']}",
            delta=round(latest["VDOT"] - prev["VDOT"], 1),
            help="衡量跑步硬实力的指标，越高越快",
        )
    with col2:
        st.metric(
            "🔋 体能 (CTL)",
            f"{latest['Fitness (CTL)']}",
            delta=round(latest["Fitness (CTL)"] - prev["Fitness (CTL)"], 1),
            help="过去42天的长期训练负荷，代表耐力基础",
        )

    col3, col4 = st.columns(2)
    with col3:
        tsb_val = latest["Form (TSB)"]
        st.metric(
            "❤️ 状态 (TSB)",
            f"{tsb_val}",
            delta=round(tsb_val - prev["Form (TSB)"], 1),
            delta_color="inverse",
            help="体能 - 疲劳。正值代表状态好，负值代表疲劳",
        )
    with col4:
        lsd_val = latest.get("LSD Decouple", "-")
        st.metric(
            "📉 LSD 脱钩率",
            str(lsd_val),
            help="长距离跑后半程的心率漂移程度，越低越好",
        )

    st.markdown("---")
    st.markdown("##### 📈 训练状态趋势")
    fig = build_pulse_trend_figure(df)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

elif nav == "📝 历史数据":
    st.markdown("##### 🗓️ 历史周报")
    display_cols = ["Week End", "Distance (km)", "Avg Pace", "VDOT", "Status"]
    st.dataframe(
        df[display_cols].sort_index(ascending=False),
        hide_index=True,
        use_container_width=True,
    )

else:
    st.markdown("### 📖 指标说明书")

    with st.expander("🚀 VDOT (跑力值)", expanded=True):
        st.markdown(
            """
        **定义**: 衡量你跑步“硬实力”的指标。类似于汽车的“马力”。

        **如何解读**:
        * 📈 **上升**: 说明你的 5km/10km 极限成绩在进步。
        * ➖ **持平**: 处于维持期，或者只有慢跑没有强度课。
        * 📉 **下降**: 可能是因为伤病、休赛或天气炎热。
        """
        )

    with st.expander("❤️ TSB (状态指数)"):
        st.markdown(
            """
        **定义**: `体能 (CTL) - 疲劳 (ATL)`。反映你身体的“新鲜度”。

        **信号灯**:
        * 🟢 **+10 到 +25**: **比赛窗口期**。腿脚轻盈，适合 PB。
        * ⚪ **-10 到 +10**: **维持期**。身体感觉正常。
        * 🟡 **-10 到 -30**: **高效训练区**。会有累的感觉，但为了进步是必须的。
        * 🔴 **低于 -30**: **受伤警戒区**！必须立刻减量休息，不要硬撑。
        """
        )

    with st.expander("🔋 CTL (体能储备)"):
        st.markdown(
            """
        **定义**: 过去 42 天的加权平均训练负荷。

        **如何解读**:
        这代表你的“耐力底子”。这个线是一步一个脚印跑出来的，掉下来很快，涨上去很慢。
        * **全马完赛建议**: CTL > 60
        * **半马完赛建议**: CTL > 40
        """
        )

    with st.expander("📉 LSD 脱钩率 (Decouple)"):
        st.markdown(
            """
        **定义**: 长距离跑中，后半程心率相对于配速的“漂移”程度。

        **如何解读**:
        * 🏆 **< 3%**: **顶级耐力**。机器一般的输出稳定性。
        * ✅ **< 5%**: **优秀**。有氧基础扎实。
        * ⚠️ **> 8%**: **耐力不足**。后半程心率飙升，身体开始无氧代偿，马拉松容易撞墙。
        """
        )

    st.caption("Designed with ❤️ by Coros-Pulse-AI")
