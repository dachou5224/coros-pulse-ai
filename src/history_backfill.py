import pandas as pd
import numpy as np
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import os
import json
import time

# --- 配置 ---
JSON_KEY = os.getenv('GOOGLE_APPLICATION_CREDENTIALS_JSON')
SHEET_NAME = 'Coros_Running_Data'

def get_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    if not JSON_KEY:
        print("❌ 错误：未找到 Google Credentials")
        return None
    try:
        creds_dict = json.loads(JSON_KEY)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"❌ 认证失败: {e}")
        return None

def validate_settings(settings_df):
    try:
        if not pd.to_numeric(settings_df['Max HR'], errors='coerce').notnull().all(): return False
        if not pd.to_numeric(settings_df['Rest HR'], errors='coerce').notnull().all(): return False
    except: return False
    return True

def get_hr_params_vectorized(dates, settings_df):
    """
    ⚡️ 向量化加速版心率匹配：
    不再一行行查，而是利用 Pandas 的 merge_asof 快速匹配最近的设置
    """
    # 确保都按时间排序
    dates = pd.DataFrame({'Date': dates}).sort_values('Date')
    settings = settings_df.sort_values('Date')
    
    # asof merge: 找到 <= 跑步日期的最近一条设置
    merged = pd.merge_asof(dates, settings, on='Date', direction='backward')
    
    # 如果有些早期跑步日期比第一条设置还早，填充第一条设置
    if merged['Max HR'].isnull().any():
        first_setting = settings.iloc[0]
        merged['Max HR'] = merged['Max HR'].fillna(first_setting['Max HR'])
        merged['Rest HR'] = merged['Rest HR'].fillna(first_setting['Rest HR'])
        
    return merged['Max HR'].values, merged['Rest HR'].values

def main():
    print("🚀 启动历史周报回溯生成器 (History Backfill)...")
    client = get_client()
    if not client: return
    sh = client.open(SHEET_NAME)

    # 1. 读取数据
    print("📥 读取所有运动数据...")
    df = pd.DataFrame(sh.sheet1.get_all_records())
    if 'Activity ID' in df.columns:
         df['Activity ID'] = df['Activity ID'].astype(str)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values('Date')

    # 2. 读取设置
    print("⚙️ 读取设置...")
    try:
        settings_ws = sh.worksheet('Settings')
        settings_df = pd.DataFrame(settings_ws.get_all_records())
        settings_df['Date'] = pd.to_datetime(settings_df['Date'], errors='coerce')
        settings_df = settings_df.dropna(subset=['Date']).sort_values('Date')
        if not validate_settings(settings_df): raise ValueError
    except:
        print("⚠️ 使用默认心率设置")
        settings_df = pd.DataFrame({'Date': [pd.Timestamp('2000-01-01')], 'Max HR': [185], 'Rest HR': [55]})

    # 3. 批量计算 TRIMP
    print("🧮 批量计算 TRIMP...")
    # 清洗数据
    df['Avg HR'] = pd.to_numeric(df['Avg HR'], errors='coerce').fillna(0)
    df['Duration (min)'] = pd.to_numeric(df['Duration (min)'], errors='coerce').fillna(0)
    
    # 获取对应的 Max/Rest HR
    max_hrs, rest_hrs = get_hr_params_vectorized(df['Date'], settings_df)
    
    # 向量化计算
    hrr = (df['Avg HR'] - rest_hrs) / (max_hrs - rest_hrs)
    hrr = hrr.clip(0, 1)
    weight = 0.64 * np.exp(1.92 * hrr)
    df['TRIMP'] = df['Duration (min)'] * hrr * weight
    df['TRIMP'] = df['TRIMP'].fillna(0).round(1)

    # 4. 构建每日时间序列 (为了计算连续的 CTL/ATL)
    print("📈 重建每日时间轴 & 计算状态指数...")
    start_date = df['Date'].min().normalize()
    end_date = df['Date'].max().normalize()
    all_days = pd.date_range(start_date, end_date, freq='D')
    
    # 按天汇总 TRIMP (防止一天多跑)
    daily_trimp = df.set_index('Date').resample('D')['TRIMP'].sum().reindex(all_days, fill_value=0)
    
    # 计算 CTL, ATL, TSB
    ctl = daily_trimp.ewm(span=42, adjust=False).mean()
    atl = daily_trimp.ewm(span=7, adjust=False).mean()
    tsb = ctl - atl
    
    # 组合成每日状态表
    daily_stats = pd.DataFrame({
        'TRIMP': daily_trimp,
        'CTL': ctl,
        'TSB': tsb
    })

    # 5. 按周重新采样 (Resample Weekly)
    # 'W-SUN' 表示每舍入到周日作为结束
    # 注意：我们想要的是 "上周一到上周日" 的数据，这里的逻辑是：
    # 这一周的总跑量、总负荷，以及这一周【结束时】的状态(TSB)
    print("📅 按周汇总数据...")
    
    # 辅助函数：计算平均配速
    def avg_pace_calc(series):
        total_sec = 0
        count = 0
        for p_str in series:
            try:
                if isinstance(p_str, str) and "'" in p_str:
                    mins = int(p_str.split("'")[0])
                    secs = int(p_str.split("'")[1].replace('"',''))
                    total_sec += mins * 60 + secs
                    count += 1
            except: pass
        return total_sec / count if count > 0 else 0

    # 聚合逻辑
    weekly_agg = df.set_index('Date').resample('W-SUN').agg({
        'Distance (km)': 'sum',
        'Activity ID': 'count', # 次数
        'TRIMP': 'sum',
        'Avg Pace': avg_pace_calc # 自定义聚合
    })
    
    # 把 TSB/CTL 也按周取样（取每周日的那个值）
    weekly_status = daily_stats.resample('W-SUN').last()
    
    # 合并
    final_report = pd.concat([weekly_agg, weekly_status[['CTL', 'TSB']]], axis=1)
    
    # 6. 准备写入数据
    print("📝 准备写入数据...")
    rows_to_write = []
    
    # 表头
    headers = ["Week Start", "Week End", "Distance (km)", "Runs", "Avg Pace", "Weekly Load", "Fitness (CTL)", "Form (TSB)", "Status"]
    
    for date_idx, row in final_report.iterrows():
        # 如果这一周没有任何数据且 TSB 还没建立起来，跳过
        if row['Distance (km)'] == 0 and row['CTL'] < 1:
            continue
            
        week_end = date_idx
        week_start = week_end - timedelta(days=6)
        
        # 格式化配速
        pace_sec = row['Avg Pace']
        pace_fmt = f"{int(pace_sec // 60)}'{int(pace_sec % 60):02d}\"" if pace_sec > 0 else "-"
        
        current_tsb = row['TSB']
        status_text = "恢复" if current_tsb > 10 else ("适中" if current_tsb > -10 else "疲劳")
        
        rows_to_write.append([
            week_start.strftime("%Y-%m-%d"),
            week_end.strftime("%Y-%m-%d"),
            round(row['Distance (km)'], 2),
            int(row['Activity ID']),
            pace_fmt,
            round(row['TRIMP']),
            round(row['CTL'], 1),
            round(row['TSB'], 1),
            status_text
        ])

    # 7. 写入 Google Sheets
    # 注意：这次是全量覆盖写入 Weekly_Report，防止重复和顺序混乱
    try:
        try:
            report_ws = sh.worksheet('Weekly_Report')
            print("🧹 清空旧的 Weekly_Report...")
            report_ws.clear()
        except:
            print("✨ 新建 Weekly_Report 表...")
            report_ws = sh.add_worksheet(title="Weekly_Report", rows=len(rows_to_write)+20, cols=20)
            
        print(f"🚀 正在写入 {len(rows_to_write)} 周的历史报告...")
        # 加上表头
        all_content = [headers] + rows_to_write
        report_ws.update(range_name='A1', values=all_content)
        print("✅ 历史回溯完成！")
        
    except Exception as e:
        print(f"❌ 写入失败: {e}")

if __name__ == "__main__":
    main()
