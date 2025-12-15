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
SHEET_NAME = "Coros_Running_Data" # 你的 Google Sheet 名字，必须完全一致

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
        # 尝试打开表格，不存在则创建
        try:
            sheet = client.open(SHEET_NAME).sheet1
            return sheet
        except gspread.exceptions.SpreadsheetNotFound:
            print(f"表格 '{SHEET_NAME}' 未找到，正在创建...")
            sh = client.create(SHEET_NAME)
            sh.share(creds_dict['client_email'], perm_type='user', role='owner')
            sheet = sh.sheet1
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

    # 获取现有 ID
    existing_ids = set()
    try:
        records = sheet.get_all_records()
        if records:
            df = pd.DataFrame(records)
            existing_ids = set(df['Activity ID'].astype(str).tolist())
    except Exception as e:
        print(f"读取现有数据跳过 (可能是新表): {e}")

    # 获取 Strava 最近 30 条跑步数据
    try:
        activities = strava.get_activities(limit=30)
        new_rows = []
        for act in activities:
            if act.type != "Run": continue
            if str(act.id) in existing_ids: continue
            
            print(f"发现新活动: {act.name} ({act.start_date_local})")
            new_rows.append(process_activity(act))
        
        if new_rows:
            new_rows.reverse() # 旧的先入库
            for row in new_rows:
                sheet.append_row(row)
            print(f"✅ 成功同步 {len(new_rows)} 条数据！")
        else:
            print("💤 没有发现新数据。")
    except Exception as e:
        print(f"获取活动列表失败: {e}")

if __name__ == "__main__":
    main()
