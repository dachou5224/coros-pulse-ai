#!/usr/bin/env python3
"""
导出静态站所需的同源 JSON 快照，避免浏览器直连 Google CSV 时的 CORS 问题。

默认输出：
- show/static/data/weekly_report.json
- show/static/data/activities.json

优先使用 Google Sheet 凭证直读；若未配置凭证，则回退到公开 CSV URL。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import gspread
import pandas as pd
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials


REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DATA_DIR = REPO_ROOT / "show" / "static" / "data"
DEFAULT_WEEKLY_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vQKYBbug9yQhYtejoO-9OMKXYQfA1Ju4ReO2YvYb7kqhWlrczvSrnHCmK_YBc5B6olsbBfUoP2Jbn5b/"
    "pub?gid=774375516&single=true&output=csv"
)
SHEET_NAME = "Coros_Running_Data"
WEEKLY_SHEET = "Weekly_Report"
ACTIVITIES_SHEET = "Activities"


def _load_env() -> None:
    load_dotenv(REPO_ROOT / ".env")


def _json_key() -> str:
    return (os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON") or "").strip()


def _get_client():
    raw = _json_key()
    if not raw:
        return None
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(raw), scope)
    return gspread.authorize(creds)


def _sheet_df(client, worksheet_name: str) -> pd.DataFrame:
    sh = client.open(SHEET_NAME)
    ws = sh.sheet1 if worksheet_name == ACTIVITIES_SHEET else sh.worksheet(worksheet_name)
    return pd.DataFrame(ws.get_all_records())


def _csv_df(url: str) -> pd.DataFrame:
    return pd.read_csv(url)


def _normalize_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "isoformat") and not isinstance(value, (str, bytes)):
        try:
            return value.isoformat()
        except Exception:
            pass
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return str(value)


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    clean = df.copy()
    for col in ("Week Start", "Week End", "Date"):
        if col in clean.columns:
            clean[col] = pd.to_datetime(clean[col], errors="coerce")
    rows: list[dict[str, Any]] = []
    for record in clean.to_dict(orient="records"):
        rows.append({key: _normalize_value(value) for key, value in record.items()})
    return rows


def _load_weekly_df(client) -> pd.DataFrame:
    url = os.getenv("WEEKLY_REPORT_CSV_URL") or DEFAULT_WEEKLY_CSV_URL
    if client is not None:
        try:
            return _sheet_df(client, WEEKLY_SHEET)
        except Exception as exc:
            print(f"⚠️ 直读 Google Sheet 失败，回退到 Weekly_Report CSV: {type(exc).__name__}")
    return _csv_df(url)


def _load_activity_df(client) -> pd.DataFrame:
    url = (os.getenv("ACTIVITY_ADVICE_CSV_URL") or "").strip()
    if client is not None:
        try:
            return _sheet_df(client, ACTIVITIES_SHEET)
        except Exception as exc:
            print(f"⚠️ 直读 Google Sheet 失败，回退到 Activities CSV: {type(exc).__name__}")
    if not url:
        return pd.DataFrame()
    return _csv_df(url)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    _load_env()
    client = _get_client()

    weekly_df = _load_weekly_df(client)
    activity_df = _load_activity_df(client)

    generated_at = datetime.now(timezone.utc).isoformat()
    weekly_payload = {
        "generated_at": generated_at,
        "rows": _records(weekly_df),
    }
    activity_payload = {
        "generated_at": generated_at,
        "rows": _records(activity_df),
    }

    _write_json(STATIC_DATA_DIR / "weekly_report.json", weekly_payload)
    _write_json(STATIC_DATA_DIR / "activities.json", activity_payload)

    print(f"✅ 已导出周报快照: {STATIC_DATA_DIR / 'weekly_report.json'} ({len(weekly_payload['rows'])} rows)")
    print(f"✅ 已导出活动快照: {STATIC_DATA_DIR / 'activities.json'} ({len(activity_payload['rows'])} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
