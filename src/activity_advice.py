"""
单次跑步教练点评：独立脚本，对最近 N 条尚未有点评的活动生成 AI 点评，
解析五段（总评、配速、心率、步频与爬升、下次训练课）分五列写入 Activities sheet1 右侧。
可单独运行，便于接入 GitHub Actions workflow。
"""
import re
import os
import json
import sys
from pathlib import Path

import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# 确保可导入 coach
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

try:
    from coach import get_activity_advice
except ImportError:
    get_activity_advice = None

JSON_KEY = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
SHEET_NAME = "Coros_Running_Data"

ADVICE_SLOTS = ["总评", "配速", "心率", "步频与爬升", "下次训练课"]


def get_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    if not JSON_KEY:
        print("❌ 错误：未找到 Google Credentials Secret")
        return None
    try:
        creds_dict = json.loads(JSON_KEY)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"❌ 认证失败: {e}")
        return None


def _parse_advice_slots(raw: str) -> dict:
    """从 coach 输出中按【标签】提取五段。"""
    slots = {}
    for tag in ADVICE_SLOTS:
        m = re.search(rf"【{re.escape(tag)}】\s*(.*?)(?=【|$)", raw, re.DOTALL)
        slots[tag] = (m.group(1).strip() if m else "")[:50000]
    return slots


def main():
    print("🚀 开始执行单次跑步教练点评...")
    if not get_activity_advice:
        print("❌ 无法导入 coach.get_activity_advice")
        return 1

    client = get_client()
    if not client:
        return 1

    try:
        sh = client.open(SHEET_NAME)
    except Exception as e:
        print(f"❌ 找不到表格 '{SHEET_NAME}': {e}")
        return 1

    # 读取 Activities
    activities_ws = sh.sheet1
    df = pd.DataFrame(activities_ws.get_all_records())
    if df.empty:
        print("❌ Activities 表无数据")
        return 1
    if "Activity ID" in df.columns:
        df["Activity ID"] = df["Activity ID"].astype(str)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.sort_values("Date")

    # 读取最新周报作 weekly_context
    report_row_dict = {}
    try:
        rpt_ws = sh.worksheet("Weekly_Report")
        rpt_records = rpt_ws.get_all_records()
        if rpt_records:
            by_week = sorted(rpt_records, key=lambda r: (r.get("Week Start") or r.get("Week End") or ""))
            last = by_week[-1]
            report_row_dict = {
                "Fitness (CTL)": last.get("Fitness (CTL)"),
                "Form (TSB)": last.get("Form (TSB)"),
                "VDOT": last.get("VDOT"),
            }
    except gspread.WorksheetNotFound:
        pass

    # 准备五列表头
    headers = activities_ws.row_values(1)
    col_indices = {}
    next_col = len(headers) + 1
    for tag in ADVICE_SLOTS:
        if tag in headers:
            col_indices[tag] = headers.index(tag) + 1
        else:
            activities_ws.update_cell(1, next_col, tag)
            col_indices[tag] = next_col
            next_col += 1

    # 去重：已有「总评」的跳过
    all_values = activities_ws.get_all_values()
    existing_ids = set()
    col_zongping = col_indices.get("总评")
    if col_zongping and len(all_values) > 1:
        for i, row in enumerate(all_values[1:], start=2):
            if len(row) >= col_zongping:
                val = row[col_zongping - 1]
                if val and str(val).strip():
                    aid = row[0] if row else ""
                    if aid:
                        existing_ids.add(str(aid).strip())

    # 最近 limit 条，按日期倒序处理
    limit = 20
    recent = df.tail(limit)
    weekly_context = report_row_dict
    appended = 0

    for idx in range(len(recent) - 1, -1, -1):
        row = recent.iloc[idx]
        aid = str(row.get("Activity ID", "")).strip()
        if not aid or aid in existing_ids:
            continue

        start_idx = max(0, idx - 4)
        recent_activities = [recent.iloc[i] for i in range(start_idx, idx + 1)]

        try:
            advice_text = get_activity_advice(
                row, recent_activities=recent_activities, weekly_context=weekly_context
            ) or ""
        except Exception as e:
            print(f"⚠️ 单条点评失败 Activity {aid}: {e}")
            advice_text = ""

        slots = _parse_advice_slots(advice_text)
        # 新 prompt 口语化输出无【标签】，解析为空时用 raw 写入总评
        if not any(slots.get(t) for t in ADVICE_SLOTS) and advice_text:
            slots["总评"] = advice_text[:50000]

        try:
            cell = activities_ws.find(str(aid), in_column=1)
            for tag in ADVICE_SLOTS:
                col = col_indices[tag]
                activities_ws.update_cell(cell.row, col, slots.get(tag, ""))
            existing_ids.add(aid)
            appended += 1
        except gspread.exceptions.CellNotFound:
            pass

    if appended > 0:
        print(f"✅ 单次跑步教练点评已写入 {appended} 条")
    else:
        print("✅ 无新活动需点评")

    return 0


if __name__ == "__main__":
    sys.exit(main())
