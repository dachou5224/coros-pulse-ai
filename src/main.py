import os
import json
import time
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from stravalib.client import Client
from stravalib import exc as strava_exc

from id_utils import normalize_activity_id

# --- 配置部分 ---
STRAVA_CLIENT_ID = os.getenv('STRAVA_CLIENT_ID')
STRAVA_CLIENT_SECRET = os.getenv('STRAVA_CLIENT_SECRET')
STRAVA_REFRESH_TOKEN = os.getenv('STRAVA_REFRESH_TOKEN')
GOOGLE_JSON_KEY = os.getenv('GOOGLE_APPLICATION_CREDENTIALS_JSON')
SHEET_NAME = "Coros_Running_Data"
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


def seconds_from_duration_like(val) -> float:
    """
    Strava 的 moving_time / elapsed_time 在 stravalib 中多为 timedelta 或整型秒数；
    部分环境会解析成 google.protobuf.well_known_types.Duration（无 total_seconds）。
    亦兼容 pint.Quantity（秒）。
    """
    if val is None:
        return 0.0
    ts = getattr(val, "total_seconds", None)
    if callable(ts):
        return float(ts())
    to_td = getattr(val, "ToTimedelta", None)
    if callable(to_td):
        try:
            td = to_td()
            if td is not None and hasattr(td, "total_seconds"):
                return float(td.total_seconds())
        except Exception:
            pass
    to_sec = getattr(val, "ToSeconds", None)
    if callable(to_sec):
        try:
            return float(to_sec())
        except Exception:
            pass
    if hasattr(val, "seconds") and hasattr(val, "nanos"):
        try:
            s = int(val.seconds)
            n = int(getattr(val, "nanos", 0) or 0)
            return s + n / 1e9
        except (TypeError, ValueError):
            pass
    try:
        import pint

        if isinstance(val, pint.Quantity):
            return float(val.to("second").magnitude)
    except Exception:
        pass
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0

def clean_id(val):
    """与 activity_advice 共用 normalize_activity_id，避免大整数经 float 丢精度或列错位。"""
    return normalize_activity_id(val)


def _sheet_cell(val):
    """gspread 写行时会 JSON 序列化；stravalib 的 ActivityType 等需压成 str/int/float。"""
    if val is None:
        return ""
    if isinstance(val, (str, int, float, bool)):
        return val
    root = getattr(val, "__root__", None)
    if root is not None:
        return str(root)
    return str(val)


def process_activity_detail(activity_id, client):
    try:
        detail = client.get_activity(activity_id)
        
        dist_km = round(float(detail.distance) / 1000, 2)
        duration_min = round(seconds_from_duration_like(detail.moving_time) / 60, 2)
        avg_pace = get_pace_str(detail.average_speed)
        max_pace = get_pace_str(detail.max_speed)

        splits_data = []
        if hasattr(detail, 'splits_metric') and detail.splits_metric:
            for s in detail.splits_metric:
                split_pace = get_pace_str(s.average_speed)
                split_hr = s.average_heartrate if hasattr(s, 'average_heartrate') else 0
                splits_data.append({"km": s.split, "pace": split_pace, "hr": round(split_hr)})
        splits_json = json.dumps(splits_data, ensure_ascii=False)

        shoe_name = ""
        if detail.gear_id:
            try:
                shoe_name = detail.gear.name if hasattr(detail.gear, 'name') else detail.gear_id
            except: pass

        return [
            str(detail.id), # 写入时确保是字符串
            detail.start_date_local.strftime("%Y-%m-%d %H:%M:%S"),
            _sheet_cell(detail.name),
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
            _sheet_cell(shoe_name),
            _sheet_cell(detail.type),
            splits_json,
        ]
    except Exception as e:
        print(f"处理 ID {activity_id} 失败: {e}")
        return None

def main():
    print("🚀 启动历史数据回溯模式 (Backfill Mode v2.0)...")
    strava = get_strava_client()
    sheet = get_google_sheet()
    
    if not strava or not sheet: return

    # 1. 强健地读取已保存 ID
    existing_ids = set()
    try:
        records = sheet.get_all_records()
        if records:
            df = pd.DataFrame(records)
            # 使用 clean_id 函数清洗每一行的 ID
            df['Clean_ID'] = df['Activity ID'].apply(clean_id)
            existing_ids = set(df['Clean_ID'].tolist())
            print(f"📊 本地已有数据: {len(existing_ids)} 条 (已清洗格式)")
    except Exception as e:
        print(f"读取现有表格出错或为空: {e}")

    # 2. 拉取清单
    print("☁️ 正在拉取 Strava 活动清单...")
    try:
        summary_iterator = strava.get_activities(limit=3000) 
        
        to_sync_ids = []
        for summary in summary_iterator:
            if summary.type != "Run": continue
            
            # 使用同样的逻辑清洗 Strava 返回的 ID
            strava_id_str = clean_id(summary.id)
            
            if strava_id_str not in existing_ids:
                to_sync_ids.append(summary.id) # 记录原始 ID 用于请求
        
        print(f"🔍 扫描完成！共发现 {len(to_sync_ids)} 条【缺失】数据待同步。")
        
        if not to_sync_ids:
            print("🎉 所有历史数据已同步完毕！")
            return

        # 3. 处理批次
        current_batch = to_sync_ids[:BATCH_SIZE]
        print(f"⚙️ 本次运行将处理 {len(current_batch)} 条数据...")
        
        new_rows = []
        for idx, act_id in enumerate(current_batch):
            print(f"[{idx+1}/{len(current_batch)}] 下载详情 ID: {act_id} ...")
            row = process_activity_detail(act_id, strava)
            if row:
                new_rows.append(row)
            time.sleep(0.5)
            
# ... (前面的代码不变) ...

        if new_rows:
            # 这里原本是 new_rows.reverse()，如果你希望最新的在最上面，可以去掉 reverse
            # 但为了保险，我们不管怎么插入，最后都做一个全表排序
            
            print(f"📝 正在写入 Google Sheets...")
            sheet.append_rows(new_rows)
            print(f"✅ 本次批次完成！已同步 {len(new_rows)} 条。")
            
            # --- 🆕 新增：自动排序逻辑 ---
            print("🧹 正在按日期重新排序 (最新的在最上面)...")
            try:
                # 假设 Date 是第 2 列
                # range='A2:R' 表示不排序第一行表头，从第2行开始排
                # sort_order='DES' 表示降序 (最新的在上面)，'ASC' 表示升序 (最旧的在上面)
                sheet.sort((2, 'des'), range=f'A2:R{sheet.row_count}') 
            except Exception as e:
                print(f"排序失败 (可能是权限或表头问题，不影响数据): {e}")

    except strava_exc.Fault as e:
        _print_strava_http_error(e)
    except Exception as e:
        print(f"运行出错: {e}")
        if getattr(e, "response", None) is not None:
            _print_strava_http_error(e)


def _print_strava_http_error(e: Exception) -> None:
    """
    Strava 官方常见码：401/403/404/429/5xx。若出现 597 等非标准码，多为中间层（代理/WAF/CDN）
    或网络设备返回的非 RFC 状态行；[None] 表示响应体里无 Strava 标准 message/errors JSON。
    「No rates present in response headers」来自 stravalib：错误页往往不带 X-RateLimit-*，可忽略。
    """
    print(f"运行出错: {e}")
    resp = getattr(e, "response", None)
    if resp is None:
        print(
            "  提示：若为 597 等异常码，请检查本机/VPS 是否经公司代理、防火墙或 CDN；"
            "另查 https://status.strava.com 与换网络重试。"
        )
        return
    print(f"  HTTP 状态码: {resp.status_code} | URL: {getattr(resp, 'url', '?')}")
    try:
        snippet = (resp.text or "").strip()[:500]
        if snippet:
            print(f"  响应正文片段: {snippet!r}")
    except Exception:
        pass
    if resp.status_code and (resp.status_code < 200 or resp.status_code >= 500):
        print(
            "  建议：等待后重试；缩小 get_activities(limit)；确认 STRAVA_* 凭证有效；"
            "用 curl -v 直连 api 排除代理劫持。"
        )


if __name__ == "__main__":
    main()
