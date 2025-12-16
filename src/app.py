import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

# --- 页面配置 ---
st.set_page_config(
    page_title="Coros Pulse Dashboard",
    page_icon="🏃‍♂️",
    layout="wide"
)

# --- 1. 连接 Google Sheets (使用 Streamlit Secrets) ---
@st.cache_data(ttl=600) # 缓存数据 10 分钟，防止频繁请求
def load_data():
    # 从 Streamlit 的云端密钥中读取配置
    # 注意：部署时我们需要在后台填入这些信息
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    
    # 构造认证信息字典
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
    
    # 打开表格
    sheet = client.open("Coros_Running_Data") # 你的表格名字
    
    # 读取历史周报
    try:
        report_ws = sheet.worksheet("Weekly_Report")
        report_df = pd.DataFrame(report_ws.get_all_records())
        # 确保 VDOT 等关键列是数字
        cols_to_num = ['VDOT', 'Fitness (CTL)', 'Form (TSB)', 'Distance (km)']
        for col in cols_to_num:
            if col in report_df.columns:
                report_df[col] = pd.to_numeric(report_df[col], errors='coerce')
    except:
        report_df = pd.DataFrame()

    return report_df

# --- 加载数据 ---
try:
    df = load_data()
    if df.empty:
        st.error("无法读取 Weekly_Report，请检查表格是否存在。")
        st.stop()
except Exception as e:
    st.error(f"连接 Google Sheets 失败，请检查密钥配置。错误信息: {e}")
    st.stop()

# --- 2. 侧边栏 ---
st.sidebar.title("🏃‍♂️ Coros AI")
st.sidebar.info("数据源: Coros -> Strava -> Google Sheets")
st.sidebar.markdown("---")
st.sidebar.write("**最近更新:**")
st.sidebar.write(df.iloc[-1]['Week End'] if not df.empty else "-")

# --- 3. 核心指标看板 ---
st.title("我的训练仪表盘")

# 取最新一周的数据
latest = df.iloc[-1]
prev = df.iloc[-2] if len(df) > 1 else latest

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("本周跑力 (VDOT)", f"{latest['VDOT']}", delta=round(latest['VDOT'] - prev['VDOT'], 1))

with col2:
    st.metric("当前状态 (TSB)", f"{latest['Form (TSB)']}", 
              delta=round(latest['Form (TSB)'] - prev['Form (TSB)'], 1),
              delta_color="inverse") # TSB 跌太多不好，所以反转颜色

with col3:
    st.metric("体能储备 (CTL)", f"{latest['Fitness (CTL)']}", delta=round(latest['Fitness (CTL)'] - prev['Fitness (CTL)'], 1))

with col4:
    lsd_val = latest.get('LSD Decouple', '-')
    st.metric("LSD 脱钩率", lsd_val)

# --- 4. 交互式图表 ---

st.markdown("### 📈 状态与体能趋势")
# 组合图：CTL (线) + TSB (柱/面)
fig = go.Figure()

# TSB 区域图
fig.add_trace(go.Scatter(
    x=df['Week End'], y=df['Form (TSB)'],
    name='状态 (TSB)',
    fill='tozeroy',
    line=dict(color='rgba(255, 99, 71, 0.5)', width=1)
))

# CTL 线图
fig.add_trace(go.Scatter(
    x=df['Week End'], y=df['Fitness (CTL)'],
    name='体能 (CTL)',
    line=dict(color='blue', width=3)
))

# VDOT 线图 (放到次坐标轴)
fig.add_trace(go.Scatter(
    x=df['Week End'], y=df['VDOT'],
    name='跑力 (VDOT)',
    line=dict(color='green', width=2, dash='dot'),
    yaxis='y2'
))

fig.update_layout(
    xaxis_title="周次",
    yaxis_title="Load / TSB",
    yaxis2=dict(title="VDOT", overlaying='y', side='right'),
    legend=dict(x=0, y=1.1, orientation='h'),
    hovermode="x unified"
)

st.plotly_chart(fig, use_container_width=True)

# --- 5. 数据表格 ---
st.markdown("### 📋 历史周报明细")
st.dataframe(
    df[['Week Start', 'Distance (km)', 'Runs', 'Avg Pace', 'VDOT', 'Form (TSB)', 'Status']].sort_index(ascending=False),
    use_container_width=True
)
