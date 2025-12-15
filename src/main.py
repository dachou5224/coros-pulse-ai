import os
import json
import time
from datetime import datetime
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from stravalib.client import Client

# --- 配置部分 ---
STRAVA_CLIENT_ID = os.getenv('STRAVA_CLIENT_ID')
STRAVA_CLIENT_SECRET = os.getenv('STRAVA_CLIENT_SECRET')
STRAVA_REFRESH_TOKEN = os.getenv('STRAVA_REFRESH_TOKEN')
GOOGLE_JSON_KEY = os.getenv('GOOGLE_APPLICATION_CREDENTIALS_JSON')
SHEET_NAME = "Coros_Running_Data"

def get_strava_client():
    if not STRAVA_REFRESH_TOKEN:
        print("错误：未配置 STRAVA_REFRESH_TOKEN")
        return None
    client = Client()
    try:
        refresh_response = client.refresh_access_token(
            client_id=STRAVA_CLIENT_ID,
            client_secret=STRAVA_CLIENT_SECRET,
            refresh_token=STRAVA_REFRESH_TOKEN
        )
        client.access_token = refresh_response['access_token']
        return client
    except Exception as e:
        print(f"Strava 授权失败: {e}")
        return None

def get_google_sheet():
    if not GOOGLE_JSON_KEY:
        print("错误：未配置 GOOGLE_JSON_KEY")
        return None
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        creds_dict = json.loads(GOOGLE_JSON_KEY)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        try:
            sheet = client.open(SHEET_NAME).sheet1
            return sheet
        except gspread.exceptions.SpreadsheetNotFound:
            print(f"表格 '{SHEET_NAME}' 未找到，正在创建...")
            sh = client.create(SHEET_NAME)
            sh.share(creds_dict['client_email'], perm_type='user', role='owner')
            sheet = sh.sheet1
            # 初始化表头
            sheet.append_row([
                "Activity ID", "Date", "Name", "Distance (km)", "Duration (min)", 
                "Avg Pace", "Avg HR", "Elevation Gain (m)", "Cadence (spm)", "Type"
            ])
            return sheet
    except Exception as e:
        print(f"Google Sheets 连接失败: {e}")
        return None

def process_activity(activity):
    dist_km = round(float(activity.distance) / 1000, 2)
    duration_min = round(activity.moving_time.total_seconds() / 60, 2)
    
    avg_pace = "0'00\""
    if activity.average_speed > 0:
        pace_decimal = (1000 / float(activity.average_speed)) / 60
        pace_min = int(pace_decimal)
        pace_sec = int((pace_decimal - pace_min) * 60)
        avg_pace = f"{pace_min}'{pace_sec:02d}\""

    return [
        str(activity.id),
        activity.start_date_local.strftime("%Y-%m-%d %H:%M:%S"),
        activity.name,
        dist_km,
        duration_min,
        avg_pace,
        activity.average_heartrate if activity.average_heartrate else 0,
        float(activity.total_elevation_gain),
        (activity.average_cadence * 2) if activity.average_cadence else 0,
        activity.type
    ]

def main():
    print("🚀 开始同步 Coros (Strava) 数据...")
    strava = get_strava_client()
    sheet = get_google_sheet()
    
    if not strava or not sheet:
        return

    # 1. 检查现有数据量
    existing_ids = set()
    is_first_run = True
    try:
        records = sheet.get_all_records()
        if records:
            df = pd.DataFrame(records)
            existing_ids = set(df['Activity ID'].astype(str).tolist())
            is_first_run = False
            print(f"📊 表中已有 {len(existing_ids)} 条数据。")
    except Exception as e:
        print(f"读取现有数据跳过 (可能是新表): {e}")

    # 2. 智能设置抓取数量
    # 如果是第一次运行（或空表），抓取无限多(limit=None)；否则只看最近50条
    limit_count = None if is_first_run else 50
    if is_first_run:
        print("🌟 检测到首次运行，正在全量抓取历史数据（这可能需要几分钟）...")
    else:
        print("🔄 检测到增量更新，正在检查最近 50 条活动...")

    # 3. 获取数据
    try:
        activities = strava.get_activities(limit=limit_count)
        new_rows = []
        
        # 遍历活动
        for act in activities:
            if act.type != "Run": continue
            if str(act.id) in existing_ids: continue
            
            # 简单的进度打印
            if is_first_run and len(new_rows) % 50 == 0 and len(new_rows) > 0:
                print(f"已处理 {len(new_rows)} 条待同步数据...")
                
            new_rows.append(process_activity(act))
        
        # 4. 批量写入 (Batch Write)
        if new_rows:
            new_rows.reverse() # 让旧的在上面，新的在下面
            print(f"📝 正在将 {len(new_rows)} 条新数据写入 Google Sheets...")
            sheet.append_rows(new_rows) # 关键优化：一次性写入
            print(f"✅ 同步完成！")
        else:
            print("💤 没有发现新数据。")
            
    except Exception as e:
        print(f"运行过程中出错: {e}")

if __name__ == "__main__":
    main()
