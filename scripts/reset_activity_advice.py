#!/usr/bin/env python3
"""
清空 Activities 表中的单次跑步 LLM 点评列，并可选择只回填最近 N 条。
默认行为：
1. 清空全表点评列（总评/配速/心率/步频与爬升/下次训练课/点评更新时间(UTC)）
2. 输出最近 N 条活动的 Activity ID 与日期，便于人工核对
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import gspread
import pandas as pd
from dotenv import load_dotenv
from gspread.utils import rowcol_to_a1
from oauth2client.service_account import ServiceAccountCredentials

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from id_utils import activity_id_column_index, normalize_activity_id

SHEET_NAME = "Coros_Running_Data"
ADVICE_COLS = ["Coach Advice", "总评", "配速", "心率", "步频与爬升", "下次训练课", "点评更新时间(UTC)"]


def get_client():
    raw = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", "").strip()
    if not raw:
        raise RuntimeError("缺少 GOOGLE_APPLICATION_CREDENTIALS_JSON")
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(raw), scope)
    return gspread.authorize(creds)


def ensure_advice_headers(ws):
    headers = ws.row_values(1)
    next_col = len(headers) + 1
    col_indices = {}
    for name in ADVICE_COLS:
        if name in headers:
            col_indices[name] = headers.index(name) + 1
        else:
            ws.update_cell(1, next_col, name)
            col_indices[name] = next_col
            next_col += 1
            headers.append(name)
    return headers, col_indices


def clear_activity_advice(ws, *, dry_run: bool = False) -> dict:
    headers, col_indices = ensure_advice_headers(ws)
    all_values = ws.get_all_values()
    row_count = max(0, len(all_values) - 1)
    if row_count == 0:
        return {"cleared_rows": 0, "cleared_ranges": [], "headers": headers}

    data = []
    for name in ADVICE_COLS:
        col = col_indices[name]
        data.append(
            {
                "range": f"{rowcol_to_a1(2, col)}:{rowcol_to_a1(row_count + 1, col)}",
                "values": [[""] for _ in range(row_count)],
            }
        )
    if not dry_run:
        ws.batch_update(data)
    return {
        "cleared_rows": row_count,
        "cleared_ranges": [item["range"] for item in data],
        "headers": headers,
    }


def latest_rows(ws, limit: int) -> list[dict]:
    df = pd.DataFrame(ws.get_all_records())
    if df.empty:
        return []
    if "Activity ID" in df.columns:
        df["Activity ID"] = df["Activity ID"].map(normalize_activity_id)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.sort_values("Date")
    recent = df.tail(limit)
    rows = []
    for _, row in recent.iterrows():
        rows.append(
            {
                "Activity ID": normalize_activity_id(row.get("Activity ID", "")),
                "Date": "" if pd.isna(row.get("Date")) else row["Date"].strftime("%Y-%m-%d %H:%M:%S"),
                "Name": str(row.get("Name", "")),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Clear all activity advice cells from Google Sheets")
    parser.add_argument("--latest", type=int, default=5, help="show latest N rows for verification")
    parser.add_argument("--dry-run", action="store_true", help="do not write to Google Sheets")
    args = parser.parse_args()

    client = get_client()
    sh = client.open(SHEET_NAME)
    ws = sh.sheet1

    result = clear_activity_advice(ws, dry_run=args.dry_run)
    recent = latest_rows(ws, args.latest)
    print(json.dumps({"clear_result": result, "latest_rows": recent}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
