import os
import json
import time
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

# ⚠️ 安全限制：每次运行最多处理多少条详情？
# Strava 限制 15分钟 100次。
# 我们设为 80，留 20 次作为余量（给 List 请求和重试使用）。
BATCH_SIZE = 80 

def get_strava_client():
    if not STRAVA_REFRESH_TOKEN: return None
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
    if not GOOGLE_JSON_KEY: return None
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
            # 初始化豪华表头
            sheet.append_row([
                "Activity ID", "Date", "Name", "Distance (km)", "Duration (min)", 
                "Avg Pace", "Max Pace", "Avg HR", "Max HR", "Suffer Score",      
                "Avg Power (w)", "Cadence (spm)", "Elevation Gain (m)", 
                "Calories (kcal)", "Temperature (C)", "Shoes", "Type", "Splits (JSON)"
            ])
            return sheet
    except Exception as e:
        print(f"Google Sheets 连接失败: {e}")
        return None

def get_pace_str(speed_mps):
    if not speed_mps or speed_mps <= 0: return "0'00\""
    pace_decimal = (1000 / float(speed_mps)) / 60
    pace_min = int(pace_decimal)
    pace_sec = int((pace_decimal - pace_min) * 60)
    return f"{pace_min}'{pace_sec:02d}\""

def process_activity_detail(activity_id, client):
    """单独封装：根据 ID 获取详情并处理"""
    try:
        # ⚠️ 这里消耗 1 次 API额度
        detail = client.get_activity(activity_id)
        
        # 基础数据
        dist_km = round(float(detail.distance) / 1000, 2)
        duration_min = round(detail.moving_time.total_seconds() / 60, 2)
        avg_pace = get_pace_str(detail.average_speed)
        max_pace = get_pace_str(detail.max_speed)

        # Splits
        splits_data = []
        if hasattr(detail, 'splits_metric') and detail.splits_metric:
            for s in detail.splits_metric:
                split_pace = get_pace_str(s.average_speed)
                split_hr = s.average_heartrate if hasattr(s, 'average_heartrate') else 0
                splits_data.append({"km": s.split, "pace": split_pace, "hr": round(split_hr)})
        splits_json = json.dumps(splits_data, ensure_ascii=False)

        # Shoes
        shoe_name = ""
        if detail.gear_id:
            try:
                shoe_name = detail.gear.name if hasattr(detail.gear, 'name') else detail.gear_id
            except: pass

        return [
            str(detail.id),
            detail.start_date_local.strftime("%Y-%m-%d %H:%M:%S"),
            detail.name,
            dist_km,
            duration_min,
            avg_pace,
            max_pace,
            detail.average_heartrate if detail.average_heartrate else 0,
            detail.max_heartrate if detail.max_heartrate else 0,
            detail.suffer_score if hasattr(detail, 'suffer_score') else 0,
            detail.average_watts if hasattr(detail, 'average_watts') else 0,
            (detail.average_cadence * 2) if detail.average_cadence else 0,
            float(detail.total_elevation_gain),
            detail.kilojoules if hasattr(detail, 'kilojoules') else 0,
            detail.average_temp if hasattr(detail, 'average_temp') else "",
            shoe_name,
            detail.type,
            splits_json
        ]
    except Exception as e:
        print(f"处理 ID {activity_id} 失败: {e}")
        return None

def main():
    print("🚀 启动历史数据回溯模式 (Backfill Mode)...")
    strava = get_strava_client()
    sheet = get_google_sheet()
    
    if not strava or not sheet: return

    # 1. 获取已保存的 ID
    existing_ids = set()
    try:
        records = sheet.get_all_records()
        if records:
            df = pd.DataFrame(records)
            existing_ids = set(df['Activity ID'].astype(str).tolist())
            print(f"📊 本地已有数据: {len(existing_ids)} 条")
    except:
        print("📊 似乎是空表，准备开始全量抓取。")

    # 2. 获取 Strava 上的"所有"活动摘要
    # Strava List API 很便宜，一次可以拉 200 条，我们可以拉个几千条
    # 只要不调用 get_activity() 就不消耗昂贵的详细额度
    print("☁️ 正在拉取 Strava 活动清单 (这可能需要一点时间)...")
    try:
        # limit=3000 大概能覆盖过去 3-5 年的数据
        # 这里的 iterator 是惰性的，我们把它转成 list 方便过滤
        # 注意：这里会消耗大约 10-15 次 API 额度 (3000/200)
        summary_iterator = strava.get_activities(limit=3000) 
        
        to_sync_ids = []
        for summary in summary_iterator:
            if summary.type != "Run": continue
            if str(summary.id) not in existing_ids:
                to_sync_ids.append(summary.id)
        
        print(f"🔍 扫描完成！共发现 {len(to_sync_ids)} 条【缺失】数据待同步。")
        
        if not to_sync_ids:
            print("🎉 所有历史数据已同步完毕！")
            return

        # 3. 截取本次任务的批次 (Batch)
        # 按照时间顺序，为了让表格好看，我们从列表末尾（最旧的）开始拿？
        # Strava 返回的是 Newest First。
        # 如果我们想补齐历史，建议还是处理最新的缺失数据，或者直接按顺序处理。
        # 这里直接取前 BATCH_SIZE 个 (最新的 80 个缺失的)
        current_batch = to_sync_ids[:BATCH_SIZE]
        
        print(f"⚙️ 本次运行将处理 {len(current_batch)} 条数据 (API 安全限制)...")
        
        new_rows = []
        for idx, act_id in enumerate(current_batch):
            print(f"[{idx+1}/{len(current_batch)}] 正在下载详情 ID: {act_id} ...")
            row = process_activity_detail(act_id, strava)
            if row:
                new_rows.append(row)
            # 稍微停顿，温柔一点
            time.sleep(0.5)
            
        # 4. 写入表格
        if new_rows:
            # 翻转一下，让旧的在上面？或者直接追加。
            # 如果想保持时间倒序（最新的在最下面），因为 current_batch 是最新的在前面
            # 所以 new_rows 0 是最新的。
            # 我们直接 append_rows，顺序无所谓，反正 Google Sheets 可以按日期排序
            new_rows.reverse() # 这样追加进去，最新的会在最下面
            print(f"📝 正在写入 Google Sheets...")
            sheet.append_rows(new_rows)
            print(f"✅ 本次批次完成！已同步 {len(new_rows)} 条。")
            print(f"⏳ 剩余待同步: {len(to_sync_ids) - len(new_rows)} 条。")
            print("💤 休息 15 分钟后继续...")
        
    except Exception as e:
        print(f"运行出错: {e}")

if __name__ == "__main__":
    main()
