import pandas as pd
import numpy as np
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import os
import json

# --- 配置 ---
# 直接复用现有的 Secret
JSON_KEY = os.getenv('GOOGLE_APPLICATION_CREDENTIALS_JSON')
SHEET_NAME = 'Coros_Running_Data'

def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    if not JSON_KEY:
        print("❌ 错误：未找到 Google Credentials Secret")
        return None
    
    # 兼容处理：如果是 JSON 字符串直接加载
    try:
        creds_dict = json.loads(JSON_KEY)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"❌ 认证失败: {e}")
        return None

def validate_settings(settings_df):
    """🛡️ 校验 Settings 表格数据的合法性"""
    required_cols = ['Date', 'Max HR', 'Rest HR']
    # 检查列名是否存在
    if not all(col in settings_df.columns for col in required_cols):
        print(f"❌ Settings 表缺少列，必须包含: {required_cols}")
        return False
    # 检查数值
    try:
        if not pd.to_numeric(settings_df['Max HR'], errors='coerce').notnull().all():
            return False
        if not pd.to_numeric(settings_df['Rest HR'], errors='coerce').notnull().all():
            return False
    except:
        return False
    return True

def get_hr_params(date, settings_df):
    """📅 根据跑步日期，查找当时生效的心率参数"""
    target_date = pd.to_datetime(date)
    # 找到所有生效日期在“跑步日期之前”的设置
    valid_settings = settings_df[settings_df['Date'] <= target_date]
    
    if valid_settings.empty:
        # 如果找不到，用最早的一条
        return settings_df.iloc[0]['Max HR'], settings_df.iloc[0]['Rest HR']
    
    # 取最后一条（也就是离跑步日期最近的一条过去配置）
    latest = valid_settings.iloc[-1]
    return latest['Max HR'], latest['Rest HR']

def main():
    print("🚀 开始执行周报分析 (AI Analyst)...")
    client = get_client()
    if not client: return

    try:
        sh = client.open(SHEET_NAME)
    except Exception as e:
        print(f"❌ 找不到表格 '{SHEET_NAME}': {e}")
        return

    # 1. 读取运动数据
    print("📥 读取运动数据...")
    try:
        worksheet = sh.sheet1
        df = pd.DataFrame(worksheet.get_all_records())
        # 清洗 Activity ID 列，防止科学计数法干扰
        if 'Activity ID' in df.columns:
             df['Activity ID'] = df['Activity ID'].astype(str)
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values('Date') # 按时间正序排列
    except Exception as e:
        print(f"❌ 读取数据失败: {e}")
        return

    # 2. 读取心率设置
    print("⚙️ 读取用户配置...")
    try:
        settings_ws = sh.worksheet('Settings')
        settings_df = pd.DataFrame(settings_ws.get_all_records())
        settings_df['Date'] = pd.to_datetime(settings_df['Date'], errors='coerce')
        settings_df = settings_df.dropna(subset=['Date']).sort_values('Date')
        
        if not validate_settings(settings_df):
            raise ValueError("校验未通过")
    except Exception as e:
        print(f"⚠️ 读取 Settings 失败 ({e})，使用默认值 (Max:185, Rest:55)")
        settings_df = pd.DataFrame({'Date': [pd.Timestamp('2000-01-01')], 'Max HR': [185], 'Rest HR': [55]})

    # 3. 计算 TRIMP
    print("🧮 计算每一单的训练负荷 (TRIMP)...")
    trimp_list = []
    for _, row in df.iterrows():
        max_hr, rest_hr = get_hr_params(row['Date'], settings_df)
        
        # 数据容错处理
        try:
            avg_hr = pd.to_numeric(row['Avg HR'], errors='coerce')
            duration = pd.to_numeric(row['Duration (min)'], errors='coerce')
            
            if pd.isna(avg_hr) or pd.isna(duration) or duration == 0 or avg_hr == 0:
                trimp_list.append(0)
                continue
                
            hrr = (avg_hr - rest_hr) / (max_hr - rest_hr)
            hrr = max(0, min(1, hrr)) # 限制在 0-1
            weight = 0.64 * np.exp(1.92 * hrr) # 男性系数
            trimp = duration * hrr * weight
            trimp_list.append(round(trimp, 1))
        except:
            trimp_list.append(0)
    
    df['TRIMP'] = trimp_list

    # 4. 生成周报 (本周概览)
    today = datetime.now()
    # 逻辑：每次运行分析“上周”的数据（因为周一早上跑，看的是刚过去的一周）
    # 或者如果你是手动触发，可能想看“最近7天”。
    # 这里我们采用：最近完整的周（上周一到上周日）
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(days=7)
    
    mask = (df['Date'] >= last_monday) & (df['Date'] < this_monday)
    weekly_data = df[mask]
    
    # 计算 TSB (状态) - 基于长期数据
    # 构建每日时间序列来计算移动平均
    daily_load = df.set_index('Date').resample('D')['TRIMP'].sum().fillna(0)
    
    # 截止到昨天的 CTL 和 ATL
    current_ctl = daily_load.ewm(span=42, adjust=False).mean().iloc[-1]
    current_atl = daily_load.ewm(span=7, adjust=False).mean().iloc[-1]
    current_tsb = current_ctl - current_atl
    
    # 准备周报行数据
    # 平均配速计算需要把 "5'30"" 转成秒
    def parse_pace(p_str):
        try:
            if not isinstance(p_str, str): return 0
            mins = int(p_str.split("'")[0])
            secs = int(p_str.split("'")[1].replace('"',''))
            return mins * 60 + secs
        except:
            return 0
            
    avg_pace_sec = 0
    if len(weekly_data) > 0:
        total_sec = weekly_data['Avg Pace'].apply(parse_pace).sum()
        avg_pace_sec = total_sec / len(weekly_data)
        
    pace_fmt = f"{int(avg_pace_sec // 60)}'{int(avg_pace_sec % 60):02d}\"" if avg_pace_sec > 0 else "-"

    report_row = [
        last_monday.strftime("%Y-%m-%d"),          # Start Date
        this_monday.strftime("%Y-%m-%d"),          # End Date
        round(weekly_data['Distance (km)'].sum(), 2), # Total Dist
        len(weekly_data),                          # Runs
        pace_fmt,                                  # Avg Pace
        round(weekly_data['TRIMP'].sum()),         # Total Load
        round(current_ctl, 1),                     # Fitness
        round(current_tsb, 1),                     # Form
        "恢复" if current_tsb > 10 else ("适中" if current_tsb > -10 else "疲劳")
    ]
    
    print(f"📊 生成周报: {report_row}")

    # 5. 写入 Weekly_Report
    try:
        try:
            report_ws = sh.worksheet('Weekly_Report')
        except:
            print("✨ 新建 Weekly_Report 表...")
            report_ws = sh.add_worksheet(title="Weekly_Report", rows=100, cols=20)
            report_ws.append_row(["Start Date", "End Date", "Distance (km)", "Runs", "Avg Pace", "Weekly Load", "Fitness (CTL)", "Form (TSB)", "Status"])
            
        # 检查是否已经写过这一周（防止重复写入）
        existing_reports = report_ws.get_all_values()
        is_duplicate = False
        for row in existing_reports:
            if len(row) > 0 and row[0] == report_row[0]:
                is_duplicate = True
                break
        
        if not is_duplicate:
            report_ws.append_row(report_row)
            print("✅ 周报已写入 Google Sheets")
        else:
            print("⚠️ 本周周报已存在，跳过写入")
            
    except Exception as e:
        print(f"❌ 写入周报失败: {e}")

if __name__ == "__main__":
    main()
