"""
从 Google Sheet 拉取最近 N 条跑步（默认 5）与 1 条周报，测试 coach：get_activity_advice、get_weekly_advice。
在项目根目录执行：python src/test_coach.py

需配置 .env：API_KEY（Gemini）；Google Sheet 二选一：
  - GOOGLE_APPLICATION_CREDENTIALS_FILE=credentials.json
  - GOOGLE_APPLICATION_CREDENTIALS_JSON= 整段 JSON 单行

可选环境变量：
  - TEST_RECENT_ACTIVITIES=5  从 Activities 表按 Date 排序后取最近几条（默认 5）
"""
import json
import os
import sys
from pathlib import Path

import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

# 项目根目录加载 .env
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# 测试时禁用卡片输出，仅输出到终端供审阅
os.environ["ENABLE_CARD_RENDER"] = "false"

# 确保可导入 coach（从项目根或 src 运行）
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from coach import get_weekly_advice, get_activity_advice
from id_utils import normalize_activity_id

SHEET_NAME = "Coros_Running_Data"


def _load_credentials_dict():
    """优先从文件路径读取，否则从环境变量 JSON 读取。"""
    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_FILE")
    if path:
        p = Path(path)
        if not p.is_absolute():
            p = ROOT / p
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        print(f"❌ 凭证文件不存在: {p}")
        return None
    raw = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if not raw:
        print("❌ 未设置 GOOGLE_APPLICATION_CREDENTIALS_FILE 或 GOOGLE_APPLICATION_CREDENTIALS_JSON")
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"❌ GOOGLE_APPLICATION_CREDENTIALS_JSON 不是合法 JSON: {e}")
        return None


def get_sheet_client():
    creds_dict = _load_credentials_dict()
    if not creds_dict:
        return None
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"❌ Google 认证失败: {e}")
        return None


def main():
    print("📥 连接 Google Sheet 并拉取数据...")
    client = get_sheet_client()
    if not client:
        return 1
    try:
        sh = client.open(SHEET_NAME)
    except Exception as e:
        print(f"❌ 打开表格失败: {e}")
        return 1

    # 最近 N 条跑步（Activities sheet1）：按 Date 升序后取尾部 N 条，与 activity_advice 逻辑一致
    n_recent = max(1, min(50, int(os.getenv("TEST_RECENT_ACTIVITIES", "5"))))
    activities_ws = sh.sheet1
    activities_records = activities_ws.get_all_records()
    if not activities_records:
        print("❌ Activities 表无数据")
        return 1
    by_date = sorted(activities_records, key=lambda r: (r.get("Date") or ""))
    recent_n = by_date[-n_recent:]
    last_activity = recent_n[-1]
    print(f"✅ 从 Sheet 拉取最近 {n_recent} 条跑步（按 Date 升序，下列最后一条为点评目标）\n")
    for i, r in enumerate(recent_n, 1):
        aid = normalize_activity_id(r.get("Activity ID"))
        print(
            f"  {i}. Activity ID={aid} | {r.get('Date')} | {r.get('Name')} | "
            f"{r.get('Distance (km)')} km"
        )
    print(
        f"\n🎯 本单点评目标: {last_activity.get('Date')} | {last_activity.get('Name')} | "
        f"{last_activity.get('Distance (km)')} km"
    )

    # 最近 1 条周报：按周排序后取最新一条
    try:
        report_ws = sh.worksheet("Weekly_Report")
    except Exception:
        print("❌ 未找到 Weekly_Report 表")
        return 1
    report_records = report_ws.get_all_records()
    if not report_records:
        print("❌ Weekly_Report 表无数据")
        return 1
    by_week = sorted(report_records, key=lambda r: (r.get("Week Start") or r.get("Week End") or ""))
    last_report = by_week[-1]
    print(f"✅ 最近 1 条周报: {last_report.get('Week Start')} ~ {last_report.get('Week End')}")

    weekly_context = {
        "Fitness (CTL)": last_report.get("Fitness (CTL)"),
        "Form (TSB)": last_report.get("Form (TSB)"),
        "VDOT": last_report.get("VDOT"),
    }

    # 测试 get_activity_advice（最新 1 条 + 同期最近 N 次作为背景）
    print("\n--- 测试 get_activity_advice ---")
    activity_advice = get_activity_advice(
        last_activity, recent_activities=recent_n, weekly_context=weekly_context
    )
    if activity_advice:
        print(activity_advice)
    else:
        print("(未返回内容或 API 未配置/失败)")

    # 测试 get_weekly_advice（用最近 1 条跑步 + 最近周报作为“当周”数据）
    print("\n--- 测试 get_weekly_advice ---")
    weekly_df = pd.DataFrame([last_activity])
    recent_weeks = by_week[-8:-1] if len(by_week) > 1 else []
    weekly_advice = get_weekly_advice(weekly_df, last_report, recent_weeks_reports=recent_weeks)
    if weekly_advice:
        print(weekly_advice)
    else:
        print("(未返回内容或 API 未配置/失败)")

    print("\n✅ 测试完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
