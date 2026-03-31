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
import math
import re

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
SETTINGS_SHEET = "Settings"


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


def _load_settings_df(client) -> pd.DataFrame:
    if client is None:
        return pd.DataFrame([{"Date": "2000-01-01", "Max HR": 185, "Rest HR": 55}])
    try:
        return _sheet_df(client, SETTINGS_SHEET)
    except Exception:
        return pd.DataFrame([{"Date": "2000-01-01", "Max HR": 185, "Rest HR": 55}])


def _parse_pace_seconds(value: Any) -> float | None:
    text = str(value or "").strip()
    match = re.match(r"^(\d+)'(\d{1,2})\"$", text)
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def _format_pace(seconds: float | None) -> str:
    if seconds is None or pd.isna(seconds) or seconds <= 0:
        return "-"
    whole = int(round(float(seconds)))
    return f"{whole // 60}'{whole % 60:02d}\""


def _pace_to_speed(value: Any) -> float:
    pace_seconds = _parse_pace_seconds(value)
    if not pace_seconds or pace_seconds <= 0:
        return 0.0
    return 1000.0 / pace_seconds


def _calculate_run_vdot(distance_km: float, duration_min: float) -> float:
    if distance_km < 3 or duration_min <= 0:
        return 0.0
    predicted_5k_min = duration_min * (5.0 / distance_km) ** 1.06
    v = 5000.0 / predicted_5k_min
    return round(-4.6 + 0.182258 * v + 0.000104 * v**2, 1)


def _calculate_decoupling(splits_json: Any) -> float | None:
    try:
        splits = json.loads(splits_json or "[]")
    except Exception:
        return None
    if not splits or len(splits) < 4:
        return None
    half = len(splits) // 2
    first_half = splits[:half]
    second_half = splits[half:]
    v1 = sum(_pace_to_speed(item.get("pace")) for item in first_half) / len(first_half)
    v2 = sum(_pace_to_speed(item.get("pace")) for item in second_half) / len(second_half)
    h1 = sum(float(item.get("hr") or 0) for item in first_half) / len(first_half)
    h2 = sum(float(item.get("hr") or 0) for item in second_half) / len(second_half)
    if v1 <= 0 or h1 <= 0 or h2 <= 0:
        return None
    ef1 = v1 / h1
    ef2 = v2 / h2
    return round((ef1 - ef2) / ef1 * 100.0, 2)


def _normalize_settings_df(settings_df: pd.DataFrame) -> pd.DataFrame:
    clean = settings_df.copy()
    clean["Date"] = pd.to_datetime(clean["Date"], errors="coerce")
    clean["Max HR"] = pd.to_numeric(clean["Max HR"], errors="coerce")
    clean["Rest HR"] = pd.to_numeric(clean["Rest HR"], errors="coerce")
    clean = clean.dropna(subset=["Date", "Max HR", "Rest HR"]).sort_values("Date")
    if clean.empty:
        return pd.DataFrame([{"Date": pd.Timestamp("2000-01-01"), "Max HR": 185.0, "Rest HR": 55.0}])
    return clean


def _hr_params_for_date(date_value: pd.Timestamp, settings_df: pd.DataFrame) -> tuple[float, float]:
    valid = settings_df[settings_df["Date"] <= date_value]
    row = valid.iloc[-1] if not valid.empty else settings_df.iloc[0]
    return float(row["Max HR"]), float(row["Rest HR"])


def _weekly_history_from_activities(activity_df: pd.DataFrame, settings_df: pd.DataFrame) -> pd.DataFrame:
    if activity_df.empty or "Date" not in activity_df.columns:
        return pd.DataFrame()

    df = activity_df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date")
    if df.empty:
        return pd.DataFrame()

    for col in ("Distance (km)", "Duration (min)", "Avg HR"):
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    settings = _normalize_settings_df(settings_df)

    def calc_trimp(row: pd.Series) -> float:
        duration = float(row.get("Duration (min)") or 0)
        avg_hr = float(row.get("Avg HR") or 0)
        if duration <= 0 or avg_hr <= 0:
            return 0.0
        max_hr, rest_hr = _hr_params_for_date(row["Date"], settings)
        if max_hr <= rest_hr:
            return 0.0
        hrr = max(0.0, min(1.0, (avg_hr - rest_hr) / (max_hr - rest_hr)))
        weight = 0.64 * math.exp(1.92 * hrr)
        return round(duration * hrr * weight, 1)

    df["TRIMP"] = df.apply(calc_trimp, axis=1)
    df["day"] = df["Date"].dt.normalize()
    df["week_start"] = df["day"] - pd.to_timedelta(df["Date"].dt.weekday, unit="D")
    daily_load = df.groupby("day")["TRIMP"].sum().sort_index()

    rows: list[dict[str, Any]] = []
    for week_start, week_df in df.groupby("week_start", sort=True):
        week_end = week_start + pd.Timedelta(days=7)
        up_to_week = daily_load[daily_load.index < week_end]
        ctl = float(up_to_week.ewm(span=42, adjust=False).mean().iloc[-1]) if not up_to_week.empty else 0.0
        atl = float(up_to_week.ewm(span=7, adjust=False).mean().iloc[-1]) if not up_to_week.empty else 0.0
        tsb = ctl - atl

        vdot_window = df[(df["Date"] >= (week_end - pd.Timedelta(days=42))) & (df["Date"] < week_end)]
        vdot_values = [
            _calculate_run_vdot(float(row["Distance (km)"] or 0), float(row["Duration (min)"] or 0))
            for _, row in vdot_window.iterrows()
        ]
        vdot_values = [value for value in vdot_values if value > 0]
        current_vdot = max(vdot_values) if vdot_values else 0.0

        avg_pace_seconds = week_df["Avg Pace"].map(_parse_pace_seconds).dropna()
        avg_pace = _format_pace(avg_pace_seconds.mean() if not avg_pace_seconds.empty else None)

        longest_decouple = "-"
        if "Splits (JSON)" in week_df.columns and not week_df.empty:
            longest_run = week_df.loc[week_df["Duration (min)"].idxmax()]
            if float(longest_run.get("Duration (min)") or 0) > 30:
                decouple = _calculate_decoupling(longest_run.get("Splits (JSON)"))
                if decouple is not None:
                    longest_decouple = f"{decouple}%"

        rows.append(
            {
                "Week Start": week_start,
                "Week End": week_end,
                "Distance (km)": round(float(week_df["Distance (km)"].sum()), 2),
                "Runs": int(len(week_df)),
                "Avg Pace": avg_pace,
                "Weekly Load": round(float(week_df["TRIMP"].sum())),
                "Fitness (CTL)": round(ctl, 1),
                "Form (TSB)": round(tsb, 1),
                "VDOT": current_vdot,
                "LSD Decouple": longest_decouple,
                "Status": "恢复" if tsb > 10 else ("适中" if tsb > -10 else "疲劳"),
                "本周总评": "",
                "核心诊断": "",
                "下周药方": "",
                "Coach Advice": "",
            }
        )

    return pd.DataFrame(rows).sort_values("Week Start", ascending=False).reset_index(drop=True)


def _merge_weekly_notes(base_df: pd.DataFrame, weekly_df: pd.DataFrame) -> pd.DataFrame:
    if base_df.empty or weekly_df.empty or "Week Start" not in weekly_df.columns:
        return base_df
    note_cols = [col for col in ("本周总评", "核心诊断", "下周药方", "Coach Advice") if col in weekly_df.columns]
    if not note_cols:
        return base_df
    notes = weekly_df[["Week Start", *note_cols]].copy()
    notes["Week Start"] = pd.to_datetime(notes["Week Start"], errors="coerce")
    merged = base_df.merge(notes, on="Week Start", how="left", suffixes=("", "_sheet"))
    for col in note_cols:
        sheet_col = f"{col}_sheet"
        if sheet_col in merged.columns:
            merged[col] = merged[sheet_col].where(merged[sheet_col].notna() & (merged[sheet_col] != ""), merged[col])
            merged = merged.drop(columns=[sheet_col])
    return merged


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
    settings_df = _load_settings_df(client)

    if len(weekly_df) < 4 and not activity_df.empty:
        rebuilt_df = _weekly_history_from_activities(activity_df, settings_df)
        if not rebuilt_df.empty and len(rebuilt_df) > len(weekly_df):
            weekly_df = _merge_weekly_notes(rebuilt_df, weekly_df)
            print(f"ℹ️ Weekly_Report 历史不足，已从 Activities 重建 {len(weekly_df)} 条周报记录")

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
